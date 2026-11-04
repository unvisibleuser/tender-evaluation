"""Opaque identifiers. Never expose sequential database IDs."""

from __future__ import annotations

import secrets
import uuid

_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


def new_id() -> uuid.UUID:
    gen = getattr(uuid, "uuid7", None)
    return gen() if gen is not None else uuid.uuid4()


def bid_reference() -> str:
    body = "".join(secrets.choice(_REF_ALPHABET) for _ in range(10))
    return f"BID-{body[:5]}-{body[5:]}"
