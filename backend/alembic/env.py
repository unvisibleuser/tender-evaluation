from __future__ import annotations

from sqlalchemy import engine_from_config, pool

import app.db.models  # noqa: F401  (register core tables)
import app.modules.commercial.models  # noqa: F401  (register commercial tables)
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connectable = engine_from_config({"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
