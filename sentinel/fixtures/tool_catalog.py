"""Canonical tool catalog — the single source of truth for the upstream MCP tool
surface.

PROVENANCE (now verified, not inferred): the upstream tool list is loaded
verbatim from ``artifacts/reference/upstream_tools_list.json``, which was
**captured LIVE on 2026-08-21** by running the published ``razorpay/mcp:latest``
image over MCP stdio and calling ``tools/list`` (a dummy ``rzp_test_`` key — the
tool list needs no real auth). See DECISIONS.md ADR-003.

An earlier version of this file was transcribed from the README/docs and had
several wrong tool names + invented tools; the live capture corrected them. The
fixture now serves EXACTLY the real 41-tool surface, so the schema-parity check
is genuine (fixture == the live-captured manifest), not circular.

FIXTURE EXTENSIONS remain: the published server exposes no dispute or
subscription tools, so the Dispute and Subscription agents are backed by clearly
labelled extensions that the parity check reports as fixture-only.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REFERENCE = Path(__file__).resolve().parent.parent.parent / "artifacts" / "reference" / "upstream_tools_list.json"

_STR = {"type": "string"}
_INT = {"type": "integer"}
_PAGINATION = {"count": _INT, "skip": _INT, "from": _INT, "to": _INT}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


def _tool(name: str, description: str, props: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": description, "inputSchema": _schema(props, required)}


@lru_cache(maxsize=1)
def _upstream_tools() -> list[dict[str, Any]]:
    """The real, live-captured upstream surface."""
    data = json.loads(_REFERENCE.read_text())
    return data["tools"]


# Loaded lazily but exposed as a module attribute for existing imports.
UPSTREAM_TOOLS: list[dict[str, Any]] = _upstream_tools()

# FIXTURE EXTENSIONS — NOT in the published upstream (verified: absent from the
# live tools/list). They model plausible near-future tools so the Dispute and
# Subscription agents have real risk classes to exercise. The parity check reports
# them as fixture-only rather than pretending they are upstream.
FIXTURE_EXTENSIONS: list[dict[str, Any]] = [
    _tool("fetch_dispute", "(fixture extension) Fetch a dispute and its underlying transaction.",
          {"dispute_id": _STR}, ["dispute_id"]),
    _tool("fetch_all_disputes", "(fixture extension) Fetch all disputes.", dict(_PAGINATION)),
    _tool("submit_dispute_evidence", "(fixture extension) Submit an evidence bundle to contest a dispute (irreversible once submitted).",
          {"dispute_id": _STR, "evidence": {"type": "object"}, "action": _STR}, ["dispute_id", "evidence", "action"]),
    _tool("fetch_all_subscriptions", "(fixture extension) Fetch all subscriptions, including recent failed charges.", dict(_PAGINATION)),
    _tool("fetch_subscription", "(fixture extension) Fetch a subscription and its last failure detail.", {"subscription_id": _STR}, ["subscription_id"]),
]

EXTENSION_NAMES = frozenset(t["name"] for t in FIXTURE_EXTENSIONS)


def upstream_manifest() -> dict[str, Any]:
    """The reference ``tools/list`` view of the real upstream (no extensions)."""
    return json.loads(_REFERENCE.read_text())


def fixture_manifest() -> dict[str, Any]:
    """What the fixture server advertises: the real upstream mirror + labelled extensions."""
    return {"tools": list(UPSTREAM_TOOLS) + FIXTURE_EXTENSIONS}
