"""Provider factory: the one place that chooses scripted (offline) vs live (real
providers) and builds the failover chain. These are the load-bearing guarantees
that keep the loop provider-agnostic (CLAUDE.md rule 5a) and the offline no-key
path untouched by the live wiring."""

from __future__ import annotations

import pytest

from sentinel.providers import factory
from sentinel.providers.base import ProviderResponse
from sentinel.providers.openai_adapter import OpenAICompatibleProvider
from sentinel.providers.scripted import ScriptedProvider

pytestmark = pytest.mark.tier1

FAKE_CFG = {
    "failover_order": ["groq", "gemini"],
    "providers": {
        "groq": {"base_url": "https://groq/v1", "api_key_env": "TEST_A_KEY",
                 "usage_fields": {"input": "prompt_tokens", "output": "completion_tokens"},
                 "models": {"strong": {"id": "g-120", "limits": {"rpm": 30, "rpd": 1000}},
                            "weak": {"id": "g-20", "limits": {"rpm": 30, "rpd": 1000}}}},
        "gemini": {"base_url": "https://gem/v1", "api_key_env": "TEST_B_KEY",
                   "usage_fields": {"input": "prompt_tokens", "output": "completion_tokens"},
                   "models": {"strong": {"id": "gem-flash", "limits": {"rpm": 10, "rpd": 250}},
                              "weak": {"id": "gem-lite", "limits": {"rpm": 15, "rpd": 1000}}}},
    },
}

BRAIN = lambda m, t: ProviderResponse(text="ok", provider="scripted", model="b")


def test_tier_resolution():
    assert factory._tier_of("reconciliation-strong", None) == "strong"
    assert factory._tier_of("x-weak", None) == "weak"
    assert factory._tier_of(None, "weak") == "weak"          # explicit tier wins
    assert factory._tier_of("no-tier-here", None) == "strong"  # safe default


def test_live_providers_built_in_failover_order_with_model_map(monkeypatch):
    monkeypatch.setenv("TEST_A_KEY", "k1")
    monkeypatch.setenv("TEST_B_KEY", "k2")
    providers, limits, notes = factory.build_live_providers("strong", FAKE_CFG)
    assert [p.name for p in providers] == ["groq", "gemini"]        # failover order preserved
    assert all(isinstance(p, OpenAICompatibleProvider) for p in providers)
    # the adapter carries the tier->real-id map, so the loop only ever sends a tier
    assert providers[0].model_map == {"strong": "g-120", "weak": "g-20"}
    assert limits["gemini"] == {"rpm": 10, "rpd": 250}


def test_live_skips_provider_without_key(monkeypatch):
    monkeypatch.setenv("TEST_A_KEY", "k1")
    monkeypatch.delenv("TEST_B_KEY", raising=False)
    providers, limits, notes = factory.build_live_providers("strong", FAKE_CFG)
    assert [p.name for p in providers] == ["groq"]                 # gemini dropped
    assert any("gemini" in n and "no key" in n for n in notes)     # never silently
    assert "gemini" not in limits


def test_build_manager_offline_is_scripted(monkeypatch):
    monkeypatch.delenv("SENTINEL_LIVE", raising=False)
    mgr, call_model = factory.build_manager(
        brain=BRAIN, model_id="reconciliation-strong", model_tier=None,
        cassette_dir="cassettes/evals", cassette_mode="replay", policy_version="1",
        fixture_version="1", system_prompt="s", clock_ms=lambda: 0)
    assert isinstance(mgr.providers[0], ScriptedProvider)
    assert mgr.providers[0].name == "scripted"
    assert call_model == "reconciliation-strong"                   # scripted uses full id
    assert mgr.cassettes.dir.name == "evals"                       # offline dir untouched


def test_build_manager_live_uses_real_providers_and_separate_dir(monkeypatch):
    monkeypatch.setenv("SENTINEL_LIVE", "1")
    monkeypatch.setenv("TEST_A_KEY", "k1")
    monkeypatch.setenv("TEST_B_KEY", "k2")
    monkeypatch.setattr(factory, "load_yaml", lambda name: FAKE_CFG)
    mgr, call_model = factory.build_manager(
        brain=BRAIN, model_id="reconciliation-weak", model_tier="weak",
        cassette_dir="cassettes/evals", cassette_mode="record", policy_version="1",
        fixture_version="1", system_prompt="s", clock_ms=lambda: 0)
    assert mgr.providers[0].name == "groq"                          # primary
    assert call_model == "weak"                                     # loop sends the tier
    assert mgr.cassettes.dir.name == "live"                         # NOT the offline dir
    assert mgr.governor is not None and mgr.provider_limits["groq"]["rpd"] == 1000


def test_build_manager_live_without_keys_falls_back_to_scripted(monkeypatch):
    monkeypatch.setenv("SENTINEL_LIVE", "1")
    monkeypatch.delenv("TEST_A_KEY", raising=False)
    monkeypatch.delenv("TEST_B_KEY", raising=False)
    monkeypatch.setattr(factory, "load_yaml", lambda name: FAKE_CFG)
    mgr, call_model = factory.build_manager(
        brain=BRAIN, model_id="reconciliation-strong", model_tier="strong",
        cassette_dir="cassettes/evals", cassette_mode="replay", policy_version="1",
        fixture_version="1", system_prompt="s", clock_ms=lambda: 0)
    assert isinstance(mgr.providers[0], ScriptedProvider)           # fail-safe
    assert mgr.cassettes.dir.name == "evals"
