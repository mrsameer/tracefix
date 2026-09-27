"""Map traceback frames to files tracked in a git repository."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from tracefix.trace_parser import Frame, ParsedTrace


@dataclass(frozen=True)
class MappedFrame:
    """A traceback frame with its resolved repository path and code context."""

    frame: Frame
    repo_path: str | None
    context: str


def _git_ls_files(repo: Path) -> list[str]:
    """Return all file paths tracked by git in *repo*."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _match_repo_path(frame_path: str, repo_files: list[str]) -> str | None:
    """Find the longest suffix match for *frame_path* among *repo_files*.

    For example, ``/srv/app/shopcart/loyalty.py`` matches
    ``shopcart/loyalty.py`` when that path is tracked in the repo.
    Returns the matched repo-relative path, or *None* if no match is found.
    """
    best: str | None = None
    best_len = 0
    # Normalise the frame path to use forward slashes for comparison.
    fp = frame_path.replace("\\", "/")
    for rp in repo_files:
        rp_norm = rp.replace("\\", "/")
        if fp.endswith(rp_norm):
            if len(rp_norm) > best_len:
                best = rp
                best_len = len(rp_norm)
    return best


def _build_context(repo: Path, repo_path: str, crash_line: int) -> str:
    """Return up to 5 lines before and 2 after *crash_line*, numbered.

    The crash line is marked with ``>``.
    """
    full_path = repo / repo_path
    try:
        source_lines = full_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""

    total = len(source_lines)
    # Convert to 0-based index.
    idx = crash_line - 1
    start = max(0, idx - 5)
    end = min(total - 1, idx + 2)

    parts: list[str] = []
    for i in range(start, end + 1):
        lineno = i + 1
        marker = ">" if lineno == crash_line else " "
        parts.append(f"{marker}{lineno:4d} | {source_lines[i]}")
    return "\n".join(parts)


def map_frames(trace: ParsedTrace, repo: Path) -> list[MappedFrame]:
    """Map each frame in *trace* to a file tracked in *repo*.

    Frames whose paths match a file in the repository get a ``repo_path`` and
    code context; all others (site-packages, stdlib, etc.) get ``repo_path=None``
    and an empty context string.
    """
    repo_files = _git_ls_files(repo)
    mapped: list[MappedFrame] = []
    for frame in trace.frames:
        repo_path = _match_repo_path(frame.path, repo_files)
        if repo_path is not None:
            context = _build_context(repo, repo_path, frame.line)
        else:
            context = ""
        mapped.append(MappedFrame(frame=frame, repo_path=repo_path, context=context))
    return mapped
