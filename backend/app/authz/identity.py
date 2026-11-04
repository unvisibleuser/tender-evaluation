"""Officer identity and role-based authorization.

MVP: ``dev`` auth mode issues HMAC-signed bearer tokens for seeded demo officers (no password).
This is refused in production by ``Settings``; replace with OIDC (MFA) before any real use.
Bidders are intentionally unauthenticated in the MVP (public submission portal).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field

from app.core.errors import Forbidden, Unauthenticated
from app.shared.enums import ActorKind, Role


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: str | None
    label: str
    roles: frozenset[Role] = field(default_factory=frozenset)

    @property
    def officer_id(self) -> uuid.UUID:
        if self.kind is not ActorKind.OFFICER or self.id is None:
            raise Forbidden("Officer identity required")
        return uuid.UUID(self.id)

    def has(self, *roles: Role) -> bool:
        return bool(self.roles.intersection(roles))

    def require(self, *roles: Role) -> None:
        if not self.has(*roles):
            raise Forbidden(f"Requires one of roles: {', '.join(r.value for r in roles)}")


SYSTEM_ACTOR = Actor(kind=ActorKind.SYSTEM, id=None, label="system:document-pipeline")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(secret: str, user_id: uuid.UUID, now_ts: int, ttl: int) -> str:
    payload = _b64(json.dumps({"sub": str(user_id), "iat": now_ts, "exp": now_ts + ttl}).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def verify_token(secret: str, token: str, now_ts: int) -> uuid.UUID:
    try:
        payload, sig = token.split(".", 1)
    except ValueError as exc:
        raise Unauthenticated("Malformed token") from exc
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        raise Unauthenticated("Invalid token signature")
    try:
        claims = json.loads(_unb64(payload))
        sub = uuid.UUID(claims["sub"])
        exp = int(claims["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise Unauthenticated("Invalid token claims") from exc
    if now_ts >= exp:
        raise Unauthenticated("Token expired")
    return sub
