"""Rate-limit governor — blocks locally BEFORE a provider rejects, so a long
eval run degrades gracefully instead of erroring in a burst.

Limits are read from ``config/providers.yaml`` (never hardcoded) with the date
they were verified. Counters live in a persistent JSON store so a restart does
not reset the daily counter and cause a burst of rejections. On the offline
scripted/replay path nothing is counted (no network is touched).
"""

from __future__ import annotations

import json
from pathlib import Path


class RateLimitGovernor:
    def __init__(self, store_path: str | Path, clock_ms):
        self.store_path = Path(store_path)
        self._clock_ms = clock_ms
        self._state: dict = self._load()

    def _load(self) -> dict:
        if self.store_path.exists():
            try:
                return json.loads(self.store_path.read_text())
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(self._state))

    def _bucket(self, provider: str, model: str) -> dict:
        key = f"{provider}:{model}"
        return self._state.setdefault(key, {"minute": [], "day": []})

    def would_exceed(self, provider: str, model: str, limits: dict) -> bool:
        now = self._clock_ms()
        b = self._bucket(provider, model)
        b["minute"] = [t for t in b["minute"] if now - t < 60_000]
        b["day"] = [t for t in b["day"] if now - t < 86_400_000]
        rpm = limits.get("rpm")
        rpd = limits.get("rpd")
        if rpm is not None and len(b["minute"]) >= rpm:
            return True
        if rpd is not None and len(b["day"]) >= rpd:
            return True
        return False

    def record(self, provider: str, model: str) -> None:
        now = self._clock_ms()
        b = self._bucket(provider, model)
        b["minute"].append(now)
        b["day"].append(now)
        self._save()

    def remaining(self, provider: str, model: str, limits: dict) -> dict:
        now = self._clock_ms()
        b = self._bucket(provider, model)
        used_min = len([t for t in b["minute"] if now - t < 60_000])
        used_day = len([t for t in b["day"] if now - t < 86_400_000])
        return {"rpm_remaining": (limits.get("rpm") or 0) - used_min,
                "rpd_remaining": (limits.get("rpd") or 0) - used_day}
