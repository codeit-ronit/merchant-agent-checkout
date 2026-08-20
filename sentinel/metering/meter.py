"""Per-run meter accumulator -> immutable ``Meter`` contract at run end."""

from __future__ import annotations

from sentinel.contracts.runs import Meter
from sentinel.providers.base import ProviderResponse


class MeterAccumulator:
    def __init__(self, price_table: dict | None = None):
        # price_table: {model_id: {"in": micros_per_mtok, "out": micros_per_mtok}}
        self._prices = price_table or {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.wall_clock_ms = 0.0
        self.policy_eval_ms = 0.0
        self.time_to_first_tool_call_ms: float | None = None
        self.provider_calls: dict[str, int] = {}
        self.model_calls: dict[str, int] = {}
        self._cost_micros = 0
        self._cost_gap = False

    def add_call(self, resp: ProviderResponse) -> None:
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens
        self.provider_calls[resp.provider] = self.provider_calls.get(resp.provider, 0) + 1
        self.model_calls[resp.model] = self.model_calls.get(resp.model, 0) + 1
        price = self._prices.get(resp.model)
        if not resp.usage.reported or price is None or price.get("in") is None:
            # provider reports no usage OR no published price -> a gap, not a guess
            self._cost_gap = True
        else:
            self._cost_micros += (resp.usage.input_tokens * price["in"] // 1_000_000
                                  + resp.usage.output_tokens * price["out"] // 1_000_000)

    def add_policy_eval(self, ms: float) -> None:
        self.policy_eval_ms += ms

    def finalise(self, wall_clock_ms: float) -> Meter:
        self.wall_clock_ms = wall_clock_ms
        return Meter(
            input_tokens=self.input_tokens, output_tokens=self.output_tokens,
            total_cost_micros=None if self._cost_gap else self._cost_micros,
            cost_gap=self._cost_gap, wall_clock_ms=round(wall_clock_ms, 3),
            policy_eval_ms=round(self.policy_eval_ms, 3),
            time_to_first_tool_call_ms=self.time_to_first_tool_call_ms,
            provider_calls=dict(self.provider_calls), model_calls=dict(self.model_calls),
        )
