"""The walkthrough seed stage must reach a consistent, auditable state and be safe to re-run."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.container import Container
from app.scripts.seed_demo import seed

API = "/api/v1"


def test_technical_stage_seed(container: Container, client: TestClient, as_: object) -> None:
    container.settings.allow_demo_early_close = (
        True  # the demo seed closes submissions early (demo mode only)
    )
    seed(container, False, "technical")
    seed(container, False, "technical")  # idempotent: no duplicate bids, runs or decisions
    ev = as_("evaluator")  # type: ignore[operator]
    tender = client.get(f"{API}/tenders", headers=ev).json()[0]
    assert tender["status"] == "TECHNICAL_EVALUATION" and tender["bid_count"] == 3
    outcomes = {
        b["bidder_legal_name"].split(" ")[0]: b["technical_outcome"]
        for b in client.get(f"{API}/tenders/{tender['id']}/bids", headers=ev).json()["items"]
    }
    assert outcomes == {
        "Shakti": "RESPONSIVE",
        "Varun": "NON_RESPONSIVE",
        "Rudra": "PENDING_OFFICER_DECISION",
    }
    assert client.get(f"{API}/tenders/{tender['id']}/review-tasks", headers=ev).json()["total"] == 4
    assert len(client.get(f"{API}/tenders/{tender['id']}/evaluation-runs", headers=ev).json()) == 1
    assert client.get(f"{API}/audit/verify", headers=as_("auditor")).json()["ok"] is True  # type: ignore[operator]
