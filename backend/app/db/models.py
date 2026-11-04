"""Core (technical-side) persistence models.

Commercial tables live in ``app.modules.commercial.models`` and must only be accessed by that module.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, enum_col
from app.db.types import UTCDateTime
from app.shared.enums import (
    ActorKind,
    ArtifactOwner,
    ClassificationMethod,
    CommercialMethod,
    ExtractionMethod,
    FieldStatus,
    PageTextStatus,
    ProcessingStatus,
    ReviewReason,
    ReviewState,
    ReviewTaskStatus,
    RulebookStatus,
    TechnicalDecision,
    TechnicalOutcome,
    TenderStatus,
)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=new_id)


class OfficerUser(Base):
    __tablename__ = "officer_user"
    id: Mapped[uuid.UUID] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    designation: Mapped[str] = mapped_column(String(200), default="")
    roles: Mapped[list[str]] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tender(Base):
    __tablename__ = "tender"
    id: Mapped[uuid.UUID] = _pk()
    reference_no: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    authority: Mapped[str] = mapped_column(String(300))
    status: Mapped[TenderStatus] = mapped_column(enum_col(TenderStatus), default=TenderStatus.DRAFT)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    submission_deadline: Mapped[datetime] = mapped_column(UTCDateTime)
    commercial_envelope_required: Mapped[bool] = mapped_column(Boolean, default=True)
    commercial_evaluation_method: Mapped[CommercialMethod | None] = mapped_column(
        enum_col(CommercialMethod), nullable=True
    )
    opening_quorum: Mapped[int] = mapped_column(Integer, default=2)
    pinned_rulebook_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rulebook_version.id", use_alter=True), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class Artifact(Base):
    """Immutable uploaded PDF (tender document or technical bid). Commercial files are NOT stored here."""

    __tablename__ = "artifact"
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    owner_type: Mapped[ArtifactOwner] = mapped_column(enum_col(ArtifactOwner))
    bid_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("bid.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    original_filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(200))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ArtifactPage(Base):
    __tablename__ = "artifact_page"
    __table_args__ = (UniqueConstraint("artifact_id", "page_no"),)
    id: Mapped[uuid.UUID] = _pk()
    artifact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifact.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer)
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    text_status: Mapped[PageTextStatus] = mapped_column(enum_col(PageTextStatus))
    # Withheld pages never have their text stored on the technical side.
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    lines: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    leakage_indicators: Mapped[list[str]] = mapped_column(JSON, default=list)
    doc_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        enum_col(ClassificationMethod), default=ClassificationMethod.NONE
    )
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)


class RulebookVersion(Base):
    __tablename__ = "rulebook_version"
    __table_args__ = (UniqueConstraint("tender_id", "version_no"),)
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[RulebookStatus] = mapped_column(enum_col(RulebookStatus), default=RulebookStatus.DRAFT)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    based_on_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_edited_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, default=1)


class Bid(Base):
    __tablename__ = "bid"
    __table_args__ = (UniqueConstraint("tender_id", "bidder_email"),)
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    bid_reference: Mapped[str] = mapped_column(String(32), unique=True)
    bidder_legal_name: Mapped[str] = mapped_column(String(300))
    bidder_email: Mapped[str] = mapped_column(String(320))
    bidder_phone: Mapped[str] = mapped_column(String(40))
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    technical_artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    package_sha256: Mapped[str] = mapped_column(String(64))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        enum_col(ProcessingStatus), default=ProcessingStatus.RECEIVED
    )
    processing_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    technical_outcome: Mapped[TechnicalOutcome] = mapped_column(
        enum_col(TechnicalOutcome), default=TechnicalOutcome.PENDING_OFFICER_DECISION
    )


class ExtractedField(Base):
    """Append-only extraction revisions. Exactly one revision per (bid, field_key) has is_current=True."""

    __tablename__ = "extracted_field"
    id: Mapped[uuid.UUID] = _pk()
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), index=True)
    field_key: Mapped[str] = mapped_column(String(64))
    revision_no: Mapped[int] = mapped_column(Integer)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[FieldStatus] = mapped_column(enum_col(FieldStatus))
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_line: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[ExtractionMethod] = mapped_column(enum_col(ExtractionMethod))
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bbox: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    review_state: Mapped[ReviewState] = mapped_column(enum_col(ReviewState))
    extractor_version: Mapped[str] = mapped_column(String(32))
    created_by_kind: Mapped[ActorKind] = mapped_column(enum_col(ActorKind))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ReviewTask(Base):
    __tablename__ = "review_task"
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), index=True)
    reason: Mapped[ReviewReason] = mapped_column(enum_col(ReviewReason))
    field_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text)
    status: Mapped[ReviewTaskStatus] = mapped_column(
        enum_col(ReviewTaskStatus), default=ReviewTaskStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    rulebook_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("rulebook_version.id"))
    rulebook_content_hash: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64))
    result_hash: Mapped[str] = mapped_column(String(64))
    bid_input_hashes: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    bid_count: Mapped[int] = mapped_column(Integer)
    started_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CriterionResult(Base):
    __tablename__ = "criterion_result"
    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("evaluation_run.id"), index=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), index=True)
    criterion_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(40))
    mandatory: Mapped[bool] = mapped_column(Boolean)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    revision_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class OfficerDecisionRecord(Base):
    __tablename__ = "officer_decision"
    id: Mapped[uuid.UUID] = _pk()
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), index=True)
    stage: Mapped[str] = mapped_column(String(20), default="TECHNICAL")
    decision: Mapped[TechnicalDecision] = mapped_column(enum_col(TechnicalDecision))
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("evaluation_run.id"))
    cited_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    overridden_criteria: Mapped[list[str]] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditEvent(Base):
    """Append-only, hash-chained. UPDATE/DELETE are blocked by database triggers."""

    __tablename__ = "audit_event"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, default=new_id)
    tender_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    bid_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    actor_kind: Mapped[ActorKind] = mapped_column(enum_col(ActorKind))
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(300))
    actor_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    action: Mapped[str] = mapped_column(String(80))
    object_type: Mapped[str] = mapped_column(String(60))
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditChainHead(Base):
    """Single-row lock target that serialises audit-chain appends."""

    __tablename__ = "audit_chain_head"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_hash: Mapped[str] = mapped_column(String(64))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    id: Mapped[uuid.UUID] = _pk()
    scope: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
