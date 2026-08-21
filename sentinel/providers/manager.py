"""ProviderManager — cassette record/replay in front of one or more providers,
with failover and a startup model probe. The agent loop talks only to this.

Modes (SENTINEL_CASSETTE):
* ``replay`` — serve from cassettes only; a miss is a HARD FAILURE. CI + anyone
  reproducing the numbers. Zero network.
* ``record`` — call the provider(s), persist each interaction.
* ``auto`` — replay on hit, record on miss. Default for local development.

Failover: on a rate-limit or transient error, back off then fail over to the
secondary provider. The provider that actually served each call is recorded so
the trace and RunRecord can attribute it (a latency number that does not name its
provider is meaningless under failover).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sentinel.providers.base import Provider, ProviderError, ProviderResponse
from sentinel.providers.cassette import CassetteMissError, CassetteStore, cassette_key


@dataclass
class ManagerConfig:
    mode: str = "auto"                 # replay | record | auto
    policy_version: str = "0"
    fixture_version: str = "0"
    system_prompt: str = ""


class ProviderManager:
    # process-wide record of (provider, model) pairs already probed, so a bulk
    # live run probes each model once, not once per scenario (each probe is a
    # real network call that counts against the free-tier daily limit).
    _probed: set = set()

    def __init__(self, providers: list[Provider], cassettes: CassetteStore,
                 config: ManagerConfig, governor=None, provider_limits: dict | None = None):
        assert providers, "at least one provider required"
        self.providers = providers        # in failover order
        self.cassettes = cassettes
        self.config = config
        self.governor = governor
        self.provider_limits = provider_limits or {}
        self.failover_count = 0
        self.calls_by_provider: dict[str, int] = {}

    # --- startup probe: refuse to start if a configured model is unavailable ---
    def probe(self, model: str) -> None:
        """In replay mode there is nothing to probe (no network). With a live
        provider, a trivial call must succeed or we refuse to start, naming the
        model+provider."""
        if self.config.mode == "replay":
            return
        primary = self.providers[0]
        keyp = (getattr(primary, "name", "?"), model)
        if keyp in ProviderManager._probed:
            return
        try:
            primary.complete(messages=[{"role": "user", "content": "ping"}], tools=[], model=model)
            ProviderManager._probed.add(keyp)
        except ProviderError as exc:
            raise RuntimeError(
                f"startup probe failed for model '{model}' on provider "
                f"'{getattr(primary, 'name', '?')}': {exc}. Refusing to start.") from exc

    def complete(self, *, messages: list[dict], tools: list[dict], model: str) -> ProviderResponse:
        key = cassette_key(
            system=self.config.system_prompt, messages=messages, tools=tools, model=model,
            provider=self.providers[0].name, policy_version=self.config.policy_version,
            fixture_version=self.config.fixture_version)

        if self.config.mode == "replay":
            if not self.cassettes.has(key):
                raise CassetteMissError(
                    f"cassette miss in replay mode (key {key[:12]}…). Re-record with "
                    f"SENTINEL_CASSETTE=record. CI never falls through to the network.")
            resp = self.cassettes.load(key)
            self.calls_by_provider[resp.provider] = self.calls_by_provider.get(resp.provider, 0) + 1
            return resp

        if self.config.mode == "auto" and self.cassettes.has(key):
            resp = self.cassettes.load(key)
            self.calls_by_provider[resp.provider] = self.calls_by_provider.get(resp.provider, 0) + 1
            return resp

        # record (or auto-miss): call the provider chain with failover
        resp = self._call_with_failover(messages, tools, model)
        self.cassettes.save(key, {"model": model, "provider": resp.provider}, resp)
        self.calls_by_provider[resp.provider] = self.calls_by_provider.get(resp.provider, 0) + 1
        return resp

    def _call_with_failover(self, messages, tools, model) -> ProviderResponse:
        last_err: Optional[Exception] = None
        for i, provider in enumerate(self.providers):
            limits = self.provider_limits.get(provider.name, {})
            # atomic check-and-record: two concurrent calls cannot both take the
            # last slot (the old would_exceed()+record() had a check-then-act race).
            if self.governor and limits and not self.governor.try_acquire(provider.name, model, limits):
                last_err = ProviderError(f"{provider.name}: local rate-limit ceiling reached")
                continue
            try:
                resp = provider.complete(messages=messages, tools=tools, model=model)
                if i > 0:
                    self.failover_count += 1
                return resp
            except ProviderError as exc:
                last_err = exc
                if i > 0:
                    self.failover_count += 1
                continue
        raise ProviderError(f"all providers exhausted: {last_err}")
