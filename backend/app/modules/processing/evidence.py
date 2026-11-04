"""Builds rule-engine evidence from persisted pages and current extraction revisions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Artifact, ArtifactPage, Bid, ExtractedField
from app.modules.processing.extractor import PageView
from app.modules.processing.pdf import PdfLine
from app.modules.rulebooks.schemas import RulebookContent
from app.shared.enums import ClassificationMethod, FieldStatus, PageTextStatus, ReviewState
from rule_engine import (
    BidEvidence,
    DocumentEvidence,
    DocumentPresence,
    EvidenceStatus,
    FieldEvidence,
    canonical_hash,
)

_ESTABLISHING = {ClassificationMethod.KEYWORD, ClassificationMethod.OFFICER}


def bid_pages(session: Session, bid: Bid) -> list[ArtifactPage]:
    if bid.technical_artifact_id is None:
        return []
    return list(
        session.scalars(
            select(ArtifactPage)
            .where(ArtifactPage.artifact_id == bid.technical_artifact_id)
            .order_by(ArtifactPage.page_no)
        ).all()
    )


def bid_artifact(session: Session, bid: Bid) -> Artifact | None:
    return session.get(Artifact, bid.technical_artifact_id) if bid.technical_artifact_id else None


def current_fields(session: Session, bid_id: uuid.UUID) -> dict[str, ExtractedField]:
    rows = session.scalars(
        select(ExtractedField).where(ExtractedField.bid_id == bid_id, ExtractedField.is_current.is_(True))
    ).all()
    return {r.field_key: r for r in rows}


def page_views(pages: Sequence[ArtifactPage]) -> list[PageView]:
    views: list[PageView] = []
    for p in pages:
        if p.text_status is not PageTextStatus.TEXT_LAYER or not p.lines:
            continue
        lines = tuple(PdfLine(text=str(ln["text"]), bbox=tuple(ln["bbox"])) for ln in p.lines)
        views.append(PageView(page_no=p.page_no, lines=lines, doc_class=p.doc_class))
    return views


def has_uncertain_pages(pages: Sequence[ArtifactPage]) -> bool:
    return any(p.text_status is not PageTextStatus.TEXT_LAYER for p in pages)


def document_evidence(content: RulebookContent, pages: Sequence[ArtifactPage]) -> dict[str, DocumentEvidence]:
    uncertain = has_uncertain_pages(pages)
    out: dict[str, DocumentEvidence] = {}
    for req in content.document_requirements:
        establishing = [
            p.page_no
            for p in pages
            if p.doc_class == req.doc_class and p.classification_method in _ESTABLISHING
        ]
        all_pages = tuple(p.page_no for p in pages if p.doc_class == req.doc_class)
        if establishing:
            presence = DocumentPresence.FOUND
        elif uncertain:
            presence = DocumentPresence.UNCERTAIN
        else:
            presence = DocumentPresence.NOT_FOUND
        out[req.doc_class] = DocumentEvidence(doc_class=req.doc_class, presence=presence, pages=all_pages)
    return out


def field_evidence(row: ExtractedField) -> FieldEvidence:
    if row.status is FieldStatus.MISSING:
        status = EvidenceStatus.MISSING
    elif row.status is FieldStatus.UNREADABLE:
        status = EvidenceStatus.UNREADABLE
    elif row.status is FieldStatus.AMBIGUOUS:
        status = EvidenceStatus.AMBIGUOUS
    elif row.review_state is ReviewState.PENDING_REVIEW:
        status = EvidenceStatus.PENDING_REVIEW
    else:
        status = EvidenceStatus.AVAILABLE
    return FieldEvidence(
        field_key=row.field_key,
        status=status,
        value=row.normalized_value if status is EvidenceStatus.AVAILABLE else None,
        revision_id=str(row.id),
    )


def build_bid_evidence(session: Session, bid: Bid, content: RulebookContent) -> BidEvidence:
    pages = bid_pages(session, bid)
    fields = {k: field_evidence(v) for k, v in current_fields(session, bid.id).items()}
    return BidEvidence(fields=fields, documents=document_evidence(content, pages))


def bid_input_fingerprint(session: Session, bid: Bid) -> str:
    pages = bid_pages(session, bid)
    return canonical_hash(
        {
            "processing": bid.processing_status.value,
            "fields": sorted(str(r.id) for r in current_fields(session, bid.id).values()),
            "pages": [
                [p.page_no, p.doc_class, p.classification_method.value, p.text_status.value] for p in pages
            ],
        }
    )
