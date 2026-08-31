"""The single normalised interface. Everything provider-specific lives behind
this line."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


class ProviderError(Exception):
    """Any provider-side failure. Carries whether it is a rate-limit (429)."""

    def __init__(self, message: str, *, rate_limited: bool = False, retry_after_ms: int | None = None):
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after_ms = retry_after_ms


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # None when the provider reports no usage — recorded as a gap, never invented.
    reported: bool = True


@dataclass(frozen=True)
class NormalisedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]     # already parsed from the provider's JSON-string form


@dataclass(frozen=True)
class ProviderResponse:
    """Normalised across providers. Either ``text`` (run done) or ``tool_calls``."""

    text: Optional[str] = None
    tool_calls: tuple[NormalisedToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    provider: str = ""
    model: str = ""
    finish_reason: str = ""
    malformed_tool_call: bool = False   # provider emitted an unparseable tool call
    # The provider's assistant message EXACTLY as returned, for echoing back
    # into history. Providers attach fields the protocol requires round-tripped
    # (Gemini 3.x: thought_signature on functionCall parts) — reconstruction
    # from normalised fields drops them, so the raw dict is kept (ADR-042).
    raw_assistant_message: Optional[dict] = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class Provider(Protocol):
    """Given messages and a tool manifest, return a normalised response."""

    name: str

    def complete(self, *, messages: list[dict], tools: list[dict], model: str) -> ProviderResponse: ...
