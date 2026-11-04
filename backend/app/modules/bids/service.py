"""Bid submission (public bidder portal) and officer-side technical scrutiny operations."""

from __future__ import annotations

import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.container import Container
from app.core import idempotency
from app.core.errors import (
    CommercialSealed,
    Conflict,
    InvalidTransition,
    NotFound,
    TechnicalSealed,
    ValidationFailed,
)
from app.core.ids import bid_reference
from app.db.models import Artifact, ArtifactPage, Bid, ExtractedField, OfficerUser, ReviewTask, Tender
from app.deps import bidder_actor
from app.modules.bids.schemas import (
    BidDetailOut,
    BidListOut,
    BidReceipt,
    BidSummaryOut,
    DocumentPresenceOut,
    FieldOut,
    FieldRevisionIn,
    FileReceipt,
    PageOut,
)
from app.modules.commercial import service as commercial
from app.modules.processing import service as processing
from app.modules.processing.evidence import bid_pages, current_fields, document_evidence
from app.modules.processing.normalize import normalize
from app.modules.processing.pdf import inspect_pdf, parse_single_page, render_page_png
from app.modules.rulebooks.schemas import RulebookContent
from app.modules.rulebooks.service import pinned_content
from app.modules.tenders.service import accepting_submissions
from app.shared.enums import (
    TECHNICAL_UNSEALED_STATUSES,
    ActorKind,
    ArtifactOwner,
    ClassificationMethod,
    ExtractionMethod,
    FieldStatus,
    PageTextStatus,
    ReviewReason,
    ReviewState,
    ReviewTaskStatus,
    Role,
    TenderStatus,
)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^[0-9+\-() ]{6,20}$")
OFFICER_ROLES = tuple(Role)
SCRUTINY_STATUSES = {TenderStatus.SUBMISSION_CLOSED, TenderStatus.TECHNICAL_EVALUATION}


def _safe_filename(name: str | None) -> str:
    base = (name or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^A-Za-z0-9._\- ]", "_", base)[:120]
    return base or "document.pdf"


def parse_amount(raw: str | None) -> Decimal:
    if raw is None or not raw.strip():
        raise ValidationFailed("Quoted total amount is required", code="AMOUNT_REQUIRED")
    try:
        amount = Decimal(raw.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ValidationFailed("Quoted total must be a number", code="AMOUNT_INVALID") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValidationFailed(
            "Quoted total must be positive with at most 2 decimal places", code="AMOUNT_INVALID"
        )
    if amount >= Decimal("1e15"):
        raise ValidationFailed("Quoted total is out of range", code="AMOUNT_INVALID")
    return amount


# --------------------------------------------------------------------------- bidder submission


def submit_bid(
    session: Session,
    container: Container,
    tender: Tender,
    *,
    legal_name: str,
    email: str,
    phone: str,
    declaration_accepted: bool,
    technical_pdf: bytes,
    technical_filename: str | None,
    commercial_pdf: bytes | None,
    quoted_total: str | None,
    idempotency_key: str | None,
) -> BidReceipt:
    clock, settings = container.clock, container.settings
    key = idempotency.check_key(idempotency_key)
    legal_name = " ".join(legal_name.split())
    email = email.strip().lower()
    phone = phone.strip()
    tech_sha = hashlib.sha256(technical_pdf).hexdigest()
    comm_sha = hashlib.sha256(commercial_pdf).hexdigest() if commercial_pdf else ""
    request_hash = hashlib.sha256(f"{email}|{tech_sha}|{comm_sha}|{quoted_total}".encode()).hexdigest()
    scope = f"bid-submit:{tender.id}"
    replay = idempotency.lookup(session, scope, key, request_hash)
    if replay is not None:
        return BidReceipt.model_validate(replay)

    if not accepting_submissions(tender, clock):
        raise Conflict(
            "This tender is not accepting submissions (closed or deadline passed)", code="SUBMISSION_CLOSED"
        )
    if not (2 <= len(legal_name) <= 300):
        raise ValidationFailed("Bidder legal name is required", code="NAME_INVALID")
    if not _EMAIL.match(email):
        raise ValidationFailed("A valid email address is required", code="EMAIL_INVALID")
    if not _PHONE.match(phone):
        raise ValidationFailed("A valid phone number is required", code="PHONE_INVALID")
    if not declaration_accepted:
        raise ValidationFailed("The bidder declaration must be accepted", code="DECLARATION_REQUIRED")

    pages = inspect_pdf(technical_pdf, max_bytes=settings.max_upload_bytes, max_pages=settings.max_pdf_pages)
    amount: Decimal | None = None
    if tender.commercial_envelope_required:
        if not commercial_pdf:
            raise ValidationFailed(
                "The sealed price bid PDF is required for this tender", code="COMMERCIAL_REQUIRED"
            )
        inspect_pdf(commercial_pdf, max_bytes=settings.max_upload_bytes, max_pages=settings.max_pdf_pages)
        amount = parse_amount(quoted_total)
    elif commercial_pdf or quoted_total:
        raise ValidationFailed(
            "This tender does not accept a separate price bid", code="COMMERCIAL_NOT_ACCEPTED"
        )

    if session.scalar(select(Bid.id).where(Bid.tender_id == tender.id, Bid.bidder_email == email)):
        raise Conflict(
            "A bid from this email address has already been submitted for this tender",
            code="DUPLICATE_SUBMISSION",
        )

    now = clock.now()
    bid = Bid(
        tender_id=tender.id,
        bid_reference=bid_reference(),
        bidder_legal_name=legal_name,
        bidder_email=email,
        bidder_phone=phone,
        submitted_at=now,
        package_sha256="",
    )
    session.add(bid)
    session.flush()

    storage_key = container.technical_store.put(technical_pdf)
    filename = _safe_filename(technical_filename)
    artifact = Artifact(
        tender_id=tender.id,
        owner_type=ArtifactOwner.BID,
        bid_id=bid.id,
        title="Technical bid (combined PDF)",
        original_filename=filename,
        sha256=tech_sha,
        size_bytes=len(technical_pdf),
        page_count=pages,
        storage_key=storage_key,
        uploaded_at=now,
    )
    session.add(artifact)
    session.flush()
    bid.technical_artifact_id = artifact.id

    commercial_receipt: FileReceipt | None = None
    if amount is not None and commercial_pdf:
        sealed = commercial.seal_envelope(
            session, container.vault, clock, tender, bid, commercial_pdf, amount
        )
        # The receipt shows only the hash and size; the original filename is not retained.
        commercial_receipt = FileReceipt(
            filename="price-bid (sealed)", sha256=sealed.plaintext_sha256, size_bytes=sealed.size_bytes
        )
    bid.package_sha256 = hashlib.sha256(f"{tech_sha}:{comm_sha}".encode()).hexdigest()
    session.flush()

    container_audit = AuditService(clock=clock)
    container_audit.record(
        session,
        bidder_actor(bid.id, legal_name),
        "BID_SUBMITTED",
        "bid",
        bid.id,
        tender_id=tender.id,
        bid_id=bid.id,
        after={
            "bid_reference": bid.bid_reference,
            "technical_sha256": tech_sha,
            "technical_pages": pages,
            "commercial_envelope_sha256": comm_sha or None,
            "package_sha256": bid.package_sha256,
        },
    )
    receipt = BidReceipt(
        bid_reference=bid.bid_reference,
        tender_reference=tender.reference_no,
        tender_title=tender.title,
        bidder_legal_name=legal_name,
        received_at=now,
        technical=FileReceipt(
            filename=filename, sha256=tech_sha, size_bytes=len(technical_pdf), page_count=pages
        ),
        commercial=commercial_receipt,
        commercial_sealed=commercial_receipt is not None,
        package_sha256=bid.package_sha256,
        notice="Your submission has been received and locked. Keep this receipt. The price bid is encrypted and "
        "will only be opened after technical evaluation, by authorised officers, if your bid is found "
        "technically responsive.",
    )
    idempotency.store(session, clock, scope, key, request_hash, receipt.model_dump(mode="json"))
    return receipt


# --------------------------------------------------------------------------- officer access


def require_unsealed(tender: Tender) -> None:
    if tender.status not in TECHNICAL_UNSEALED_STATUSES:
        raise TechnicalSealed("Bid contents are sealed until submissions close")


def get_bid_for_officer(session: Session, actor: Actor, bid_id: uuid.UUID) -> tuple[Bid, Tender]:
    actor.require(*OFFICER_ROLES)
    bid = session.get(Bid, bid_id)
    if bid is None:
        raise NotFound("Bid not found")
    tender = session.get(Tender, bid.tender_id)
    assert tender is not None
    require_unsealed(tender)
    return bid, tender


def _summary(session: Session, bid: Bid) -> BidSummaryOut:
    pages = bid_pages(session, bid)
    open_tasks = (
        session.scalar(
            select(func.count())
            .select_from(ReviewTask)
            .where(ReviewTask.bid_id == bid.id, ReviewTask.status == ReviewTaskStatus.OPEN)
        )
        or 0
    )
    artifact = session.get(Artifact, bid.technical_artifact_id) if bid.technical_artifact_id else None
    return BidSummaryOut(
        id=bid.id,
        tender_id=bid.tender_id,
        bid_reference=bid.bid_reference,
        bidder_legal_name=bid.bidder_legal_name,
        submitted_at=bid.submitted_at,
        processing_status=bid.processing_status,
        processing_error=bid.processing_error,
        technical_outcome=bid.technical_outcome,
        page_count=artifact.page_count if artifact else 0,
        open_review_tasks=int(open_tasks),
        withheld_pages=sum(p.text_status is PageTextStatus.WITHHELD_COMMERCIAL for p in pages),
        unreadable_pages=sum(p.text_status is PageTextStatus.NO_TEXT_LAYER for p in pages),
    )


def list_bids(
    session: Session, actor: Actor, tender: Tender, limit: int, offset: int, search: str | None
) -> BidListOut:
    actor.require(*OFFICER_ROLES)
    require_unsealed(tender)
    q = select(Bid).where(Bid.tender_id == tender.id)
    if search:
        like = f"%{search.strip()[:100]}%"
        q = q.where(Bid.bidder_legal_name.ilike(like) | Bid.bid_reference.ilike(like))
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = session.scalars(q.order_by(Bid.submitted_at).limit(limit).offset(offset)).all()
    return BidListOut(
        items=[_summary(session, b) for b in rows], total=int(total), limit=limit, offset=offset
    )


def _provenance(row: ExtractedField) -> str:
    if row.review_state is ReviewState.OFFICER_CORRECTED:
        return "Officer corrected"
    if row.review_state is ReviewState.OFFICER_VERIFIED:
        return "Officer verified"
    if row.review_state is ReviewState.PENDING_REVIEW:
        return "Automated extraction — pending officer review"
    return "Automated extraction (unverified)"


def _officer_label(session: Session, row: ExtractedField) -> str:
    if row.created_by_kind is ActorKind.SYSTEM or row.created_by is None:
        return f"system ({row.extractor_version})"
    u = session.get(OfficerUser, row.created_by)
    return u.display_name if u else "officer"


def field_out(session: Session, row: ExtractedField, content: RulebookContent) -> FieldOut:
    fd = content.field_map().get(row.field_key)
    return FieldOut(
        id=row.id,
        field_key=row.field_key,
        label=fd.label if fd else row.field_key,
        data_type=fd.data_type.value if fd else "string",
        revision_no=row.revision_no,
        status=row.status,
        raw_value=row.raw_value,
        source_line=row.source_line,
        normalized_value=row.normalized_value,
        unit=row.unit,
        confidence=row.confidence,
        method=row.method,
        page_no=row.page_no,
        bbox=row.bbox,
        flags=row.flags,
        candidates=row.candidates,
        review_state=row.review_state,
        provenance=_provenance(row),
        created_at=row.created_at,
        created_by_label=_officer_label(session, row),
        reason=row.reason,
    )


def bid_detail(session: Session, actor: Actor, bid_id: uuid.UUID) -> BidDetailOut:
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    _rv, content = pinned_content(session, tender)
    pages = bid_pages(session, bid)
    artifact = session.get(Artifact, bid.technical_artifact_id) if bid.technical_artifact_id else None
    docs = document_evidence(content, pages)
    fields = current_fields(session, bid.id)
    order = {f.field_key: i for i, f in enumerate(content.fields)}
    return BidDetailOut(
        bid=_summary(session, bid),
        bidder_email=bid.bidder_email,
        bidder_phone=bid.bidder_phone,
        technical_sha256=artifact.sha256 if artifact else None,
        technical_filename=artifact.original_filename if artifact else None,
        pages=[
            PageOut(
                page_no=p.page_no,
                width=p.width,
                height=p.height,
                text_status=p.text_status,
                doc_class=p.doc_class,
                classification_method=p.classification_method,
                classification_confidence=p.classification_confidence,
                matched_keywords=p.matched_keywords,
                leakage_indicators=p.leakage_indicators,
            )
            for p in pages
        ],
        documents=[
            DocumentPresenceOut(
                doc_class=d.doc_class,
                name=d.name,
                mandatory=d.mandatory,
                presence=docs[d.doc_class].presence.value,
                pages=list(docs[d.doc_class].pages),
            )
            for d in content.document_requirements
        ],
        fields=[
            field_out(session, r, content)
            for r in sorted(fields.values(), key=lambda r: order.get(r.field_key, 999))
        ],
    )


def field_history(session: Session, actor: Actor, bid_id: uuid.UUID, field_key: str) -> list[FieldOut]:
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    _rv, content = pinned_content(session, tender)
    rows = session.scalars(
        select(ExtractedField)
        .where(ExtractedField.bid_id == bid.id, ExtractedField.field_key == field_key)
        .order_by(ExtractedField.revision_no.desc())
    ).all()
    return [field_out(session, r, content) for r in rows]


def page_image(
    session: Session, container: Container, actor: Actor, bid_id: uuid.UUID, page_no: int
) -> bytes:
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    page = session.scalar(
        select(ArtifactPage).where(
            ArtifactPage.artifact_id == bid.technical_artifact_id, ArtifactPage.page_no == page_no
        )
    )
    if page is None:
        raise NotFound("Page not found")
    if page.text_status is PageTextStatus.WITHHELD_COMMERCIAL:
        raise CommercialSealed("This page is withheld: it may contain price information")
    artifact = session.get(Artifact, bid.technical_artifact_id)
    assert artifact is not None
    return render_page_png(container.technical_store.get(artifact.storage_key), page_no)


def _require_scrutiny(tender: Tender) -> None:
    if tender.status not in SCRUTINY_STATUSES:
        raise InvalidTransition("Evidence can only be changed during technical scrutiny")


def add_field_revision(
    session: Session,
    container: Container,
    actor: Actor,
    audit: AuditService,
    bid_id: uuid.UUID,
    field_key: str,
    data: FieldRevisionIn,
) -> ExtractedField:
    actor.require(Role.TECHNICAL_EVALUATOR)
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    _require_scrutiny(tender)
    _rv, content = pinned_content(session, tender)
    fd = content.field_map().get(field_key)
    if fd is None:
        raise NotFound("Field is not defined in the pinned rulebook")
    prior = current_fields(session, bid.id).get(field_key)
    artifact = session.get(Artifact, bid.technical_artifact_id) if bid.technical_artifact_id else None
    now = container.clock.now()
    new = ExtractedField(
        bid_id=bid.id,
        field_key=field_key,
        revision_no=(prior.revision_no + 1) if prior else 1,
        supersedes_id=prior.id if prior else None,
        is_current=True,
        extractor_version="officer",
        created_by_kind=ActorKind.OFFICER,
        created_by=actor.officer_id,
        reason=data.reason,
        created_at=now,
        flags=[],
        candidates=prior.candidates if prior else [],
    )
    if data.action == "VERIFY":
        if prior is None or prior.status is not FieldStatus.EXTRACTED or prior.normalized_value is None:
            raise Conflict(
                "Only an extracted value can be verified; use CORRECT to enter a value",
                code="NOTHING_TO_VERIFY",
            )
        for attr in (
            "status",
            "raw_value",
            "source_line",
            "normalized_value",
            "unit",
            "confidence",
            "method",
            "artifact_id",
            "page_no",
            "bbox",
            "flags",
        ):
            setattr(new, attr, getattr(prior, attr))
        new.review_state = ReviewState.OFFICER_VERIFIED
    elif data.action == "CORRECT":
        if not data.value or data.page_no is None:
            raise ValidationFailed("A corrected value and the evidence page number are required")
        if artifact is None or data.page_no > artifact.page_count:
            raise ValidationFailed("Evidence page number is outside the submitted document")
        norm = normalize(data.value, fd.data_type, fd.unit)
        if norm.value is None:
            raise ValidationFailed(
                f"Value could not be interpreted as {fd.data_type.value}: {', '.join(norm.flags)}",
                code="VALUE_UNPARSEABLE",
            )
        new.status, new.raw_value, new.normalized_value = FieldStatus.EXTRACTED, data.value, norm.value
        new.unit, new.confidence, new.method = norm.unit or fd.unit, None, ExtractionMethod.HUMAN
        new.artifact_id, new.page_no, new.bbox = artifact.id, data.page_no, None
        new.flags = norm.flags
        new.review_state = ReviewState.OFFICER_CORRECTED
    else:
        new.status = FieldStatus.MISSING if data.action == "CONFIRM_MISSING" else FieldStatus.UNREADABLE
        new.method = ExtractionMethod.HUMAN
        new.page_no = data.page_no
        new.artifact_id = artifact.id if artifact and data.page_no else None
        new.review_state = ReviewState.OFFICER_VERIFIED
    if prior is not None:
        prior.is_current = False
        session.flush()
    session.add(new)
    session.flush()
    processing.close_field_tasks(
        session,
        container.clock,
        bid.id,
        field_key,
        f"{data.action} by officer: {data.reason}",
        actor.officer_id,
    )
    processing.refresh_status(session, bid)
    audit.record(
        session,
        actor,
        f"FIELD_{data.action}",
        "extracted_field",
        new.id,
        tender_id=tender.id,
        bid_id=bid.id,
        reason=data.reason,
        before={
            "field_key": field_key,
            "revision_id": str(prior.id) if prior else None,
            "status": prior.status.value if prior else None,
            "normalized_value": prior.normalized_value if prior else None,
        },
        after={
            "field_key": field_key,
            "revision_id": str(new.id),
            "status": new.status.value,
            "normalized_value": new.normalized_value,
            "evidence_page": new.page_no,
        },
    )
    return new


def reclassify_page(
    session: Session,
    container: Container,
    actor: Actor,
    audit: AuditService,
    bid_id: uuid.UUID,
    page_no: int,
    doc_class: str | None,
    reason: str,
) -> None:
    actor.require(Role.TECHNICAL_EVALUATOR)
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    _require_scrutiny(tender)
    _rv, content = pinned_content(session, tender)
    if doc_class is not None and doc_class not in {d.doc_class for d in content.document_requirements}:
        raise ValidationFailed("Unknown document class for this tender")
    page = session.scalar(
        select(ArtifactPage).where(
            ArtifactPage.artifact_id == bid.technical_artifact_id, ArtifactPage.page_no == page_no
        )
    )
    if page is None:
        raise NotFound("Page not found")
    if page.text_status is PageTextStatus.WITHHELD_COMMERCIAL:
        raise CommercialSealed("Withheld pages must be released before classification")

    before = {"doc_class": page.doc_class, "method": page.classification_method.value}
    page.doc_class = doc_class
    page.classification_method = ClassificationMethod.OFFICER
    page.classification_confidence = 1.0
    session.flush()
    audit.record(
        session,
        actor,
        "PAGE_RECLASSIFIED",
        "artifact_page",
        page.id,
        tender_id=tender.id,
        bid_id=bid.id,
        reason=reason,
        before=before,
        after={"doc_class": doc_class, "method": "OFFICER", "page": page_no},
    )
    processing.reextract(session, container, audit, actor, bid)


def release_withheld_page(
    session: Session,
    container: Container,
    actor: Actor,
    audit: AuditService,
    bid_id: uuid.UUID,
    page_no: int,
    reason: str,
) -> None:
    """Approver accepts the exposure risk and releases a page flagged as possible price content."""
    actor.require(Role.APPROVER)
    bid, tender = get_bid_for_officer(session, actor, bid_id)
    _require_scrutiny(tender)
    page = session.scalar(
        select(ArtifactPage).where(
            ArtifactPage.artifact_id == bid.technical_artifact_id, ArtifactPage.page_no == page_no
        )
    )
    if page is None:
        raise NotFound("Page not found")
    if page.text_status is not PageTextStatus.WITHHELD_COMMERCIAL:
        raise Conflict("Page is not withheld", code="NOT_WITHHELD")
    artifact = session.get(Artifact, bid.technical_artifact_id)
    assert artifact is not None
    parsed = parse_single_page(container.technical_store.get(artifact.storage_key), page_no)
    page.text_status = PageTextStatus.TEXT_LAYER if parsed.has_text_layer else PageTextStatus.NO_TEXT_LAYER
    page.text = parsed.text if parsed.has_text_layer else None
    page.lines = (
        [{"text": ln.text, "bbox": [round(v, 2) for v in ln.bbox]} for ln in parsed.lines]
        if parsed.has_text_layer
        else None
    )
    for t in session.scalars(
        select(ReviewTask).where(
            ReviewTask.bid_id == bid.id,
            ReviewTask.page_no == page_no,
            ReviewTask.status == ReviewTaskStatus.OPEN,
            ReviewTask.reason == ReviewReason.POSSIBLE_COMMERCIAL_LEAKAGE,
        )
    ).all():
        t.status, t.resolved_by, t.resolved_at = (
            ReviewTaskStatus.RESOLVED,
            actor.officer_id,
            container.clock.now(),
        )
        t.resolution = f"Released by approver: {reason}"
    session.flush()
    audit.record(
        session,
        actor,
        "WITHHELD_PAGE_RELEASED",
        "artifact_page",
        page.id,
        tender_id=tender.id,
        bid_id=bid.id,
        reason=reason,
        after={
            "page": page_no,
            "indicators": page.leakage_indicators,
            "exposure_risk_accepted_by": actor.label,
        },
    )
    processing.reextract(session, container, audit, actor, bid)
