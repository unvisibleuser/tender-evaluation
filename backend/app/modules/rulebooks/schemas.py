"""Rulebook content schema (canonical; ``schemas/rulebook.schema.json`` is generated from this)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.shared.enums import RulebookStatus
from rule_engine import Condition as EngineCondition
from rule_engine import DataType, Operator, UnknownApplicability

_KEY = r"^[a-z][a-z0-9_]{1,63}$"
_CRIT = r"^[A-Z0-9][A-Z0-9_\-]{1,63}$"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionCategory(StrEnum):
    ELIGIBILITY = "eligibility"
    ADMINISTRATIVE = "administrative"
    TECHNICAL = "technical"
    EXPERIENCE = "experience"
    FINANCIAL_CAPACITY = "financial_capacity"
    DECLARATION = "declaration"
    SUPPORTING_DOCUMENT = "supporting_document"


class Interpretation(StrEnum):
    EXPLICIT = "explicit"
    NORMALIZED = "normalized"
    OFFICER_DEFINED = "officer_defined"
    UNRESOLVED = "unresolved"  # NEEDS_OFFICER_INPUT — blocks approval


class DateBasis(StrEnum):
    SUBMISSION_DEADLINE = "SUBMISSION_DEADLINE"
    BID_SUBMITTED_AT = "BID_SUBMITTED_AT"
    FIXED_DATE = "FIXED_DATE"


class FailureConsequence(StrEnum):
    OFFICER_DECISION = "OFFICER_DECISION"
    TENDER_STATED_REJECTION = "TENDER_STATED_REJECTION"  # requires quoted source clause


class SourceReference(Strict):
    artifact_id: uuid.UUID | None = None
    document_title: str = Field(min_length=1, max_length=300)
    page: int = Field(ge=1)
    clause: str | None = Field(default=None, max_length=200)
    quote: str | None = Field(default=None, max_length=2000)


class FieldDefinition(Strict):
    field_key: str = Field(pattern=_KEY)
    label: str = Field(min_length=1, max_length=200)
    data_type: DataType
    unit: str | None = Field(default=None, max_length=20)
    aliases: list[str] = Field(min_length=1, max_length=30)
    doc_classes: list[str] = Field(default_factory=list)
    critical: bool = True

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, v: list[str]) -> list[str]:
        cleaned = [a.strip() for a in v if a.strip()]
        if not cleaned or any(len(a) > 100 for a in cleaned):
            raise ValueError("aliases must be non-empty and at most 100 characters each")
        return cleaned


class DocumentRequirement(Strict):
    doc_class: str = Field(pattern=_KEY)
    name: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(min_length=1, max_length=30)
    mandatory: bool = True


class ApplicabilityCondition(Strict):
    field_key: str = Field(pattern=_KEY)
    operator: Operator
    value: JsonValue = None
    if_unknown: UnknownApplicability = UnknownApplicability.REVIEW


class Criterion(Strict):
    criterion_id: str = Field(pattern=_CRIT)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=4000)
    category: CriterionCategory
    stage: Literal["technical"] = "technical"
    mandatory: bool = True
    operator: Operator
    field_key: str | None = Field(default=None, pattern=_KEY)
    doc_class: str | None = Field(default=None, pattern=_KEY)
    expected: JsonValue = None
    evaluation_date_basis: DateBasis | None = None
    basis_fixed_date: date | None = None
    applies_if: ApplicabilityCondition | None = None
    interpretation: Interpretation = Interpretation.EXPLICIT
    failure_consequence: FailureConsequence = FailureConsequence.OFFICER_DECISION
    source_references: list[SourceReference] = Field(default_factory=list)
    scoring: None = Field(
        default=None,
        description="Scoring is not supported in the MVP; must be null (REQUIRES_OFFICER_CONFIGURATION).",
    )


class RulebookContent(Strict):
    schema_version: Literal["1.0"] = "1.0"
    fields: list[FieldDefinition] = Field(default_factory=list)
    document_requirements: list[DocumentRequirement] = Field(default_factory=list)
    criteria: list[Criterion] = Field(default_factory=list)

    def field_map(self) -> dict[str, FieldDefinition]:
        return {f.field_key: f for f in self.fields}

    def to_engine_condition(self, c: ApplicabilityCondition) -> EngineCondition:
        fd = self.field_map()[c.field_key]
        return EngineCondition(
            field_key=c.field_key,
            data_type=fd.data_type,
            operator=c.operator,
            value=c.value,
            if_unknown=c.if_unknown,
        )


class ValidationIssue(BaseModel):
    code: str
    severity: Literal["BLOCKING", "WARNING"]
    path: str
    message: str


class RulebookVersionOut(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    version_no: int
    status: RulebookStatus
    content: RulebookContent
    content_hash: str
    based_on_id: uuid.UUID | None
    created_by: uuid.UUID
    created_at: datetime
    submitted_at: datetime | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    approval_reason: str | None
    row_version: int
    is_pinned: bool
    issues: list[ValidationIssue]


class CreateVersionIn(Strict):
    based_on_id: uuid.UUID | None = None


class UpdateContentIn(Strict):
    content: RulebookContent
    row_version: int


class ReasonIn(Strict):
    reason: str = Field(min_length=3, max_length=2000)


class PinIn(Strict):
    version_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=2000)
