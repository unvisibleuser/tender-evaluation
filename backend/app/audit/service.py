"""Append-only, hash-chained audit trail.

Never put bid prices, document text, PAN/bank numbers or tokens into ``before``/``after``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authz.identity import Actor
from app.core.clock import Clock
from app.db.models import AuditChainHead, AuditEvent

GENESIS = "0" * 64

# Keys that must never appear in audit payloads (defence in depth).
_FORBIDDEN_KEYS = {"quoted_total", "quoted_total_amount", "amount", "price", "text", "token", "password"}


def _clean(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    bad = _FORBIDDEN_KEYS.intersection(k.lower() for k in payload)
    if bad:
        raise ValueError(f"audit payload contains forbidden keys: {sorted(bad)}")
    cleaned: dict[str, Any] = json.loads(json.dumps(payload, default=str))
    return cleaned


def _event_hash(prev_hash: str, body: dict[str, Any]) -> str:
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + data).encode()).hexdigest()


def _body(e: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "tender_id": str(e.tender_id) if e.tender_id else None,
        "bid_id": str(e.bid_id) if e.bid_id else None,
        "actor_kind": e.actor_kind.value,
        "actor_id": e.actor_id,
        "actor_label": e.actor_label,
        "actor_roles": sorted(e.actor_roles),
        "action": e.action,
        "object_type": e.object_type,
        "object_id": e.object_id,
        "reason": e.reason,
        "before": e.before,
        "after": e.after,
        "correlation_id": e.correlation_id,
        "created_at": e.created_at.isoformat(),
    }


@dataclass
class AuditService:
    clock: Clock
    correlation_id: str | None = None

    def record(
        self,
        session: Session,
        actor: Actor,
        action: str,
        object_type: str,
        object_id: uuid.UUID | str | None,
        *,
        tender_id: uuid.UUID | None = None,
        bid_id: uuid.UUID | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> AuditEvent:
        head = session.execute(
            select(AuditChainHead).where(AuditChainHead.id == 1).with_for_update()
        ).scalar_one_or_none()
        if head is None:
            head = AuditChainHead(id=1, last_hash=GENESIS)
            session.add(head)
            session.flush()
        event = AuditEvent(
            id=uuid.uuid4(),
            tender_id=tender_id,
            bid_id=bid_id,
            actor_kind=actor.kind,
            actor_id=actor.id,
            actor_label=actor.label,
            actor_roles=sorted(r.value for r in actor.roles),
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            reason=reason,
            before=_clean(before),
            after=_clean(after),
            correlation_id=self.correlation_id,
            created_at=at or self.clock.now(),
            prev_hash=head.last_hash,
            hash="",
        )
        event.hash = _event_hash(event.prev_hash, _body(event))
        head.last_hash = event.hash
        session.add(event)
        session.flush()
        return event


def verify_chain(session: Session) -> tuple[bool, int, str | None]:
    """Returns (ok, events_checked, first_broken_event_id)."""
    prev = GENESIS
    count = 0
    for event in session.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        count += 1
        if event.prev_hash != prev or _event_hash(prev, _body(event)) != event.hash:
            return False, count, str(event.id)
        prev = event.hash
    head = session.get(AuditChainHead, 1)
    if head is not None and head.last_hash != prev:
        return False, count, None
    return True, count, None
