"""Fixture-vs-upstream schema parity check.

Evals pass against fixtures. If upstream schemas change and the fixture drifts,
evals could pass against a world that no longer exists. This check compares the
fixture server's advertised ``tools/list`` against the committed reference
manifest (``artifacts/reference/upstream_tools_list.json``) and reports:

* **matched** — same name + structurally-equal input schema.
* **schema_drift** — same name, different schema. FAILS.
* **missing_from_fixture** — in the reference upstream, absent from the fixture.
  FAILS (the double is incomplete).
* **fixture_only** — in the fixture, not in the reference upstream. Reported,
  NOT a failure — these are the labelled fixture extensions (disputes,
  subscriptions), which is honest drift, not a bug.

Run offline: ``python -m sentinel.fixtures.schema_parity`` (exit 1 on failure).

Caveat stated honestly: the reference manifest itself was derived from docs
research, not a live ``tools/list`` (ADR-003). In a real deployment
``make reference-manifest`` re-captures it live and this check then catches
genuine fixture drift.
"""

from __future__ import annotations

import json
import sys

from sentinel.common.config import repo_root
from sentinel.fixtures.tool_catalog import EXTENSION_NAMES, fixture_manifest

REFERENCE = repo_root() / "artifacts" / "reference" / "upstream_tools_list.json"


def _canon_schema(schema: dict) -> str:
    return json.dumps(schema, sort_keys=True)


def check() -> tuple[bool, dict[str, list[str]]]:
    reference = json.loads(REFERENCE.read_text())
    ref_by_name = {t["name"]: t for t in reference["tools"]}
    fix_by_name = {t["name"]: t for t in fixture_manifest()["tools"]}

    result: dict[str, list[str]] = {
        "matched": [], "schema_drift": [], "missing_from_fixture": [], "fixture_only": [],
    }

    for name, ref_tool in ref_by_name.items():
        fix_tool = fix_by_name.get(name)
        if fix_tool is None:
            result["missing_from_fixture"].append(name)
        elif _canon_schema(ref_tool["inputSchema"]) != _canon_schema(fix_tool["inputSchema"]):
            result["schema_drift"].append(name)
        else:
            result["matched"].append(name)

    for name in fix_by_name:
        if name not in ref_by_name:
            result["fixture_only"].append(name)

    # fixture_only is only OK if every such tool is a declared extension.
    undeclared_extras = [n for n in result["fixture_only"] if n not in EXTENSION_NAMES]
    ok = (not result["schema_drift"]
          and not result["missing_from_fixture"]
          and not undeclared_extras)
    return ok, result


def main() -> int:
    if not REFERENCE.exists():
        print(f"reference manifest missing: {REFERENCE}\nrun: make reference-manifest")
        return 1
    ok, result = check()
    print(f"schema parity: {len(result['matched'])} matched, "
          f"{len(result['schema_drift'])} drift, "
          f"{len(result['missing_from_fixture'])} missing, "
          f"{len(result['fixture_only'])} fixture-only (extensions)")
    for name in result["schema_drift"]:
        print(f"  DRIFT: {name}")
    for name in result["missing_from_fixture"]:
        print(f"  MISSING FROM FIXTURE: {name}")
    if result["fixture_only"]:
        print("  fixture-only (labelled extensions, informational): " + ", ".join(result["fixture_only"]))
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
