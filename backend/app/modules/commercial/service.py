"""Sealed commercial envelopes, dual-control opening and tender-defined commercial evaluation.

Rules:
- Before the opening event nobody (including commercial officers) can read prices or price PDFs.
- Opening requires tender status TECHNICAL_COMPLETED, ``opening_quorum`` distinct authorising
  officers, and decrypts ONLY envelopes of bids an officer recorded as technically RESPONSIVE.
- Ranking runs only with the tender's configured method; otherwise REQUIRES_OFFICER_CONFIGURATION.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.core.clock import Clock
from app.core.errors import CommercialSealed, Conflict, InvalidTransition, NotFound
from app.db.models import Bid, OfficerUser, Tender
from app.modules.commercial.models import (
    CommercialEnvelope,
    CommercialOffer,
    CommercialOpeningAuthorization,
    CommercialOpeningEvent,
    RankingSnapshot,
)
from app.modules.commercial.vault import CommercialVault
from app.shared.enums import CommercialMethod, Role, TechnicalOutcome, TenderStatus

OPENED_STATUSES = {TenderStatus.COMMERCIAL_OPENED, TenderStatus.COMMERCIAL_EVALUATED}


class SealReceipt(BaseModel):
    envelope_id: uuid.UUID
    plaintext_sha256: str
    size_bytes: int


class AuthorizationOut(BaseModel):
    officer_id: uuid.UUID
    officer_label: str
    created_at: str
    reason: str


class CommercialStatusOut(BaseModel):
    tender_status: TenderStatus
    sealed: bool
    envelopes_received: int
    eligible_bids: int
    quorum: int
    authorizations: list[AuthorizationOut]
    can_authorize: bool
    can_open: bool
    opened_at: str | None
    opened_by: str | None
    evaluation_method: CommercialMethod | None


class OfferOut(BaseModel):
    bid_id: uuid.UUID
    bid_reference: str
    bidder_legal_name: str
    quoted_total: str
    currency: str
    source: str


class RankingRow(BaseModel):
    rank: int
    bid_id: str
    bid_reference: str
    bidder_legal_name: str
    quoted_total: str
    currency: str
    tie: bool


class RankingOut(BaseModel):
    id: uuid.UUID
    method: CommercialMethod
    method_label: str
    created_at: str
    rows: list[RankingRow]
    notes: list[str]


METHOD_LABELS = {
    CommercialMethod.LOWEST_QUOTED_TOTAL: "Lowest quoted total price (L1), as configured for this tender"
}


def seal_envelope(
    session: Session,
    vault: CommercialVault,
    clock: Clock,
    tender: Tender,
    bid: Bid,
    document: bytes,
    quoted_total: Decimal,
    currency: str = "INR",
) -> SealReceipt:
    envelope_id = uuid.uuid4()
    sealed = vault.seal(envelope_id, document, quoted_total)
    session.add(
        CommercialEnvelope(
            id=envelope_id,
            tender_id=tender.id,
            bid_id=bid.id,
            storage_key=sealed.storage_key,
            ciphertext_sha256=sealed.ciphertext_sha256,
            plaintext_sha256=sealed.plaintext_sha256,
            size_bytes=sealed.size_bytes,
            wrapped_key=sealed.wrapped_key,
            sealed_amount=sealed.sealed_amount,
            currency=currency,
            received_at=clock.now(),
        )
    )
    return SealReceipt(
        envelope_id=envelope_id, plaintext_sha256=sealed.plaintext_sha256, size_bytes=sealed.size_bytes
    )


def _require_commercial_reader(actor: Actor) -> None:
    actor.require(Role.COMMERCIAL_OFFICER, Role.AUDITOR)


def _event(session: Session, tender_id: uuid.UUID) -> CommercialOpeningEvent | None:
    return session.scalar(select(CommercialOpeningEvent).where(CommercialOpeningEvent.tender_id == tender_id))


def _eligible_bids(session: Session, tender_id: uuid.UUID) -> list[Bid]:
    return list(
        session.scalars(
            select(Bid).where(
                Bid.tender_id == tender_id, Bid.technical_outcome == TechnicalOutcome.RESPONSIVE
            )
        ).all()
    )


def _label(session: Session, officer_id: uuid.UUID) -> str:
    u = session.get(OfficerUser, officer_id)
    return f"{u.display_name} ({u.username})" if u else str(officer_id)


def status(session: Session, actor: Actor, tender: Tender) -> CommercialStatusOut:
    _require_commercial_reader(actor)
    auths = session.scalars(
        select(CommercialOpeningAuthorization)
        .where(CommercialOpeningAuthorization.tender_id == tender.id)
        .order_by(CommercialOpeningAuthorization.created_at)
    ).all()
    envelopes = session.scalars(
        select(CommercialEnvelope.id).where(CommercialEnvelope.tender_id == tender.id)
    ).all()
    event = _event(session, tender.id)
    ready = tender.status is TenderStatus.TECHNICAL_COMPLETED
    already = actor.id is not None and any(str(a.officer_id) == actor.id for a in auths)
    return CommercialStatusOut(
        tender_status=tender.status,
        sealed=event is None,
        envelopes_received=len(envelopes),
        eligible_bids=len(_eligible_bids(session, tender.id)),
        quorum=tender.opening_quorum,
        authorizations=[
            AuthorizationOut(
                officer_id=a.officer_id,
                officer_label=_label(session, a.officer_id),
                created_at=a.created_at.isoformat(),
                reason=a.reason,
            )
            for a in auths
        ],
        can_authorize=ready and actor.has(Role.COMMERCIAL_OFFICER) and not already and event is None,
        can_open=ready
        and actor.has(Role.COMMERCIAL_OFFICER)
        and len(auths) >= tender.opening_quorum
        and event is None,
        opened_at=event.executed_at.isoformat() if event else None,
        opened_by=_label(session, event.executed_by) if event else None,
        evaluation_method=tender.commercial_evaluation_method,
    )


def authorize(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, tender: Tender, reason: str
) -> None:
    actor.require(Role.COMMERCIAL_OFFICER)
    if tender.status is not TenderStatus.TECHNICAL_COMPLETED:
        raise InvalidTransition(
            "Commercial opening can be authorised only after technical evaluation is completed"
        )
    if _event(session, tender.id) is not None:
        raise Conflict("Commercial bids already opened", code="ALREADY_OPENED")
    existing = session.scalar(
        select(CommercialOpeningAuthorization).where(
            CommercialOpeningAuthorization.tender_id == tender.id,
            CommercialOpeningAuthorization.officer_id == actor.officer_id,
        )
    )
    if existing is not None:
        raise Conflict("You have already authorised this opening", code="ALREADY_AUTHORIZED")
    auth = CommercialOpeningAuthorization(
        tender_id=tender.id, officer_id=actor.officer_id, reason=reason, created_at=clock.now()
    )
    session.add(auth)
    session.flush()
    audit.record(
        session,
        actor,
        "COMMERCIAL_OPENING_AUTHORIZED",
        "tender",
        tender.id,
        tender_id=tender.id,
        reason=reason,
        after={"authorization_id": str(auth.id)},
    )


def open_envelopes(
    session: Session,
    actor: Actor,
    audit: AuditService,
    clock: Clock,
    vault: CommercialVault,
    tender: Tender,
    reason: str,
) -> CommercialOpeningEvent:
    actor.require(Role.COMMERCIAL_OFFICER)
    if tender.status is not TenderStatus.TECHNICAL_COMPLETED:
        raise InvalidTransition("Commercial opening requires technical evaluation to be completed")
    if _event(session, tender.id) is not None:
        raise Conflict("Commercial bids already opened", code="ALREADY_OPENED")
    auths = session.scalars(
        select(CommercialOpeningAuthorization).where(CommercialOpeningAuthorization.tender_id == tender.id)
    ).all()
    distinct = {a.officer_id for a in auths}
    if len(distinct) < tender.opening_quorum:
        raise Conflict(
            f"Opening requires {tender.opening_quorum} distinct authorising officers; "
            f"{len(distinct)} recorded",
            code="QUORUM_NOT_MET",
        )
    eligible = _eligible_bids(session, tender.id)
    eligible_ids = {b.id for b in eligible}
    envelopes = session.scalars(
        select(CommercialEnvelope).where(CommercialEnvelope.tender_id == tender.id)
    ).all()
    event = CommercialOpeningEvent(
        tender_id=tender.id,
        executed_by=actor.officer_id,
        executed_at=clock.now(),
        authorizer_ids=sorted(str(i) for i in distinct),
        eligible_bid_ids=sorted(str(i) for i in eligible_ids),
        sealed_bid_ids=sorted(str(e.bid_id) for e in envelopes if e.bid_id not in eligible_ids),
        verified_hashes={},
        reason=reason,
    )
    session.add(event)
    session.flush()
    verified: dict[str, str] = {}
    for env in envelopes:
        if env.bid_id not in eligible_ids:
            continue  # technically non-responsive envelopes are never decrypted
        opened = vault.open(
            env.id,
            env.storage_key,
            env.wrapped_key,
            env.sealed_amount,
            env.plaintext_sha256,
            opening_event_id=event.id,
        )
        session.add(
            CommercialOffer(
                tender_id=tender.id,
                bid_id=env.bid_id,
                opening_event_id=event.id,
                quoted_total=opened.quoted_total,
                currency=env.currency,
            )
        )
        verified[str(env.bid_id)] = env.plaintext_sha256
    event.verified_hashes = verified
    tender.status = TenderStatus.COMMERCIAL_OPENED
    tender.row_version += 1
    session.flush()
    audit.record(
        session,
        actor,
        "COMMERCIAL_OPENED",
        "tender",
        tender.id,
        tender_id=tender.id,
        reason=reason,
        before={"status": TenderStatus.TECHNICAL_COMPLETED.value},
        after={
            "status": TenderStatus.COMMERCIAL_OPENED.value,
            "opening_event_id": str(event.id),
            "authorizers": event.authorizer_ids,
            "opened_bids": sorted(verified),
            "left_sealed": event.sealed_bid_ids,
            "verified_hashes": verified,
        },
    )
    return event


def _require_opened(session: Session, actor: Actor, tender: Tender) -> CommercialOpeningEvent:
    _require_commercial_reader(actor)
    event = _event(session, tender.id)
    if event is None or tender.status not in OPENED_STATUSES:
        raise CommercialSealed("Commercial bids are sealed until the authorised opening event")
    return event


def offers(session: Session, actor: Actor, tender: Tender) -> list[OfferOut]:
    _require_opened(session, actor, tender)
    rows = session.execute(
        select(CommercialOffer, Bid)
        .join(Bid, Bid.id == CommercialOffer.bid_id)
        .where(CommercialOffer.tender_id == tender.id)
    ).all()
    return [
        OfferOut(
            bid_id=b.id,
            bid_reference=b.bid_reference,
            bidder_legal_name=b.bidder_legal_name,
            quoted_total=format(o.quoted_total, "f"),
            currency=o.currency,
            source=o.source,
        )
        for o, b in sorted(rows, key=lambda r: r[1].bid_reference)
    ]


def price_document(
    session: Session,
    actor: Actor,
    audit: AuditService,
    vault: CommercialVault,
    tender: Tender,
    bid_id: uuid.UUID,
) -> bytes:
    event = _require_opened(session, actor, tender)
    if str(bid_id) not in event.eligible_bid_ids:
        raise CommercialSealed("This envelope was not opened (bid not technically responsive)")
    env = session.scalar(
        select(CommercialEnvelope).where(
            CommercialEnvelope.bid_id == bid_id, CommercialEnvelope.tender_id == tender.id
        )
    )
    if env is None:
        raise NotFound("Commercial envelope not found")
    opened = vault.open(
        env.id,
        env.storage_key,
        env.wrapped_key,
        env.sealed_amount,
        env.plaintext_sha256,
        opening_event_id=event.id,
    )
    audit.record(
        session,
        actor,
        "COMMERCIAL_DOCUMENT_VIEWED",
        "commercial_envelope",
        env.id,
        tender_id=tender.id,
        bid_id=bid_id,
    )
    return opened.document


def evaluate(session: Session, actor: Actor, audit: AuditService, clock: Clock, tender: Tender) -> RankingOut:
    actor.require(Role.COMMERCIAL_OFFICER)
    _require_opened(session, actor, tender)
    if tender.status is not TenderStatus.COMMERCIAL_OPENED:
        raise InvalidTransition("Commercial evaluation has already been recorded for this tender")
    method = tender.commercial_evaluation_method
    if method is None:
        raise Conflict(
            "No tender-defined commercial evaluation method is configured",
            code="REQUIRES_OFFICER_CONFIGURATION",
        )
    offer_rows = offers(session, actor, tender)
    ordered = sorted(offer_rows, key=lambda o: (Decimal(o.quoted_total), o.bid_reference))
    rows: list[RankingRow] = []
    rank = 0
    previous: Decimal | None = None
    for idx, o in enumerate(ordered):
        amount = Decimal(o.quoted_total)
        if previous is None or amount != previous:
            rank = idx + 1
        previous = amount
        tie = sum(1 for x in ordered if Decimal(x.quoted_total) == amount) > 1
        rows.append(
            RankingRow(
                rank=rank,
                bid_id=str(o.bid_id),
                bid_reference=o.bid_reference,
                bidder_legal_name=o.bidder_legal_name,
                quoted_total=o.quoted_total,
                currency=o.currency,
                tie=tie,
            )
        )
    snap = RankingSnapshot(
        tender_id=tender.id,
        method=method,
        created_by=actor.officer_id,
        created_at=clock.now(),
        result=[r.model_dump() for r in rows],
    )
    session.add(snap)
    tender.status = TenderStatus.COMMERCIAL_EVALUATED
    tender.row_version += 1
    session.flush()
    audit.record(
        session,
        actor,
        "COMMERCIAL_EVALUATED",
        "ranking_snapshot",
        snap.id,
        tender_id=tender.id,
        before={"status": TenderStatus.COMMERCIAL_OPENED.value},
        after={
            "status": TenderStatus.COMMERCIAL_EVALUATED.value,
            "method": method.value,
            "ranked_bids": len(rows),
        },
    )
    return _ranking_out(snap)


def _ranking_out(snap: RankingSnapshot) -> RankingOut:
    rows = [RankingRow.model_validate(r) for r in snap.result]
    notes = ["Ranking is computed by the tender-configured method only. It is not an award decision."]
    if any(r.tie for r in rows):
        notes.append(
            "Tied offers exist; tie resolution must follow the tender's stated procedure (officer action)."
        )
    notes.append(
        "Combined technical-commercial ranking is not available: no tender-published formula is configured."
    )
    return RankingOut(
        id=snap.id,
        method=snap.method,
        method_label=METHOD_LABELS[snap.method],
        created_at=snap.created_at.isoformat(),
        rows=rows,
        notes=notes,
    )


def latest_ranking(session: Session, actor: Actor, tender: Tender) -> RankingOut | None:
    _require_opened(session, actor, tender)
    snap = session.scalars(
        select(RankingSnapshot)
        .where(RankingSnapshot.tender_id == tender.id)
        .order_by(RankingSnapshot.created_at.desc())
    ).first()
    return _ranking_out(snap) if snap else None
