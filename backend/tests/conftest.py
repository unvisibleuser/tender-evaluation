from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.modules.commercial.models  # noqa: F401
from app.container import Container, InlineTaskRunner, build_container
from app.core.clock import FixedClock
from app.core.config import Settings
from app.db.base import Base
from app.db.session import APPEND_ONLY_TABLES, append_only_trigger_sql
from app.main import create_app
from app.scripts.seed_demo import ensure_officers

T0 = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        storage_root=tmp_path / "storage",
        token_secret="test-secret-for-unit-tests-only",
        allow_demo_early_close=False,
    )


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def container(settings: Settings, clock: FixedClock) -> Iterator[Container]:
    c = build_container(settings, clock=clock, tasks=InlineTaskRunner())
    Base.metadata.create_all(c.engine)
    with c.engine.begin() as conn:
        for table in APPEND_ONLY_TABLES:
            for stmt in append_only_trigger_sql(c.engine.dialect.name, table):
                conn.execute(text(stmt))
    with c.session_factory() as s:
        ensure_officers(s)
        s.commit()
    yield c
    c.engine.dispose()


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    app = create_app(container.settings, container)
    with TestClient(app) as tc:
        yield tc


class Officers:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        self._cache: dict[str, dict[str, str]] = {}

    def __call__(self, username: str) -> dict[str, str]:
        if username not in self._cache:
            r = self._client.post("/api/v1/auth/dev-login", json={"username": username})
            assert r.status_code == 200, r.text
            self._cache[username] = {"Authorization": f"Bearer {r.json()['token']}"}
        return self._cache[username]

    def reset(self) -> None:
        """Forget cached tokens (e.g. after advancing the clock beyond token TTL)."""
        self._cache.clear()


@pytest.fixture
def as_(client: TestClient) -> Officers:
    return Officers(client)
