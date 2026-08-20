"""Provider abstraction — one normalised interface over multiple inference
providers, so the agent loop never branches on which provider served a call.

If the loop ever branches on the active provider, the abstraction has leaked and
must be fixed, not worked around (docs/spec/06 §4.1).

Offline note (ADR-000): the default demo/eval "model" is a deterministic
``ScriptedProvider`` that needs no network. Real OpenAI-compatible adapters
(Groq, Gemini) exist and activate only when a key is present, in record mode; the
cassette layer then makes their responses replayable with no key.
"""

from sentinel.providers.base import (
    NormalisedToolCall,
    Provider,
    ProviderError,
    ProviderResponse,
    Usage,
)
from sentinel.providers.cassette import CassetteMissError, CassetteStore, cassette_key
from sentinel.providers.manager import ProviderManager
from sentinel.providers.scripted import ScriptedProvider

__all__ = [
    "Provider", "ProviderResponse", "NormalisedToolCall", "Usage", "ProviderError",
    "ScriptedProvider", "CassetteStore", "cassette_key", "CassetteMissError",
    "ProviderManager",
]
