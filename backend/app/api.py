"""HTTP routes (/api/v1). Handlers are thin: authenticate, validate, call a service, commit, respond."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.audit.service import verify_chain
from app.authz.identity import Actor, issue_token
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.db.models import AuditEvent, OfficerUser, RulebookVersion, Tender
from app.deps import AuditDep, ContainerDep, OfficerDep, SessionDep
from app.modules.bids import service as bids
from app.modules.bids.schemas import (
    BidDetailOut,
    BidListOut,
    BidReceipt,
    FieldOut,
    FieldRevisionIn,
    ReasonIn,
    ReclassifyIn,
)
from app.modules.commercial import service as commercial
from app.modules.evaluation import service as evaluation
from app.modules.processing.service import process_bid
from app.modules.review import service as review
from app.modules.rulebooks import service as rulebooks
from app.modules.rulebooks.schemas import (
    CreateVersionIn,
    PinIn,
    RulebookContent,
    RulebookVersionOut,
    UpdateContentIn,
    ValidationIssue,
)
from app.modules.rulebooks.schemas import ReasonIn as RbReasonIn
from app.modules.rulebooks.validation import validate_rulebook
from app.modules.tenders import artifacts
from app.modules.tenders import service as tenders
from app.modules.tenders.schemas import PublicTenderOut, TenderCreate, TenderOut, TenderUpdate, TransitionIn
from app.shared.enums import ActorKind, ReviewTaskStatus, Role, TenderStatus

router = APIRouter(prefix="/api/v1")
PNG = {"content-type": "image/png", "cache-control": "no-store"}


# ------------------------------------------------------------------ auth (MVP dev identity)


class DevLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=2, max_length=64)


class OfficerOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    designation: str
    roles: list[Role]


class LoginOut(BaseModel):
    token: str
    officer: OfficerOut
    environment: str


def _officer_out(u: OfficerUser) -> OfficerOut:
    return OfficerOut(
        id=u.id,
        username=u.username,
        display_name=u.display_name,
        designation=u.designation,
        roles=[Role(r) for r in u.roles],
    )


@router.get("/auth/demo-officers", response_model=list[OfficerOut], tags=["auth"])
def demo_officers(c: ContainerDep, s: SessionDep) -> list[OfficerOut]:
    if c.settings.auth_mode != "dev":
        raise NotFound("Not available")
    return [
        _officer_out(u)
        for u in s.scalars(
            select(OfficerUser).where(OfficerUser.active.is_(True)).order_by(OfficerUser.username)
        ).all()
    ]


@router.post("/auth/dev-login", response_model=LoginOut, tags=["auth"])
def dev_login(body: DevLoginIn, c: ContainerDep, s: SessionDep, a: AuditDep) -> LoginOut:
    if c.settings.auth_mode != "dev":
        raise NotFound("Not available")
    user = s.scalar(
        select(OfficerUser).where(OfficerUser.username == body.username, OfficerUser.active.is_(True))
    )
    if user is None:
        raise Forbidden("Unknown officer")
    token = issue_token(
        c.settings.token_secret, user.id, int(c.clock.now().timestamp()), c.settings.token_ttl_seconds
    )

    a.record(
        s,
        Actor(
            ActorKind.OFFICER,
            str(user.id),
            f"{user.display_name} ({user.username})",
            frozenset(Role(r) for r in user.roles),
        ),
        "OFFICER_SIGNED_IN",
        "officer_user",
        user.id,
    )
    s.commit()
    return LoginOut(token=token, officer=_officer_out(user), environment=c.settings.environment)


@router.get("/auth/me", response_model=OfficerOut, tags=["auth"])
def me(actor: OfficerDep, s: SessionDep) -> OfficerOut:
    user = s.get(OfficerUser, actor.officer_id)
    assert user is not None
    return _officer_out(user)


# ------------------------------------------------------------------ public bidder portal (no auth in MVP)


@router.get("/public/tenders", response_model=list[PublicTenderOut], tags=["bidder-portal"])
def public_tenders(c: ContainerDep, s: SessionDep) -> list[PublicTenderOut]:
    rows = s.scalars(
        select(Tender)
        .where(Tender.status == TenderStatus.OPEN_FOR_SUBMISSION)
        .order_by(Tender.submission_deadline)
    ).all()
    return [tenders.public_view(s, t, c.clock) for t in rows]


@router.get("/public/tenders/{tender_id}", response_model=PublicTenderOut, tags=["bidder-portal"])
def public_tender(tender_id: uuid.UUID, c: ContainerDep, s: SessionDep) -> PublicTenderOut:
    t = s.get(Tender, tender_id)
    if t is None or t.status is not TenderStatus.OPEN_FOR_SUBMISSION:
        raise NotFound("Tender not found or not open for submission")
    return tenders.public_view(s, t, c.clock)


@router.post(
    "/public/tenders/{tender_id}/bids", response_model=BidReceipt, status_code=201, tags=["bidder-portal"]
)
async def submit_bid(
    tender_id: uuid.UUID,
    c: ContainerDep,
    s: SessionDep,
    bidder_legal_name: Annotated[str, Form(max_length=300)],
    bidder_email: Annotated[str, Form(max_length=320)],
    bidder_phone: Annotated[str, Form(max_length=40)],
    declaration_accepted: Annotated[bool, Form()],
    technical_pdf: Annotated[UploadFile, File()],
    commercial_pdf: Annotated[UploadFile | None, File()] = None,
    quoted_total_amount: Annotated[str | None, Form(max_length=40)] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> BidReceipt:
    t = s.get(Tender, tender_id)
    if t is None or t.status is not TenderStatus.OPEN_FOR_SUBMISSION:
        raise NotFound("Tender not found or not open for submission")
    limit = c.settings.max_upload_bytes
    tech = await technical_pdf.read(limit + 1)
    comm = await commercial_pdf.read(limit + 1) if commercial_pdf is not None else None
    receipt = bids.submit_bid(
        s,
        c,
        t,
        legal_name=bidder_legal_name,
        email=bidder_email,
        phone=bidder_phone,
        declaration_accepted=declaration_accepted,
        technical_pdf=tech,
        technical_filename=technical_pdf.filename,
        commercial_pdf=comm or None,
        quoted_total=quoted_total_amount,
        idempotency_key=idempotency_key,
    )
    s.commit()
    return receipt


# ------------------------------------------------------------------ tenders


@router.get("/tenders", response_model=list[TenderOut], tags=["tenders"])
def list_tenders(actor: OfficerDep, s: SessionDep) -> list[TenderOut]:
    actor.require(*bids.OFFICER_ROLES)
    return [
        tenders.to_out(s, t, actor)
        for t in s.scalars(select(Tender).order_by(Tender.created_at.desc())).all()
    ]


@router.post("/tenders", response_model=TenderOut, status_code=201, tags=["tenders"])
def create_tender(
    body: TenderCreate, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> TenderOut:
    t = tenders.create_tender(s, actor, a, c.clock, body)
    s.commit()
    return tenders.to_out(s, t, actor)


@router.get("/tenders/{tender_id}", response_model=TenderOut, tags=["tenders"])
def get_tender(tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> TenderOut:
    actor.require(*bids.OFFICER_ROLES)
    return tenders.to_out(s, tenders.get_tender(s, tender_id), actor)


@router.put("/tenders/{tender_id}", response_model=TenderOut, tags=["tenders"])
def update_tender(
    tender_id: uuid.UUID, body: TenderUpdate, actor: OfficerDep, s: SessionDep, a: AuditDep
) -> TenderOut:
    t = tenders.update_tender(s, actor, a, tenders.get_tender(s, tender_id), body)
    s.commit()
    return tenders.to_out(s, t, actor)


@router.post("/tenders/{tender_id}/actions/{action}", response_model=TenderOut, tags=["tenders"])
def tender_action(
    tender_id: uuid.UUID,
    action: str,
    body: TransitionIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> TenderOut:
    t = tenders.transition(
        s, actor, a, c.clock, c.settings, tenders.get_tender(s, tender_id), action, body.reason
    )
    s.commit()
    if action == "close":  # schedule document processing only after the close is durable
        for bid_id in tenders.bid_ids(s, t.id):
            c.tasks.submit(process_bid, c, bid_id)
    return tenders.to_out(s, t, actor)


@router.post(
    "/tenders/{tender_id}/documents",
    response_model=artifacts.TenderArtifactOut,
    status_code=201,
    tags=["tenders"],
)
async def upload_tender_document(
    tender_id: uuid.UUID,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
    title: Annotated[str, Form(max_length=300)],
    file: Annotated[UploadFile, File()],
) -> artifacts.TenderArtifactOut:
    data = await file.read(c.settings.max_upload_bytes + 1)
    art = artifacts.upload(s, c, actor, a, tenders.get_tender(s, tender_id), title, file.filename, data)
    s.commit()
    return artifacts.to_out(art)


@router.get(
    "/tenders/{tender_id}/documents", response_model=list[artifacts.TenderArtifactOut], tags=["tenders"]
)
def list_tender_documents(
    tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep
) -> list[artifacts.TenderArtifactOut]:
    return [artifacts.to_out(x) for x in artifacts.list_for(s, actor, tenders.get_tender(s, tender_id))]


@router.get("/tender-documents/{artifact_id}/pages/{page_no}/image", tags=["tenders"])
def tender_document_page(
    artifact_id: uuid.UUID, page_no: int, actor: OfficerDep, c: ContainerDep, s: SessionDep
) -> Response:
    return Response(artifacts.page_png(s, c, actor, artifact_id, page_no), headers=PNG)


# ------------------------------------------------------------------ rulebooks


@router.get(
    "/tenders/{tender_id}/rulebook/versions", response_model=list[RulebookVersionOut], tags=["rulebooks"]
)
def list_versions(tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> list[RulebookVersionOut]:
    actor.require(*bids.OFFICER_ROLES)
    t = tenders.get_tender(s, tender_id)
    rows = s.scalars(
        select(RulebookVersion)
        .where(RulebookVersion.tender_id == t.id)
        .order_by(RulebookVersion.version_no.desc())
    ).all()
    return [rulebooks.to_out(s, r) for r in rows]


@router.post(
    "/tenders/{tender_id}/rulebook/versions",
    response_model=RulebookVersionOut,
    status_code=201,
    tags=["rulebooks"],
)
def create_version(
    tender_id: uuid.UUID,
    body: CreateVersionIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> RulebookVersionOut:
    rv = rulebooks.create_version(s, actor, a, c.clock, tenders.get_tender(s, tender_id), body.based_on_id)
    s.commit()
    return rulebooks.to_out(s, rv)


@router.get("/rulebook-versions/{version_id}", response_model=RulebookVersionOut, tags=["rulebooks"])
def get_version(version_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> RulebookVersionOut:
    actor.require(*bids.OFFICER_ROLES)
    return rulebooks.to_out(s, rulebooks.get_version(s, version_id))


@router.put("/rulebook-versions/{version_id}/content", response_model=RulebookVersionOut, tags=["rulebooks"])
def update_version(
    version_id: uuid.UUID, body: UpdateContentIn, actor: OfficerDep, s: SessionDep, a: AuditDep
) -> RulebookVersionOut:
    rv = rulebooks.update_content(
        s, actor, a, rulebooks.get_version(s, version_id), body.content, body.row_version
    )
    s.commit()
    return rulebooks.to_out(s, rv)


@router.post("/rulebook/validate", response_model=list[ValidationIssue], tags=["rulebooks"])
def validate_content(body: RulebookContent, actor: OfficerDep) -> list[ValidationIssue]:
    actor.require(*bids.OFFICER_ROLES)
    return validate_rulebook(body)


@router.post(
    "/rulebook-versions/{version_id}/{action}", response_model=RulebookVersionOut, tags=["rulebooks"]
)
def version_action(
    version_id: uuid.UUID,
    action: str,
    body: RbReasonIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> RulebookVersionOut:
    rv = rulebooks.get_version(s, version_id)
    if action == "submit":
        rulebooks.submit(s, actor, a, c.clock, rv, body.reason)
    elif action == "approve":
        rulebooks.approve(s, actor, a, c.clock, rv, body.reason)
    elif action == "request-changes":
        rulebooks.request_changes(s, actor, a, rv, body.reason)
    else:
        raise NotFound("Unknown rulebook action")
    s.commit()
    return rulebooks.to_out(s, rv)


@router.post("/tenders/{tender_id}/rulebook/pin", response_model=TenderOut, tags=["rulebooks"])
def pin_version(
    tender_id: uuid.UUID, body: PinIn, actor: OfficerDep, s: SessionDep, a: AuditDep
) -> TenderOut:
    t = tenders.get_tender(s, tender_id)
    rulebooks.pin(s, actor, a, t, rulebooks.get_version(s, body.version_id), body.reason)
    s.commit()
    return tenders.to_out(s, t, actor)


# ------------------------------------------------------------------ bids / technical scrutiny


@router.get("/tenders/{tender_id}/bids", response_model=BidListOut, tags=["bids"])
def list_bids(
    tender_id: uuid.UUID,
    actor: OfficerDep,
    s: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> BidListOut:
    return bids.list_bids(s, actor, tenders.get_tender(s, tender_id), limit, offset, q)


@router.get("/bids/{bid_id}", response_model=BidDetailOut, tags=["bids"])
def bid_detail(bid_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> BidDetailOut:
    return bids.bid_detail(s, actor, bid_id)


@router.get("/bids/{bid_id}/pages/{page_no}/image", tags=["bids"])
def bid_page_image(
    bid_id: uuid.UUID, page_no: int, actor: OfficerDep, c: ContainerDep, s: SessionDep
) -> Response:
    return Response(bids.page_image(s, c, actor, bid_id, page_no), headers=PNG)


@router.get("/bids/{bid_id}/fields/{field_key}/history", response_model=list[FieldOut], tags=["bids"])
def field_history(bid_id: uuid.UUID, field_key: str, actor: OfficerDep, s: SessionDep) -> list[FieldOut]:
    return bids.field_history(s, actor, bid_id, field_key)


@router.post("/bids/{bid_id}/fields/{field_key}/revisions", response_model=BidDetailOut, tags=["bids"])
def field_revision(
    bid_id: uuid.UUID,
    field_key: str,
    body: FieldRevisionIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> BidDetailOut:
    bids.add_field_revision(s, c, actor, a, bid_id, field_key, body)
    s.commit()
    return bids.bid_detail(s, actor, bid_id)


@router.post("/bids/{bid_id}/pages/{page_no}/classification", response_model=BidDetailOut, tags=["bids"])
def reclassify(
    bid_id: uuid.UUID,
    page_no: int,
    body: ReclassifyIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> BidDetailOut:
    bids.reclassify_page(s, c, actor, a, bid_id, page_no, body.doc_class, body.reason)
    s.commit()
    return bids.bid_detail(s, actor, bid_id)


@router.post("/bids/{bid_id}/pages/{page_no}/release", response_model=BidDetailOut, tags=["bids"])
def release_page(
    bid_id: uuid.UUID,
    page_no: int,
    body: ReasonIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> BidDetailOut:
    bids.release_withheld_page(s, c, actor, a, bid_id, page_no, body.reason)
    s.commit()
    return bids.bid_detail(s, actor, bid_id)


@router.post("/bids/{bid_id}/reprocess", response_model=BidDetailOut, tags=["bids"])
def reprocess(bid_id: uuid.UUID, actor: OfficerDep, c: ContainerDep, s: SessionDep) -> BidDetailOut:
    """Retry document processing for a bid whose pipeline FAILED."""
    actor.require(Role.TECHNICAL_EVALUATOR)
    bid, _t = bids.get_bid_for_officer(s, actor, bid_id)
    if bid.processing_status.value != "FAILED":
        raise ValidationFailed("Only failed bids can be reprocessed")
    process_bid(c, bid.id)
    s.expire_all()
    return bids.bid_detail(s, actor, bid_id)


# ------------------------------------------------------------------ review queue


@router.get("/tenders/{tender_id}/review-tasks", response_model=review.ReviewTaskList, tags=["review"])
def review_tasks(
    tender_id: uuid.UUID,
    actor: OfficerDep,
    s: SessionDep,
    status: ReviewTaskStatus | None = ReviewTaskStatus.OPEN,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> review.ReviewTaskList:
    return review.list_tasks(s, actor, tenders.get_tender(s, tender_id), status, limit, offset)


@router.post("/review-tasks/{task_id}/acknowledge", status_code=204, tags=["review"])
def acknowledge_task(
    task_id: uuid.UUID,
    body: review.AcknowledgeIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> Response:
    review.acknowledge(s, actor, a, c.clock, task_id, body.resolution)
    s.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ technical evaluation & decisions


@router.post(
    "/tenders/{tender_id}/evaluation-runs",
    response_model=evaluation.RunOut,
    status_code=201,
    tags=["evaluation"],
)
def run_evaluation(
    tender_id: uuid.UUID, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> evaluation.RunOut:
    run = evaluation.run_technical_evaluation(s, actor, a, c.clock, tenders.get_tender(s, tender_id))
    s.commit()
    return evaluation.run_detail(s, actor, run.id)


@router.get(
    "/tenders/{tender_id}/evaluation-runs", response_model=list[evaluation.RunSummaryOut], tags=["evaluation"]
)
def list_runs(tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> list[evaluation.RunSummaryOut]:
    return evaluation.list_runs(s, actor, tenders.get_tender(s, tender_id))


@router.get("/evaluation-runs/{run_id}", response_model=evaluation.RunOut, tags=["evaluation"])
def get_run(run_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> evaluation.RunOut:
    return evaluation.run_detail(s, actor, run_id)


@router.post(
    "/bids/{bid_id}/technical-decision",
    response_model=evaluation.DecisionOut,
    status_code=201,
    tags=["evaluation"],
)
def technical_decision(
    bid_id: uuid.UUID,
    body: evaluation.DecisionIn,
    actor: OfficerDep,
    c: ContainerDep,
    s: SessionDep,
    a: AuditDep,
) -> evaluation.DecisionOut:
    rec = evaluation.record_decision(s, actor, a, c.clock, bid_id, body)
    s.commit()
    return evaluation._decision_out(s, rec)


# ------------------------------------------------------------------ commercial (sealed)


@router.get(
    "/tenders/{tender_id}/commercial/status",
    response_model=commercial.CommercialStatusOut,
    tags=["commercial"],
)
def commercial_status(
    tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep
) -> commercial.CommercialStatusOut:
    return commercial.status(s, actor, tenders.get_tender(s, tender_id))


@router.post(
    "/tenders/{tender_id}/commercial/authorizations",
    response_model=commercial.CommercialStatusOut,
    tags=["commercial"],
)
def commercial_authorize(
    tender_id: uuid.UUID, body: RbReasonIn, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> commercial.CommercialStatusOut:
    t = tenders.get_tender(s, tender_id)
    commercial.authorize(s, actor, a, c.clock, t, body.reason)
    s.commit()
    return commercial.status(s, actor, t)


@router.post(
    "/tenders/{tender_id}/commercial/open", response_model=commercial.CommercialStatusOut, tags=["commercial"]
)
def commercial_open(
    tender_id: uuid.UUID, body: RbReasonIn, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> commercial.CommercialStatusOut:
    t = tenders.get_tender(s, tender_id)
    commercial.open_envelopes(s, actor, a, c.clock, c.vault, t, body.reason)
    s.commit()
    return commercial.status(s, actor, t)


@router.get(
    "/tenders/{tender_id}/commercial/offers", response_model=list[commercial.OfferOut], tags=["commercial"]
)
def commercial_offers(tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep) -> list[commercial.OfferOut]:
    return commercial.offers(s, actor, tenders.get_tender(s, tender_id))


@router.get("/tenders/{tender_id}/commercial/bids/{bid_id}/document", tags=["commercial"])
def commercial_document(
    tender_id: uuid.UUID, bid_id: uuid.UUID, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> Response:
    data = commercial.price_document(s, actor, a, c.vault, tenders.get_tender(s, tender_id), bid_id)
    s.commit()
    return Response(
        data,
        headers={
            "content-type": "application/pdf",
            "cache-control": "no-store",
            "content-disposition": "inline; filename=price-bid.pdf",
        },
    )


@router.post(
    "/tenders/{tender_id}/commercial/evaluation", response_model=commercial.RankingOut, tags=["commercial"]
)
def commercial_evaluate(
    tender_id: uuid.UUID, actor: OfficerDep, c: ContainerDep, s: SessionDep, a: AuditDep
) -> commercial.RankingOut:
    out = commercial.evaluate(s, actor, a, c.clock, tenders.get_tender(s, tender_id))
    s.commit()
    return out


@router.get(
    "/tenders/{tender_id}/commercial/ranking",
    response_model=commercial.RankingOut | None,
    tags=["commercial"],
)
def commercial_ranking(
    tender_id: uuid.UUID, actor: OfficerDep, s: SessionDep
) -> commercial.RankingOut | None:
    return commercial.latest_ranking(s, actor, tenders.get_tender(s, tender_id))


# ------------------------------------------------------------------ audit


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: str
    actor_kind: str
    actor_label: str
    actor_roles: list[str]
    action: str
    object_type: str
    object_id: str | None
    bid_id: uuid.UUID | None
    reason: str | None
    before: dict[str, object] | None
    after: dict[str, object] | None
    hash: str


class AuditListOut(BaseModel):
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int


class AuditVerifyOut(BaseModel):
    ok: bool
    events_checked: int
    first_broken_event_id: str | None


@router.get("/tenders/{tender_id}/audit-events", response_model=AuditListOut, tags=["audit"])
def audit_events(
    tender_id: uuid.UUID,
    actor: OfficerDep,
    s: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditListOut:
    actor.require(*bids.OFFICER_ROLES)
    t = tenders.get_tender(s, tender_id)
    q = select(AuditEvent).where(AuditEvent.tender_id == t.id)
    total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = s.scalars(q.order_by(AuditEvent.seq.desc()).limit(limit).offset(offset)).all()
    return AuditListOut(
        items=[
            AuditEventOut(
                id=e.id,
                created_at=e.created_at.isoformat(),
                actor_kind=e.actor_kind.value,
                actor_label=e.actor_label,
                actor_roles=e.actor_roles,
                action=e.action,
                object_type=e.object_type,
                object_id=e.object_id,
                bid_id=e.bid_id,
                reason=e.reason,
                before=e.before,
                after=e.after,
                hash=e.hash,
            )
            for e in rows
        ],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/audit/verify", response_model=AuditVerifyOut, tags=["audit"])
def audit_verify(actor: OfficerDep, s: SessionDep) -> AuditVerifyOut:
    actor.require(Role.AUDITOR, Role.TENDER_ADMIN)
    ok, n, broken = verify_chain(s)
    return AuditVerifyOut(ok=ok, events_checked=n, first_broken_event_id=broken)
