"""Local filesystem object store (MinIO/S3 adapter can implement the same protocol).

Technical and commercial objects live in separate namespaces (directories / buckets) so that the
technical code path is never handed a commercial store.
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import Protocol

_KEY_RE = re.compile(r"^[a-f0-9]{48}$")


class ObjectStore(Protocol):
    namespace: str

    def put(self, data: bytes) -> str: ...

    def get(self, key: str) -> bytes: ...


class LocalObjectStore:
    def __init__(self, root: Path, namespace: str) -> None:
        self.namespace = namespace
        self._root = (root / namespace).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not _KEY_RE.match(key):  # opaque keys only: no traversal, no original filenames
            raise ValueError("invalid object key")
        return self._root / key[:2] / key

    def put(self, data: bytes) -> str:
        key = secrets.token_hex(24)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o440)  # write-once intent; best effort on Windows
        except OSError:
            pass
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()
