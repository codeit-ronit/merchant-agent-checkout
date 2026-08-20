"""Redaction and trust-quarantine — subsystems that operate on data in flight
and must never themselves become the leak.

The model never sees a real financial identifier, because it does not need one:
PII is replaced with a stable per-run token it can reason over. Untrusted text is
wrapped in a per-run nonce delimiter so instructions embedded in data cannot be
confused with instructions from the operator.
"""

from sentinel.redaction.engine import RedactionSession, redact_result, rehydrate_arguments
from sentinel.redaction.quarantine import (
    QuarantineWrapper,
    UnissuedTokenError,
)

__all__ = [
    "RedactionSession", "redact_result", "rehydrate_arguments",
    "QuarantineWrapper", "UnissuedTokenError",
]
