"""Base class for every data contract.

* ``frozen=True`` — immutable. Decisions, audit entries, and traces are facts.
* ``extra="forbid"`` — a typo in a field name is an error at construction, not a
  silently dropped value.
* ``schema_version`` — every persisted structure is versioned. On an
  incompatible read, ``ensure_schema`` fails loudly rather than misparsing.

Redaction-awareness: any field that could carry raw PII is declared with
``Field(exclude=True)`` so it never appears in ``model_dump()`` /
``model_dump_json()`` — the serialisation used for logs, traces, audit, and API
responses. The safe representation is therefore the *default* representation;
leaking requires going out of your way. In practice SENTINEL keeps raw PII out
of contract objects entirely (redaction happens at the proxy before an object is
built), so these excluded fields are belt-and-braces.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class Contract(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        use_enum_values=False,
        validate_default=True,
    )

    schema_version: int = Field(default=SCHEMA_VERSION)

    def safe_dict(self) -> dict[str, Any]:
        """Serialisation guaranteed free of excluded (PII-bearing) fields.
        This is what every output surface uses."""
        return self.model_dump(mode="json")

    def safe_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def ensure_schema(cls, data: dict[str, Any]) -> "Contract":
        """Parse a persisted record, failing loudly on an incompatible version
        rather than silently misparsing (contract rule 3)."""
        version = data.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"{cls.__name__} record is schema_version {version}; this build "
                f"understands up to {SCHEMA_VERSION}. Refusing to misparse."
            )
        return cls.model_validate(data)
