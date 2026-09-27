"""Run one build task through IBM Bob (ACP) and keep a transcript as evidence.

Usage: uv run python scripts/bob_task.py <name> <prompt-file> [--mode agent]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tracefix.bob_acp import BobSession

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "bob_sessions"


def main() -> None:
    """Send the prompt file to Bob and log every session update."""
    name, prompt_file = sys.argv[1], Path(sys.argv[2])
    mode = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--mode" else "agent"
    LOG_DIR.mkdir(exist_ok=True)
    log = (LOG_DIR / f"{name}.jsonl").open("w")
    prompt = prompt_file.read_text()

    def handle_event(event: dict) -> None:
        log.write(json.dumps({"t": time.time(), **event}) + "\n")
        log.flush()
        if event.get("sessionUpdate") == "tool_call":
            print(f"[{name}] tool: {event.get('title')}", flush=True)

    started = time.time()
    session = BobSession(ROOT, mode=mode, on_event=handle_event)
    result = session.prompt(prompt, timeout=1800)
    session.close()
    summary = {
        "task": name,
        "session_id": session.session_id,
        "mode": mode,
        "stop_reason": result.stop_reason,
        "seconds": round(time.time() - started, 1),
        "tool_calls": len(result.tool_calls),
        "final_message": result.text,
    }
    (LOG_DIR / f"{name}.summary.json").write_text(json.dumps(summary, indent=2))
    print(result.text)


if __name__ == "__main__":
    main()
