"""Build the static GitHub Pages site from a recorded TraceFix run.

Usage: uv run python scripts/build_site.py out/INC-4127
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REPORT_TEMPLATE = ROOT / "tracefix" / "report_template.html"


def main() -> None:
    """Inject the recorded run into the replay page and copy the report."""
    run_dir = Path(sys.argv[1])
    incident = json.loads((run_dir / "report.json").read_text())
    events = [
        json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()
    ]
    payload = json.dumps({"incident": incident, "events": events}).replace("</", "<\\/")
    template = (SITE / "demo_template.html").read_text()
    (SITE / "demo.html").write_text(template.replace("__TRACEFIX_DATA__", payload))
    report = REPORT_TEMPLATE.read_text().replace("__TRACEFIX_DATA__", payload)
    title = f"TraceFix · {incident['exception']}"
    (SITE / "report.html").write_text(report.replace("__TRACEFIX_TITLE__", title))
    runs = SITE / "runs" / run_dir.name
    runs.mkdir(parents=True, exist_ok=True)
    for name in ("report.json", "report.md", "events.jsonl"):
        shutil.copy(run_dir / name, runs / name)
    print(f"site built from {run_dir}")


if __name__ == "__main__":
    main()
