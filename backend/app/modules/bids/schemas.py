from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.enums import (
    ClassificationMethod,
    ExtractionMethod,
    FieldStatus,
    PageTextStatus,
    ProcessingStatus,
    ReviewState,
    TechnicalOutcome,
)


class FileReceipt(BaseModel):
    filename: str
    sha256: str
    size_bytes: int
    page_count: int | None = None


class BidReceipt(BaseModel):
    bid_reference: str
    tender_reference: str
    tender_title: str
    bidder_legal_name: str
    received_at: datetime
    technical: FileReceipt
    commercial: FileReceipt | None
    commercial_sealed: bool
    package_sha256: str
    notice: str


class BidSummaryOut(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    bid_reference: str
    bidder_legal_name: str
    submitted_at: datetime
    processing_status: ProcessingStatus
    processing_error: str | None
    technical_outcome: TechnicalOutcome
    page_count: int
    open_review_tasks: int
    withheld_pages: int
    unreadable_pages: int


class BidListOut(BaseModel):
    items: list[BidSummaryOut]
    total: int
    limit: int
    offset: int


class PageOut(BaseModel):
    page_no: int
    width: float
    height: float
    text_status: PageTextStatus
    doc_class: str | None
    classification_method: ClassificationMethod
    classification_confidence: float | None
    matched_keywords: list[str]
    leakage_indicators: list[str]


class FieldOut(BaseModel):
    id: uuid.UUID
    field_key: str
    label: str
    data_type: str
    revision_no: int
    status: FieldStatus
    raw_value: str | None
    source_line: str | None
    normalized_value: str | None
    unit: str | None
    confidence: float | None
    method: ExtractionMethod
    page_no: int | None
    bbox: list[float] | None
    flags: list[str]
    candidates: list[dict[str, object]]
    review_state: ReviewState
    provenance: str
    created_at: datetime
    created_by_label: str
    reason: str | None


class DocumentPresenceOut(BaseModel):
    doc_class: str
    name: str
    mandatory: bool
    presence: str
    pages: list[int]


class BidDetailOut(BaseModel):
    bid: BidSummaryOut
    bidder_email: str
    bidder_phone: str
    technical_sha256: str | None
    technical_filename: str | None
    pages: list[PageOut]
    documents: list[DocumentPresenceOut]
    fields: list[FieldOut]


class FieldRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["VERIFY", "CORRECT", "CONFIRM_MISSING", "MARK_UNREADABLE"]
    value: str | None = Field(default=None, max_length=500)
    page_no: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=5, max_length=2000)


class ReclassifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_class: str | None
    reason: str = Field(min_length=5, max_length=2000)


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=2000)
