"""FastAPI dependencies: container, DB session, officer identity, audit service."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor, verify_token
from app.container import Container
from app.core.errors import Unauthenticated
from app.db.models import OfficerUser
from app.shared.enums import ActorKind, Role


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_session(container: ContainerDep) -> Iterator[Session]:
    """Session per request. Handlers commit explicitly; anything uncommitted is rolled back."""
    session = container.session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_audit(request: Request, container: ContainerDep) -> AuditService:
    return AuditService(clock=container.clock, correlation_id=getattr(request.state, "correlation_id", None))


AuditDep = Annotated[AuditService, Depends(get_audit)]


def get_officer(request: Request, container: ContainerDep, session: SessionDep) -> Actor:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthenticated("Officer sign-in required")
    now_ts = int(container.clock.now().timestamp())
    user_id = verify_token(container.settings.token_secret, header[7:].strip(), now_ts)
    user = session.get(OfficerUser, user_id)
    if user is None or not user.active:
        raise Unauthenticated("Unknown or inactive officer")
    return Actor(
        kind=ActorKind.OFFICER,
        id=str(user.id),
        label=f"{user.display_name} ({user.username})",
        roles=frozenset(Role(r) for r in user.roles),
    )


OfficerDep = Annotated[Actor, Depends(get_officer)]


def bidder_actor(bid_id: uuid.UUID, legal_name: str) -> Actor:
    return Actor(kind=ActorKind.BIDDER, id=str(bid_id), label=f"bidder:{legal_name}")
