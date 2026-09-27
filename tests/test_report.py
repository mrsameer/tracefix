"""Tests for tracefix.report: markdown, html_report, write_reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracefix.blame import BlameHit
from tracefix.pipeline import Incident, StageResult
from tracefix.report import html_report, markdown, write_reports
from tracefix.repo_map import MappedFrame
from tracefix.trace_parser import Frame, ParsedTrace

# ---------------------------------------------------------------------------
# Helpers — build a realistic Incident by hand
# ---------------------------------------------------------------------------

_FRAME_IN_REPO = Frame(
    path="/srv/app/service/billing.py",
    line=42,
    function="charge",
    code="return process(amount)",
)
_FRAME_OUTSIDE = Frame(
    path="/usr/lib/python3.11/decimal.py",
    line=711,
    function="__truediv__",
    code="raise InvalidOperation",
)

_MAPPED_IN_REPO = MappedFrame(
    frame=_FRAME_IN_REPO,
    repo_path="service/billing.py",
    context="> 42 | return process(amount)",
)
_MAPPED_OUTSIDE = MappedFrame(
    frame=_FRAME_OUTSIDE,
    repo_path=None,
    context="",
)

_BLAME_HIT = BlameHit(
    sha="abcdef1234567890" * 2 + "ab",  # 40-char sha
    author="Alice",
    author_time=1_700_000_000,
    summary="perf: fast path for billing",
    path="service/billing.py",
    line=42,
    code="return process(amount)",
)


def _make_incident() -> Incident:
    """Build a fully-populated Incident for report tests."""
    trace = ParsedTrace(
        exc_type="ZeroDivisionError",
        message="division by zero",
        frames=[_FRAME_IN_REPO, _FRAME_OUTSIDE],
    )
    incident = Incident(
        incident_id="INC-2024-001",
        trace=trace,
        frames=[_MAPPED_IN_REPO, _MAPPED_OUTSIDE],
        suspects=[(_BLAME_HIT, 87.5)],
        branch="tracefix/INC-2024-001",
        repro=StageResult(ok=True, attempts=1, seconds=12.3, session_id="s-abc"),
        fix=StageResult(ok=True, attempts=2, seconds=34.5, session_id="s-def"),
        repro_test="def test_repro():\n    charge(0)\n",
        fix_diff="--- a/service/billing.py\n+++ b/service/billing.py\n@@ -41,1 +41,1 @@\n-    return process(amount)\n+    return process(amount or 1)\n",
        baseline_passed=True,
        total_seconds=50.1,
    )
    return incident


# ---------------------------------------------------------------------------
# markdown() tests
# ---------------------------------------------------------------------------


class TestMarkdown:
    def setup_method(self) -> None:
        self.incident = _make_incident()
        self.md = markdown(self.incident)

    def test_contains_incident_id(self) -> None:
        assert "INC-2024-001" in self.md

    def test_contains_crash_site(self) -> None:
        """The in-repo crash site (last frame with repo_path) must appear."""
        assert "service/billing.py" in self.md
        assert "42" in self.md

    def test_contains_suspect_sha_prefix(self) -> None:
        """First 8 chars of the blame SHA must appear."""
        assert "abcdef12" in self.md

    def test_suspect_summary_and_author(self) -> None:
        assert "perf: fast path for billing" in self.md
        assert "Alice" in self.md

    def test_stage_table_repro_row(self) -> None:
        """The Reproduction row should appear with ✅ and attempt count."""
        assert "Reproduction (Bob)" in self.md
        assert "✅" in self.md

    def test_stage_table_fix_row(self) -> None:
        """The Fix row should appear with ✅ and attempt count."""
        assert "Fix (Bob)" in self.md

    def test_repro_test_fenced_block(self) -> None:
        """The repro test code must be inside a fenced python block."""
        assert "```python" in self.md
        assert "def test_repro():" in self.md

    def test_fix_diff_fenced_block(self) -> None:
        """The fix diff must be inside a fenced diff block."""
        assert "```diff" in self.md
        assert "service/billing.py" in self.md

    def test_exception_type_in_header(self) -> None:
        assert "ZeroDivisionError" in self.md

    def test_no_suspects_graceful(self) -> None:
        """An incident with no suspects renders without errors."""
        inc = _make_incident()
        inc.suspects.clear()
        result = markdown(inc)
        assert "INC-2024-001" in result


# ---------------------------------------------------------------------------
# html_report() tests
# ---------------------------------------------------------------------------


class TestHtmlReport:
    def setup_method(self) -> None:
        self.incident = _make_incident()
        self.events: list[dict] = [
            {"t": 0.1, "stage": "analyze", "kind": "done", "data": {"suspect": "abcdef12 ..."}}
        ]
        self.html = html_report(self.incident, self.events)

    def test_title_contains_exception_type(self) -> None:
        """The <title> element must contain the exception type."""
        assert "ZeroDivisionError" in self.html
        assert "<title>" in self.html

    def test_json_payload_embedded(self) -> None:
        """The JSON payload must be present inside the script#data element."""
        assert '"INC-2024-001"' in self.html

    def test_script_close_tag_escaped(self) -> None:
        """</script> inside the JSON payload must be escaped to <\\/script>."""
        # Inject a </script> string into repro_test and regenerate
        inc = _make_incident()
        inc.repro_test = "x = '</script>injected'"
        result = html_report(inc, [])
        # The raw </script> must NOT appear unescaped inside the JSON data block
        # (the template replaces </ with <\/)
        data_section = result.split('<script id="data"')[1].split("</script>")[0]
        assert "</script>" not in data_section

    def test_html_is_not_empty(self) -> None:
        assert len(self.html) > 500


# ---------------------------------------------------------------------------
# write_reports() tests
# ---------------------------------------------------------------------------


class TestWriteReports:
    def _make_events_jsonl(self, path: Path) -> None:
        events = [
            {"t": 0.1, "stage": "analyze", "kind": "done", "data": {"suspect": None}},
            {"t": 1.0, "stage": "repro", "kind": "verify", "data": {"ok": True, "detail": "ok"}},
        ]
        path.write_text("\n".join(json.dumps(e) for e in events) + "\n")

    def test_all_three_files_written(self, tmp_path: Path) -> None:
        """write_reports must produce report.json, report.md, and report.html."""
        out_dir = tmp_path / "out"
        events_path = tmp_path / "events.jsonl"
        self._make_events_jsonl(events_path)
        html_path = write_reports(_make_incident(), out_dir, events_path)
        assert (out_dir / "report.json").exists()
        assert (out_dir / "report.md").exists()
        assert (out_dir / "report.html").exists()
        assert html_path == out_dir / "report.html"

    def test_json_is_valid_and_has_id(self, tmp_path: Path) -> None:
        """report.json must be valid JSON containing the incident id."""
        out_dir = tmp_path / "out"
        events_path = tmp_path / "events.jsonl"
        self._make_events_jsonl(events_path)
        write_reports(_make_incident(), out_dir, events_path)
        data = json.loads((out_dir / "report.json").read_text())
        assert data["id"] == "INC-2024-001"

    def test_md_contains_crash_site(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        events_path = tmp_path / "events.jsonl"
        self._make_events_jsonl(events_path)
        write_reports(_make_incident(), out_dir, events_path)
        md = (out_dir / "report.md").read_text()
        assert "service/billing.py" in md

    def test_html_contains_incident_id(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "out"
        events_path = tmp_path / "events.jsonl"
        self._make_events_jsonl(events_path)
        write_reports(_make_incident(), out_dir, events_path)
        html_text = (out_dir / "report.html").read_text()
        assert "INC-2024-001" in html_text
