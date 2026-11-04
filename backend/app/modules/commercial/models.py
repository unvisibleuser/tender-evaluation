"""Commercial (sealed) persistence models.

ACCESS RULE: only ``app.modules.commercial`` may import this module. Plaintext prices exist only in
``CommercialOffer`` and only after an authorised ``CommercialOpeningEvent``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, enum_col
from app.db.types import DecimalText, UTCDateTime
from app.shared.enums import CommercialMethod


class CommercialEnvelope(Base):
    __tablename__ = "commercial_envelope"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), unique=True)
    storage_key: Mapped[str] = mapped_column(String(200))
    ciphertext_sha256: Mapped[str] = mapped_column(String(64))
    plaintext_sha256: Mapped[str] = mapped_column(String(64))  # committed at submission, shown on receipt
    size_bytes: Mapped[int] = mapped_column(Integer)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    sealed_amount: Mapped[bytes] = mapped_column(LargeBinary)  # AES-GCM(quoted total) under envelope key
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CommercialOpeningAuthorization(Base):
    __tablename__ = "commercial_opening_authorization"
    __table_args__ = (UniqueConstraint("tender_id", "officer_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    officer_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CommercialOpeningEvent(Base):
    __tablename__ = "commercial_opening_event"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), unique=True)
    executed_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    executed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    authorizer_ids: Mapped[list[str]] = mapped_column(JSON)
    eligible_bid_ids: Mapped[list[str]] = mapped_column(JSON)
    sealed_bid_ids: Mapped[list[str]] = mapped_column(JSON)  # envelopes intentionally left unopened
    verified_hashes: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)


class CommercialOffer(Base):
    __tablename__ = "commercial_offer"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    bid_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("bid.id"), unique=True)
    opening_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("commercial_opening_event.id"))
    quoted_total: Mapped[Decimal] = mapped_column(DecimalText)
    currency: Mapped[str] = mapped_column(String(3))
    source: Mapped[str] = mapped_column(String(40), default="BIDDER_DECLARED_TOTAL")


class RankingSnapshot(Base):
    __tablename__ = "commercial_ranking_snapshot"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tender_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tender.id"), index=True)
    method: Mapped[CommercialMethod] = mapped_column(enum_col(CommercialMethod))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("officer_user.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    result: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
