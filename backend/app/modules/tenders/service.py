"""Tender lifecycle. All transitions are validated here (domain layer) and audited."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.core.clock import Clock
from app.core.config import Settings
from app.core.errors import Conflict, InvalidTransition, NotFound, ValidationFailed, VersionConflict
from app.db.models import Bid, OfficerDecisionRecord, RulebookVersion, Tender
from app.modules.rulebooks.schemas import RulebookContent
from app.modules.tenders.schemas import (
    PublicTenderOut,
    RequiredDocumentOut,
    TenderCreate,
    TenderOut,
    TenderUpdate,
)
from app.shared.enums import Role, RulebookStatus, TenderStatus

TERMINAL = {TenderStatus.CANCELLED, TenderStatus.COMMERCIAL_EVALUATED}

# action -> (from statuses, to status, roles)
TRANSITIONS: dict[str, tuple[set[TenderStatus], TenderStatus, tuple[Role, ...]]] = {
    "publish": ({TenderStatus.DRAFT}, TenderStatus.OPEN_FOR_SUBMISSION, (Role.TENDER_ADMIN,)),
    "close": ({TenderStatus.OPEN_FOR_SUBMISSION}, TenderStatus.SUBMISSION_CLOSED, (Role.TENDER_ADMIN,)),
    "start-technical": (
        {TenderStatus.SUBMISSION_CLOSED},
        TenderStatus.TECHNICAL_EVALUATION,
        (Role.TENDER_ADMIN,),
    ),
    "complete-technical": (
        {TenderStatus.TECHNICAL_EVALUATION},
        TenderStatus.TECHNICAL_COMPLETED,
        (Role.APPROVER,),
    ),
    "cancel": (
        set(TenderStatus) - TERMINAL,
        TenderStatus.CANCELLED,
        (Role.TENDER_ADMIN,),
    ),
}


def get_tender(session: Session, tender_id: uuid.UUID) -> Tender:
    tender = session.get(Tender, tender_id)
    if tender is None:
        raise NotFound("Tender not found")
    return tender


def bid_count(session: Session, tender_id: uuid.UUID) -> int:
    return int(session.scalar(select(func.count()).select_from(Bid).where(Bid.tender_id == tender_id)) or 0)


def to_out(session: Session, tender: Tender, actor: Actor) -> TenderOut:
    version_no = None
    if tender.pinned_rulebook_version_id:
        rv = session.get(RulebookVersion, tender.pinned_rulebook_version_id)
        version_no = rv.version_no if rv else None
    allowed = [
        name
        for name, (sources, _to, roles) in TRANSITIONS.items()
        if tender.status in sources and actor.has(*roles)
    ]
    return TenderOut(
        id=tender.id,
        reference_no=tender.reference_no,
        title=tender.title,
        description=tender.description,
        authority=tender.authority,
        status=tender.status,
        timezone=tender.timezone,
        submission_deadline=tender.submission_deadline,
        commercial_envelope_required=tender.commercial_envelope_required,
        commercial_evaluation_method=tender.commercial_evaluation_method,
        opening_quorum=tender.opening_quorum,
        pinned_rulebook_version_id=tender.pinned_rulebook_version_id,
        pinned_rulebook_version_no=version_no,
        created_at=tender.created_at,
        closed_at=tender.closed_at,
        row_version=tender.row_version,
        bid_count=bid_count(session, tender.id),
        allowed_actions=allowed,
    )


def _snapshot(t: Tender) -> dict[str, object]:
    return {
        "reference_no": t.reference_no,
        "title": t.title,
        "authority": t.authority,
        "status": t.status.value,
        "submission_deadline": t.submission_deadline.isoformat(),
        "timezone": t.timezone,
        "commercial_envelope_required": t.commercial_envelope_required,
        "commercial_evaluation_method": t.commercial_evaluation_method,
        "opening_quorum": t.opening_quorum,
    }


def create_tender(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, data: TenderCreate
) -> Tender:
    actor.require(Role.TENDER_ADMIN)
    if session.scalar(select(Tender.id).where(Tender.reference_no == data.reference_no)):
        raise Conflict("A tender with this reference number already exists", code="DUPLICATE_REFERENCE")
    tender = Tender(
        reference_no=data.reference_no,
        title=data.title,
        description=data.description,
        authority=data.authority,
        submission_deadline=data.submission_deadline,
        timezone=data.timezone,
        commercial_envelope_required=data.commercial_envelope_required,
        commercial_evaluation_method=data.commercial_evaluation_method,
        opening_quorum=data.opening_quorum,
        created_by=actor.officer_id,
        created_at=clock.now(),
    )
    session.add(tender)
    session.flush()
    audit.record(
        session, actor, "TENDER_CREATED", "tender", tender.id, tender_id=tender.id, after=_snapshot(tender)
    )
    return tender


def update_tender(
    session: Session, actor: Actor, audit: AuditService, tender: Tender, data: TenderUpdate
) -> Tender:
    actor.require(Role.TENDER_ADMIN)
    if tender.status is not TenderStatus.DRAFT:
        raise InvalidTransition("Tender details can only be edited while in DRAFT")
    if data.row_version != tender.row_version:
        raise VersionConflict("Tender was modified by someone else; reload and retry")
    before = _snapshot(tender)
    for name in (
        "reference_no",
        "title",
        "description",
        "authority",
        "submission_deadline",
        "timezone",
        "commercial_envelope_required",
        "commercial_evaluation_method",
        "opening_quorum",
    ):
        setattr(tender, name, getattr(data, name))
    tender.row_version += 1
    session.flush()
    audit.record(
        session,
        actor,
        "TENDER_UPDATED",
        "tender",
        tender.id,
        tender_id=tender.id,
        before=before,
        after=_snapshot(tender),
    )
    return tender


def transition(
    session: Session,
    actor: Actor,
    audit: AuditService,
    clock: Clock,
    settings: Settings,
    tender: Tender,
    action: str,
    reason: str,
) -> Tender:
    """Apply a lifecycle action. Callers must commit before scheduling follow-up work."""
    if action not in TRANSITIONS:
        raise NotFound("Unknown tender action")
    sources, target, roles = TRANSITIONS[action]
    actor.require(*roles)
    if tender.status not in sources:
        raise InvalidTransition(f"Cannot {action} a tender in status {tender.status}")
    now = clock.now()
    audit_action = f"TENDER_{action.upper().replace('-', '_')}"

    if action == "publish":
        rv = (
            session.get(RulebookVersion, tender.pinned_rulebook_version_id)
            if tender.pinned_rulebook_version_id
            else None
        )
        if rv is None or rv.status is not RulebookStatus.APPROVED:
            raise Conflict(
                "An approved rulebook version must be pinned before publishing", code="RULEBOOK_NOT_APPROVED"
            )
        if tender.submission_deadline <= now:
            raise Conflict("Submission deadline must be in the future", code="DEADLINE_PASSED")
    elif action == "close":
        if now < tender.submission_deadline:
            if not settings.allow_demo_early_close:
                raise Conflict(
                    "Submissions cannot be closed before the deadline", code="DEADLINE_NOT_REACHED"
                )
            if len(reason.strip()) < 10:
                raise ValidationFailed("Early close (demo only) requires a reason of at least 10 characters")
            audit_action = "TENDER_CLOSED_EARLY_DEMO"
        tender.closed_at = now
    elif action == "complete-technical":
        bids = session.scalars(select(Bid.id).where(Bid.tender_id == tender.id)).all()
        decided = set(
            session.scalars(
                select(OfficerDecisionRecord.bid_id).where(
                    OfficerDecisionRecord.tender_id == tender.id, OfficerDecisionRecord.is_current.is_(True)
                )
            ).all()
        )
        pending = [b for b in bids if b not in decided]
        if pending:
            raise Conflict(
                f"{len(pending)} bid(s) still lack an officer technical decision", code="DECISIONS_PENDING"
            )
    elif action == "cancel" and len(reason.strip()) < 10:
        raise ValidationFailed("Cancellation requires a reason of at least 10 characters")

    before = tender.status
    tender.status = target
    tender.row_version += 1
    session.flush()
    audit.record(
        session,
        actor,
        audit_action,
        "tender",
        tender.id,
        tender_id=tender.id,
        reason=reason or None,
        before={"status": before.value},
        after={"status": target.value},
    )
    return tender


def accepting_submissions(tender: Tender, clock: Clock) -> bool:
    return tender.status is TenderStatus.OPEN_FOR_SUBMISSION and clock.now() < tender.submission_deadline


def public_view(session: Session, tender: Tender, clock: Clock) -> PublicTenderOut:
    docs: list[RequiredDocumentOut] = []
    if tender.pinned_rulebook_version_id:
        rv = session.get(RulebookVersion, tender.pinned_rulebook_version_id)
        if rv is not None:
            content = RulebookContent.model_validate(rv.content)
            docs = [
                RequiredDocumentOut(name=d.name, mandatory=d.mandatory) for d in content.document_requirements
            ]
    return PublicTenderOut(
        id=tender.id,
        reference_no=tender.reference_no,
        title=tender.title,
        description=tender.description,
        authority=tender.authority,
        timezone=tender.timezone,
        submission_deadline=tender.submission_deadline,
        accepting_submissions=accepting_submissions(tender, clock),
        commercial_envelope_required=tender.commercial_envelope_required,
        required_documents=docs,
    )


def bid_ids(session: Session, tender_id: uuid.UUID) -> list[uuid.UUID]:
    return list(session.scalars(select(Bid.id).where(Bid.tender_id == tender_id)).all())
