"""Provider abstraction: normalisation conformance, cassette record/replay,
replay-miss-is-hard-failure, and the startup model probe (docs/spec/06 §4)."""

from __future__ import annotations

import json

import pytest

from sentinel.providers.base import NormalisedToolCall, ProviderError, ProviderResponse
from sentinel.providers.cassette import CassetteMissError, CassetteStore, cassette_key
from sentinel.providers.manager import ManagerConfig, ProviderManager
from sentinel.providers.scripted import ScriptedProvider

pytestmark = pytest.mark.tier1


def test_scripted_provider_normalises_and_attributes():
    brain = lambda m, t: ProviderResponse(tool_calls=(NormalisedToolCall("1", "fetch_payment", {"payment_id": "pay_X"}),))
    p = ScriptedProvider(brain, model="brain")
    resp = p.complete(messages=[{"role": "user", "content": "hi"}], tools=[], model="brain")
    assert resp.provider == "scripted" and resp.has_tool_calls
    assert resp.tool_calls[0].arguments == {"payment_id": "pay_X"}
    assert resp.usage.reported


def test_openai_adapter_normalises_json_string_arguments(monkeypatch):
    """Conformance: arguments arrive as a JSON STRING and must be parsed to a
    dict; usage field names normalised."""
    from sentinel.providers import openai_adapter as oa

    class FakeResp:
        status_code = 200
        headers = {}
        def json(self):
            return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
                    "tool_calls": [{"id": "call_1", "type": "function",
                    "function": {"name": "create_refund", "arguments": json.dumps({"payment_id": "pay_X", "amount": 500})}}]}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    p = oa.OpenAICompatibleProvider("groq", "https://x/v1", "SOME_ENV", {"input": "prompt_tokens", "output": "completion_tokens"})
    p.api_key = "test"  # pretend a key is set
    resp = p.complete(messages=[], tools=[], model="m")
    assert resp.tool_calls[0].arguments == {"payment_id": "pay_X", "amount": 500}   # parsed to dict
    assert resp.usage.input_tokens == 12 and resp.usage.output_tokens == 5
    assert not resp.malformed_tool_call


def test_openai_adapter_flags_malformed_arguments(monkeypatch):
    from sentinel.providers import openai_adapter as oa

    class FakeResp:
        status_code = 200
        headers = {}
        def json(self):
            return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None,
                    "tool_calls": [{"id": "c", "function": {"name": "create_refund", "arguments": "{not json"}}]}}],
                    "usage": {}}

    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp())
    p = oa.OpenAICompatibleProvider("groq", "https://x/v1", "E", {"input": "prompt_tokens", "output": "completion_tokens"})
    p.api_key = "test"
    resp = p.complete(messages=[], tools=[], model="m")
    assert resp.malformed_tool_call and resp.tool_calls[0].arguments == {}   # never guessed


def test_cassette_record_then_replay(tmp_path):
    store = CassetteStore(tmp_path)
    brain = lambda m, t: ProviderResponse(text="done", provider="scripted", model="b")
    provider = ScriptedProvider(brain, model="b")
    rec = ProviderManager([provider], store, ManagerConfig(mode="record", policy_version="1", fixture_version="1"))
    r1 = rec.complete(messages=[{"role": "user", "content": "x"}], tools=[], model="b")
    assert r1.text == "done" and store.refreshed == 1

    replay = ProviderManager([provider], store, ManagerConfig(mode="replay", policy_version="1", fixture_version="1"))
    r2 = replay.complete(messages=[{"role": "user", "content": "x"}], tools=[], model="b")
    assert r2.text == "done"


@pytest.mark.critical
def test_cassette_miss_in_replay_is_hard_failure(tmp_path):
    store = CassetteStore(tmp_path)
    provider = ScriptedProvider(lambda m, t: ProviderResponse(text="x"), model="b")
    replay = ProviderManager([provider], store, ManagerConfig(mode="replay", policy_version="1", fixture_version="1"))
    with pytest.raises(CassetteMissError):
        replay.complete(messages=[{"role": "user", "content": "never recorded"}], tools=[], model="b")


def test_cassette_key_includes_policy_and_fixture_version():
    base = dict(system="s", messages=[{"role": "user", "content": "m"}], tools=[], model="m", provider="p")
    k1 = cassette_key(**base, policy_version="1", fixture_version="1")
    k2 = cassette_key(**base, policy_version="2", fixture_version="1")   # policy changed
    k3 = cassette_key(**base, policy_version="1", fixture_version="2")   # fixture changed
    assert k1 != k2 != k3 and k1 != k3   # any change invalidates the replay


def test_startup_probe_refuses_on_unavailable_model():
    class Dead:
        name = "dead"
        def complete(self, **k): raise ProviderError("model gone")
    mgr = ProviderManager([Dead()], CassetteStore("cassettes/_probe_test"),
                          ManagerConfig(mode="record"))
    with pytest.raises(RuntimeError) as exc:
        mgr.probe("some-model")
    assert "some-model" in str(exc.value)


def test_failover_to_secondary_on_rate_limit(tmp_path):
    class Primary:
        name = "primary"
        def complete(self, **k): raise ProviderError("429", rate_limited=True)
    class Secondary:
        name = "secondary"
        def complete(self, **k): return ProviderResponse(text="served by B", provider="secondary", model=k["model"])
    mgr = ProviderManager([Primary(), Secondary()], CassetteStore(tmp_path),
                          ManagerConfig(mode="record"))
    resp = mgr.complete(messages=[{"role": "user", "content": "x"}], tools=[], model="m")
    assert resp.provider == "secondary" and mgr.failover_count == 1
