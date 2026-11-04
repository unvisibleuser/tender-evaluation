"""Rulebook versioning: DRAFT -> IN_REVIEW -> APPROVED (immutable) -> SUPERSEDED.

The author of a version can never approve it (separation of duties). Approved content is frozen;
changes require a new version based on it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, Forbidden, InvalidTransition, NotFound, VersionConflict
from app.db.models import RulebookVersion, Tender
from app.modules.rulebooks.schemas import RulebookContent, RulebookVersionOut
from app.modules.rulebooks.validation import has_blocking, validate_rulebook
from app.shared.enums import Role, RulebookStatus, TenderStatus
from rule_engine import canonical_hash


def content_hash(content: RulebookContent) -> str:
    return canonical_hash(content.model_dump(mode="json"))


def get_version(session: Session, version_id: uuid.UUID) -> RulebookVersion:
    rv = session.get(RulebookVersion, version_id)
    if rv is None:
        raise NotFound("Rulebook version not found")
    return rv


def to_out(session: Session, rv: RulebookVersion) -> RulebookVersionOut:
    tender = session.get(Tender, rv.tender_id)
    content = RulebookContent.model_validate(rv.content)
    return RulebookVersionOut(
        id=rv.id,
        tender_id=rv.tender_id,
        version_no=rv.version_no,
        status=rv.status,
        content=content,
        content_hash=rv.content_hash,
        based_on_id=rv.based_on_id,
        created_by=rv.created_by,
        created_at=rv.created_at,
        submitted_at=rv.submitted_at,
        approved_by=rv.approved_by,
        approved_at=rv.approved_at,
        approval_reason=rv.approval_reason,
        row_version=rv.row_version,
        is_pinned=bool(tender and tender.pinned_rulebook_version_id == rv.id),
        issues=validate_rulebook(content),
    )


def create_version(
    session: Session,
    actor: Actor,
    audit: AuditService,
    clock: Clock,
    tender: Tender,
    based_on_id: uuid.UUID | None,
) -> RulebookVersion:
    actor.require(Role.TENDER_ADMIN)
    if tender.status not in (TenderStatus.DRAFT, TenderStatus.OPEN_FOR_SUBMISSION):
        raise InvalidTransition("Rulebook versions can only be created before submissions close")
    content = RulebookContent()
    if based_on_id is not None:
        base = get_version(session, based_on_id)
        if base.tender_id != tender.id:
            raise NotFound("Rulebook version not found")
        content = RulebookContent.model_validate(base.content)
    next_no = (
        int(
            session.scalar(
                select(func.coalesce(func.max(RulebookVersion.version_no), 0)).where(
                    RulebookVersion.tender_id == tender.id
                )
            )
            or 0
        )
        + 1
    )
    rv = RulebookVersion(
        tender_id=tender.id,
        version_no=next_no,
        status=RulebookStatus.DRAFT,
        content=content.model_dump(mode="json"),
        content_hash=content_hash(content),
        based_on_id=based_on_id,
        created_by=actor.officer_id,
        last_edited_by=actor.officer_id,
        created_at=clock.now(),
    )
    session.add(rv)
    session.flush()
    audit.record(
        session,
        actor,
        "RULEBOOK_VERSION_CREATED",
        "rulebook_version",
        rv.id,
        tender_id=tender.id,
        after={"version_no": next_no, "based_on_id": str(based_on_id) if based_on_id else None},
    )
    return rv


def update_content(
    session: Session,
    actor: Actor,
    audit: AuditService,
    rv: RulebookVersion,
    content: RulebookContent,
    row_version: int,
) -> RulebookVersion:
    actor.require(Role.TENDER_ADMIN)
    if rv.status is not RulebookStatus.DRAFT:
        raise InvalidTransition("Only DRAFT rulebook versions can be edited; create a new version instead")
    if row_version != rv.row_version:
        raise VersionConflict("Rulebook was modified by someone else; reload and retry")
    before_hash = rv.content_hash
    rv.content = content.model_dump(mode="json")
    rv.content_hash = content_hash(content)
    rv.last_edited_by = actor.officer_id
    rv.row_version += 1
    session.flush()
    audit.record(
        session,
        actor,
        "RULEBOOK_DRAFT_EDITED",
        "rulebook_version",
        rv.id,
        tender_id=rv.tender_id,
        before={"content_hash": before_hash},
        after={"content_hash": rv.content_hash, "criteria": len(content.criteria)},
    )
    return rv


def submit(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, rv: RulebookVersion, reason: str
) -> None:
    actor.require(Role.TENDER_ADMIN)
    if rv.status is not RulebookStatus.DRAFT:
        raise InvalidTransition("Only DRAFT versions can be submitted for approval")
    issues = validate_rulebook(RulebookContent.model_validate(rv.content))
    if has_blocking(issues):
        raise Conflict(
            "Rulebook has blocking validation issues",
            code="RULEBOOK_INVALID",
            details=[i.model_dump() for i in issues if i.severity == "BLOCKING"],
        )
    rv.status = RulebookStatus.IN_REVIEW
    rv.submitted_by = actor.officer_id
    rv.submitted_at = clock.now()
    rv.row_version += 1
    audit.record(
        session,
        actor,
        "RULEBOOK_SUBMITTED",
        "rulebook_version",
        rv.id,
        tender_id=rv.tender_id,
        reason=reason,
        before={"status": "DRAFT"},
        after={"status": "IN_REVIEW"},
    )


def request_changes(
    session: Session, actor: Actor, audit: AuditService, rv: RulebookVersion, reason: str
) -> None:
    actor.require(Role.APPROVER)
    if rv.status is not RulebookStatus.IN_REVIEW:
        raise InvalidTransition("Only IN_REVIEW versions can be returned for changes")
    rv.status = RulebookStatus.DRAFT
    rv.row_version += 1
    audit.record(
        session,
        actor,
        "RULEBOOK_CHANGES_REQUESTED",
        "rulebook_version",
        rv.id,
        tender_id=rv.tender_id,
        reason=reason,
        before={"status": "IN_REVIEW"},
        after={"status": "DRAFT"},
    )


def approve(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, rv: RulebookVersion, reason: str
) -> None:
    actor.require(Role.APPROVER)
    if rv.status is not RulebookStatus.IN_REVIEW:
        raise InvalidTransition("Only IN_REVIEW versions can be approved")
    officer = actor.officer_id
    if officer in (rv.created_by, rv.last_edited_by, rv.submitted_by):
        raise Forbidden(
            "Separation of duties: the author/editor of a rulebook version cannot approve it",
            code="SEPARATION_OF_DUTIES",
        )
    content = RulebookContent.model_validate(rv.content)
    if has_blocking(validate_rulebook(content)):
        raise Conflict("Rulebook has blocking validation issues", code="RULEBOOK_INVALID")
    if content_hash(content) != rv.content_hash:
        raise Conflict("Rulebook content hash mismatch", code="INTEGRITY_ERROR")
    rv.status = RulebookStatus.APPROVED
    rv.approved_by = officer
    rv.approved_at = clock.now()
    rv.approval_reason = reason
    rv.row_version += 1
    audit.record(
        session,
        actor,
        "RULEBOOK_APPROVED",
        "rulebook_version",
        rv.id,
        tender_id=rv.tender_id,
        reason=reason,
        before={"status": "IN_REVIEW"},
        after={"status": "APPROVED", "content_hash": rv.content_hash},
    )


def pin(
    session: Session, actor: Actor, audit: AuditService, tender: Tender, rv: RulebookVersion, reason: str
) -> None:
    """Make an APPROVED version the one all bids are evaluated against."""
    actor.require(Role.TENDER_ADMIN)
    if rv.tender_id != tender.id:
        raise NotFound("Rulebook version not found")
    if rv.status is not RulebookStatus.APPROVED:
        raise Conflict("Only APPROVED versions can be pinned", code="RULEBOOK_NOT_APPROVED")
    if tender.status not in (TenderStatus.DRAFT, TenderStatus.OPEN_FOR_SUBMISSION):
        raise InvalidTransition("The evaluation rulebook cannot change after submissions close")
    previous = tender.pinned_rulebook_version_id
    if previous == rv.id:
        return
    if previous is not None:
        old = session.get(RulebookVersion, previous)
        if old is not None:
            old.status = RulebookStatus.SUPERSEDED
    tender.pinned_rulebook_version_id = rv.id
    tender.row_version += 1
    audit.record(
        session,
        actor,
        "RULEBOOK_PINNED",
        "tender",
        tender.id,
        tender_id=tender.id,
        reason=reason,
        before={"pinned_rulebook_version_id": str(previous) if previous else None},
        after={"pinned_rulebook_version_id": str(rv.id), "content_hash": rv.content_hash},
    )


def pinned_content(session: Session, tender: Tender) -> tuple[RulebookVersion, RulebookContent]:
    if tender.pinned_rulebook_version_id is None:
        raise Conflict("Tender has no pinned rulebook", code="RULEBOOK_NOT_PINNED")
    rv = get_version(session, tender.pinned_rulebook_version_id)
    if rv.status is not RulebookStatus.APPROVED:
        raise Conflict("Pinned rulebook is not approved", code="RULEBOOK_NOT_APPROVED")
    content = RulebookContent.model_validate(rv.content)
    if content_hash(content) != rv.content_hash:
        raise Conflict("Pinned rulebook failed integrity check", code="INTEGRITY_ERROR")
    return rv, content


@event.listens_for(RulebookVersion, "before_update")
def _guard_approved_immutable(_mapper: object, _conn: object, target: RulebookVersion) -> None:
    """ORM-level guard: approved/superseded content can never be changed in place."""
    state = inspect(target)
    status_hist = state.attrs.status.history
    original_status = status_hist.deleted[0] if status_hist.deleted else target.status
    if original_status in (RulebookStatus.APPROVED, RulebookStatus.SUPERSEDED):
        for attr in ("content", "content_hash", "approved_by", "approved_at", "approval_reason"):
            if state.attrs[attr].history.has_changes():
                raise Conflict("Approved rulebook versions are immutable", code="RULEBOOK_IMMUTABLE")
