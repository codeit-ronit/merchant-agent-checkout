"""Reverse schema→config drift check (ADR-024).

`check_arg_paths` (scripts/live_check.py) already validates the FORWARD direction:
every arg-path a tool *declares* exists in the real schema. This check is the
REVERSE — the direction that let `create_qr_code` sit with an ungoverned
`payment_amount`: a tool whose real schema carries a money-shaped field
(`amount`, `*_amount`, numeric) MUST either declare an `amount_arg_path` covering
it, or be explicitly WAIVED. A field that is neither is drift, and drift on an
amount means the amount governance (ceilings, tiers, currency) can't see it.

It does not make drift literally impossible — "money-shaped" is a heuristic — but
it forces a human decision (classify it or waive it) on every numeric money field,
which is exactly the step that was skipped.

Run offline: ``python -m sentinel.fixtures.config_coverage`` (exit 1 on failure).
"""

from __future__ import annotations

import json
import sys

from sentinel.common.config import repo_root
from sentinel.proxy.classifier import load_tool_classes

REFERENCE = repo_root() / "artifacts" / "reference" / "upstream_tools_list.json"

# Tools whose money-shaped field is deliberately NOT an amount to govern.
# Each entry must carry a one-line reason (documented, not silent).
AMOUNT_WAIVERS: dict[str, str] = {
    # e.g. "some_tool": "the 'amount' field is a read-only filter, binds nothing",
}

_NUMERIC = {"number", "integer"}


def _money_fields(schema: dict) -> list[str]:
    """Top-level numeric properties whose name looks like a bindable amount."""
    props = (schema or {}).get("properties", {})
    out = []
    for name, spec in props.items():
        t = spec.get("type")
        n = name.lower()
        if t in _NUMERIC and (n == "amount" or n.endswith("_amount")):
            out.append(name)
    return out


def check() -> tuple[bool, list[dict]]:
    reference = json.loads(REFERENCE.read_text())
    cfg = load_tool_classes().get("tools", {})
    findings: list[dict] = []
    for tool in reference["tools"]:
        name = tool["name"]
        fields = _money_fields(tool.get("inputSchema", {}))
        if not fields:
            continue
        spec = cfg.get(name, {})
        declared = spec.get("amount_arg_path")
        if name in AMOUNT_WAIVERS:
            continue
        if declared is None or declared not in fields:
            findings.append({"tool": name, "money_fields": fields, "declared": declared})
    return (not findings), findings


def main() -> int:
    if not REFERENCE.exists():
        print(f"reference manifest missing: {REFERENCE}\nrun: make reference-manifest")
        return 1
    ok, findings = check()
    if ok:
        print("amount-field coverage OK: every money-shaped schema field is classified or waived.")
        return 0
    print("AMOUNT-FIELD COVERAGE FAILED — money-shaped fields with no amount_arg_path:")
    for f in findings:
        print(f"  {f['tool']}: schema has {f['money_fields']} but amount_arg_path={f['declared']!r} "
              f"— classify it (add amount_arg_path) or add a documented waiver.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
