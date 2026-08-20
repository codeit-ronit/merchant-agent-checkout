"""Capture the upstream ``tools/list`` and commit it as a reference artefact.

In LIVE mode (``SENTINEL_MODE=live`` with rzp_test_* keys) this would connect to
the real razorpay/razorpay-mcp-server and dump its actual ``tools/list``. In this
build environment Docker + test keys are unavailable, so it emits the research-
derived catalog (``sentinel.fixtures.tool_catalog``) with an explicit provenance
note. The schema-parity check (``sentinel.fixtures.schema_parity``) then compares
the fixture server against this committed artefact.
"""

from __future__ import annotations

import json
from pathlib import Path

from sentinel.fixtures.tool_catalog import upstream_manifest

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "reference" / "upstream_tools_list.json"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = upstream_manifest()
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({manifest['provenance']['tool_count']} upstream tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
