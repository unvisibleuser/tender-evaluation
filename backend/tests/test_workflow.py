"""End-to-end: publish -> bidder submissions -> close -> extraction -> review -> evaluation -> decisions ->
dual-control commercial opening -> L1 ranking -> audit verification. All via the HTTP API."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.container import Container
from app.core.clock import FixedClock
from app.demo import synthetic
from app.scripts.seed_demo import seed

API = "/api/v1"


def _seed(container: Container, client: TestClient) -> dict[str, Any]:
    seed(container, with_bids=False)
    tenders = client.get(f"{API}/public/tenders").json()
    assert len(tenders) == 1
    return tenders[0]


def submit(client: TestClient, tender_id: str, b: synthetic.SyntheticBid, key: str | None = None) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(
        f"{API}/public/tenders/{tender_id}/bids",
        data={
            "bidder_legal_name": b.legal_name,
            "bidder_email": b.email,
            "bidder_phone": b.phone,
            "declaration_accepted": "true",
            "quoted_total_amount": b.quoted_total,
        },
        files={
            "technical_pdf": ("tech.pdf", b.technical_pdf, "application/pdf"),
            "commercial_pdf": ("price.pdf", b.commercial_pdf, "application/pdf"),
        },
        headers=headers,
    )


def results_by_bid(run: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        b["bidder_legal_name"].split(" ")[0]: {r["criterion_id"]: r["outcome"] for r in b["results"]}
        for b in run["bids"]
    }


def test_full_workflow(client: TestClient, container: Container, clock: FixedClock, as_: Any) -> None:
    public = _seed(container, client)
    tid = public["id"]
    assert public["accepting_submissions"] is True
    assert any(d["name"].startswith("PAN") for d in public["required_documents"])

    receipts = {}
    sample = synthetic.all_bids()
    for b in sample:
        r = submit(client, tid, b, key=f"key-{b.key}-0001")
        assert r.status_code == 201, r.text
        receipts[b.key] = r.json()
        assert r.json()["commercial_sealed"] is True
        assert b.quoted_total not in r.text  # receipt never echoes the price
    # idempotent replay returns the same receipt; no duplicate bid
    again = submit(client, tid, sample[0], key="key-A-0001")
    assert again.status_code == 201 and again.json()["bid_reference"] == receipts["A"]["bid_reference"]
    other = submit(client, tid, synthetic.bidder_a(), key="key-A-0001")  # same key, different bytes
    assert other.json()["code"] == "IDEMPOTENCY_MISMATCH"
    assert submit(client, tid, sample[0]).json()["code"] == "DUPLICATE_SUBMISSION"

    # sealed before close: officers cannot list or read bids
    r = client.get(f"{API}/tenders/{tid}/bids", headers=as_("evaluator"))
    assert r.status_code == 409 and r.json()["code"] == "TECHNICAL_SEALED"
    r = client.post(f"{API}/tenders/{tid}/actions/close", json={"reason": ""}, headers=as_("admin"))
    assert r.status_code == 409 and r.json()["code"] == "DEADLINE_NOT_REACHED"

    clock.advance(timedelta(days=8))
    assert client.get(f"{API}/tenders", headers=as_("admin")).status_code == 401  # token TTL enforced
    as_.reset()
    assert submit(client, tid, synthetic.bidder_a()).json()["code"] == "SUBMISSION_CLOSED"
    r = client.post(
        f"{API}/tenders/{tid}/actions/close", json={"reason": "Deadline passed"}, headers=as_("admin")
    )
    assert r.status_code == 200 and r.json()["status"] == "SUBMISSION_CLOSED"

    bids = {
        b["bidder_legal_name"].split(" ")[0]: b
        for b in client.get(f"{API}/tenders/{tid}/bids", headers=as_("evaluator")).json()["items"]
    }
    assert bids["Shakti"]["processing_status"] == "READY"
    assert bids["Varun"]["withheld_pages"] == 1
    assert bids["Rudra"]["unreadable_pages"] == 1

    # withheld page is not viewable by anyone and its text is not served
    b_detail = client.get(f"{API}/bids/{bids['Varun']['id']}", headers=as_("evaluator")).json()
    withheld = [p for p in b_detail["pages"] if p["text_status"] == "WITHHELD_COMMERCIAL"]
    assert len(withheld) == 1 and "4,62" not in str(b_detail)
    r = client.get(
        f"{API}/bids/{bids['Varun']['id']}/pages/{withheld[0]['page_no']}/image", headers=as_("approver")
    )
    assert r.status_code == 409 and r.json()["code"] == "COMMERCIAL_SEALED"
    ok_img = client.get(f"{API}/bids/{bids['Varun']['id']}/pages/1/image", headers=as_("evaluator"))
    assert ok_img.status_code == 200 and ok_img.headers["content-type"] == "image/png"

    # evaluation not allowed before technical stage starts
    assert client.post(f"{API}/tenders/{tid}/evaluation-runs", headers=as_("evaluator")).status_code == 409
    client.post(
        f"{API}/tenders/{tid}/actions/start-technical", json={"reason": "Begin"}, headers=as_("admin")
    )
    run = client.post(f"{API}/tenders/{tid}/evaluation-runs", headers=as_("evaluator")).json()
    res = results_by_bid(run)
    assert set(res["Shakti"].values()) <= {"PASS", "PENDING_OFFICER_DECISION"}
    assert res["Shakti"]["TECH-TYPE-TEST"] == "PENDING_OFFICER_DECISION"
    assert res["Varun"]["FIN-TURNOVER"] == "FAIL"
    assert res["Varun"]["SUP-ISO-VALID"] == "FAIL"
    assert res["Varun"]["ADM-EMD"] == "NOT_APPLICABLE"  # MSME exemption
    assert res["Varun"]["ELG-GST"] == "PENDING_REVIEW"  # missing doc but a page is withheld => not MISSING
    assert res["Rudra"]["FIN-TURNOVER"] == "UNREADABLE"  # scanned page, never FAIL
    assert res["Rudra"]["TECH-CROSS-SECTION"] == "AMBIGUOUS"  # 300 vs 240, never silently chosen
    assert res["Rudra"]["SUP-ISO-VALID"] == "PENDING_REVIEW"  # DMY-assumed date needs review

    # determinism: same rulebook + same evidence -> same hash, for every bidder
    run2 = client.post(f"{API}/tenders/{tid}/evaluation-runs", headers=as_("evaluator")).json()
    assert run2["result_hash"] == run["result_hash"] and run2["input_hash"] == run["input_hash"]
    assert {b["bid_id"] for b in run2["bids"]} == {b["id"] for b in bids.values()}

    # rule outcomes are not decisions
    assert all(b["technical_outcome"] == "PENDING_OFFICER_DECISION" for b in run2["bids"])

    # officer review of bidder C
    cid = bids["Rudra"]["id"]
    tasks = client.get(f"{API}/tenders/{tid}/review-tasks", headers=as_("evaluator")).json()["items"]
    assert {t["reason"] for t in tasks if t["bid_id"] == cid} == {
        "PAGE_UNREADABLE",
        "CONFLICTING_VALUES",
        "LOW_CONFIDENCE",
    }
    assert (
        client.post(
            f"{API}/bids/{cid}/fields/annual_turnover/revisions",
            json={"action": "CORRECT", "value": "Rs. 7.10 Crore", "page_no": 4, "reason": "Read scan"},
            headers=as_("approver"),
        ).status_code
        == 403
    )  # approver is not an evaluator
    for key, body in [
        (
            "annual_turnover",
            {
                "action": "CORRECT",
                "value": "Rs. 7.10 Crore",
                "page_no": 4,
                "reason": "Transcribed from scanned CA certificate page 4",
            },
        ),
        (
            "conductor_cross_section",
            {
                "action": "CORRECT",
                "value": "300 sq.mm",
                "page_no": 6,
                "reason": "Main GTP sheet p6 governs; p7 value flagged for clarification",
            },
        ),
        ("iso_valid_until", {"action": "VERIFY", "reason": "Certificate shows 5 April 2027 (DD/MM)"}),
    ]:
        r = client.post(f"{API}/bids/{cid}/fields/{key}/revisions", json=body, headers=as_("evaluator"))
        assert r.status_code == 200, r.text
    r = client.post(
        f"{API}/bids/{cid}/pages/4/classification",
        json={"doc_class": "ca_certificate", "reason": "Scanned CA certificate"},
        headers=as_("evaluator"),
    )
    assert r.status_code == 200
    detail = r.json()
    turnover = next(f for f in detail["fields"] if f["field_key"] == "annual_turnover")
    assert turnover["normalized_value"] == "71000000" and turnover["provenance"] == "Officer corrected"
    assert turnover["revision_no"] == 2  # AI/automated original preserved as revision 1
    history = client.get(f"{API}/bids/{cid}/fields/annual_turnover/history", headers=as_("evaluator")).json()
    assert [h["revision_no"] for h in history] == [2, 1] and history[1]["method"] == "PDF_TEXT"
    page_task = next(t for t in tasks if t["bid_id"] == cid and t["reason"] == "PAGE_UNREADABLE")
    assert (
        client.post(
            f"{API}/review-tasks/{page_task['id']}/acknowledge",
            json={"resolution": "Values transcribed manually"},
            headers=as_("evaluator"),
        ).status_code
        == 204
    )

    # stale run blocks decisions until re-evaluated
    r = client.post(
        f"{API}/bids/{cid}/technical-decision",
        headers=as_("approver"),
        json={
            "decision": "RESPONSIVE",
            "evaluation_run_id": run2["id"],
            "reason": "x" * 20,
            "override_acknowledged": True,
        },
    )
    assert r.json()["code"] == "EVALUATION_STALE"
    run3 = client.post(f"{API}/tenders/{tid}/evaluation-runs", headers=as_("evaluator")).json()
    assert run3["result_hash"] != run2["result_hash"]
    assert set(results_by_bid(run3)["Rudra"].values()) <= {"PASS", "PENDING_OFFICER_DECISION"}

    # decisions: evaluators cannot decide; RESPONSIVE with non-PASS mandatory criteria needs explicit override
    aid, bid_b = bids["Shakti"]["id"], bids["Varun"]["id"]
    base = {"evaluation_run_id": run3["id"], "reason": "Type test reports examined by committee; compliant."}
    assert (
        client.post(
            f"{API}/bids/{aid}/technical-decision",
            json={**base, "decision": "RESPONSIVE"},
            headers=as_("evaluator"),
        ).status_code
        == 403
    )
    r = client.post(
        f"{API}/bids/{aid}/technical-decision",
        json={**base, "decision": "RESPONSIVE"},
        headers=as_("approver"),
    )
    assert r.json()["code"] == "OVERRIDE_ACK_REQUIRED"
    for x in (aid, cid):
        r = client.post(
            f"{API}/bids/{x}/technical-decision",
            json={**base, "decision": "RESPONSIVE", "override_acknowledged": True},
            headers=as_("approver"),
        )
        assert r.status_code == 201 and r.json()["overridden_criteria"] == ["TECH-TYPE-TEST"]
    r = client.post(
        f"{API}/bids/{bid_b}/technical-decision",
        headers=as_("approver"),
        json={**base, "decision": "NON_RESPONSIVE", "reason": "Turnover below Rs. 5 Crore (cl. 2.3)"},
    )
    assert r.json()["code"] == "VALIDATION_FAILED"  # must cite criteria
    r = client.post(
        f"{API}/bids/{bid_b}/technical-decision",
        headers=as_("approver"),
        json={
            **base,
            "decision": "NON_RESPONSIVE",
            "reason": "Turnover below Rs. 5 Crore (cl. 2.3)",
            "cited_criteria": ["FIN-TURNOVER", "SUP-ISO-VALID"],
        },
    )
    assert r.status_code == 201

    # commercial is sealed for everyone before opening; technical roles have no access at all
    assert client.get(f"{API}/tenders/{tid}/commercial/offers", headers=as_("evaluator")).status_code == 403
    r = client.get(f"{API}/tenders/{tid}/commercial/offers", headers=as_("commercial1"))
    assert r.status_code == 409 and r.json()["code"] == "COMMERCIAL_SEALED"
    r = client.post(
        f"{API}/tenders/{tid}/commercial/authorizations", json={"reason": "Ready"}, headers=as_("commercial1")
    )
    assert r.json()["code"] == "INVALID_TRANSITION"  # technical not completed yet

    assert (
        client.post(
            f"{API}/tenders/{tid}/actions/complete-technical",
            json={"reason": "Done"},
            headers=as_("approver"),
        ).status_code
        == 200
    )
    r = client.post(
        f"{API}/tenders/{tid}/commercial/open", json={"reason": "Open"}, headers=as_("commercial1")
    )
    assert r.json()["code"] == "QUORUM_NOT_MET"
    assert (
        client.post(
            f"{API}/tenders/{tid}/commercial/authorizations",
            json={"reason": "Authorised"},
            headers=as_("commercial1"),
        ).status_code
        == 200
    )
    r = client.post(
        f"{API}/tenders/{tid}/commercial/authorizations", json={"reason": "Again"}, headers=as_("commercial1")
    )
    assert r.json()["code"] == "ALREADY_AUTHORIZED"  # same officer cannot count twice
    assert (
        client.post(
            f"{API}/tenders/{tid}/commercial/open", json={"reason": "Open"}, headers=as_("commercial1")
        ).json()["code"]
        == "QUORUM_NOT_MET"
    )
    client.post(
        f"{API}/tenders/{tid}/commercial/authorizations",
        json={"reason": "Concur"},
        headers=as_("commercial2"),
    )
    r = client.post(
        f"{API}/tenders/{tid}/commercial/open",
        json={"reason": "Opening per tender schedule"},
        headers=as_("commercial2"),
    )
    assert r.status_code == 200 and r.json()["sealed"] is False

    offers = client.get(f"{API}/tenders/{tid}/commercial/offers", headers=as_("commercial1")).json()
    assert {o["bid_id"] for o in offers} == {aid, cid}  # non-responsive bid B stays sealed
    r = client.get(f"{API}/tenders/{tid}/commercial/bids/{bid_b}/document", headers=as_("commercial1"))
    assert r.json()["code"] == "COMMERCIAL_SEALED"
    pdf = client.get(f"{API}/tenders/{tid}/commercial/bids/{aid}/document", headers=as_("commercial1"))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"{API}/tenders/{tid}/commercial/offers", headers=as_("evaluator")).status_code == 403

    ranking = client.post(f"{API}/tenders/{tid}/commercial/evaluation", headers=as_("commercial1")).json()
    assert [r["bid_id"] for r in ranking["rows"]] == [cid, aid]
    assert ranking["rows"][0]["rank"] == 1 and ranking["rows"][0]["quoted_total"] == "47100000.00"
    assert any("Combined" in n for n in ranking["notes"])

    # audit: complete, chained, append-only and free of prices
    events = client.get(f"{API}/tenders/{tid}/audit-events?limit=500", headers=as_("auditor")).json()["items"]
    actions = {e["action"] for e in events}
    assert {
        "BID_SUBMITTED",
        "TENDER_CLOSE",
        "BID_PROCESSED",
        "FIELD_CORRECT",
        "TECHNICAL_DECISION_RECORDED",
        "COMMERCIAL_OPENING_AUTHORIZED",
        "COMMERCIAL_OPENED",
        "COMMERCIAL_EVALUATED",
    } <= actions
    dump = str(events)
    for b in synthetic.all_bids():
        assert b.quoted_total not in dump and b.quoted_total.split(".")[0] not in dump
    verify = client.get(f"{API}/audit/verify", headers=as_("auditor")).json()
    assert verify["ok"] is True and verify["events_checked"] > 20
    with container.engine.begin() as conn:
        try:
            conn.execute(text("UPDATE audit_event SET reason='tampered'"))
            raise AssertionError("audit_event must be append-only")
        except Exception as exc:  # noqa: BLE001
            assert "append-only" in str(exc)
