"""Commerce eval fixture integrity: the generated merchant regenerates
byte-identically (so scenario reasoning can cite the committed truth), and
the authored suite keeps its shape."""

from __future__ import annotations

import json

import pytest
import yaml

from evals.commerce.merchants import SPICE_JSON, dump_spice_route
from sentinel.common.config import repo_root

pytestmark = pytest.mark.tier1

SCEN_DIR = repo_root() / "evals" / "commerce" / "scenarios"


def test_spice_route_regenerates_byte_identically():
    """The anti-circularity anchor: scenarios were authored against the
    committed spice-route.json; this proves the generator still produces
    exactly that truth (same seed, same catalog, no silent drift)."""
    committed = json.loads(SPICE_JSON.read_text())
    assert dump_spice_route() == committed


def test_suite_covers_all_six_categories():
    scenarios = [yaml.safe_load(p.read_text()) for p in sorted(SCEN_DIR.glob("*.yaml"))]
    assert len(scenarios) >= 12
    categories = {s["category"] for s in scenarios}
    assert categories == {"satisfiable", "constrained", "unsatisfiable",
                          "failure_recovery", "policy_triggering", "adversarial"}


def test_every_scenario_carries_authored_reasoning():
    """The discipline made structural: no scenario without its pre-run
    reasoning and expected decision — a suite that ratifies behaviour instead
    of testing it is the circular-validation disease in its final form."""
    for path in sorted(SCEN_DIR.glob("*.yaml")):
        scn = yaml.safe_load(path.read_text())
        assert scn.get("reasoning", "").strip().startswith("AUTHORED BEFORE RUNNING"), path.name
        assert scn.get("expected_decision"), path.name
        assert scn.get("assertions"), path.name
        # the expected decision is also asserted, not just stated
        decision_asserts = [a for a in scn["assertions"] if a["type"] == "decision_is"]
        assert decision_asserts and decision_asserts[0]["params"]["value"] == scn["expected_decision"], path.name
