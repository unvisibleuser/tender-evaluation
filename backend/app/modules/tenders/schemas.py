from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import available_timezones

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.shared.enums import CommercialMethod, TenderStatus


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TenderCreate(_In):
    reference_no: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9/\-_. ]+$")
    title: str = Field(min_length=3, max_length=500)
    description: str = Field(default="", max_length=10000)
    authority: str = Field(min_length=2, max_length=300)
    submission_deadline: AwareDatetime
    timezone: str = "Asia/Kolkata"
    commercial_envelope_required: bool = True
    commercial_evaluation_method: CommercialMethod | None = None
    opening_quorum: int = Field(default=2, ge=1, le=5)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError("unknown IANA timezone")
        return v


class TenderUpdate(TenderCreate):
    row_version: int


class TransitionIn(_In):
    reason: str = Field(default="", max_length=2000)


class TenderOut(BaseModel):
    id: uuid.UUID
    reference_no: str
    title: str
    description: str
    authority: str
    status: TenderStatus
    timezone: str
    submission_deadline: datetime
    commercial_envelope_required: bool
    commercial_evaluation_method: CommercialMethod | None
    opening_quorum: int
    pinned_rulebook_version_id: uuid.UUID | None
    pinned_rulebook_version_no: int | None
    created_at: datetime
    closed_at: datetime | None
    row_version: int
    bid_count: int
    allowed_actions: list[str]


class RequiredDocumentOut(BaseModel):
    name: str
    mandatory: bool


class PublicTenderOut(BaseModel):
    id: uuid.UUID
    reference_no: str
    title: str
    description: str
    authority: str
    timezone: str
    submission_deadline: datetime
    accepting_submissions: bool
    commercial_envelope_required: bool
    required_documents: list[RequiredDocumentOut]
