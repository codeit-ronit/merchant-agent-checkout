"""Reason-code taxonomy: full template coverage, safe rendering, no PII leak
(docs/spec/04 §3.5)."""

from __future__ import annotations

import pytest

from sentinel.contracts.reasons import (
    CODE_DISPOSITION,
    ReasonCode,
    reason_templates,
    render_reason,
)
from tests.conftest import SYNTHETIC_PII

pytestmark = pytest.mark.tier1


def test_every_code_has_a_non_empty_template():
    templates = reason_templates()
    for code in ReasonCode:
        assert code in templates, f"{code} has no template"
        assert templates[code].strip(), f"{code} template is empty"


def test_every_code_has_a_disposition():
    for code in ReasonCode:
        assert code in CODE_DISPOSITION


def test_every_template_renders_with_no_params():
    # Must never raise, even with zero parameters (safe fallbacks fill in).
    for code in ReasonCode:
        text = render_reason(code)
        assert text and isinstance(text, str)


def test_rendering_with_params():
    text = render_reason(ReasonCode.DENY_AMOUNT_EXCEEDS_CAP,
                         tool="create_refund", amount="₹24,500.00", cap="₹10,000.00")
    assert "create_refund" in text
    assert "₹24,500.00" in text


@pytest.mark.critical
@pytest.mark.parametrize("pii_value", list(SYNTHETIC_PII.values()))
def test_rendered_reason_never_leaks_pii(pii_value):
    """Even if a caller mistakenly passed PII as a param, the *templates* never
    reference PII fields — but we also assert rendering a representative call
    produces no PII. (Callers must not pass PII; templates only use amounts,
    tools, caps.)"""
    for code in ReasonCode:
        text = render_reason(code, tool="create_refund", amount="₹24,500.00",
                             cap="₹10,000.00", rule="r1", threshold="₹10,000.00")
        assert pii_value not in text
