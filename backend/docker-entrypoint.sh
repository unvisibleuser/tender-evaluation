#!/bin/sh
set -eu

if [ "${TENDER_SEED_DEMO:-true}" = "true" ]; then
    # Applies migrations, then seeds SYNTHETIC officers + demo tender (idempotent).
    # TENDER_SEED_STAGE=open keeps the tender open for live bidder submission; technical = walkthrough state.
    python -m app.scripts.seed_demo --stage "${TENDER_SEED_STAGE:-technical}"
else
    alembic upgrade head
fi

exec "$@"
