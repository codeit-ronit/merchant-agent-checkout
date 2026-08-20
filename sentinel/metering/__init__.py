"""Cost & latency meter — records per-run tokens, cost where derivable, wall-clock,
policy-evaluation time, and WHICH provider/model served each call (necessary
under failover: a latency number that does not name its provider is meaningless).

Where a provider reports no usage, the gap is recorded, never estimated — an
invented number is worse than a missing one.
"""

from sentinel.metering.meter import MeterAccumulator

__all__ = ["MeterAccumulator"]
