"""Git blame utilities for identifying suspect commits in a traceback."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from tracefix.repo_map import MappedFrame


@dataclass(frozen=True)
class BlameHit:
    """A single line attribution from ``git blame --porcelain``."""

    sha: str
    author: str
    author_time: int
    summary: str
    path: str
    line: int
    code: str


def blame_lines(repo: Path, path: str, start: int, end: int) -> list[BlameHit]:
    """Run ``git blame --porcelain -L start,end`` and return parsed results.

    *start* and *end* are 1-based line numbers.  Lines before 1 are clamped
    to 1; if *start* > *end* after clamping an empty list is returned.
    """
    start = max(1, start)
    end = max(start, end)

    result = subprocess.run(
        ["git", "blame", "--porcelain", f"-L{start},{end}", "--", path],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return _parse_porcelain(result.stdout, path)


def _parse_porcelain(output: str, path: str) -> list[BlameHit]:
    """Parse the output of ``git blame --porcelain`` into :class:`BlameHit` objects.

    The porcelain format emits a *header block* the first time a commit SHA is
    seen.  Subsequent references to the same SHA omit all header fields.  We
    accumulate per-commit metadata and look it up when building hits.
    """
    lines = output.splitlines()
    commit_meta: dict[str, dict[str, str]] = {}
    hits: list[BlameHit] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        # Each "group" starts with: <sha40> <orig-line> <final-line> [<num-lines>]
        parts = line.split()
        if len(parts) >= 3 and len(parts[0]) == 40 and parts[0].isalnum():
            sha = parts[0]
            final_line = int(parts[2])
            i += 1
            # Collect header fields until we hit the tab-prefixed code line.
            meta: dict[str, str] = {}
            while i < len(lines) and not lines[i].startswith("\t"):
                kv = lines[i]
                if " " in kv:
                    key, _, val = kv.partition(" ")
                    meta[key] = val
                i += 1
            # Merge into persistent store (first occurrence wins for that sha).
            if sha not in commit_meta:
                commit_meta[sha] = meta
            else:
                # Fill in any missing keys from the new block.
                for k, v in meta.items():
                    commit_meta[sha].setdefault(k, v)
            # Tab-prefixed line is the source code.
            code = lines[i][1:] if i < len(lines) else ""
            i += 1
            stored = commit_meta[sha]
            hits.append(
                BlameHit(
                    sha=sha,
                    author=stored.get("author", "unknown"),
                    author_time=int(stored.get("author-time", "0")),
                    summary=stored.get("summary", ""),
                    path=path,
                    line=final_line,
                    code=code,
                )
            )
        else:
            i += 1

    return hits


def suspect_commits(
    repo: Path,
    frames: list[MappedFrame],
    window: int = 3,
) -> list[tuple[BlameHit, float]]:
    """Rank suspect commits by how likely they caused the crash.

    Blame ±*window* lines around each in-repo frame's line number.  Scoring:

    * Each hit contributes ``recency_weight`` based on ``author_time``.
    * A hit on the *crash frame* (last frame) is multiplied by 3×.
    * A hit on the *exact crash line* of the crash frame is multiplied by 5×.

    The crash frame is the last :class:`MappedFrame` that has a ``repo_path``.

    Returns unique commits (by SHA) sorted by total score descending.
    """
    # Identify the crash frame (last in-repo frame).
    crash_frame: MappedFrame | None = None
    for mf in reversed(frames):
        if mf.repo_path is not None:
            crash_frame = mf
            break

    now = int(time.time())

    scores: dict[str, float] = {}
    best_hit: dict[str, BlameHit] = {}

    for mf in frames:
        if mf.repo_path is None:
            continue
        is_crash = mf is crash_frame
        crash_line = mf.frame.line

        start = max(1, crash_line - window)
        end = crash_line + window

        try:
            hits = blame_lines(repo, mf.repo_path, start, end)
        except subprocess.CalledProcessError:
            continue

        for hit in hits:
            # Recency: newer commits score higher; cap to avoid zero-division.
            age = max(1, now - hit.author_time)
            recency = 1.0 / age * 1e9  # scale so numbers are readable

            multiplier = 1.0
            if is_crash:
                multiplier = 3.0
                if hit.line == crash_line:
                    multiplier = 5.0

            scores[hit.sha] = scores.get(hit.sha, 0.0) + recency * multiplier
            if hit.sha not in best_hit:
                best_hit[hit.sha] = hit

    ranked = sorted(scores.keys(), key=lambda sha: scores[sha], reverse=True)
    return [(best_hit[sha], scores[sha]) for sha in ranked]
