"""Tests for tracefix.repo_map."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tracefix.trace_parser import Frame, ParsedTrace
from tracefix.repo_map import MappedFrame, map_frames


# ---------------------------------------------------------------------------
# Fixture: tiny git repo
# ---------------------------------------------------------------------------

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_AUTHOR_DATE": "2024-01-01T00:00:00",
    "GIT_COMMITTER_DATE": "2024-01-01T00:00:00",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**__import__("os").environ, **GIT_ENV},
    )


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> Path:
    """A small git repo with a couple of tracked Python files."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")

    # Create directory structure: shopcart/loyalty.py
    (tmp_path / "shopcart").mkdir()
    loyalty = tmp_path / "shopcart" / "loyalty.py"
    loyalty.write_text(
        "# loyalty module\n"
        "def apply_discount(cart):\n"
        "    # line 3\n"
        "    # line 4\n"
        "    # line 5\n"
        "    # line 6\n"
        "    # line 7\n"
        "    return cart * 0.9\n",
        encoding="utf-8",
    )

    # A top-level utility file
    util = tmp_path / "utils.py"
    util.write_text("def helper():\n    pass\n", encoding="utf-8")

    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial commit")
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trace(*frames: Frame, exc_type: str = "ZeroDivisionError") -> ParsedTrace:
    return ParsedTrace(exc_type=exc_type, message="oops", frames=list(frames))


def _frame(path: str, line: int = 5, func: str = "fn", code: str = "") -> Frame:
    return Frame(path=path, line=line, function=func, code=code)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMapFrames:
    def test_exact_match(self, tiny_repo: Path) -> None:
        trace = _make_trace(_frame("shopcart/loyalty.py", line=5))
        mapped = map_frames(trace, tiny_repo)
        assert mapped[0].repo_path == "shopcart/loyalty.py"

    def test_suffix_match(self, tiny_repo: Path) -> None:
        """Absolute deploy path should resolve via suffix matching."""
        trace = _make_trace(_frame("/srv/app/shopcart/loyalty.py", line=5))
        mapped = map_frames(trace, tiny_repo)
        assert mapped[0].repo_path == "shopcart/loyalty.py"

    def test_no_match_returns_none(self, tiny_repo: Path) -> None:
        trace = _make_trace(_frame("/usr/lib/python3.11/importlib/__init__.py"))
        mapped = map_frames(trace, tiny_repo)
        assert mapped[0].repo_path is None
        assert mapped[0].context == ""

    def test_context_crash_line_marked(self, tiny_repo: Path) -> None:
        trace = _make_trace(_frame("/srv/app/shopcart/loyalty.py", line=5))
        mapped = map_frames(trace, tiny_repo)
        context = mapped[0].context
        # Line 5 should be marked with >
        assert ">   5" in context or ">5" in context or "> 5" in context

    def test_context_includes_surrounding_lines(self, tiny_repo: Path) -> None:
        trace = _make_trace(_frame("/srv/app/shopcart/loyalty.py", line=5))
        mapped = map_frames(trace, tiny_repo)
        context = mapped[0].context
        # Lines 1-7 should appear (up to 5 before + 2 after line 5 = lines 1–7)
        assert "loyalty module" in context  # line 1

    def test_multiple_frames(self, tiny_repo: Path) -> None:
        frames = [
            _frame("/srv/app/shopcart/loyalty.py", line=5),
            _frame("/usr/lib/python3.11/something.py", line=1),
            _frame("/srv/app/utils.py", line=2),
        ]
        trace = _make_trace(*frames)
        mapped = map_frames(trace, tiny_repo)
        assert mapped[0].repo_path == "shopcart/loyalty.py"
        assert mapped[1].repo_path is None
        assert mapped[2].repo_path == "utils.py"

    def test_context_lines_at_start_of_file(self, tiny_repo: Path) -> None:
        """Context near line 1 should not include negative-index lines."""
        trace = _make_trace(_frame("/srv/app/shopcart/loyalty.py", line=1))
        mapped = map_frames(trace, tiny_repo)
        context = mapped[0].context
        assert context  # not empty
        # line 1 must be marked
        assert ">   1" in context or "> 1" in context or ">1" in context

    def test_mapped_frame_is_frozen(self, tiny_repo: Path) -> None:
        trace = _make_trace(_frame("/srv/app/shopcart/loyalty.py", line=5))
        mf = map_frames(trace, tiny_repo)[0]
        with pytest.raises((AttributeError, TypeError)):
            mf.repo_path = "changed"  # type: ignore[misc]
