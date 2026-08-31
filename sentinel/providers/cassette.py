"""Cassette record/replay — the reproducibility foundation (docs/spec/02 §4.3).

Every model interaction is recorded once and replayed thereafter, keyed by a
content hash of EVERYTHING that could change the response:

    hash(system + message history + tool manifest + model id + provider
         + policy set version + fixture dataset version)

An incomplete key is the worst failure in the harness — a stale replay looks
like a passing test while answering a question you no longer ask. So the key
includes the policy version and fixture version, not just the prompt: a policy
change alters the denial messages appended to the history, which changes
subsequent turns.

A cassette miss in REPLAY mode is a HARD FAILURE — CI never silently falls
through to the network. Cassettes are committed and contain only synthetic data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sentinel.common.canonical import sha256_hex
from sentinel.providers.base import NormalisedToolCall, ProviderResponse, Usage


class CassetteMissError(Exception):
    """Raised on a replay-mode miss — never a silent fall-through to the network."""


def cassette_key(*, system: str, messages: list[dict], tools: list[dict], model: str,
                 provider: str, policy_version: str, fixture_version: str) -> str:
    return sha256_hex({
        "system": system,
        "messages": messages,
        "tools": [t.get("name", t) for t in tools],
        "model": model,
        "provider": provider,
        "policy_version": policy_version,
        "fixture_version": fixture_version,
    })


def _response_to_dict(r: ProviderResponse) -> dict[str, Any]:
    return {
        "text": r.text,
        "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in r.tool_calls],
        "usage": {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
                  "reported": r.usage.reported},
        "provider": r.provider, "model": r.model, "finish_reason": r.finish_reason,
        "malformed_tool_call": r.malformed_tool_call,
        "raw_assistant_message": r.raw_assistant_message,
    }


def _dict_to_response(d: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        text=d.get("text"),
        tool_calls=tuple(NormalisedToolCall(tc["id"], tc["name"], tc["arguments"])
                         for tc in d.get("tool_calls", [])),
        usage=Usage(**d.get("usage", {})),
        provider=d.get("provider", ""), model=d.get("model", ""),
        finish_reason=d.get("finish_reason", ""),
        malformed_tool_call=d.get("malformed_tool_call", False),
        raw_assistant_message=d.get("raw_assistant_message"),
    )


class CassetteStore:
    """One JSON file per cassette under ``cassettes/``. Committed to the repo."""

    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.refreshed = 0     # cassettes recorded this run (a large number is suspicious)

    def _path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def has(self, key: str) -> bool:
        return self._path(key).exists()

    def load(self, key: str) -> ProviderResponse:
        data = json.loads(self._path(key).read_text())
        return _dict_to_response(data["response"])

    def save(self, key: str, request_meta: dict, response: ProviderResponse) -> None:
        payload = {"key": key, "request": request_meta, "response": _response_to_dict(response)}
        self._path(key).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        self.refreshed += 1
