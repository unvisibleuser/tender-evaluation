"""Tender (authority) documents used as citation sources for rulebook criteria."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.container import Container
from app.core.errors import InvalidTransition, NotFound
from app.db.models import Artifact, Tender
from app.modules.bids.service import OFFICER_ROLES, _safe_filename
from app.modules.processing.pdf import inspect_pdf, render_page_png
from app.shared.enums import ArtifactOwner, Role, TenderStatus


class TenderArtifactOut(BaseModel):
    id: uuid.UUID
    title: str
    original_filename: str
    sha256: str
    size_bytes: int
    page_count: int
    uploaded_at: datetime


def upload(
    session: Session,
    container: Container,
    actor: Actor,
    audit: AuditService,
    tender: Tender,
    title: str,
    filename: str | None,
    data: bytes,
) -> Artifact:
    actor.require(Role.TENDER_ADMIN)
    if tender.status is TenderStatus.CANCELLED:
        raise InvalidTransition("Cannot add documents to a cancelled tender")
    pages = inspect_pdf(
        data, max_bytes=container.settings.max_upload_bytes, max_pages=container.settings.max_pdf_pages
    )
    art = Artifact(
        tender_id=tender.id,
        owner_type=ArtifactOwner.TENDER,
        bid_id=None,
        title=title.strip()[:300] or "Tender document",
        original_filename=_safe_filename(filename),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        page_count=pages,
        storage_key=container.technical_store.put(data),
        uploaded_at=container.clock.now(),
    )
    session.add(art)
    session.flush()
    audit.record(
        session,
        actor,
        "TENDER_DOCUMENT_UPLOADED",
        "artifact",
        art.id,
        tender_id=tender.id,
        after={"title": art.title, "sha256": art.sha256, "pages": pages},
    )
    return art


def to_out(a: Artifact) -> TenderArtifactOut:
    return TenderArtifactOut(
        id=a.id,
        title=a.title,
        original_filename=a.original_filename,
        sha256=a.sha256,
        size_bytes=a.size_bytes,
        page_count=a.page_count,
        uploaded_at=a.uploaded_at,
    )


def list_for(session: Session, actor: Actor, tender: Tender) -> list[Artifact]:
    actor.require(*OFFICER_ROLES)
    return list(
        session.scalars(
            select(Artifact)
            .where(Artifact.tender_id == tender.id, Artifact.owner_type == ArtifactOwner.TENDER)
            .order_by(Artifact.uploaded_at)
        ).all()
    )


def page_png(
    session: Session, container: Container, actor: Actor, artifact_id: uuid.UUID, page_no: int
) -> bytes:
    actor.require(*OFFICER_ROLES)
    art = session.get(Artifact, artifact_id)
    if art is None or art.owner_type is not ArtifactOwner.TENDER:
        raise NotFound("Tender document not found")
    return render_page_png(container.technical_store.get(art.storage_key), page_no)
