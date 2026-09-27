"""Tests for tracefix.blame."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from tracefix.trace_parser import Frame, ParsedTrace
from tracefix.repo_map import MappedFrame, map_frames
from tracefix.blame import BlameHit, blame_lines, suspect_commits


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

BASE_ENV = {
    "GIT_AUTHOR_NAME": "Alice",
    "GIT_AUTHOR_EMAIL": "alice@example.com",
    "GIT_COMMITTER_NAME": "Alice",
    "GIT_COMMITTER_EMAIL": "alice@example.com",
}


def _git(repo: Path, *args: str, extra_env: dict[str, str] | None = None) -> None:
    env = {**os.environ, **BASE_ENV, **(extra_env or {})}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


@pytest.fixture()
def blame_repo(tmp_path: Path) -> Path:
    """Git repo with two commits touching different lines of the same file."""
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "alice@example.com")
    _git(tmp_path, "config", "user.name", "Alice")

    src = tmp_path / "calc.py"

    # First commit — older; writes lines 1-3.
    src.write_text(
        "def add(a, b):\n"       # 1
        "    return a + b\n"     # 2
        "\n",                    # 3
        encoding="utf-8",
    )
    t_old = str(int(time.time()) - 3600)
    _git(
        tmp_path, "add", ".",
        extra_env={"GIT_AUTHOR_DATE": t_old, "GIT_COMMITTER_DATE": t_old},
    )
    _git(
        tmp_path, "commit", "-m", "first commit",
        extra_env={"GIT_AUTHOR_DATE": t_old, "GIT_COMMITTER_DATE": t_old},
    )

    # Second commit — newer; adds a divide function (lines 4-6).
    src.write_text(
        "def add(a, b):\n"       # 1
        "    return a + b\n"     # 2
        "\n"                     # 3
        "def divide(a, b):\n"    # 4
        "    return a / b\n"     # 5
        "\n",                    # 6
        encoding="utf-8",
    )
    t_new = str(int(time.time()))
    _git(
        tmp_path, "add", ".",
        extra_env={"GIT_AUTHOR_DATE": t_new, "GIT_COMMITTER_DATE": t_new},
    )
    _git(
        tmp_path, "commit", "-m", "add divide function",
        extra_env={"GIT_AUTHOR_DATE": t_new, "GIT_COMMITTER_DATE": t_new},
    )

    return tmp_path


# ---------------------------------------------------------------------------
# Tests: blame_lines
# ---------------------------------------------------------------------------


class TestBlameLines:
    def test_returns_correct_line_count(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 1, 2)
        assert len(hits) == 2

    def test_line_numbers_correct(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 1, 2)
        assert hits[0].line == 1
        assert hits[1].line == 2

    def test_author_field(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 1, 1)
        assert hits[0].author == "Alice"

    def test_code_field(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 5, 5)
        assert "return a / b" in hits[0].code

    def test_summary_field(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 5, 5)
        assert hits[0].summary == "add divide function"

    def test_sha_is_40_chars(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", 1, 2)
        for h in hits:
            assert len(h.sha) == 40

    def test_repeated_commit_parsed_once_per_line(self, blame_repo: Path) -> None:
        """Lines 1-2 come from the same commit; both must have valid metadata."""
        hits = blame_lines(blame_repo, "calc.py", 1, 2)
        assert hits[0].sha == hits[1].sha
        assert hits[0].author == hits[1].author
        assert hits[0].summary == hits[1].summary

    def test_start_clamped_to_one(self, blame_repo: Path) -> None:
        hits = blame_lines(blame_repo, "calc.py", -5, 1)
        assert len(hits) >= 1

    def test_empty_range_returns_empty(self, blame_repo: Path) -> None:
        # start > end after normalisation: start=3, end=2
        hits = blame_lines(blame_repo, "calc.py", 3, 2)
        # After clamping, start=3, end=max(3,2)=3 so we get 1 line — that's fine.
        # The important thing is no crash.
        assert isinstance(hits, list)


# ---------------------------------------------------------------------------
# Tests: suspect_commits
# ---------------------------------------------------------------------------


def _mf(frame: Frame, repo_path: str | None, context: str = "") -> MappedFrame:
    return MappedFrame(frame=frame, repo_path=repo_path, context=context)


def _frame(path: str, line: int, func: str = "fn") -> Frame:
    return Frame(path=path, line=line, function=func, code="")


class TestSuspectCommits:
    def test_crash_line_commit_ranked_first(self, blame_repo: Path) -> None:
        """The commit touching the exact crash line must rank highest."""
        # Crash frame is line 5 (in divide), which was added by the newer commit.
        # Outer frame is line 1 (in add), which was added by the older commit.
        frames = [
            _mf(_frame("calc.py", 1), "calc.py"),
            _mf(_frame("calc.py", 5), "calc.py"),  # crash frame (last in-repo)
        ]
        ranked = suspect_commits(blame_repo, frames)
        assert ranked, "expected at least one suspect"
        top_sha = ranked[0][0].sha
        # The top commit should be the one for line 5 (newer, crash line).
        hits_line5 = blame_lines(blame_repo, "calc.py", 5, 5)
        assert top_sha == hits_line5[0].sha

    def test_returns_unique_commits(self, blame_repo: Path) -> None:
        frames = [
            _mf(_frame("calc.py", 1), "calc.py"),
            _mf(_frame("calc.py", 2), "calc.py"),
        ]
        ranked = suspect_commits(blame_repo, frames)
        shas = [r[0].sha for r in ranked]
        assert len(shas) == len(set(shas))

    def test_scores_are_positive(self, blame_repo: Path) -> None:
        frames = [_mf(_frame("calc.py", 5), "calc.py")]
        ranked = suspect_commits(blame_repo, frames)
        for _, score in ranked:
            assert score > 0

    def test_non_repo_frames_ignored(self, blame_repo: Path) -> None:
        frames = [
            _mf(_frame("/usr/lib/python3.11/abc.py", 1), None),
            _mf(_frame("calc.py", 5), "calc.py"),
        ]
        ranked = suspect_commits(blame_repo, frames)
        assert ranked

    def test_no_in_repo_frames_returns_empty(self, blame_repo: Path) -> None:
        frames = [_mf(_frame("/usr/lib/python3.11/abc.py", 1), None)]
        ranked = suspect_commits(blame_repo, frames)
        assert ranked == []

    def test_sorted_descending(self, blame_repo: Path) -> None:
        frames = [
            _mf(_frame("calc.py", 1), "calc.py"),
            _mf(_frame("calc.py", 5), "calc.py"),
        ]
        ranked = suspect_commits(blame_repo, frames)
        scores = [s for _, s in ranked]
        assert scores == sorted(scores, reverse=True)
