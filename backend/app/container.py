"""Explicit dependency container (no global mutable state). Stored on ``app.state.container``."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.db.session import make_engine, make_session_factory
from app.modules.commercial.vault import CommercialVault, load_or_create_kek
from app.storage.local import LocalObjectStore, ObjectStore

log = logging.getLogger(__name__)


class TaskRunner(Protocol):
    def submit(self, fn: Callable[..., Any], *args: Any) -> None: ...


class ThreadTaskRunner:
    """In-process background runner (MVP). Replace with Celery/RQ adapter for production."""

    def __init__(self, workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="doc-worker")

    def submit(self, fn: Callable[..., Any], *args: Any) -> None:
        def run() -> None:
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 - tasks record their own failure state
                log.exception("background task failed")

        self._pool.submit(run)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True)


class InlineTaskRunner:
    """Synchronous runner for tests and scripts."""

    def submit(self, fn: Callable[..., Any], *args: Any) -> None:
        fn(*args)


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[Session]
    clock: Clock
    technical_store: ObjectStore
    vault: CommercialVault
    tasks: TaskRunner


def build_container(
    settings: Settings, *, clock: Clock | None = None, tasks: TaskRunner | None = None
) -> Container:
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        from pathlib import Path

        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.database_url)
    kek = load_or_create_kek(
        settings.commercial_master_key,
        settings.storage_root.parent / "commercial.kek",
        allow_generate=settings.environment in ("demo", "test"),
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=make_session_factory(engine),
        clock=clock or SystemClock(),
        technical_store=LocalObjectStore(settings.storage_root, "technical"),
        vault=CommercialVault(kek, LocalObjectStore(settings.storage_root, "commercial")),
        tasks=tasks or ThreadTaskRunner(),
    )
