"""Approval lifecycle. Invariants enforced here and proven in tests:
single-use, argument-bound, absolute expiry, terminal rejection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from sentinel.common.ids import IdFactory
from sentinel.contracts.approvals import ApprovalRequest
from sentinel.contracts.decision import DecisionContext, PolicyDecision
from sentinel.contracts.enums import ApprovalStatus


class ApprovalRepository(Protocol):
    def put(self, approval: ApprovalRequest) -> None: ...
    def get(self, approval_id: str) -> ApprovalRequest | None: ...
    def pending(self) -> list[ApprovalRequest]: ...


class InMemoryApprovalRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, ApprovalRequest] = {}

    def put(self, approval: ApprovalRequest) -> None:
        self._by_id[approval.id] = approval

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._by_id.get(approval_id)

    def pending(self) -> list[ApprovalRequest]:
        return [a for a in self._by_id.values() if a.status == ApprovalStatus.PENDING]


class SqliteApprovalRepository:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, status TEXT, body TEXT)")
        self._conn.commit()

    def put(self, approval: ApprovalRequest) -> None:
        self._conn.execute("INSERT OR REPLACE INTO approvals VALUES (?,?,?)",
                           (approval.id, approval.status.value, approval.model_dump_json()))
        self._conn.commit()

    def get(self, approval_id: str) -> ApprovalRequest | None:
        row = self._conn.execute("SELECT body FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return ApprovalRequest.model_validate(json.loads(row[0])) if row else None

    def pending(self) -> list[ApprovalRequest]:
        rows = self._conn.execute("SELECT body FROM approvals WHERE status=?",
                                  (ApprovalStatus.PENDING.value,)).fetchall()
        return [ApprovalRequest.model_validate(json.loads(r[0])) for r in rows]


class ApprovalStore:
    def __init__(self, repo: ApprovalRepository | None = None, id_factory: IdFactory | None = None,
                 default_ttl_ms: int = 3_600_000):
        self._repo = repo or InMemoryApprovalRepository()
        self._ids = id_factory or IdFactory()
        self.default_ttl_ms = default_ttl_ms

    def create(self, *, context: DecisionContext, decision: PolicyDecision, summary: str,
               now_ms: int, ttl_ms: int | None = None, processed_untrusted: bool = False) -> ApprovalRequest:
        appr = ApprovalRequest(
            id=self._ids.approval(), run_id=context.run_id, call_id=context.call_id,
            context=context, decision=decision, argument_hash=context.argument_hash,
            summary=summary, created_at_ms=now_ms,
            expires_at_ms=now_ms + (ttl_ms or self.default_ttl_ms),
            processed_untrusted_content=processed_untrusted,
        )
        self._repo.put(appr)
        return appr

    def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._repo.get(approval_id)

    def resolve(self, approval_id: str, *, approve: bool, resolver_id: str, now_ms: int,
                note: str | None = None) -> ApprovalRequest:
        appr = self._repo.get(approval_id)
        if appr is None:
            raise KeyError(approval_id)
        if appr.status != ApprovalStatus.PENDING:
            return appr                                   # terminal states are final
        if appr.is_expired(now_ms):
            expired = appr.model_copy(update={"status": ApprovalStatus.EXPIRED})
            self._repo.put(expired)
            return expired
        status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        resolved = appr.model_copy(update={"status": status, "resolver_id": resolver_id,
                                           "resolved_at_ms": now_ms, "note": note})
        self._repo.put(resolved)
        return resolved

    def consume(self, approval_id: str, argument_hash: str, now_ms: int) -> bool:
        """Single-use: mark an APPROVED, unexpired, argument-matching approval
        CONSUMED. Returns True if it authorised this exact call; False otherwise.
        A consumed or mismatched approval never authorises a second call."""
        appr = self._repo.get(approval_id)
        if appr is None or not appr.authorises(argument_hash, now_ms):
            return False
        self._repo.put(appr.model_copy(update={"status": ApprovalStatus.CONSUMED}))
        return True

    def pending(self) -> list[ApprovalRequest]:
        return self._repo.pending()
