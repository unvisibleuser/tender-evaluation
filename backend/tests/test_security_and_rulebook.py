from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.clock import FixedClock
from app.core.errors import CommercialSealed
from app.db.models import RulebookVersion
from app.demo import synthetic
from app.modules.commercial.vault import CommercialVault
from app.modules.rulebooks.schemas import RulebookContent
from app.modules.rulebooks.validation import validate_rulebook
from app.scripts.seed_demo import seed
from app.storage.local import LocalObjectStore
from tests.test_workflow import API, submit


@pytest.fixture
def tid(container: Container, client: TestClient) -> str:
    seed(container, with_bids=False)
    return str(client.get(f"{API}/public/tenders").json()[0]["id"])


# ------------------------------------------------------------------ authentication / authorization


def test_officer_endpoints_require_auth(client: TestClient, tid: str) -> None:
    for path in (
        f"/tenders/{tid}",
        f"/tenders/{tid}/bids",
        f"/tenders/{tid}/commercial/offers",
        f"/tenders/{tid}/audit-events",
    ):
        r = client.get(API + path)
        assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"


def test_tampered_token_rejected(client: TestClient, tid: str, as_: Any) -> None:
    token = as_("admin")["Authorization"]
    bad = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert client.get(f"{API}/tenders", headers={"Authorization": bad}).status_code == 401


def test_role_separation(client: TestClient, tid: str, as_: Any) -> None:
    body = {
        "reference_no": "X-1",
        "title": "Another tender",
        "authority": "Demo",
        "submission_deadline": "2027-01-01T10:00:00+05:30",
    }
    assert client.post(f"{API}/tenders", json=body, headers=as_("evaluator")).status_code == 403
    assert client.post(f"{API}/tenders", json=body, headers=as_("admin")).status_code == 201
    for officer in ("admin", "evaluator", "approver"):
        r = client.get(f"{API}/tenders/{tid}/commercial/status", headers=as_(officer))
        assert r.status_code == 403, officer
    assert client.get(f"{API}/audit/verify", headers=as_("evaluator")).status_code == 403


def test_unknown_ids_are_not_found(client: TestClient, as_: Any) -> None:
    assert client.get(f"{API}/bids/{uuid.uuid4()}", headers=as_("evaluator")).status_code == 404
    assert client.get(f"{API}/tenders/not-a-uuid", headers=as_("admin")).status_code == 422


# ------------------------------------------------------------------ bidder portal input validation


def _encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    doc.close()
    return bytes(data)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"MZ\x90\x00 not a pdf", "NOT_PDF"),
        (b"%PDF-1.7 garbage that is not really a pdf", "CORRUPT_PDF"),
        (b"", "EMPTY_FILE"),
    ],
)
def test_hostile_files_rejected(client: TestClient, tid: str, payload: bytes, code: str) -> None:
    b = synthetic.bidder_a()
    r = client.post(
        f"{API}/public/tenders/{tid}/bids",
        data={
            "bidder_legal_name": b.legal_name,
            "bidder_email": b.email,
            "bidder_phone": b.phone,
            "declaration_accepted": "true",
            "quoted_total_amount": b.quoted_total,
        },
        files={
            "technical_pdf": ("x.pdf", payload, "application/pdf"),
            "commercial_pdf": ("p.pdf", b.commercial_pdf, "application/pdf"),
        },
    )
    assert r.status_code == 422 and r.json()["code"] == code


def test_encrypted_pdf_rejected(client: TestClient, tid: str) -> None:
    b = synthetic.bidder_a()
    r = client.post(
        f"{API}/public/tenders/{tid}/bids",
        data={
            "bidder_legal_name": b.legal_name,
            "bidder_email": b.email,
            "bidder_phone": b.phone,
            "declaration_accepted": "true",
            "quoted_total_amount": b.quoted_total,
        },
        files={
            "technical_pdf": ("x.pdf", _encrypted_pdf(), "application/pdf"),
            "commercial_pdf": ("p.pdf", b.commercial_pdf, "application/pdf"),
        },
    )
    assert r.json()["code"] == "ENCRYPTED_PDF"


@pytest.mark.parametrize("amount", ["", "-5", "abc", "1.234", "0", "1e20"])
def test_invalid_amounts(client: TestClient, tid: str, amount: str) -> None:
    b = synthetic.bidder_a()
    b = synthetic.SyntheticBid(
        b.key, b.legal_name, b.email, b.phone, b.technical_pdf, b.commercial_pdf, amount
    )
    r = submit(client, tid, b)
    assert r.status_code == 422 and r.json()["code"] in {"AMOUNT_REQUIRED", "AMOUNT_INVALID"}


def test_declaration_required(client: TestClient, tid: str) -> None:
    b = synthetic.bidder_a()
    r = client.post(
        f"{API}/public/tenders/{tid}/bids",
        data={
            "bidder_legal_name": b.legal_name,
            "bidder_email": b.email,
            "bidder_phone": b.phone,
            "declaration_accepted": "false",
            "quoted_total_amount": b.quoted_total,
        },
        files={
            "technical_pdf": ("t.pdf", b.technical_pdf, "application/pdf"),
            "commercial_pdf": ("p.pdf", b.commercial_pdf, "application/pdf"),
        },
    )
    assert r.json()["code"] == "DECLARATION_REQUIRED"


def test_no_submission_after_deadline_even_if_not_closed(
    client: TestClient, tid: str, clock: FixedClock
) -> None:
    clock.advance(timedelta(days=7, seconds=1))
    assert submit(client, tid, synthetic.bidder_a()).json()["code"] == "SUBMISSION_CLOSED"


def test_public_endpoints_never_expose_bids_or_prices(client: TestClient, tid: str) -> None:
    b = synthetic.bidder_a()
    submit(client, tid, b)
    text = client.get(f"{API}/public/tenders/{tid}").text + client.get(f"{API}/public/tenders").text
    assert b.legal_name not in text and b.quoted_total not in text


# ------------------------------------------------------------------ commercial confidentiality


def test_no_price_in_any_technical_response(
    client: TestClient, container: Container, clock: FixedClock, tid: str, as_: Any
) -> None:
    sample = synthetic.all_bids()
    for b in sample:
        submit(client, tid, b)
    clock.advance(timedelta(days=8))
    as_.reset()
    client.post(f"{API}/tenders/{tid}/actions/close", json={"reason": "Deadline"}, headers=as_("admin"))
    client.post(f"{API}/tenders/{tid}/actions/start-technical", json={"reason": "x"}, headers=as_("admin"))
    run = client.post(f"{API}/tenders/{tid}/evaluation-runs", headers=as_("evaluator")).json()
    bodies = [
        str(run),
        client.get(f"{API}/tenders/{tid}/bids", headers=as_("evaluator")).text,
        client.get(f"{API}/tenders/{tid}/review-tasks", headers=as_("evaluator")).text,
        client.get(f"{API}/tenders/{tid}/audit-events", headers=as_("auditor")).text,
    ]
    for item in client.get(f"{API}/tenders/{tid}/bids", headers=as_("evaluator")).json()["items"]:
        bodies.append(client.get(f"{API}/bids/{item['id']}", headers=as_("evaluator")).text)
    blob = "\n".join(bodies)
    for b in sample:
        whole = b.quoted_total.split(".")[0]
        assert whole not in blob and f"{int(whole):,}" not in blob
    assert "4,62,50,000" not in blob and "1,850" not in blob  # leaked prices on bidder B's technical page


def test_vault_refuses_without_opening_event(container: Container, tmp_path: Any) -> None:
    vault = CommercialVault(b"k" * 32, LocalObjectStore(tmp_path, "commercial"))
    eid = uuid.uuid4()
    sealed = vault.seal(eid, b"%PDF-1.4 price", __import__("decimal").Decimal("100.00"))
    with pytest.raises(CommercialSealed):
        vault.open(
            eid,
            sealed.storage_key,
            sealed.wrapped_key,
            sealed.sealed_amount,
            sealed.plaintext_sha256,
            opening_event_id=None,
        )
    raw = (tmp_path / "commercial" / sealed.storage_key[:2] / sealed.storage_key).read_bytes()
    assert b"price" not in raw and b"100.00" not in sealed.sealed_amount  # ciphertext at rest
    with pytest.raises(ValueError):
        CommercialVault(b"k" * 32, LocalObjectStore(tmp_path, "technical"))  # wrong namespace


def test_commercial_module_isolation() -> None:
    """Only the commercial module (and migrations) may import commercial models."""
    import pathlib
    import re

    root = pathlib.Path(__file__).parents[1] / "app"
    pattern = re.compile(r"^\s*(from|import)\s+app\.modules\.commercial\.(models|vault)", re.MULTILINE)
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("modules/commercial/") or rel in {"container.py"}:
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert offenders == []


# ------------------------------------------------------------------ rulebook governance


def _content() -> dict[str, Any]:
    return synthetic.demo_rulebook(None)


def test_demo_rulebook_valid() -> None:
    issues = validate_rulebook(RulebookContent.model_validate(_content()))
    assert [i for i in issues if i.severity == "BLOCKING"] == []


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda c: c["criteria"][0].update(source_references=[]), "MISSING_SOURCE_REFERENCE"),
        (lambda c: c["criteria"][3].update(expected=None), "MISSING_THRESHOLD"),
        (lambda c: c["criteria"][3].update(field_key="nope"), "UNKNOWN_FIELD"),
        (lambda c: c["criteria"][4].update(evaluation_date_basis=None), "MISSING_DATE_BASIS"),
        (lambda c: c["criteria"][3].update(interpretation="unresolved"), "NEEDS_OFFICER_INPUT"),
        (
            lambda c: c["criteria"][3].update(
                failure_consequence="TENDER_STATED_REJECTION",
                source_references=[{"document_title": "x", "page": 1}],
            ),
            "REJECTION_NOT_QUOTED",
        ),
        (lambda c: c["criteria"][3].update(expected=5.5), "INVALID_EXPECTED"),
        (lambda c: c["criteria"].append(copy.deepcopy(c["criteria"][0])), "DUPLICATE_CRITERION"),
        (lambda c: c["criteria"][8].update(operator="GT"), "TYPE_MISMATCH"),
    ],
)
def test_validation_blocks(mutate: Any, code: str) -> None:
    c = _content()
    mutate(c)
    issues = validate_rulebook(RulebookContent.model_validate(c))
    assert code in {i.code for i in issues if i.severity == "BLOCKING"}


def test_invented_scoring_rejected_by_schema() -> None:
    c = _content()
    c["criteria"][0]["scoring"] = {"weight": 70}
    with pytest.raises(Exception):  # noqa: B017
        RulebookContent.model_validate(c)


def test_rulebook_lifecycle_and_separation_of_duties(
    client: TestClient, container: Container, tid: str, as_: Any
) -> None:
    pinned = client.get(f"{API}/tenders/{tid}", headers=as_("admin")).json()["pinned_rulebook_version_id"]
    approved = client.get(f"{API}/rulebook-versions/{pinned}", headers=as_("admin")).json()
    # approved version immutable via API
    r = client.put(
        f"{API}/rulebook-versions/{pinned}/content",
        json={"content": approved["content"], "row_version": approved["row_version"]},
        headers=as_("admin"),
    )
    assert r.json()["code"] == "INVALID_TRANSITION"
    # ... and via ORM
    with container.session_factory() as s:
        rv = s.get(RulebookVersion, uuid.UUID(pinned))
        assert rv is not None
        rv.content = {**rv.content, "criteria": []}
        with pytest.raises(Exception, match="immutable"):
            s.flush()
    # new version based on approved one; optimistic concurrency
    new = client.post(
        f"{API}/tenders/{tid}/rulebook/versions", json={"based_on_id": pinned}, headers=as_("admin")
    ).json()
    body = {"content": new["content"], "row_version": new["row_version"]}
    assert (
        client.put(
            f"{API}/rulebook-versions/{new['id']}/content", json=body, headers=as_("admin")
        ).status_code
        == 200
    )
    stale = client.put(f"{API}/rulebook-versions/{new['id']}/content", json=body, headers=as_("admin"))
    assert stale.json()["code"] == "VERSION_CONFLICT"
    # cannot approve before submission, approver cannot be author
    assert (
        client.post(
            f"{API}/rulebook-versions/{new['id']}/approve",
            json={"reason": "approved"},
            headers=as_("approver"),
        ).json()["code"]
        == "INVALID_TRANSITION"
    )
    client.post(f"{API}/rulebook-versions/{new['id']}/submit", json={"reason": "ready"}, headers=as_("admin"))
    assert (
        client.post(
            f"{API}/rulebook-versions/{new['id']}/approve", json={"reason": "approved"}, headers=as_("admin")
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{API}/rulebook-versions/{new['id']}/approve",
            json={"reason": "checked"},
            headers=as_("approver"),
        ).status_code
        == 200
    )
    # unapproved draft cannot be pinned
    draft = client.post(f"{API}/tenders/{tid}/rulebook/versions", json={}, headers=as_("admin")).json()
    r = client.post(
        f"{API}/tenders/{tid}/rulebook/pin",
        json={"version_id": draft["id"], "reason": "try"},
        headers=as_("admin"),
    )
    assert r.json()["code"] == "RULEBOOK_NOT_APPROVED"
    # empty draft cannot even be submitted
    r = client.post(
        f"{API}/rulebook-versions/{draft['id']}/submit", json={"reason": "submit empty"}, headers=as_("admin")
    )
    assert r.json()["code"] == "RULEBOOK_INVALID"


def test_tender_cannot_publish_without_approved_rulebook(client: TestClient, as_: Any) -> None:
    t = client.post(
        f"{API}/tenders",
        headers=as_("admin"),
        json={
            "reference_no": "T-NO-RB",
            "title": "No rulebook",
            "authority": "Demo",
            "submission_deadline": "2027-01-01T10:00:00+05:30",
        },
    ).json()
    r = client.post(f"{API}/tenders/{t['id']}/actions/publish", json={"reason": "go"}, headers=as_("admin"))
    assert r.json()["code"] == "RULEBOOK_NOT_APPROVED"
    r = client.post(f"{API}/tenders/{t['id']}/actions/cancel", json={"reason": "short"}, headers=as_("admin"))
    assert r.json()["code"] == "VALIDATION_FAILED"
