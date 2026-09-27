"""Parse CPython tracebacks from arbitrary log text into structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

TRACEBACK_HEADER: Final = "Traceback (most recent call last):"
CHAIN_MARKERS: Final = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)

_FRAME_RE = re.compile(
    r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+), in (?P<func>\S+)'
)
_EXC_RE = re.compile(r"^(?P<type>[\w][\w.]*(?:\[[\w., ]+\])?)(?:: (?P<msg>.*))?$")
_CARET_RE = re.compile(r"^\s*[\^~]+\s*$")


@dataclass(frozen=True)
class Frame:
    """A single frame from a Python traceback."""

    path: str
    line: int
    function: str
    code: str


@dataclass(frozen=True)
class ParsedTrace:
    """A parsed Python traceback."""

    exc_type: str
    message: str
    frames: list[Frame]


def _split_into_blocks(text: str) -> list[str]:
    """Split *text* into traceback blocks separated by chain markers or new headers.

    Returns the raw text for every block that starts with a traceback header.
    Non-traceback leading content is silently ignored.
    """
    # Replace chain markers with a sentinel so we can split cleanly.
    sentinel = "\x00TRACEFIX_SPLIT\x00"
    for marker in CHAIN_MARKERS:
        text = text.replace(marker, sentinel)
    parts = text.split(sentinel)

    blocks: list[str] = []
    for part in parts:
        # A single part may itself contain multiple independent traceback headers
        # (e.g. two errors logged one after the other without chaining).
        while TRACEBACK_HEADER in part:
            idx = part.index(TRACEBACK_HEADER)
            rest = part[idx:]
            # Find the next occurrence of the header within rest (after the first char).
            next_idx = rest.find(TRACEBACK_HEADER, len(TRACEBACK_HEADER))
            if next_idx == -1:
                blocks.append(rest)
                break
            else:
                blocks.append(rest[:next_idx])
                part = rest[next_idx:]
    return blocks


def _is_code_line(line: str) -> bool:
    """Return True if *line* is an indented source code line (not a caret line)."""
    if not line or not line[0].isspace():
        return False
    stripped = line.strip()
    if not stripped:
        return False
    if _CARET_RE.match(line):
        return False
    if _FRAME_RE.match(line):
        return False
    return True


def _is_exc_line(line: str) -> bool:
    """Return True if *line* looks like an exception declaration."""
    stripped = line.strip()
    if not stripped or stripped.startswith("File ") or stripped.startswith("~"):
        return False
    # Must not be indented (exception lines are at column 0).
    if line and line[0].isspace():
        return False
    return bool(_EXC_RE.match(stripped))


def _parse_exc_line(line: str) -> tuple[str, str]:
    """Return (exc_type, message) from an exception line."""
    stripped = line.strip()
    m = _EXC_RE.match(stripped)
    if not m:
        return stripped, ""
    exc_type = m.group("type").strip()
    message = (m.group("msg") or "").strip()
    return exc_type, message


def _parse_single_block(block: str) -> ParsedTrace:
    """Parse one traceback block (no chained exceptions) into a ParsedTrace."""
    lines = block.splitlines()

    # Advance past the header line.
    start = 0
    for i, ln in enumerate(lines):
        if ln.strip() == TRACEBACK_HEADER:
            start = i + 1
            break

    frames: list[Frame] = []
    i = start
    while i < len(lines):
        ln = lines[i]

        # Check for exception line first (at column 0, not a frame).
        if _is_exc_line(ln):
            exc_type, message = _parse_exc_line(ln)
            return ParsedTrace(exc_type=exc_type, message=message, frames=frames)

        m = _FRAME_RE.match(ln)
        if m:
            path = m.group("path")
            lineno = int(m.group("line"))
            func = m.group("func")
            i += 1

            # Peek at the next lines to find the source code line (if any).
            code = ""
            # Skip over any source lines and caret lines that belong to this frame.
            while i < len(lines):
                peek = lines[i]
                if _CARET_RE.match(peek):
                    # Caret annotation — skip it.
                    i += 1
                    continue
                if _is_code_line(peek):
                    # Source code line — capture the first one.
                    if not code:
                        code = peek.strip()
                    i += 1
                    continue
                # Anything else (frame header, exc line, blank at col 0) — stop.
                break

            frames.append(Frame(path=path, line=lineno, function=func, code=code))
            continue

        # Skip unrecognised lines (blank lines, noise).
        i += 1

    raise ValueError("Traceback block has no exception line")


def parse_traceback(text: str) -> ParsedTrace:
    """Parse the *last* traceback block from arbitrary log text.

    Handles chained exceptions by using the final exception in the chain.
    Raises :class:`ValueError` if no traceback is found.
    """
    blocks = _split_into_blocks(text)
    if not blocks:
        raise ValueError("No traceback found in text")
    # Use the last block — that is the final exception in any chain.
    return _parse_single_block(blocks[-1])
