#!/bin/sh
set -eu

if [ "${TENDER_SEED_DEMO:-true}" = "true" ]; then
    # Applies migrations, then seeds SYNTHETIC officers + demo tender if absent (idempotent).
    python -m app.scripts.seed_demo
else
    alembic upgrade head
fi

exec "$@"
