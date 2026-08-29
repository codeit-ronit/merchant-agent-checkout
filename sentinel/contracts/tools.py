"""``ToolDescriptor`` — the reconciled view of one tool.

The provenance and PII maps are the unglamorous, manual work that makes the
proxy able to quarantine and redact *by field* rather than blanket-treating
whole responses. They are derived by reading each tool's actual response shape
(config/tool_classes.yaml), not guessed from names.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import Field

from sentinel.contracts.base import Contract
from sentinel.contracts.enums import BindingRole, ClassificationStatus, Provenance, RiskClass


class FieldProvenance(Contract):
    """One output field's trust level (dotted path into the tool result)."""

    field_path: str
    provenance: Provenance


class PiiField(Contract):
    """One output field that may contain PII of a given type."""

    field_path: str
    pii_type: str          # e.g. "PAN_CARD", "BANK_ACCOUNT", "VPA", "PHONE", "EMAIL", "NAME"


class ToolDescriptor(Contract):
    name: str                              # as presented to the model (may be namespaced)
    upstream_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)

    risk_class: RiskClass
    config_source: str = ""                # which config assigned the class
    classification_status: ClassificationStatus

    # --- money semantics: where in the ARGUMENTS the money meaning lives ---
    moves_money: bool = False
    binding_role: BindingRole = BindingRole.NONE   # financial-commitment axis (ADR-024)
    amount_arg_path: Optional[str] = None      # dotted path to the amount (integer minor units)
    currency_arg_path: Optional[str] = None
    entity_arg_paths: tuple[str, ...] = ()     # args that reference an entity (scope)
    counterparty_arg_path: Optional[str] = None  # arg naming a payout destination (novelty)

    # --- rehydration: which ARGUMENTS legitimately need a real (de-tokenised) value ---
    rehydratable_arg_paths: tuple[str, ...] = ()

    # --- output maps: for result post-processing ---
    provenance_map: tuple[FieldProvenance, ...] = ()
    pii_map: tuple[PiiField, ...] = ()

    # --- pagination awareness (silent page-one reads are a correctness bug) ---
    is_paginated: bool = False

    # --- domain outcome: which RESPONSE field carries the tool's own verdict.
    # Declarative (set in tool_classes.yaml), so a tool whose successful call
    # can still REFUSE at the domain level (e.g. a commit gate returning a
    # structured rejection) surfaces that verdict as a first-class, queryable
    # audit field instead of an ALLOW that quietly meant "no purchase". ---
    outcome_field: Optional[str] = None

    @property
    def is_forbidden(self) -> bool:
        return self.risk_class == RiskClass.FORBIDDEN

    @property
    def is_callable(self) -> bool:
        """Forbidden and unknown tools are never callable."""
        return self.risk_class not in (RiskClass.FORBIDDEN, RiskClass.UNKNOWN)
