"""Minimal Agent Client Protocol (ACP) client for driving IBM Bob Shell.

Bob Shell exposes an ACP server over stdio (`bob acp`). It reuses the SSO login
of the interactive shell, so no API key is required.
"""

from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable

EventHandler = Callable[[dict[str, Any]], None]
_STARTUP_LOCK = threading.Lock()


@dataclass
class BobResult:
    """Outcome of one prompt turn sent to Bob."""

    text: str
    stop_reason: str
    tool_calls: list[str] = field(default_factory=list)


class BobSession:
    """A single Bob ACP session bound to a workspace directory."""

    def __init__(
        self,
        workspace: Path,
        mode: str = "agent",
        on_event: EventHandler | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.on_event = on_event or (lambda _event: None)
        self._next_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, Queue[dict[str, Any]]] = {}
        self._updates: Queue[dict[str, Any]] = Queue()
        self._proc = subprocess.Popen(
            ["bob", "acp", "--trust", "--auto-approve", "--accept-license"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=self.workspace,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()
        # Bob persists workspace trust to a shared file; serialise session start-up
        # so parallel agents don't race on it.
        with _STARTUP_LOCK:
            init = {"protocolVersion": 1, "clientCapabilities": {}}
            self._request("initialize", init)
            result = self._request(
                "session/new", {"cwd": str(self.workspace), "mcpServers": []}
            )
        self.session_id: str = result["sessionId"]
        if mode != "agent":
            self._request(
                "session/set_mode", {"sessionId": self.session_id, "modeId": mode}
            )

    def prompt(self, text: str, timeout: float = 900) -> BobResult:
        """Send a prompt and block until Bob finishes the turn."""
        chunks: list[str] = []
        tools: list[str] = []
        req_id = self._send(
            "session/prompt",
            {"sessionId": self.session_id, "prompt": [{"type": "text", "text": text}]},
        )
        while True:
            try:
                update = self._updates.get(timeout=1)
                self._collect(update, chunks, tools)
            except Empty:
                pass
            done = self._responses[req_id]
            if not done.empty():
                response = done.get()
                self._drain(chunks, tools)
                if "error" in response:
                    raise RuntimeError(f"Bob error: {response['error']}")
                reason = response.get("result", {}).get("stopReason", "unknown")
                return BobResult("".join(chunks), reason, tools)
            timeout -= 1
            if timeout <= 0:
                raise TimeoutError("Bob did not finish in time")

    def cancel(self) -> None:
        """Ask Bob to stop the current turn (ACP `session/cancel`)."""
        params = {"sessionId": self.session_id}
        try:
            self._write({"method": "session/cancel", "params": params})
        except (BrokenPipeError, ValueError, OSError):
            pass

    def close(self) -> None:
        """Terminate the Bob ACP process."""
        self._proc.terminate()

    def _collect(
        self, update: dict[str, Any], chunks: list[str], tools: list[str]
    ) -> None:
        self.on_event(update)
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content", {})
            if content.get("type") == "text":
                chunks.append(content["text"])
        elif kind == "tool_call":
            tools.append(update.get("title", "tool"))

    def _drain(self, chunks: list[str], tools: list[str]) -> None:
        while not self._updates.empty():
            self._collect(self._updates.get(), chunks, tools)

    def _send(self, method: str, params: dict[str, Any]) -> int:
        self._next_id += 1
        self._responses[self._next_id] = Queue()
        self._write({"id": self._next_id, "method": method, "params": params})
        return self._next_id

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._responses[self._send(method, params)].get(timeout=120)
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response["result"]

    def _write(self, message: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        with self._lock:
            self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
            self._proc.stdin.flush()

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._dispatch(message)

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "method" not in message:
            self._responses[message["id"]].put(message)
        elif message["method"] == "session/update":
            self._updates.put(message["params"]["update"])
        elif message["method"] == "session/request_permission":
            self._approve(message)
        elif "id" in message:
            self._write({"id": message["id"], "result": None})

    def _approve(self, message: dict[str, Any]) -> None:
        options = message["params"].get("options", [])
        allow = next(
            (o for o in options if o.get("kind", "").startswith("allow")),
            options[0] if options else {"optionId": "allow"},
        )
        outcome = {"outcome": "selected", "optionId": allow["optionId"]}
        self._write({"id": message["id"], "result": {"outcome": outcome}})
