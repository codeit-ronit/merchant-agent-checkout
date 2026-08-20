"""Policy loading: valid sets load, malformed files refuse to start, the
permissive baseline is blocked in live mode (docs/spec/04 §3.4)."""

from __future__ import annotations

import pytest

from sentinel.contracts.enums import RunMode
from sentinel.policy_loader import PolicyLoadError, load_policy_set, parse_policy_set

pytestmark = pytest.mark.tier1


def test_three_policy_sets_load():
    for name in ("strict", "permissive", "reconciliation-readonly"):
        ps = load_policy_set(name)
        assert ps.id == name and ps.rules


def test_permissive_blocked_in_live_mode():
    with pytest.raises(PolicyLoadError):
        load_policy_set("permissive", mode=RunMode.LIVE)


def test_missing_policy_refuses():
    with pytest.raises(PolicyLoadError):
        load_policy_set("does-not-exist")


def test_unknown_rule_type_refuses():
    with pytest.raises(PolicyLoadError):
        parse_policy_set({"id": "x", "version": "1",
                          "rules": [{"id": "r", "type": "arbitrary_expression", "code": "os.system('rm')"}]})


def test_malformed_rule_params_refuse():
    with pytest.raises(PolicyLoadError):
        parse_policy_set({"id": "x", "version": "1",
                          "rules": [{"id": "r", "type": "amount_cap"}]})  # missing max_minor


def test_missing_required_top_level_field_refuses():
    with pytest.raises(PolicyLoadError):
        parse_policy_set({"version": "1", "rules": []})  # no id


def test_duplicate_rule_ids_refuse():
    with pytest.raises(PolicyLoadError):
        parse_policy_set({"id": "x", "version": "1", "rules": [
            {"id": "dup", "type": "tool_allow", "tools": ["a"]},
            {"id": "dup", "type": "tool_allow", "tools": ["b"]},
        ]})
