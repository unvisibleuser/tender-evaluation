from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import Conflict, ValidationFailed
from app.db.models import IdempotencyRecord


def check_key(key: str | None) -> str | None:
    if key is None:
        return None
    key = key.strip()
    if not (8 <= len(key) <= 120) or not key.replace("-", "").replace("_", "").isalnum():
        raise ValidationFailed("Idempotency-Key must be 8-120 alphanumeric/dash characters")
    return key


def lookup(session: Session, scope: str, key: str | None, request_hash: str) -> dict[str, Any] | None:
    if key is None:
        return None
    rec = session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.scope == scope, IdempotencyRecord.key == key)
    )
    if rec is None:
        return None
    if rec.request_hash != request_hash:
        raise Conflict("Idempotency-Key reused with a different request", code="IDEMPOTENCY_MISMATCH")
    return rec.response


def store(
    session: Session, clock: Clock, scope: str, key: str | None, request_hash: str, response: dict[str, Any]
) -> None:
    if key is None:
        return
    session.add(
        IdempotencyRecord(
            scope=scope, key=key, request_hash=request_hash, response=response, created_at=clock.now()
        )
    )
