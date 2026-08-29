"""Drawdown ledger: derived balance, atomic reservations, REAL concurrency.

The concurrency tests use genuinely parallel threads released by a barrier —
sequential tests pass on a broken implementation (04 §5).
"""

from __future__ import annotations

import threading

import pytest

from conduit.mandate.ledger import (
    DrawdownLedger,
    EntryKind,
    InMemoryLedgerRepository,
    LedgerError,
    Mandate,
    SqliteLedgerRepository,
)

pytestmark = pytest.mark.tier1


@pytest.fixture(params=["memory", "sqlite"])
def ledger(request, tmp_path):
    repo = (InMemoryLedgerRepository() if request.param == "memory"
            else SqliteLedgerRepository(tmp_path / "ledger.db"))
    led = DrawdownLedger(repo)
    led.create_mandate(Mandate("mnd_dinner", 200000, "INR"))  # ₹2,000
    return led


class TestLifecycle:
    def test_reserve_confirm_draws_down(self, ledger):
        ledger.reserve("mnd_dinner", 74000, ref="cart_1", now_ms=1)
        bal = ledger.balance("mnd_dinner")
        assert (bal.reserved_minor, bal.drawn_minor, bal.remaining_minor) == (74000, 0, 126000)
        bal = ledger.confirm("mnd_dinner", ref="cart_1", now_ms=2)
        assert (bal.reserved_minor, bal.drawn_minor, bal.remaining_minor) == (0, 74000, 126000)

    def test_reserve_release_returns_hold(self, ledger):
        ledger.reserve("mnd_dinner", 74000, ref="cart_1", now_ms=1)
        bal = ledger.release("mnd_dinner", ref="cart_1", now_ms=2)
        assert (bal.reserved_minor, bal.drawn_minor, bal.remaining_minor) == (0, 0, 200000)

    def test_reverse_is_an_entry_not_a_deletion(self, ledger):
        ledger.reserve("mnd_dinner", 74000, ref="cart_1", now_ms=1)
        ledger.confirm("mnd_dinner", ref="cart_1", now_ms=2)
        bal = ledger.reverse("mnd_dinner", ref="cart_1", now_ms=3)
        assert bal.remaining_minor == 200000                    # money came back
        kinds = [e.kind for e in ledger.entries("mnd_dinner")]
        assert kinds == [EntryKind.RESERVE, EntryKind.CONFIRM, EntryKind.REVERSE]

    def test_shortfall_is_named_with_amounts(self, ledger):
        with pytest.raises(LedgerError, match="short by ₹100.00"):
            ledger.reserve("mnd_dinner", 210000, ref="cart_1", now_ms=1)

    def test_double_reserve_same_ref_refused(self, ledger):
        ledger.reserve("mnd_dinner", 1000, ref="cart_1", now_ms=1)
        with pytest.raises(LedgerError, match="already holds"):
            ledger.reserve("mnd_dinner", 1000, ref="cart_1", now_ms=2)

    def test_confirm_without_reservation_refused(self, ledger):
        with pytest.raises(LedgerError, match="no active reservation"):
            ledger.confirm("mnd_dinner", ref="cart_ghost", now_ms=1)

    def test_unknown_mandate_fails_closed_with_next_step(self, ledger):
        with pytest.raises(LedgerError, match="Create one"):
            ledger.reserve("mnd_ghost", 1, ref="c", now_ms=1)

    def test_float_amount_refused(self, ledger):
        with pytest.raises(LedgerError, match="integer"):
            ledger.reserve("mnd_dinner", 740.0, ref="c", now_ms=1)


class TestDerivedBalance:
    def test_balance_reconstructs_after_reopen(self, tmp_path):
        path = tmp_path / "led.db"
        led = DrawdownLedger(SqliteLedgerRepository(path))
        led.create_mandate(Mandate("mnd_x", 100000, "INR"))
        led.reserve("mnd_x", 30000, ref="a", now_ms=1)
        led.confirm("mnd_x", ref="a", now_ms=2)
        led.reserve("mnd_x", 20000, ref="b", now_ms=3)
        # a fresh ledger over the same file derives the identical balance —
        # nothing authoritative lived in memory
        led2 = DrawdownLedger(SqliteLedgerRepository(path))
        bal = led2.balance("mnd_x")
        assert (bal.drawn_minor, bal.reserved_minor, bal.remaining_minor) == (30000, 20000, 50000)


class TestRealConcurrency:
    @pytest.mark.critical
    def test_parallel_reserves_cannot_overdraw(self):
        """₹2,000 mandate, 16 threads each reserving ₹300 simultaneously.
        Exactly 6 can fit (₹1,800); the rest must fail with the shortfall
        named. Threads start on a barrier so they genuinely race."""
        led = DrawdownLedger(InMemoryLedgerRepository())
        led.create_mandate(Mandate("mnd_race", 200000, "INR"))
        n = 16
        barrier = threading.Barrier(n)
        results: list[str] = [""] * n

        def worker(i: int) -> None:
            barrier.wait()
            try:
                led.reserve("mnd_race", 30000, ref=f"cart_{i}", now_ms=i)
                results[i] = "ok"
            except LedgerError:
                results[i] = "refused"

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count("ok") == 6            # floor(200000 / 30000)
        bal = led.balance("mnd_race")
        assert bal.reserved_minor == 180000
        assert bal.remaining_minor == 20000        # never negative, never interleaved
        assert bal.reserved_minor + bal.drawn_minor <= 200000

    @pytest.mark.critical
    def test_two_commits_one_mandate_second_fails_cleanly(self):
        """The spec's exact scenario: two agents, one mandate, concurrent
        commits that do not both fit. One wins, one gets the named shortfall."""
        led = DrawdownLedger(InMemoryLedgerRepository())
        led.create_mandate(Mandate("mnd_pair", 100000, "INR"))
        barrier = threading.Barrier(2)
        outcomes: dict[str, str] = {}

        def commit(ref: str) -> None:
            barrier.wait()
            try:
                led.reserve("mnd_pair", 70000, ref=ref, now_ms=1)
                led.confirm("mnd_pair", ref=ref, now_ms=2)
                outcomes[ref] = "committed"
            except LedgerError as exc:
                outcomes[ref] = f"refused: {exc}"

        a = threading.Thread(target=commit, args=("cart_a",))
        b = threading.Thread(target=commit, args=("cart_b",))
        a.start(); b.start(); a.join(); b.join()

        assert sorted(v.split(":")[0] for v in outcomes.values()) == ["committed", "refused"]
        refused = next(v for v in outcomes.values() if v.startswith("refused"))
        assert "short by" in refused
        assert led.balance("mnd_pair").drawn_minor == 70000  # exactly one draw
