"""TraceFix command line: `tracefix run` and `tracefix analyze`."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from tracefix import pipeline
from tracefix.prompts import incident_brief
from tracefix.report import write_reports

DIM, BOLD, GREEN, RED, CYAN, YELLOW, RESET = (
    "\033[2m",
    "\033[1m",
    "\033[32m",
    "\033[31m",
    "\033[36m",
    "\033[33m",
    "\033[0m",
)
STAGE_LABELS = {
    "analyze": "Analyze trace",
    "branch": "Incident branch",
    "baseline": "Baseline suite",
    "repro": "Bob · reproduce",
    "fix": "Bob · fix",
    "done": "Done",
}


def main(argv: list[str] | None = None) -> None:
    """Entry point for the `tracefix` command."""
    args = _parser().parse_args(argv)
    trace_text = Path(args.trace).read_text() if args.trace != "-" else sys.stdin.read()
    repo = Path(args.repo).resolve()
    incident_id = args.id or time.strftime("inc-%Y%m%d-%H%M%S")
    if args.command == "analyze":
        print(incident_brief(pipeline.analyze(trace_text, repo, incident_id)))
        return
    out_dir = Path(args.out) / incident_id
    events_path = out_dir / "events.jsonl"
    events_path.unlink(missing_ok=True)
    record = pipeline.save_events(events_path)

    def handle_event(stage: str, kind: str, data: dict[str, Any]) -> None:
        record(stage, kind, data)
        _print_event(stage, kind, data)

    _banner(incident_id, repo)
    incident = pipeline.run(
        trace_text, repo, incident_id, handle_event, not args.no_fix, args.agents
    )
    report = write_reports(incident, out_dir, events_path)
    print(f"\n{BOLD}Report:{RESET} {report}")
    sys.exit(0 if incident.repro.ok and (args.no_fix or incident.fix.ok) else 1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracefix",
        description="Production stack trace -> verified failing test -> verified fix, "
        "powered by IBM Bob.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "analyze"):
        cmd = sub.add_parser(name)
        cmd.add_argument("trace", help="file containing the traceback ('-' = stdin)")
        cmd.add_argument("--repo", default=".", help="git repository of the service")
        cmd.add_argument("--id", help="incident id (default: timestamp)")
        cmd.add_argument("--out", default="out", help="report directory")
        cmd.add_argument("--no-fix", action="store_true", help="stop after repro")
        cmd.add_argument(
            "--agents",
            type=int,
            default=1,
            help="race N Bob agents in parallel git worktrees; first verified wins",
        )
    return parser


def _banner(incident_id: str, repo: Path) -> None:
    print(f"{BOLD}{CYAN}TraceFix{RESET} {DIM}· incident {incident_id} · {repo}{RESET}")


def _print_event(stage: str, kind: str, data: dict[str, Any]) -> None:
    label = f"{BOLD}{STAGE_LABELS.get(stage, stage):<17}{RESET}"
    who = f"bob#{data['agent']}" if "agent" in data else "bob"
    if kind == "tool":
        print(f"  {DIM}│ {who} › {data['title'][:90]}{RESET}")
    elif kind == "verify":
        mark = f"{GREEN}✔ VERIFIED{RESET}" if data["ok"] else f"{RED}✘ REJECTED{RESET}"
        first = data["detail"].splitlines()[0]
        print(f"  {mark} {who} attempt {data['attempt']}: {first}")
    elif kind == "error":
        print(f"  {RED}! {who} failed: {data['error'][:100]}{RESET}")
    elif kind == "cancel":
        print(f"  {YELLOW}■ {who} stopped — another agent already won{RESET}")
    elif kind == "start" and stage in ("repro", "fix"):
        print(f"{label} {DIM}{who} · Bob ACP session {data['session'][:12]}…{RESET}")
    elif kind == "done":
        print(_done_line(stage, label, data))


def _done_line(stage: str, label: str, data: dict[str, Any]) -> str:
    if stage == "analyze":
        return (
            f"{label} {data['exception']}\n{' ' * 18}{data['in_repo']}/{data['frames']}"
            f" frames in repo · suspect {YELLOW}{data['suspect']}{RESET}"
        )
    if stage == "branch":
        return f"{label} {data['branch']}"
    if stage == "baseline":
        state = f"{GREEN}green{RESET}" if data["passed"] else f"{RED}red{RESET}"
        return f"{label} existing tests {state}"
    if stage in ("repro", "fix"):
        state = f"{GREEN}ok{RESET}" if data["ok"] else f"{RED}failed{RESET}"
        race = (
            f", winner bob#{data['agent']} of {data['agents']}"
            if data["agents"] > 1
            else ""
        )
        attempts = f"{data['attempts']} attempt(s){race}"
        return f"{label} {state} in {data['seconds']}s ({attempts})"
    return f"{label} total {data['seconds']}s"


if __name__ == "__main__":
    main()
