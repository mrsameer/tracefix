"""Build the static GitHub Pages site from recorded TraceFix runs.

Usage: uv run python scripts/build_site.py out/INC-4127 [out/INC-4133 ...]

The first run is featured as `demo.html` / `report.html`; every run also gets
`runs/<id>/replay.html` and `runs/<id>/report.html`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPORT_TEMPLATE = ROOT / "tracefix" / "report_template.html"
REPLAY_TEMPLATE = SITE / "demo_template.html"


def main() -> None:
    """Render replay and report pages for each recorded run."""
    run_dirs = [Path(arg) for arg in sys.argv[1:]]
    for index, run_dir in enumerate(run_dirs):
        replay, report = render(run_dir)
        target = SITE / "runs" / run_dir.name
        target.mkdir(parents=True, exist_ok=True)
        (target / "replay.html").write_text(replay)
        (target / "report.html").write_text(report)
        for name in ("report.json", "report.md", "events.jsonl"):
            shutil.copy(run_dir / name, target / name)
        if index == 0:
            (SITE / "demo.html").write_text(replay)
            (SITE / "report.html").write_text(report)
    print(f"site built from {len(run_dirs)} run(s)")


def render(run_dir: Path) -> tuple[str, str]:
    """Return (replay_html, report_html) for one recorded run."""
    incident = json.loads((run_dir / "report.json").read_text())
    lines = (run_dir / "events.jsonl").read_text().splitlines()
    events = [json.loads(line) for line in lines]
    payload = json.dumps({"incident": incident, "events": events}).replace("</", "<\\/")
    replay = REPLAY_TEMPLATE.read_text().replace("__TRACEFIX_DATA__", payload)
    title = f"TraceFix · {incident['exception']}"
    report = REPORT_TEMPLATE.read_text().replace("__TRACEFIX_DATA__", payload)
    return replay, report.replace("__TRACEFIX_TITLE__", title)


if __name__ == "__main__":
    main()
