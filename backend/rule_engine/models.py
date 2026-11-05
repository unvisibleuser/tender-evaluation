"""Typed inputs/outputs for the deterministic rule engine.

This package is intentionally pure: no database, network, filesystem or LLM imports.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue

ENGINE_VERSION = "1.0.0"


class DataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    MONEY = "money"
    DATE = "date"
    BOOLEAN = "boolean"


class Operator(StrEnum):
    EQ = "EQ"
    NEQ = "NEQ"
    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    IN = "IN"
    NOT_IN = "NOT_IN"
    CONTAINS = "CONTAINS"
    DOCUMENT_PRESENT = "DOCUMENT_PRESENT"
    DATE_VALID_ON = "DATE_VALID_ON"  # field date (e.g. expiry) is on/after the basis date
    DATE_NOT_AFTER = "DATE_NOT_AFTER"  # field date (e.g. issue) is on/before the basis date
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


COMPARISON_OPERATORS = {
    Operator.EQ,
    Operator.NEQ,
    Operator.GT,
    Operator.GTE,
    Operator.LT,
    Operator.LTE,
    Operator.BETWEEN,
    Operator.IN,
    Operator.NOT_IN,
    Operator.CONTAINS,
}
ORDERED_OPERATORS = {Operator.GT, Operator.GTE, Operator.LT, Operator.LTE, Operator.BETWEEN}
DATE_BASIS_OPERATORS = {Operator.DATE_VALID_ON, Operator.DATE_NOT_AFTER}
FIELD_OPERATORS = COMPARISON_OPERATORS | DATE_BASIS_OPERATORS


class RuleOutcome(StrEnum):
    PASS = "PASS"  # noqa: S105 - outcome label, not a credential
    FAIL = "FAIL"
    MISSING = "MISSING"
    UNREADABLE = "UNREADABLE"
    AMBIGUOUS = "AMBIGUOUS"
    PENDING_REVIEW = "PENDING_REVIEW"
    PENDING_OFFICER_DECISION = "PENDING_OFFICER_DECISION"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EVALUATED = "NOT_EVALUATED"


class EvidenceStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    UNREADABLE = "UNREADABLE"
    AMBIGUOUS = "AMBIGUOUS"
    PENDING_REVIEW = "PENDING_REVIEW"


class DocumentPresence(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNCERTAIN = "UNCERTAIN"  # e.g. unreadable or withheld pages could contain it


class UnknownApplicability(StrEnum):
    """Officer-configured handling when an applicability condition's input is unavailable."""

    REVIEW = "REVIEW"
    APPLIES = "APPLIES"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FieldEvidence(_Frozen):
    field_key: str
    status: EvidenceStatus
    value: str | None = None  # canonical normalized value as string (Decimal / ISO date / text)
    revision_id: str | None = None


class DocumentEvidence(_Frozen):
    doc_class: str
    presence: DocumentPresence
    pages: tuple[int, ...] = ()


class Condition(_Frozen):
    field_key: str
    data_type: DataType
    operator: Operator
    value: JsonValue = None
    if_unknown: UnknownApplicability = UnknownApplicability.REVIEW


class RuleSpec(_Frozen):
    criterion_id: str
    name: str
    operator: Operator
    mandatory: bool
    field_key: str | None = None
    data_type: DataType | None = None
    doc_class: str | None = None
    expected: JsonValue = None
    basis_date: date | None = None
    applies_if: Condition | None = None


class BidEvidence(_Frozen):
    fields: dict[str, FieldEvidence] = Field(default_factory=dict)
    documents: dict[str, DocumentEvidence] = Field(default_factory=dict)


class CriterionEvaluation(_Frozen):
    criterion_id: str
    outcome: RuleOutcome
    mandatory: bool
    actual: str | None
    expected: str | None
    explanation: str
    revision_ids: tuple[str, ...] = ()
