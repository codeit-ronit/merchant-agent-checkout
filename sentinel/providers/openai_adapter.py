"""OpenAI-compatible adapter — covers BOTH selected providers (Groq, Gemini)
because both speak POST /chat/completions with tools=[...] and return
``tool_calls[].function.arguments`` as a JSON string (ADR-002a).

Only used in RECORD/LIVE mode when a key is present; the default offline path
never constructs this. It normalises: JSON-string arguments -> dict, usage field
names, and 429 rate-limit signalling with retry-after.
"""

from __future__ import annotations

import json
import os

from sentinel.providers.base import (
    NormalisedToolCall,
    ProviderError,
    ProviderResponse,
    Usage,
)


class OpenAICompatibleProvider:
    def __init__(self, name: str, base_url: str, api_key_env: str, usage_fields: dict):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self._usage_fields = usage_fields

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, *, messages: list[dict], tools: list[dict], model: str) -> ProviderResponse:
        if not self.api_key:
            raise ProviderError(f"{self.name}: no API key set (offline). Use fixture/replay mode.")
        import httpx  # local import: never needed on the offline path

        payload = {
            "model": model, "messages": messages,
            "tools": [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object"})}} for t in tools],
            "temperature": 0,
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions",
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json=payload, timeout=60)
        except Exception as exc:  # network error
            raise ProviderError(f"{self.name}: transport error: {exc}") from exc

        if resp.status_code == 429:
            ra = resp.headers.get("retry-after")
            raise ProviderError(f"{self.name}: rate limited", rate_limited=True,
                                retry_after_ms=int(float(ra) * 1000) if ra else None)
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        usage = data.get("usage", {})
        u = Usage(
            input_tokens=usage.get(self._usage_fields["input"], 0),
            output_tokens=usage.get(self._usage_fields["output"], 0),
            reported=bool(usage),
        )
        tool_calls = []
        malformed = False
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if not isinstance(args, dict):
                    raise ValueError("arguments not an object")
            except Exception:
                malformed = True   # never guess the intended arguments
                args = {}
            tool_calls.append(NormalisedToolCall(tc.get("id", ""), fn.get("name", ""), args))

        return ProviderResponse(
            text=msg.get("content"), tool_calls=tuple(tool_calls), usage=u,
            provider=self.name, model=model,
            finish_reason=choice.get("finish_reason", ""), malformed_tool_call=malformed,
        )
