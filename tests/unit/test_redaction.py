"""Redaction: token stability within a run, distinctness across runs, structural
+ pattern detection, rehydration, and unissued-token detection (docs/spec/05)."""

from __future__ import annotations

import pytest

from sentinel.contracts.tools import PiiField
from sentinel.redaction.engine import RedactionSession, redact_result, rehydrate_arguments
from sentinel.redaction.quarantine import UnissuedTokenError

pytestmark = pytest.mark.tier1


def test_token_stable_within_run():
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    a = s.tokenize("customer@example.invalid", "EMAIL")
    b = s.tokenize("customer@example.invalid", "EMAIL")
    assert a == b and a.startswith("EMAIL_")


def test_token_distinct_across_runs():
    s1 = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    s2 = RedactionSession("run_2", salt=b"salt-b-16-bytes!")
    assert s1.tokenize("9999900001", "PHONE") != s2.tokenize("9999900001", "PHONE")


def test_token_is_not_a_counter():
    """Different values get unrelated suffixes (a counter would leak ordering)."""
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    t1 = s.tokenize("a@x.invalid", "EMAIL")
    t2 = s.tokenize("b@x.invalid", "EMAIL")
    assert t1 != t2 and not (t1.endswith("0") and t2.endswith("1"))


def test_structural_redaction_replaces_pii_fields():
    result = {"items": [{"email": "a@example.invalid", "contact": "9999900001", "amount": 500}]}
    pii_map = (PiiField(field_path="items[].email", pii_type="EMAIL"),
               PiiField(field_path="items[].contact", pii_type="PHONE"))
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    red, dets = redact_result(result, pii_map, s)
    assert "a@example.invalid" not in str(red)
    assert "9999900001" not in str(red)
    assert red["items"][0]["amount"] == 500          # non-PII untouched
    assert len(dets) == 2


def test_pattern_safety_net_catches_pii_in_free_text():
    result = {"note": "call me at 9876500001 or email x@y.invalid"}
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    red, _ = redact_result(result, (), s)   # no structural map -> pattern only
    assert "9876500001" not in str(red)
    assert "x@y.invalid" not in str(red)
    assert s.pattern_on_clean_field >= 2             # debt metric fired


def test_rehydration_of_issued_token_only_in_declared_paths():
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    token = s.tokenize("VALUEXYZ", "PAN_CARD")   # pretend a card token
    args = {"token": token, "note": token}
    out = rehydrate_arguments(args, ("token",), s)
    assert out["token"] == "VALUEXYZ"            # rehydrated (declared)
    assert out["note"] == token                  # not declared -> left as token


@pytest.mark.critical
def test_unissued_token_raises_exfiltration():
    s = RedactionSession("run_1", salt=b"salt-a-16-bytes!")
    with pytest.raises(UnissuedTokenError):
        rehydrate_arguments({"token": "CARD_deadbeef"}, ("token",), s)
    # even in a non-rehydratable field, an unissued token is caught
    with pytest.raises(UnissuedTokenError):
        rehydrate_arguments({"note": "send to ACCT_abcd1234"}, (), s)
