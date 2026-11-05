"""Bid document pipeline: ingest pages -> withhold possible price pages -> classify -> extract -> review queue.

All outputs are proposals persisted as revisions; nothing here decides compliance.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import SYSTEM_ACTOR, Actor
from app.container import Container
from app.core.clock import Clock
from app.core.errors import DomainError
from app.db.models import ArtifactPage, Bid, ExtractedField, ReviewTask, Tender
from app.modules.processing.classifier import DocClassSpec, PageClassification, classify_page
from app.modules.processing.evidence import (
    bid_artifact,
    bid_pages,
    current_fields,
    has_uncertain_pages,
    page_views,
)
from app.modules.processing.extractor import EXTRACTOR_VERSION, FieldSpec, extract_field
from app.modules.processing.leakage import detect_price_content
from app.modules.processing.normalize import REVIEW_FLAGS
from app.modules.processing.pdf import ParsedPage, parse_pdf
from app.modules.rulebooks.schemas import FieldDefinition, RulebookContent
from app.modules.rulebooks.service import pinned_content
from app.shared.enums import (
    ActorKind,
    ClassificationMethod,
    ExtractionMethod,
    FieldStatus,
    PageTextStatus,
    ProcessingStatus,
    ReviewReason,
    ReviewState,
    ReviewTaskStatus,
)

log = logging.getLogger(__name__)


def doc_specs(content: RulebookContent) -> list[DocClassSpec]:
    return [DocClassSpec(d.doc_class, tuple(d.keywords)) for d in content.document_requirements]


def _open_task(
    session: Session,
    clock: Clock,
    bid: Bid,
    reason: ReviewReason,
    detail: str,
    *,
    field_key: str | None = None,
    page_no: int | None = None,
) -> None:
    session.add(
        ReviewTask(
            tender_id=bid.tender_id,
            bid_id=bid.id,
            reason=reason,
            field_key=field_key,
            page_no=page_no,
            detail=detail,
            created_at=clock.now(),
        )
    )


def close_field_tasks(
    session: Session,
    clock: Clock,
    bid_id: uuid.UUID,
    field_key: str,
    resolution: str,
    officer: uuid.UUID | None,
) -> None:
    tasks = session.scalars(
        select(ReviewTask).where(
            ReviewTask.bid_id == bid_id,
            ReviewTask.field_key == field_key,
            ReviewTask.status == ReviewTaskStatus.OPEN,
        )
    ).all()
    for t in tasks:
        t.status = ReviewTaskStatus.RESOLVED
        t.resolved_at = clock.now()
        t.resolved_by = officer
        t.resolution = resolution


def classify_pages(pages: Sequence[ArtifactPage], content: RulebookContent) -> None:
    """(Re)classify non-officer pages in order. Officer classifications are preserved."""
    specs = doc_specs(content)
    previous: PageClassification | None = None
    for page in pages:
        if page.classification_method is ClassificationMethod.OFFICER:
            previous = PageClassification(page.doc_class, ClassificationMethod.OFFICER, 1.0, ())
            continue
        if page.text_status is not PageTextStatus.TEXT_LAYER or page.text is None:
            page.doc_class, page.classification_method = None, ClassificationMethod.NONE
            page.classification_confidence, page.matched_keywords = None, []
            previous = None
            continue
        result = classify_page(page.text, specs, previous)
        page.doc_class = result.doc_class
        page.classification_method = result.method
        page.classification_confidence = result.confidence
        page.matched_keywords = list(result.matched_keywords)
        previous = result


def _page_row(artifact_id: uuid.UUID, parsed: ParsedPage) -> ArtifactPage:
    indicators = detect_price_content(parsed.text) if parsed.has_text_layer else []
    if indicators:
        status, text, lines = PageTextStatus.WITHHELD_COMMERCIAL, None, None
    elif parsed.has_text_layer:
        status = PageTextStatus.TEXT_LAYER
        text = parsed.text
        lines = [{"text": ln.text, "bbox": [round(v, 2) for v in ln.bbox]} for ln in parsed.lines]
    else:
        status, text, lines = PageTextStatus.NO_TEXT_LAYER, None, None
    return ArtifactPage(
        artifact_id=artifact_id,
        page_no=parsed.page_no,
        width=parsed.width,
        height=parsed.height,
        text_status=status,
        text=text,
        lines=lines,
        leakage_indicators=indicators,
    )


def run_extraction(
    session: Session, clock: Clock, bid: Bid, content: RulebookContent, threshold: float
) -> dict[str, int]:
    pages = bid_pages(session, bid)
    views = page_views(pages)
    uncertain = has_uncertain_pages(pages)
    existing = current_fields(session, bid.id)
    artifact_id = bid.technical_artifact_id
    stats = {"extracted": 0, "review": 0, "not_extracted": 0, "preserved_officer": 0}
    for fd in content.fields:
        prior = existing.get(fd.field_key)
        if prior is not None and prior.created_by_kind is ActorKind.OFFICER:
            stats["preserved_officer"] += 1  # never overwrite human review with automation
            continue
        spec = FieldSpec(fd.field_key, fd.data_type, fd.unit, tuple(fd.aliases), tuple(fd.doc_classes))
        res = extract_field(spec, views, unreadable_in_scope=uncertain)
        review_state, task = _review_policy(
            fd,
            res.status,
            res.chosen.confidence if res.chosen else None,
            res.flags + (res.chosen.flags if res.chosen else []),
            threshold,
        )
        if prior is not None:
            prior.is_current = False
            close_field_tasks(session, clock, bid.id, fd.field_key, "Superseded by re-extraction", None)
        chosen = res.chosen
        row = ExtractedField(
            bid_id=bid.id,
            field_key=fd.field_key,
            revision_no=(prior.revision_no + 1) if prior else 1,
            supersedes_id=prior.id if prior else None,
            is_current=True,
            status=res.status,
            raw_value=chosen.raw_value if chosen else None,
            source_line=chosen.source_line if chosen else None,
            normalized_value=chosen.normalized if chosen and res.status is FieldStatus.EXTRACTED else None,
            unit=chosen.unit if chosen else fd.unit,
            confidence=chosen.confidence if chosen else None,
            method=ExtractionMethod.PDF_TEXT,
            artifact_id=artifact_id if chosen else None,
            page_no=chosen.page_no if chosen else None,
            bbox=chosen.bbox if chosen else None,
            flags=sorted(set(res.flags + (chosen.flags if chosen else []))),
            candidates=[c.as_dict() for c in res.candidates],
            review_state=review_state,
            extractor_version=EXTRACTOR_VERSION,
            created_by_kind=ActorKind.SYSTEM,
            created_by=None,
            created_at=clock.now(),
        )
        session.add(row)
        if task is not None:
            reason, detail = task
            _open_task(
                session,
                clock,
                bid,
                reason,
                detail,
                field_key=fd.field_key,
                page_no=chosen.page_no if chosen else None,
            )
            stats["review"] += 1
        stats["extracted" if res.status is FieldStatus.EXTRACTED else "not_extracted"] += 1
    session.flush()
    return stats


def _review_policy(
    fd: FieldDefinition, status: FieldStatus, confidence: float | None, flags: list[str], threshold: float
) -> tuple[ReviewState, tuple[ReviewReason, str] | None]:
    if status is FieldStatus.AMBIGUOUS:
        if "CONFLICTING_VALUES" in flags:
            return ReviewState.PENDING_REVIEW, (
                ReviewReason.CONFLICTING_VALUES,
                f"Conflicting values found for '{fd.label}'",
            )
        return ReviewState.PENDING_REVIEW, (
            ReviewReason.VALUE_UNPARSEABLE,
            f"Label for '{fd.label}' found but value could not be interpreted",
        )
    if status is FieldStatus.EXTRACTED and fd.critical:
        review_flags = sorted(set(flags) & REVIEW_FLAGS)
        if (confidence is not None and confidence < threshold) or review_flags:
            why = ", ".join(review_flags) or f"confidence {confidence:.2f} below {threshold:.2f}"
            return ReviewState.PENDING_REVIEW, (ReviewReason.LOW_CONFIDENCE, f"'{fd.label}': {why}")
    return ReviewState.AUTO_PROPOSED, None


def _refresh_status(session: Session, bid: Bid) -> None:
    open_tasks = session.scalars(
        select(ReviewTask.id).where(ReviewTask.bid_id == bid.id, ReviewTask.status == ReviewTaskStatus.OPEN)
    ).first()
    bid.processing_status = ProcessingStatus.REVIEW_REQUIRED if open_tasks else ProcessingStatus.READY


def refresh_status(session: Session, bid: Bid) -> None:
    if bid.processing_status in (ProcessingStatus.READY, ProcessingStatus.REVIEW_REQUIRED):
        _refresh_status(session, bid)


def process_bid(container: Container, bid_id: uuid.UUID) -> None:
    """Background task entry point. Owns its own session and transaction."""
    audit = AuditService(clock=container.clock)
    with container.session_factory() as session:
        bid = session.get(Bid, bid_id)
        if bid is None or bid.processing_status not in (ProcessingStatus.RECEIVED, ProcessingStatus.FAILED):
            return
        bid.processing_status = ProcessingStatus.PROCESSING
        session.commit()
        try:
            stats = _process(session, container, audit, bid)
            session.commit()
            log.info("bid processed bid_id=%s pages=%s", bid.id, stats.get("pages"))
        except Exception as exc:  # noqa: BLE001 - record failure state, never leak details
            session.rollback()
            bid = session.get(Bid, bid_id)
            assert bid is not None
            bid.processing_status = ProcessingStatus.FAILED
            bid.processing_error = exc.code if isinstance(exc, DomainError) else "PROCESSING_ERROR"
            audit.record(
                session,
                SYSTEM_ACTOR,
                "BID_PROCESSING_FAILED",
                "bid",
                bid.id,
                tender_id=bid.tender_id,
                bid_id=bid.id,
                after={"error": bid.processing_error},
            )
            session.commit()
            log.exception("bid processing failed bid_id=%s", bid_id)


def _process(session: Session, container: Container, audit: AuditService, bid: Bid) -> dict[str, int]:
    tender = session.get(Tender, bid.tender_id)
    assert tender is not None
    _rv, content = pinned_content(session, tender)
    artifact = bid_artifact(session, bid)
    if artifact is None:
        raise DomainError("Bid has no technical artifact", code="NO_TECHNICAL_ARTIFACT")
    if not bid_pages(session, bid):
        data = container.technical_store.get(artifact.storage_key)
        for parsed in parse_pdf(data):
            session.add(_page_row(artifact.id, parsed))
        session.flush()
    pages = bid_pages(session, bid)
    classify_pages(pages, content)
    for p in pages:
        if p.text_status is PageTextStatus.NO_TEXT_LAYER:
            _open_task(
                session,
                container.clock,
                bid,
                ReviewReason.PAGE_UNREADABLE,
                f"Page {p.page_no} has no text layer (scanned/image). OCR is not configured in this MVP; "
                "an officer must read the page and enter any required values manually.",
                page_no=p.page_no,
            )
        elif p.text_status is PageTextStatus.WITHHELD_COMMERCIAL:
            _open_task(
                session,
                container.clock,
                bid,
                ReviewReason.POSSIBLE_COMMERCIAL_LEAKAGE,
                f"Page {p.page_no} appears to contain price information ({', '.join(p.leakage_indicators)}). "
                "Content is withheld from all officers. An approver may release it with a recorded reason; "
                "apply the tender's clause on price disclosure in the technical bid.",
                page_no=p.page_no,
            )
    session.flush()
    stats = run_extraction(
        session, container.clock, bid, content, container.settings.review_confidence_threshold
    )
    _refresh_status(session, bid)
    summary = {
        "pages": len(pages),
        "unreadable_pages": sum(p.text_status is PageTextStatus.NO_TEXT_LAYER for p in pages),
        "withheld_pages": sum(p.text_status is PageTextStatus.WITHHELD_COMMERCIAL for p in pages),
        **stats,
    }
    audit.record(
        session,
        SYSTEM_ACTOR,
        "BID_PROCESSED",
        "bid",
        bid.id,
        tender_id=bid.tender_id,
        bid_id=bid.id,
        after={**summary, "extractor_version": EXTRACTOR_VERSION},
    )
    return summary


def reextract(
    session: Session, container: Container, audit: AuditService, actor: Actor, bid: Bid
) -> dict[str, int]:
    tender = session.get(Tender, bid.tender_id)
    assert tender is not None
    _rv, content = pinned_content(session, tender)
    classify_pages(bid_pages(session, bid), content)
    stats = run_extraction(
        session, container.clock, bid, content, container.settings.review_confidence_threshold
    )
    _refresh_status(session, bid)
    audit.record(
        session, actor, "BID_REEXTRACTED", "bid", bid.id, tender_id=bid.tender_id, bid_id=bid.id, after=stats
    )
    return stats
