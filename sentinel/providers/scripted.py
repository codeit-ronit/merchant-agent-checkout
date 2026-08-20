"""A deterministic provider that stands in for a real model offline.

It delegates to a ``brain`` callable — ``(messages, tools) -> ProviderResponse`` —
supplied by the agent. The brain is deterministic Python: the honest, offline
substitute for an LLM's turn-by-turn decisions. In record mode against a real
provider the same loop runs against Groq/Gemini instead; the loop cannot tell.

Usage is reported as a small fixed token estimate so the meter has something to
attribute; it is clearly labelled ``provider="scripted"`` so nobody mistakes it
for a real cost.
"""

from __future__ import annotations

from typing import Callable

from sentinel.providers.base import ProviderResponse, Usage

Brain = Callable[[list[dict], list[dict]], ProviderResponse]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, brain: Brain, model: str = "scripted-deterministic"):
        self._brain = brain
        self.model = model

    def complete(self, *, messages: list[dict], tools: list[dict], model: str) -> ProviderResponse:
        resp = self._brain(messages, tools)
        # stamp attribution + a nominal usage estimate
        est_in = sum(len(str(m.get("content", ""))) for m in messages) // 4
        est_out = len(resp.text or "") // 4 + 20 * len(resp.tool_calls)
        return ProviderResponse(
            text=resp.text, tool_calls=resp.tool_calls,
            usage=Usage(input_tokens=est_in, output_tokens=est_out, reported=True),
            provider=self.name, model=model or self.model,
            finish_reason=resp.finish_reason or ("tool_calls" if resp.tool_calls else "stop"),
            malformed_tool_call=resp.malformed_tool_call,
        )
