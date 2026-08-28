"""Reverse schema->config drift check (ADR-024): a money-shaped schema field with
no declared amount_arg_path is a failure — this is the check that would have
caught create_qr_code's ungoverned payment_amount."""

from __future__ import annotations

import pytest

from sentinel.fixtures import config_coverage as cc

pytestmark = pytest.mark.tier1


def test_live_surface_has_full_amount_coverage():
    ok, findings = cc.check()
    assert ok, f"money-shaped fields with no amount_arg_path: {findings}"


def test_reverse_check_catches_an_undeclared_amount(monkeypatch):
    orig = cc.load_tool_classes

    def patched():
        c = orig()
        c["tools"]["create_qr_code"] = {k: v for k, v in c["tools"]["create_qr_code"].items()
                                        if k != "amount_arg_path"}
        return c

    monkeypatch.setattr(cc, "load_tool_classes", patched)
    ok, findings = cc.check()
    assert not ok and any(f["tool"] == "create_qr_code" for f in findings)
