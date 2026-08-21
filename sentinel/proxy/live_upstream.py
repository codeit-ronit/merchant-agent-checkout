"""``LiveUpstream`` — a real MCP client to the published ``razorpay/mcp`` server.

This is the counterpart to ``FixtureUpstream``: it satisfies the same ``Upstream``
interface (``list_tools`` / ``call_tool``) but speaks the MCP protocol to a live
razorpay-mcp-server instance running with TEST-MODE keys. The proxy, policy
engine, redaction, and audit sit on top unchanged — so the identical enforcement
that the fixture demonstrates runs against the genuine API.

Two hard rules enforced here:
* **Test mode only.** A key not beginning ``rzp_test_`` is rejected before any
  connection is opened. A ``rzp_live_`` key raises.
* **Never in the public demo / never committed.** This path is opt-in
  (``SENTINEL_MODE=live``) and used locally to validate parity + a read + a policy
  denial against the real server. Evals and the red-team stay on the fixture.

Transport: connects to the server over MCP stdio (default: `docker run -i` the
image) or a streamable-HTTP URL. The MCP SDK client is async; this class bridges
to the synchronous ``Upstream`` interface with a dedicated event-loop thread that
owns a long-lived session.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from typing import Any


class LiveKeyError(RuntimeError):
    """Raised when a non-test-mode key is supplied. Test mode only, ever."""


def require_test_mode(key_id: str | None) -> str:
    key = (key_id or os.environ.get("RAZORPAY_KEY_ID") or "").strip()
    if not key:
        raise LiveKeyError("RAZORPAY_KEY_ID is not set. Live mode needs a rzp_test_ key.")
    if key.startswith("rzp_live_"):
        raise LiveKeyError("REFUSING a live key. SENTINEL is test-mode only (rzp_test_*).")
    if not key.startswith("rzp_test_"):
        raise LiveKeyError(f"key '{key[:8]}…' is not a rzp_test_ key; refusing to connect.")
    return key


def _content_to_result(call_result: Any) -> dict[str, Any]:
    """Normalise an MCP CallToolResult into the plain dict our proxy expects.
    razorpay-mcp returns JSON text content; parse it, else wrap the text."""
    parts = []
    for item in getattr(call_result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
    blob = "\n".join(parts) if parts else ""
    try:
        return json.loads(blob) if blob else {}
    except Exception:
        return {"text": blob}


class LiveUpstream:
    """Synchronous wrapper over an async MCP client session."""

    def __init__(self, *, command: str | None = None, args: list[str] | None = None,
                 url: str | None = None, env: dict[str, str] | None = None):
        require_test_mode((env or {}).get("RAZORPAY_KEY_ID"))
        self._command = command
        self._args = args or []
        self._url = url
        self._env = env or {}
        self._q: "queue.Queue" = queue.Queue()
        self._ready = threading.Event()
        self._err: Exception | None = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=30)
        if self._err:
            raise self._err

    # ---- Upstream interface ----
    def list_tools(self) -> list[dict[str, Any]]:
        return self._submit(("list_tools", None, None))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._submit(("call_tool", name, arguments))

    def close(self) -> None:
        self._q.put(("__stop__", None, None, None))

    # ---- async worker (owns the session for its lifetime) ----
    def _submit(self, cmd) -> Any:
        result_box: "queue.Queue" = queue.Queue(maxsize=1)
        self._q.put((*cmd, result_box))
        ok, value = result_box.get()
        if not ok:
            raise value
        return value

    def _run_loop(self) -> None:
        import asyncio
        try:
            asyncio.run(self._serve())
        except Exception as exc:  # pragma: no cover - connection/setup failure
            self._err = exc
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession
        # choose transport
        if self._url:
            from mcp.client.streamable_http import streamablehttp_client
            ctx = streamablehttp_client(self._url)
            async with ctx as (read, write, *_):
                await self._session_loop(ClientSession, read, write)
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=self._command or "docker",
                                           args=self._args, env={**os.environ, **self._env})
            async with stdio_client(params) as (read, write):
                await self._session_loop(ClientSession, read, write)

    async def _session_loop(self, ClientSession, read, write) -> None:
        import asyncio
        async with ClientSession(read, write) as session:
            await session.initialize()
            self._ready.set()
            loop = asyncio.get_running_loop()
            while True:
                op, name, args, box = await loop.run_in_executor(None, self._q.get)
                if op == "__stop__":
                    return
                try:
                    if op == "list_tools":
                        res = await session.list_tools()
                        value = [t.model_dump(by_alias=True) if hasattr(t, "model_dump")
                                 else {"name": t.name, "description": t.description,
                                       "inputSchema": t.inputSchema}
                                 for t in res.tools]
                        # normalise key name to inputSchema for our classifier
                        for v in value:
                            if "inputSchema" not in v and "input_schema" in v:
                                v["inputSchema"] = v.pop("input_schema")
                    else:
                        res = await session.call_tool(name, args or {})
                        value = _content_to_result(res)
                    box.put((True, value))
                except Exception as exc:
                    box.put((False, exc))
