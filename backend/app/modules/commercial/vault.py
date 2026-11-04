"""Envelope encryption for sealed commercial bids.

Each envelope gets a random 256-bit data key (DEK). The price PDF and the declared total are encrypted
with AES-256-GCM under the DEK; the DEK is wrapped by the key-encryption key (KEK). The KEK is only
held by this module. ``open_envelope`` requires a persisted opening event, so no code path can
decrypt before the authorised opening.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import CommercialSealed
from app.storage.local import ObjectStore

_NONCE = 12


def load_or_create_kek(configured: str, key_file: Path, allow_generate: bool) -> bytes:
    if configured:
        key = base64.b64decode(configured)
    elif key_file.exists():
        key = base64.b64decode(key_file.read_text().strip())
    elif allow_generate:
        key = AESGCM.generate_key(bit_length=256)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(base64.b64encode(key).decode())
    else:
        raise RuntimeError("commercial KEK not configured")
    if len(key) != 32:
        raise RuntimeError("commercial KEK must be 32 bytes")
    return key


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def _unseal(key: bytes, blob: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:_NONCE], blob[_NONCE:], aad)


@dataclass(frozen=True)
class SealedEnvelope:
    storage_key: str
    ciphertext_sha256: str
    plaintext_sha256: str
    size_bytes: int
    wrapped_key: bytes
    sealed_amount: bytes


@dataclass(frozen=True)
class OpenedEnvelope:
    document: bytes
    quoted_total: Decimal


class CommercialVault:
    def __init__(self, kek: bytes, store: ObjectStore) -> None:
        if store.namespace != "commercial":
            raise ValueError("CommercialVault requires the commercial object store")
        self._kek = kek
        self._store = store

    def seal(self, envelope_id: uuid.UUID, document: bytes, quoted_total: Decimal) -> SealedEnvelope:
        dek = AESGCM.generate_key(bit_length=256)
        aad = envelope_id.bytes
        ciphertext = _seal(dek, document, aad + b"doc")
        key = self._store.put(ciphertext)
        return SealedEnvelope(
            storage_key=key,
            ciphertext_sha256=hashlib.sha256(ciphertext).hexdigest(),
            plaintext_sha256=hashlib.sha256(document).hexdigest(),
            size_bytes=len(document),
            wrapped_key=_seal(self._kek, dek, aad + b"dek"),
            sealed_amount=_seal(dek, format(quoted_total, "f").encode(), aad + b"amount"),
        )

    def open(
        self,
        envelope_id: uuid.UUID,
        storage_key: str,
        wrapped_key: bytes,
        sealed_amount: bytes,
        expected_plaintext_sha256: str,
        *,
        opening_event_id: uuid.UUID | None,
    ) -> OpenedEnvelope:
        if opening_event_id is None:
            raise CommercialSealed("Commercial envelope cannot be decrypted before an opening event")
        aad = envelope_id.bytes
        dek = _unseal(self._kek, wrapped_key, aad + b"dek")
        document = _unseal(dek, self._store.get(storage_key), aad + b"doc")
        if hashlib.sha256(document).hexdigest() != expected_plaintext_sha256:
            raise RuntimeError("commercial envelope integrity check failed")
        amount = Decimal(_unseal(dek, sealed_amount, aad + b"amount").decode())
        return OpenedEnvelope(document=document, quoted_total=amount)
