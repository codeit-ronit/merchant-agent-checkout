"""Tool classifier + startup reconciliation.

At startup the proxy introspects the upstream ``tools/list`` and reconciles it
against ``config/tool_classes.yaml`` into three sets:

* **CLASSIFIED** — present in both. Use the configured class.
* **UNCLASSIFIED** — on the server, absent from config. Class = ``UNKNOWN`` ->
  denied, surfaced loudly. A tool added upstream next month must not silently
  become callable.
* **STALE** — in config, absent from the server. Warn; upstream may have
  removed/renamed it.

Classification is NEVER guessed from a tool's name — an unclassified tool is
denied. Forbidden tools are removed from the manifest entirely so they never
enter the model's context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sentinel.common.config import load_yaml
from sentinel.contracts.enums import BindingRole, ClassificationStatus, RiskClass
from sentinel.contracts.tools import FieldProvenance, PiiField, Provenance, ToolDescriptor


@dataclass
class ReconciliationReport:
    """The deliverable that demonstrates the system degrades safely when the
    world changes underneath it."""

    classified: list[ToolDescriptor] = field(default_factory=list)
    unclassified: list[str] = field(default_factory=list)   # UNKNOWN -> denied
    stale: list[str] = field(default_factory=list)          # in config, not on server
    forbidden_removed: list[str] = field(default_factory=list)

    @property
    def callable_manifest(self) -> list[ToolDescriptor]:
        """Tools the agent may actually see: classified & not forbidden/unknown.
        Unclassified tools are represented as UNKNOWN descriptors so the proxy
        can deny them with a reason, but they are filtered from the model's
        manifest."""
        return [t for t in self.classified if t.is_callable]

    def summary(self) -> str:
        return (f"{len(self.callable_manifest)} tools available · "
                f"{len(self.unclassified)} UNCLASSIFIED (denied) · "
                f"{len(self.stale)} stale · {len(self.forbidden_removed)} forbidden removed")


def _parse_provenance_map(raw: dict[str, str] | None) -> tuple[FieldProvenance, ...]:
    if not raw:
        return ()
    return tuple(FieldProvenance(field_path=k, provenance=Provenance(v)) for k, v in raw.items())


def _parse_pii_map(raw: dict[str, str] | None) -> tuple[PiiField, ...]:
    if not raw:
        return ()
    return tuple(PiiField(field_path=k, pii_type=v) for k, v in raw.items())


def _descriptor(name: str, spec: dict[str, Any], upstream_tool: dict[str, Any],
                status: ClassificationStatus, source: str) -> ToolDescriptor:
    return ToolDescriptor(
        name=name,
        upstream_name=name,
        description=upstream_tool.get("description", ""),
        input_schema=upstream_tool.get("inputSchema", {}),
        risk_class=RiskClass(spec["risk_class"]),
        config_source=source,
        classification_status=status,
        moves_money=bool(spec.get("moves_money", False)),
        binding_role=BindingRole(spec.get("binding_role", "NONE")),
        amount_arg_path=spec.get("amount_arg_path"),
        currency_arg_path=spec.get("currency_arg_path"),
        entity_arg_paths=tuple(spec.get("entity_arg_paths", []) or []),
        counterparty_arg_path=spec.get("counterparty_arg_path"),
        rehydratable_arg_paths=tuple(spec.get("rehydratable_arg_paths", []) or []),
        provenance_map=_parse_provenance_map(spec.get("provenance_map")),
        pii_map=_parse_pii_map(spec.get("pii_map")),
        is_paginated=bool(spec.get("is_paginated", False)),
        outcome_field=spec.get("outcome_field"),
    )


def load_tool_classes(config_name: str = "tool_classes.yaml") -> dict[str, Any]:
    return load_yaml(config_name)


def reconcile(upstream_tools: list[dict[str, Any]],
              config_name: str = "tool_classes.yaml") -> ReconciliationReport:
    cfg = load_tool_classes(config_name)
    tool_specs: dict[str, Any] = cfg.get("tools", {}) or {}
    forbidden_names = set(cfg.get("forbidden", []) or [])
    source = f"{config_name}@v{cfg.get('version', '?')}"

    report = ReconciliationReport()
    upstream_by_name = {t["name"]: t for t in upstream_tools}

    for name, upstream_tool in upstream_by_name.items():
        if name in forbidden_names:
            report.classified.append(_descriptor(
                name, {"risk_class": RiskClass.FORBIDDEN.value}, upstream_tool,
                ClassificationStatus.CLASSIFIED, source))
            report.forbidden_removed.append(name)
            continue
        spec = tool_specs.get(name)
        if spec is None:
            # UNCLASSIFIED -> UNKNOWN, fail closed. Represent it so the proxy can
            # deny it by name, but it is filtered from the model's manifest.
            report.classified.append(ToolDescriptor(
                name=name, upstream_name=name,
                description=upstream_tool.get("description", ""),
                input_schema=upstream_tool.get("inputSchema", {}),
                risk_class=RiskClass.UNKNOWN, config_source=source,
                classification_status=ClassificationStatus.UNCLASSIFIED))
            report.unclassified.append(name)
        else:
            report.classified.append(_descriptor(
                name, spec, upstream_tool, ClassificationStatus.CLASSIFIED, source))

    # STALE: in config, not on the server.
    for name in tool_specs:
        if name not in upstream_by_name and name not in forbidden_names:
            report.stale.append(name)

    return report


def descriptor_index(report: ReconciliationReport) -> dict[str, ToolDescriptor]:
    """name -> descriptor, INCLUDING unclassified ones, so the proxy can resolve
    any name the model somehow emits and deny unknowns explicitly."""
    return {t.name: t for t in report.classified}
