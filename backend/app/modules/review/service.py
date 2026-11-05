"""Human review queue. Field tasks are resolved by creating officer revisions (bids.service)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, NotFound
from app.db.models import Bid, ReviewTask, Tender
from app.modules.bids.service import OFFICER_ROLES, require_unsealed
from app.modules.processing.service import refresh_status
from app.shared.enums import ReviewReason, ReviewTaskStatus, Role

PAGE_REASONS = {ReviewReason.PAGE_UNREADABLE}


class ReviewTaskOut(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    bid_id: uuid.UUID
    bid_reference: str
    bidder_legal_name: str
    reason: ReviewReason
    field_key: str | None
    page_no: int | None
    detail: str
    status: ReviewTaskStatus
    created_at: datetime
    resolved_at: datetime | None
    resolution: str | None
    resolution_path: str


class ReviewTaskList(BaseModel):
    items: list[ReviewTaskOut]
    total: int
    limit: int
    offset: int


class AcknowledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution: str = Field(min_length=5, max_length=2000)


def _path(t: ReviewTask) -> str:
    if t.field_key:
        return "FIELD_REVISION"  # resolve via POST /bids/{bid}/fields/{key}/revisions
    if t.reason is ReviewReason.POSSIBLE_COMMERCIAL_LEAKAGE:
        return "APPROVER_RELEASE_OR_ACKNOWLEDGE"
    return "ACKNOWLEDGE"


def list_tasks(
    session: Session, actor: Actor, tender: Tender, status: ReviewTaskStatus | None, limit: int, offset: int
) -> ReviewTaskList:
    actor.require(*OFFICER_ROLES)
    require_unsealed(tender)
    q = (
        select(ReviewTask, Bid)
        .join(Bid, Bid.id == ReviewTask.bid_id)
        .where(ReviewTask.tender_id == tender.id)
    )
    if status is not None:
        q = q.where(ReviewTask.status == status)
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.execute(q.order_by(ReviewTask.created_at, ReviewTask.id).limit(limit).offset(offset)).all()
    return ReviewTaskList(
        items=[
            ReviewTaskOut(
                id=t.id,
                tender_id=t.tender_id,
                bid_id=t.bid_id,
                bid_reference=b.bid_reference,
                bidder_legal_name=b.bidder_legal_name,
                reason=t.reason,
                field_key=t.field_key,
                page_no=t.page_no,
                detail=t.detail,
                status=t.status,
                created_at=t.created_at,
                resolved_at=t.resolved_at,
                resolution=t.resolution,
                resolution_path=_path(t),
            )
            for t, b in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


def acknowledge(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, task_id: uuid.UUID, resolution: str
) -> None:
    task = session.get(ReviewTask, task_id)
    if task is None:
        raise NotFound("Review task not found")
    tender = session.get(Tender, task.tender_id)
    assert tender is not None
    require_unsealed(tender)
    if task.status is not ReviewTaskStatus.OPEN:
        raise Conflict("Task is already resolved", code="ALREADY_RESOLVED")
    if task.field_key:
        raise Conflict(
            "Field tasks are resolved by verifying or correcting the field value", code="USE_FIELD_REVISION"
        )
    if task.reason is ReviewReason.POSSIBLE_COMMERCIAL_LEAKAGE:
        actor.require(Role.APPROVER)  # "keep withheld" acknowledgement
    else:
        actor.require(Role.TECHNICAL_EVALUATOR)
    task.status, task.resolved_by, task.resolved_at = ReviewTaskStatus.RESOLVED, actor.officer_id, clock.now()
    task.resolution = resolution
    bid = session.get(Bid, task.bid_id)
    assert bid is not None
    refresh_status(session, bid)
    audit.record(
        session,
        actor,
        "REVIEW_TASK_ACKNOWLEDGED",
        "review_task",
        task.id,
        tender_id=task.tender_id,
        bid_id=task.bid_id,
        reason=resolution,
        after={"reason": task.reason.value, "page": task.page_no},
    )
