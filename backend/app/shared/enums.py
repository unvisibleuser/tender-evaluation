"""Canonical application enums. Rule-level enums live in ``rule_engine.models``."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    TENDER_ADMIN = "TENDER_ADMIN"
    APPROVER = "APPROVER"
    TECHNICAL_EVALUATOR = "TECHNICAL_EVALUATOR"
    COMMERCIAL_OFFICER = "COMMERCIAL_OFFICER"
    AUDITOR = "AUDITOR"


class TenderStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN_FOR_SUBMISSION = "OPEN_FOR_SUBMISSION"
    SUBMISSION_CLOSED = "SUBMISSION_CLOSED"
    TECHNICAL_EVALUATION = "TECHNICAL_EVALUATION"
    TECHNICAL_COMPLETED = "TECHNICAL_COMPLETED"
    COMMERCIAL_OPENED = "COMMERCIAL_OPENED"
    COMMERCIAL_EVALUATED = "COMMERCIAL_EVALUATED"
    CANCELLED = "CANCELLED"


# Statuses in which the technical bid contents may be viewed by officers.
TECHNICAL_UNSEALED_STATUSES = frozenset(
    {
        TenderStatus.SUBMISSION_CLOSED,
        TenderStatus.TECHNICAL_EVALUATION,
        TenderStatus.TECHNICAL_COMPLETED,
        TenderStatus.COMMERCIAL_OPENED,
        TenderStatus.COMMERCIAL_EVALUATED,
    }
)


class CommercialMethod(StrEnum):
    LOWEST_QUOTED_TOTAL = "LOWEST_QUOTED_TOTAL"


class RulebookStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ArtifactOwner(StrEnum):
    TENDER = "TENDER"
    BID = "BID"


class ProcessingStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    READY = "READY"
    FAILED = "FAILED"


class TechnicalOutcome(StrEnum):
    PENDING_OFFICER_DECISION = "PENDING_OFFICER_DECISION"
    RESPONSIVE = "RESPONSIVE"
    NON_RESPONSIVE = "NON_RESPONSIVE"


class PageTextStatus(StrEnum):
    TEXT_LAYER = "TEXT_LAYER"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"  # scanned/image-only page; OCR or manual transcription required
    WITHHELD_COMMERCIAL = "WITHHELD_COMMERCIAL"  # possible price content; masked until released/opened


class ClassificationMethod(StrEnum):
    KEYWORD = "KEYWORD"
    CONTINUATION = "CONTINUATION"
    OFFICER = "OFFICER"
    NONE = "NONE"


class FieldStatus(StrEnum):
    EXTRACTED = "EXTRACTED"
    MISSING = "MISSING"
    AMBIGUOUS = "AMBIGUOUS"
    UNREADABLE = "UNREADABLE"


class ReviewState(StrEnum):
    AUTO_PROPOSED = "AUTO_PROPOSED"
    PENDING_REVIEW = "PENDING_REVIEW"
    OFFICER_VERIFIED = "OFFICER_VERIFIED"
    OFFICER_CORRECTED = "OFFICER_CORRECTED"


class ExtractionMethod(StrEnum):
    PDF_TEXT = "PDF_TEXT"
    OCR = "OCR"
    HUMAN = "HUMAN"


class ReviewReason(StrEnum):
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONFLICTING_VALUES = "CONFLICTING_VALUES"
    VALUE_UNPARSEABLE = "VALUE_UNPARSEABLE"
    PAGE_UNREADABLE = "PAGE_UNREADABLE"
    POSSIBLE_COMMERCIAL_LEAKAGE = "POSSIBLE_COMMERCIAL_LEAKAGE"


class ReviewTaskStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class TechnicalDecision(StrEnum):
    RESPONSIVE = "RESPONSIVE"
    NON_RESPONSIVE = "NON_RESPONSIVE"


class ActorKind(StrEnum):
    OFFICER = "OFFICER"
    BIDDER = "BIDDER"
    SYSTEM = "SYSTEM"
