"""Policy file loading and validation. This performs I/O and therefore lives
OUTSIDE the pure ``sentinel.policy`` package (the purity check would fail if a
YAML reader were inside it).

A malformed policy file is a **startup failure** — never a fall-back to a
permissive default. The permissive baseline is blocked in live mode with a loud
error.
"""

from __future__ import annotations

from typing import Any

import yaml

from sentinel.common.config import config_dir
from sentinel.contracts.enums import RunMode
from sentinel.policy.rules import RULE_TYPES, PolicySet, Rule


class PolicyLoadError(Exception):
    """Raised on any malformed policy — the caller refuses to start."""


def _build_rule(raw: dict[str, Any]) -> Rule:
    if "type" not in raw:
        raise PolicyLoadError(f"rule missing 'type': {raw.get('id', raw)}")
    rule_type = raw["type"]
    cls = RULE_TYPES.get(rule_type)
    if cls is None:
        raise PolicyLoadError(f"unknown rule type '{rule_type}' (not in the closed rule set)")
    params = {k: v for k, v in raw.items() if k != "type"}
    try:
        return cls(**params)
    except Exception as exc:
        raise PolicyLoadError(f"invalid '{rule_type}' rule {raw.get('id')}: {exc}") from exc


def parse_policy_set(data: dict[str, Any]) -> PolicySet:
    for field in ("id", "version"):
        if field not in data:
            raise PolicyLoadError(f"policy set missing required field '{field}'")
    rules_raw = data.get("rules", [])
    if not isinstance(rules_raw, list):
        raise PolicyLoadError("'rules' must be a list")
    rules = tuple(_build_rule(r) for r in rules_raw)
    ids = [r.id for r in rules]
    if len(set(ids)) != len(ids):
        raise PolicyLoadError(f"duplicate rule ids in policy set {data['id']}")
    try:
        return PolicySet(
            id=data["id"], version=str(data["version"]),
            description=data.get("description", ""), author=data.get("author", ""),
            is_permissive_baseline=bool(data.get("is_permissive_baseline", False)),
            rules=rules,
        )
    except Exception as exc:
        raise PolicyLoadError(f"invalid policy set {data.get('id')}: {exc}") from exc


def load_policy_set(policy_set_id: str, mode: RunMode = RunMode.FIXTURE) -> PolicySet:
    path = config_dir() / "policies" / f"{policy_set_id}.yaml"
    if not path.exists():
        # A missing policy is fail-closed: refuse to start, never default open.
        raise PolicyLoadError(f"policy set not found: {path}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"policy file {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyLoadError(f"policy file {path} did not parse to a mapping")
    ps = parse_policy_set(data)
    if ps.is_permissive_baseline and mode == RunMode.LIVE:
        raise PolicyLoadError(
            "REFUSING to load the permissive baseline in LIVE mode — it disables "
            "guardrails and exists only to produce the red-team 'before' half.")
    return ps


def load_all_policy_sets(mode: RunMode = RunMode.FIXTURE) -> dict[str, PolicySet]:
    out: dict[str, PolicySet] = {}
    for path in sorted((config_dir() / "policies").glob("*.yaml")):
        ps = parse_policy_set(yaml.safe_load(path.read_text()))
        if ps.is_permissive_baseline and mode == RunMode.LIVE:
            continue
        out[ps.id] = ps
    return out
