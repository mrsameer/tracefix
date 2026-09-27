"""Deterministic verification gates: TraceFix never trusts Bob's word, only pytest."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from tracefix.trace_parser import ParsedTrace, parse_traceback

PYTEST_ARGS = ["-q", "--tb=native", "-p", "no:cacheprovider", "--no-header"]


@dataclass(frozen=True)
class PytestRun:
    """Result of one pytest invocation."""

    passed: bool
    output: str


@dataclass(frozen=True)
class SignatureCheck:
    """Whether a test failure reproduces the production failure."""

    matches: bool
    reason: str


def run_pytest(repo: Path, target: str | None = None) -> PytestRun:
    """Run pytest in `repo`, optionally on a single test file."""
    cmd = [sys.executable, "-m", "pytest", *PYTEST_ARGS]
    if target:
        cmd.append(target)
    proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=600)
    return PytestRun(proc.returncode == 0, proc.stdout + proc.stderr)


def check_signature(run: PytestRun, production: ParsedTrace) -> SignatureCheck:
    """Accept a repro only if it fails like production did.

    Same exception type, raised from the same function as the production crash.
    """
    if run.passed:
        return SignatureCheck(False, "the test passed; it does not reproduce the bug")
    try:
        observed = parse_traceback(run.output)
    except ValueError:
        return SignatureCheck(False, "the test failed without a Python traceback")
    expected_fn = production.frames[-1].function
    observed_fns = [frame.function for frame in observed.frames]
    if observed.exc_type.split(".")[-1] != production.exc_type.split(".")[-1]:
        return SignatureCheck(
            False,
            f"raised {observed.exc_type}, production raised {production.exc_type}",
        )
    if not observed_fns or observed_fns[-1] != expected_fn:
        crash_fn = observed_fns[-1] if observed_fns else "?"
        return SignatureCheck(
            False, f"crashed in {crash_fn}(), production crashed in {expected_fn}()"
        )
    return SignatureCheck(
        True, f"{observed.exc_type} raised from {expected_fn}() — matches production"
    )


def changed_files(repo: Path) -> list[str]:
    """List files modified or added in the working tree."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line[3:].strip() for line in proc.stdout.splitlines() if line.strip()]
