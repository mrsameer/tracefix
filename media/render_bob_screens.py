# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright"]
# ///
"""Render captured Bob Shell TUI sessions (raw pty bytes) to PNG via xterm.js.

The raw captures come from `bob -r <task-id>` run in a 150x45 pseudo-terminal.
Only redaction: the Bob account e-mail on the "Logged in as" line.

Usage: uv run media/render_bob_screens.py
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

MEDIA = Path(__file__).resolve().parent
TASKS = ("01_demo_repo", "02_parser_blame", "03_gate_tests")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")
PAGE = """<!doctype html><html><head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css">
<script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.js"></script>
<style>body{margin:0;background:#0b0e14;padding:18px}
.cap{color:#9aa3b5;font:14px Inter,system-ui,sans-serif;margin:0 0 10px 4px}
.cap b{color:#eef1f6}</style></head><body>
<div class="cap"><b>IBM Bob Shell</b> · task session __TASK__ (__ID__) · resumed with <code>bob -r</code></div>
<div id="t"></div><script>
const term = new Terminal({cols: 150, rows: 45, fontSize: 13, fontFamily: 'Menlo, monospace',
  theme: {background: '#0b0e14'}, allowProposedApi: true});
term.open(document.getElementById('t'));
const bytes = Uint8Array.from(atob('__DATA__'), c => c.charCodeAt(0));
term.write(bytes, () => { document.body.dataset.done = '1'; });
</script></body></html>"""


def main() -> None:
    """Write media/bob_screens/<task>.png for each captured session."""
    out_dir = MEDIA / "bob_screens"
    out_dir.mkdir(exist_ok=True)
    summaries = {p.stem.split(".")[0]: p for p in (MEDIA.parent / "bob_sessions").glob("*.summary.json")}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for task in TASKS:
            page = browser.new_page(
                viewport={"width": 1180, "height": 760}, device_scale_factor=2
            )
            raw = (MEDIA / "build" / f"{task}.raw").read_bytes()
            raw = EMAIL.sub(b"[redacted]", raw)
            session = re.search(r'"session_id": "(\w+)"', summaries[task].read_text())
            html = (PAGE.replace("__DATA__", base64.b64encode(raw).decode())
                    .replace("__TASK__", task).replace("__ID__", session.group(1) if session else "?"))
            page.set_content(html)
            page.wait_for_function("document.body.dataset.done === \"1\"", timeout=15000)
            page.wait_for_timeout(500)
            box = page.locator("body").bounding_box()
            page.screenshot(path=out_dir / f"{task}.png", full_page=True)
            print(task, box)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
