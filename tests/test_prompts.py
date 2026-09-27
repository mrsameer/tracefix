"""Tests for tracefix.prompts: repro_prompt, fix_prompt, retry_prompt."""

from __future__ import annotations

import pytest

from tracefix.blame import BlameHit
from tracefix.pipeline import Incident, StageResult
from tracefix.prompts import fix_prompt, repro_prompt, retry_prompt
from tracefix.repo_map import MappedFrame
from tracefix.trace_parser import Frame, ParsedTrace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_PATH = "tests/test_tracefix_repro.py"


def _make_incident() -> Incident:
    """Minimal but realistic Incident for prompt tests."""
    trace = ParsedTrace(
        exc_type="KeyError",
        message="'user_id'",
        frames=[
            Frame(path="/app/api/views.py", line=55, function="get_user", code="return db[key]"),
            Frame(path="/app/core/db.py", line=12, function="lookup", code="return self._cache[key]"),
        ],
    )
    frames = [
        MappedFrame(
            frame=trace.frames[0],
            repo_path="api/views.py",
            context="> 55 | return db[key]",
        ),
        MappedFrame(
            frame=trace.frames[1],
            repo_path="core/db.py",
            context="> 12 | return self._cache[key]",
        ),
    ]
    return Incident(
        incident_id="INC-TEST-007",
        trace=trace,
        frames=frames,
        suspects=[],
        branch="tracefix/INC-TEST-007",
        repro=StageResult(ok=False),
        fix=StageResult(ok=False),
    )


# ---------------------------------------------------------------------------
# repro_prompt tests
# ---------------------------------------------------------------------------


class TestReproPrompt:
    def setup_method(self) -> None:
        self.incident = _make_incident()
        self.prompt = repro_prompt(self.incident, _TEST_PATH)

    def test_names_test_path(self) -> None:
        """The exact test file path must appear in the prompt."""
        assert _TEST_PATH in self.prompt

    def test_names_exception_type(self) -> None:
        """The production exception type must be stated."""
        assert "KeyError" in self.prompt

    def test_names_crash_function(self) -> None:
        """The crashing function (last frame) must be named."""
        assert "lookup" in self.prompt

    def test_forbids_editing_other_files(self) -> None:
        """Bob must be told not to modify files other than the test path."""
        lower = self.prompt.lower()
        # 'do not modify any file other than' or similar phrasing
        assert "do not modify" in lower or "not modify" in lower

    def test_incident_id_included(self) -> None:
        """The incident id should appear so the docstring can reference it."""
        assert "INC-TEST-007" in self.prompt

    def test_includes_run_instruction(self) -> None:
        """Must tell Bob to run pytest on the test path."""
        assert _TEST_PATH in self.prompt
        assert "pytest" in self.prompt.lower()


# ---------------------------------------------------------------------------
# fix_prompt tests
# ---------------------------------------------------------------------------


class TestFixPrompt:
    def setup_method(self) -> None:
        self.incident = _make_incident()
        self.prompt = fix_prompt(self.incident, _TEST_PATH)

    def test_names_test_path(self) -> None:
        """The repro test path must appear so Bob knows what to leave alone."""
        assert _TEST_PATH in self.prompt

    def test_forbids_editing_test(self) -> None:
        """Bob must be explicitly told not to edit the test file."""
        lower = self.prompt.lower()
        assert "must not edit" in lower or "not edit" in lower or "not modify" in lower

    def test_full_suite_instruction(self) -> None:
        """Bob must be told to run the full suite."""
        assert "pytest" in self.prompt.lower()

    def test_names_exception_in_brief(self) -> None:
        """The incident brief (embedded) must still contain the exception type."""
        assert "KeyError" in self.prompt


# ---------------------------------------------------------------------------
# retry_prompt tests
# ---------------------------------------------------------------------------


class TestRetryPrompt:
    def test_contains_detail(self) -> None:
        """Short details pass through verbatim."""
        detail = "the test raised ValueError, not KeyError"
        result = retry_prompt(detail)
        assert detail in result

    def test_truncates_long_detail(self) -> None:
        """Details longer than 4000 chars must be truncated to at most 4000 chars."""
        long_detail = "x" * 10_000
        result = retry_prompt(long_detail)
        # The slice [:4000] should have been applied — the result must not
        # contain all 10 000 chars of the detail.
        assert long_detail not in result
        # But it must contain the first 4000 chars.
        assert "x" * 4000 in result

    def test_exact_4000_chars_not_truncated(self) -> None:
        """Exactly 4000 chars of detail passes through without truncation."""
        detail = "y" * 4000
        result = retry_prompt(detail)
        assert detail in result

    def test_prompt_mentions_rejection(self) -> None:
        """The retry prompt must clearly communicate that verification failed."""
        result = retry_prompt("something went wrong")
        lower = result.lower()
        assert "rejected" in lower or "verification" in lower
