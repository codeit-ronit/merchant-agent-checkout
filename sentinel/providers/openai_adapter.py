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
    def __init__(self, name: str, base_url: str, api_key_env: str, usage_fields: dict,
                 model_map: dict | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self._usage_fields = usage_fields
        # logical tier ("strong"/"weak") -> the provider's real model id. Empty map
        # means the caller already passes a real id (pass-through). This is the only
        # place the tier->id translation happens, so the loop stays tier-only.
        self.model_map = model_map or {}

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, *, messages: list[dict], tools: list[dict], model: str) -> ProviderResponse:
        if not self.api_key:
            raise ProviderError(f"{self.name}: no API key set (offline). Use fixture/replay mode.")
        import httpx  # local import: never needed on the offline path

        real_model = self.model_map.get(model, model)
        payload = {
            "model": real_model, "messages": messages,
            "tools": [{"type": "function", "function": {
                "name": t["name"], "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object"})}} for t in tools],
            "temperature": 0,
        }
        def _post():
            return httpx.post(f"{self.base_url}/chat/completions",
                              headers={"Authorization": f"Bearer {self.api_key}"},
                              json=payload, timeout=240)  # thinking models routinely exceed 60s (ADR-042)

        try:
            resp = _post()
            if resp.status_code in (502, 503, 504):
                # transient capacity blips ("high demand") — one paced retry
                # before surfacing; killing a 12-step run over one 503 wastes
                # every recorded step before it (ADR-042).
                import time as _time
                _time.sleep(10)
                resp = _post()
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
            raw_assistant_message=msg,
            provider=self.name, model=real_model,   # record the REAL id served, not the tier
            finish_reason=choice.get("finish_reason", ""), malformed_tool_call=malformed,
        )
