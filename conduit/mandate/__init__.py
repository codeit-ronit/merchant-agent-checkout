"""Mandate — consent moved upstream (MODELLED, Reserve-Pay-shaped).

Phase 2 builds the load-bearing core: the append-only drawdown ledger with
atomic reservations — the serialisation point that makes concurrent over-draw
impossible. Phase 3 adds the lifecycle semantics (merchant scope, expiry,
revocation) and the policy-engine composition.
"""
