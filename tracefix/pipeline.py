"""TraceFix pipeline: stack trace -> brief -> suspect -> verified repro -> verified fix."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from tracefix.blame import BlameHit, suspect_commits
from tracefix.bob_acp import BobSession
from tracefix.prompts import fix_prompt, repro_prompt, retry_prompt
from tracefix.repo_map import MappedFrame, map_frames
from tracefix.trace_parser import ParsedTrace, parse_traceback
from tracefix.verify import changed_files, check_signature, run_pytest

REPRO_TEST = "tests/test_tracefix_repro.py"
MAX_ATTEMPTS = 3

Emit = Callable[[str, str, dict[str, Any]], None]
Gate = Callable[[Path], tuple[bool, str]]
STRATEGIES = {
    "repro": (
        "reproduce through the public API with the smallest realistic payload.",
        "reproduce through the public API with a payload modelled on real traffic.",
    ),
    "fix": (
        "prefer the smallest guard at the crash site.",
        "prefer fixing the root cause where the bad state is first computed.",
    ),
}


@dataclass
class StageResult:
    """Outcome of an agentic stage (repro or fix)."""

    ok: bool = False
    attempts: int = 0
    agent: int = 1
    agents: int = 1
    finished_at: float = 0.0
    seconds: float = 0.0
    session_id: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class Incident:
    """Everything TraceFix learned about one production failure."""

    incident_id: str
    trace: ParsedTrace
    frames: list[MappedFrame]
    suspects: list[tuple[BlameHit, float]]
    branch: str = ""
    repro: StageResult = field(default_factory=StageResult)
    fix: StageResult = field(default_factory=StageResult)
    repro_test: str = ""
    fix_diff: str = ""
    baseline_passed: bool = True
    total_seconds: float = 0.0


def analyze(trace_text: str, repo: Path, incident_id: str) -> Incident:
    """Run the deterministic stages: parse, map to repo, blame."""
    trace = parse_traceback(trace_text)
    frames = map_frames(trace, repo)
    return Incident(
        incident_id, trace, frames, _as_confidence(suspect_commits(repo, frames))
    )


def _as_confidence(
    suspects: list[tuple[BlameHit, float]],
) -> list[tuple[BlameHit, float]]:
    """Turn raw blame scores into a share of total suspicion (percent)."""
    total = sum(score for _, score in suspects) or 1.0
    return [(hit, round(100 * score / total, 1)) for hit, score in suspects]


def run(
    trace_text: str,
    repo: Path,
    incident_id: str,
    emit: Emit,
    with_fix: bool = True,
    agents: int = 1,
) -> Incident:
    """Run the full pipeline and return the populated incident."""
    started = time.time()
    emit("analyze", "start", {})
    incident = analyze(trace_text, repo, incident_id)
    emit("analyze", "done", _analysis_summary(incident))
    incident.branch = _create_branch(repo, incident_id)
    emit("branch", "done", {"branch": incident.branch})
    incident.baseline_passed = run_pytest(repo).passed
    emit("baseline", "done", {"passed": incident.baseline_passed})
    incident.repro = _reproduce(incident, repo, emit, agents)
    if incident.repro.ok:
        incident.repro_test = (repo / REPRO_TEST).read_text()
        _commit(repo, f"test: reproduce {incident.trace.exc_type} ({incident_id})")
    if with_fix and incident.repro.ok:
        incident.fix = _fix(incident, repo, emit, agents)
        if incident.fix.ok:
            incident.fix_diff = _diff_head(repo)
            _commit(
                repo,
                f"fix: {incident.trace.exc_type} in "
                f"{incident.trace.frames[-1].function}() ({incident_id})",
            )
    incident.total_seconds = round(time.time() - started, 1)
    emit("done", "done", {"seconds": incident.total_seconds})
    return incident


def _reproduce(incident: Incident, repo: Path, emit: Emit, agents: int) -> StageResult:
    """Ask Bob for a failing test until it fails exactly like production."""

    def gate(workdir: Path) -> tuple[bool, str]:
        touched = [f for f in changed_files(workdir) if f != REPRO_TEST]
        if not (workdir / REPRO_TEST).exists():
            return False, f"{REPRO_TEST} was not created"
        if touched:
            return (
                False,
                f"only {REPRO_TEST} may change, but you also changed {touched}",
            )
        result = run_pytest(workdir, REPRO_TEST)
        check = check_signature(result, incident.trace)
        detail = check.reason if check.matches else f"{check.reason}\n\n{result.output}"
        return check.matches, detail

    prompt = repro_prompt(incident, REPRO_TEST)
    return _race("repro", prompt, gate, repo, emit, agents)


def _fix(incident: Incident, repo: Path, emit: Emit, agents: int) -> StageResult:
    """Ask Bob for a fix until the repro passes and the full suite stays green."""

    def gate(workdir: Path) -> tuple[bool, str]:
        if REPRO_TEST in changed_files(workdir):
            return False, f"you must not modify {REPRO_TEST}"
        repro = run_pytest(workdir, REPRO_TEST)
        if not repro.passed:
            return False, f"the reproduction test still fails:\n\n{repro.output}"
        suite = run_pytest(workdir)
        if not suite.passed:
            return False, f"the fix breaks the existing suite:\n\n{suite.output}"
        return True, "repro test passes and the full suite is green"

    prompt = fix_prompt(incident, REPRO_TEST)
    return _race("fix", prompt, gate, repo, emit, agents)


def _race(
    stage: str, prompt: str, gate: Gate, repo: Path, emit: Emit, agents: int
) -> StageResult:
    """Run `agents` Bob sessions in isolated worktrees; first verified one wins.

    With a single agent Bob works directly in the repository.
    """
    started = time.time()
    if agents == 1:
        result = _attempts(stage, prompt, gate, repo, emit, 1, threading.Event())
    else:
        result = _race_worktrees(stage, prompt, gate, repo, emit, agents)
    result.seconds = round(time.time() - started, 1)
    emit(stage, "done", asdict(result))
    return result


def _race_worktrees(
    stage: str, prompt: str, gate: Gate, repo: Path, emit: Emit, agents: int
) -> StageResult:
    stop = threading.Event()
    trees = [_add_worktree(repo, f"{stage}-{k}") for k in range(1, agents + 1)]
    results: list[StageResult] = [StageResult() for _ in trees]

    def work(k: int) -> None:
        agent_prompt = f"{prompt}\n\nStrategy hint: {STRATEGIES[stage][k % 2]}"
        try:
            results[k] = _attempts(
                stage, agent_prompt, gate, trees[k], emit, k + 1, stop
            )
        except (RuntimeError, TimeoutError) as err:
            emit(stage, "error", {"agent": k + 1, "error": str(err)[:300]})
            results[k] = StageResult(agent=k + 1, notes=[str(err)[:300]])

    threads = [threading.Thread(target=work, args=(k,)) for k in range(agents)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    winner = min(
        (r for r in results if r.ok), key=lambda r: r.finished_at, default=None
    )
    if winner:
        _apply_tree(trees[winner.agent - 1], repo)
    for tree in trees:
        _git(repo, "worktree", "remove", "--force", str(tree))
    final = winner or results[0]
    final.agents = agents
    return final


def _attempts(
    stage: str,
    prompt: str,
    gate: Gate,
    workdir: Path,
    emit: Emit,
    agent: int,
    stop: threading.Event,
) -> StageResult:
    """Prompt Bob, verify with `gate`, feed failures back, up to MAX_ATTEMPTS."""
    result = StageResult(agent=agent)
    session = BobSession(
        workdir, on_event=lambda e: _forward_tool(stage, agent, e, emit)
    )
    result.session_id = session.session_id
    emit(stage, "start", {"session": session.session_id, "agent": agent})
    watcher = threading.Thread(
        target=lambda: stop.wait() and session.cancel(), daemon=True
    )
    watcher.start()
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result.attempts = attempt
            session.prompt(prompt)
            if stop.is_set():
                result.notes.append("stopped: another agent won the race")
                emit(stage, "cancel", {"agent": agent})
                break
            ok, detail = gate(workdir)
            result.notes.append(detail.splitlines()[0])
            data = {"attempt": attempt, "ok": ok, "detail": detail[:600]}
            emit(stage, "verify", {**data, "agent": agent})
            if ok and not stop.is_set():
                stop.set()
                result.ok = True
                result.finished_at = time.time()
                break
            prompt = retry_prompt(detail)
    finally:
        session.close()
    return result


def _forward_tool(stage: str, agent: int, event: dict[str, Any], emit: Emit) -> None:
    if event.get("sessionUpdate") == "tool_call":
        emit(stage, "tool", {"title": event.get("title", ""), "agent": agent})


def _add_worktree(repo: Path, name: str) -> Path:
    tree = repo.parent / f".tracefix-{repo.name}-{name}"
    if tree.exists():
        _git(repo, "worktree", "remove", "--force", str(tree))
    _git(repo, "worktree", "add", "-q", "--detach", str(tree), "HEAD")
    return tree


def _apply_tree(tree: Path, repo: Path) -> None:
    """Copy the winning worktree's changes into the main repository."""
    _git(tree, "add", "-A")
    patch = _git(tree, "diff", "--cached", "--binary")
    subprocess.run(
        ["git", "apply", "--whitespace=nowarn"],
        cwd=repo,
        input=patch,
        text=True,
        check=True,
    )


def _analysis_summary(incident: Incident) -> dict[str, Any]:
    top = incident.suspects[0][0] if incident.suspects else None
    return {
        "exception": f"{incident.trace.exc_type}: {incident.trace.message}",
        "frames": len(incident.trace.frames),
        "in_repo": sum(1 for f in incident.frames if f.repo_path),
        "suspect": f"{top.sha[:8]} {top.summary} ({top.author})" if top else None,
    }


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return proc.stdout


def _create_branch(repo: Path, incident_id: str) -> str:
    branch = f"tracefix/{incident_id}"
    _git(repo, "checkout", "-q", "-B", branch)
    return branch


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=TraceFix",
        "-c",
        "user.email=tracefix@localhost",
        "commit",
        "-q",
        "-m",
        message,
    )


def _diff_head(repo: Path) -> str:
    _git(repo, "add", "-A")
    return _git(repo, "diff", "--cached")


def save_events(path: Path) -> Emit:
    """Build an emitter that appends JSON lines to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def emit(stage: str, kind: str, data: dict[str, Any]) -> None:
        event = {"t": round(time.time() - started, 2), "stage": stage, "kind": kind}
        with path.open("a") as fh:
            fh.write(json.dumps({**event, "data": data}) + "\n")

    return emit
