"""Incident reports: JSON (machine), Markdown (PR body) and HTML (shareable)."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tracefix.pipeline import Incident

TEMPLATE = Path(__file__).parent / "report_template.html"


def incident_dict(incident: Incident) -> dict[str, Any]:
    """Serialize an incident for the JSON and HTML reports."""
    return {
        "id": incident.incident_id,
        "exception": incident.trace.exc_type,
        "message": incident.trace.message,
        "branch": incident.branch,
        "baseline_passed": incident.baseline_passed,
        "total_seconds": incident.total_seconds,
        "frames": [
            {
                "path": m.frame.path,
                "line": m.frame.line,
                "function": m.frame.function,
                "code": m.frame.code,
                "repo_path": m.repo_path,
                "context": m.context,
            }
            for m in incident.frames
        ],
        "suspects": [
            {**asdict(hit), "score": round(score, 2)}
            for hit, score in incident.suspects
        ],
        "repro": asdict(incident.repro),
        "fix": asdict(incident.fix),
        "repro_test": incident.repro_test,
        "fix_diff": incident.fix_diff,
    }


def markdown(incident: Incident) -> str:
    """Render a pull-request-ready Markdown summary."""
    data = incident_dict(incident)
    top = data["suspects"][0] if data["suspects"] else None
    crash = next((f for f in reversed(data["frames"]) if f["repo_path"]), None)
    lines = [
        f"## TraceFix incident `{data['id']}`",
        "",
        f"**Production failure:** `{data['exception']}: {data['message']}`",
    ]
    if crash:
        lines.append(
            f"**Crash site:** `{crash['repo_path']}:{crash['line']}` "
            f"in `{crash['function']}()`"
        )
    if top:
        lines.append(
            f"**Suspect commit:** `{top['sha'][:8]}` {top['summary']} — {top['author']}"
        )
    lines += [
        "",
        "| Stage | Result | Attempts | Time |",
        "| --- | --- | --- | --- |",
        _stage_row("Reproduction (Bob)", data["repro"]),
        _stage_row("Fix (Bob)", data["fix"]),
        "",
        f"Total time: **{data['total_seconds']}s**. Branch: `{data['branch']}`.",
        "",
        "### Verified regression test",
        "```python",
        data["repro_test"].rstrip(),
        "```",
        "",
        "### Fix",
        "```diff",
        data["fix_diff"].rstrip(),
        "```",
    ]
    return "\n".join(lines) + "\n"


def html_report(incident: Incident, events: list[dict[str, Any]]) -> str:
    """Render the self-contained HTML report."""
    payload = json.dumps({"incident": incident_dict(incident), "events": events})
    safe = payload.replace("</", "<\\/")
    return (
        TEMPLATE.read_text()
        .replace("__TRACEFIX_DATA__", safe)
        .replace(
            "__TRACEFIX_TITLE__", html.escape(f"TraceFix · {incident.trace.exc_type}")
        )
    )


def write_reports(incident: Incident, out_dir: Path, events_path: Path) -> Path:
    """Write report.json, report.md and report.html; return the HTML path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    (out_dir / "report.json").write_text(json.dumps(incident_dict(incident), indent=2))
    (out_dir / "report.md").write_text(markdown(incident))
    html_path = out_dir / "report.html"
    html_path.write_text(html_report(incident, events))
    return html_path


def _stage_row(name: str, stage: dict[str, Any]) -> str:
    status = (
        "✅ verified" if stage["ok"] else ("❌ failed" if stage["attempts"] else "—")
    )
    return f"| {name} | {status} | {stage['attempts']} | {stage['seconds']}s |"
