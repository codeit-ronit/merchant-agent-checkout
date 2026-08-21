"""Provider-manager factory — the ONE place that decides scripted (offline) vs
live (real Groq/Gemini) and builds the failover chain from config/providers.yaml.

The agent loop calls :func:`build_manager` and receives ``(manager, call_model)``;
it never names a provider or branches on one (CLAUDE.md rule 5a). Every
provider-specific concern — base URLs, tier->model-id mapping, failover order,
rate limits — lives behind this line.

Live is opt-in and fail-safe:

* enabled only when ``SENTINEL_LIVE`` is truthy AND at least one configured
  provider has its API key in the environment; otherwise it falls back to the
  deterministic scripted brain, so a stray env var can never break offline runs.
* NEVER used by the red-team (fixture-only, rule 7) — that runner never sets
  ``SENTINEL_LIVE``.
* records to a SEPARATE cassette directory (``…/live``) so the committed,
  no-key, reproducible cassettes are never touched or mixed with real ones.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from sentinel.common.config import load_yaml
from sentinel.providers.base import Provider
from sentinel.providers.cassette import CassetteStore
from sentinel.providers.governor import RateLimitGovernor
from sentinel.providers.manager import ManagerConfig, ProviderManager
from sentinel.providers.openai_adapter import OpenAICompatibleProvider
from sentinel.providers.scripted import ScriptedProvider

_TIERS = {"strong", "weak"}


def _truthy(v: Optional[str]) -> bool:
    return bool(v) and v.strip().lower() not in {"0", "false", "no"}


def live_enabled() -> bool:
    """True when the operator has explicitly opted into real providers."""
    return _truthy(os.environ.get("SENTINEL_LIVE"))


def _tier_of(model_id: Optional[str], model_tier: Optional[str]) -> str:
    if model_tier in _TIERS:
        return model_tier  # type: ignore[return-value]
    if model_id and "-" in model_id:
        suffix = model_id.rsplit("-", 1)[-1]
        if suffix in _TIERS:
            return suffix
    return "strong"


def build_live_providers(tier: str, config: Optional[dict] = None):
    """Build real providers in failover order for one capability tier.

    Only providers whose ``api_key_env`` is set in the environment are included,
    each carrying a tier->real-model-id map. Returns
    ``(providers, provider_limits, notes)`` where ``notes`` is a human-readable
    audit of what was included/skipped (never silently drops a provider).
    """
    cfg = config if config is not None else load_yaml("providers.yaml")
    providers_cfg = cfg.get("providers", {})
    order = cfg.get("failover_order") or list(providers_cfg.keys())
    providers: list[Provider] = []
    limits: dict[str, dict] = {}
    notes: list[str] = []
    for name in order:
        pconf = providers_cfg.get(name)
        if not pconf:
            notes.append(f"{name}: not in providers.yaml — skipped")
            continue
        env_name = pconf["api_key_env"]
        if not os.environ.get(env_name):
            notes.append(f"{name}: no key in {env_name} — skipped")
            continue
        models = pconf.get("models", {})
        if tier not in models:
            notes.append(f"{name}: no '{tier}' model configured — skipped")
            continue
        model_map = {t: m["id"] for t, m in models.items()
                     if isinstance(m, dict) and "id" in m}
        providers.append(OpenAICompatibleProvider(
            name=name, base_url=pconf["base_url"], api_key_env=env_name,
            usage_fields=pconf.get("usage_fields",
                                   {"input": "prompt_tokens", "output": "completion_tokens"}),
            model_map=model_map))
        limits[name] = dict(models[tier].get("limits", {}))
        notes.append(f"{name}: tier '{tier}' -> {model_map.get(tier)} (limits {limits[name]})")
    return providers, limits, notes


def build_manager(*, brain, model_id: Optional[str], model_tier: Optional[str],
                  cassette_dir: str, cassette_mode: str, policy_version: str,
                  fixture_version: str, system_prompt: str, clock_ms,
                  state_dir: str = "sentinel_state") -> Tuple[ProviderManager, str]:
    """Return ``(manager, call_model)`` for the agent loop.

    Offline (default): a :class:`ScriptedProvider` over the agent's deterministic
    brain — behaviour is byte-identical to before this factory existed.
    Live: real providers in failover order, a separate ``live`` cassette dir, and
    the rate-limit governor wired in. ``call_model`` is the logical tier the loop
    passes to ``complete()`` — the adapter maps it to the real id.
    """
    if live_enabled():
        tier = _tier_of(model_id, model_tier)
        providers, limits, _notes = build_live_providers(tier)
        if providers:
            live_dir = str(Path(cassette_dir).parent / "live")
            governor = RateLimitGovernor(Path(state_dir) / "governor.json", clock_ms)
            manager = ProviderManager(
                providers, CassetteStore(live_dir),
                ManagerConfig(mode=cassette_mode, policy_version=policy_version,
                              fixture_version=fixture_version, system_prompt=system_prompt),
                governor=governor, provider_limits=limits)
            return manager, tier
        # SENTINEL_LIVE set but no usable key -> fall through to scripted (fail safe)

    scripted_model = model_id or "scripted-deterministic"
    provider = ScriptedProvider(brain, model=scripted_model)
    manager = ProviderManager(
        [provider], CassetteStore(cassette_dir),
        ManagerConfig(mode=cassette_mode, policy_version=policy_version,
                      fixture_version=fixture_version, system_prompt=system_prompt))
    return manager, provider.model
