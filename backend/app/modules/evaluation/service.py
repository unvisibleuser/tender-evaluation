"""Technical evaluation runs (deterministic) and officer technical decisions.

Every run evaluates ALL bids of the tender against the single pinned, approved rulebook version.
Rule outcomes are never decisions: a bid's technical outcome changes only via an officer decision.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditService
from app.authz.identity import Actor
from app.core.clock import Clock
from app.core.errors import Conflict, InvalidTransition, NotFound, ValidationFailed
from app.db.models import Bid, CriterionResult, EvaluationRun, OfficerDecisionRecord, OfficerUser, Tender
from app.modules.bids.service import OFFICER_ROLES, require_unsealed
from app.modules.processing.evidence import bid_input_fingerprint, build_bid_evidence
from app.modules.rulebooks.schemas import Criterion, DateBasis, RulebookContent
from app.modules.rulebooks.service import pinned_content
from app.shared.enums import ProcessingStatus, Role, TechnicalDecision, TechnicalOutcome, TenderStatus
from rule_engine import (
    ENGINE_VERSION,
    CriterionEvaluation,
    RuleOutcome,
    RuleSpec,
    canonical_hash,
    evaluate,
    results_hash,
)

ACCEPTABLE_FOR_RESPONSIVE = {RuleOutcome.PASS.value, RuleOutcome.NOT_APPLICABLE.value}


class CriterionResultOut(BaseModel):
    criterion_id: str
    outcome: str
    mandatory: bool
    actual: str | None
    expected: str | None
    explanation: str
    revision_ids: list[str]


class BidResultsOut(BaseModel):
    bid_id: uuid.UUID
    bid_reference: str
    bidder_legal_name: str
    technical_outcome: TechnicalOutcome
    stale: bool
    counts: dict[str, int]
    results: list[CriterionResultOut]
    decision: DecisionOut | None


class CriterionHeader(BaseModel):
    criterion_id: str
    name: str
    category: str
    mandatory: bool
    operator: str
    source: str


class RunOut(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    rulebook_version_id: uuid.UUID
    rulebook_content_hash: str
    engine_version: str
    input_hash: str
    result_hash: str
    bid_count: int
    created_at: datetime
    started_by_label: str
    is_latest: bool
    criteria: list[CriterionHeader]
    bids: list[BidResultsOut]


class RunSummaryOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    result_hash: str
    bid_count: int
    started_by_label: str


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: TechnicalDecision
    evaluation_run_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=4000)
    cited_criteria: list[str] = Field(default_factory=list, max_length=100)
    override_acknowledged: bool = False


class DecisionOut(BaseModel):
    id: uuid.UUID
    decision: TechnicalDecision
    reason: str
    cited_criteria: list[str]
    overridden_criteria: list[str]
    decided_by_label: str
    decided_at: datetime
    evaluation_run_id: uuid.UUID
    stage: Literal["TECHNICAL"] = "TECHNICAL"


BidResultsOut.model_rebuild()


def _basis_date(c: Criterion, tender: Tender, bid: Bid) -> date | None:
    tz = ZoneInfo(tender.timezone)
    match c.evaluation_date_basis:
        case DateBasis.SUBMISSION_DEADLINE:
            return tender.submission_deadline.astimezone(tz).date()
        case DateBasis.BID_SUBMITTED_AT:
            return bid.submitted_at.astimezone(tz).date()
        case DateBasis.FIXED_DATE:
            return c.basis_fixed_date
    return None


def rule_specs(content: RulebookContent, tender: Tender, bid: Bid) -> list[RuleSpec]:
    fields = content.field_map()
    specs: list[RuleSpec] = []
    for c in content.criteria:
        fd = fields.get(c.field_key) if c.field_key else None
        specs.append(
            RuleSpec(
                criterion_id=c.criterion_id,
                name=c.name,
                operator=c.operator,
                mandatory=c.mandatory,
                field_key=c.field_key,
                data_type=fd.data_type if fd else None,
                doc_class=c.doc_class,
                expected=c.expected,
                basis_date=_basis_date(c, tender, bid),
                applies_if=content.to_engine_condition(c.applies_if) if c.applies_if else None,
            )
        )
    return specs


def _not_evaluated(content: RulebookContent, why: str) -> list[CriterionEvaluation]:
    return [
        CriterionEvaluation(
            criterion_id=c.criterion_id,
            outcome=RuleOutcome.NOT_EVALUATED,
            mandatory=c.mandatory,
            actual=None,
            expected=None,
            explanation=why,
        )
        for c in content.criteria
    ]


def run_technical_evaluation(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, tender: Tender
) -> EvaluationRun:
    actor.require(Role.TECHNICAL_EVALUATOR)
    if tender.status is not TenderStatus.TECHNICAL_EVALUATION:
        raise InvalidTransition("Evaluation runs are only allowed during TECHNICAL_EVALUATION")
    rv, content = pinned_content(session, tender)
    bids = list(
        session.scalars(select(Bid).where(Bid.tender_id == tender.id).order_by(Bid.submitted_at)).all()
    )
    busy = [
        b.bid_reference
        for b in bids
        if b.processing_status in (ProcessingStatus.RECEIVED, ProcessingStatus.PROCESSING)
    ]
    if busy:
        raise Conflict(
            f"Document processing still running for: {', '.join(busy)}", code="BIDS_STILL_PROCESSING"
        )
    per_bid: dict[str, list[CriterionEvaluation]] = {}
    fingerprints: dict[str, str] = {}
    for bid in bids:
        fingerprints[str(bid.id)] = bid_input_fingerprint(session, bid)
        if bid.processing_status is ProcessingStatus.FAILED:
            per_bid[str(bid.id)] = _not_evaluated(
                content, "Document processing failed; officer action required."
            )
        else:
            per_bid[str(bid.id)] = evaluate(
                rule_specs(content, tender, bid), build_bid_evidence(session, bid, content)
            )
    run = EvaluationRun(
        tender_id=tender.id,
        rulebook_version_id=rv.id,
        rulebook_content_hash=rv.content_hash,
        engine_version=ENGINE_VERSION,
        input_hash=canonical_hash({"rulebook": rv.content_hash, "bids": fingerprints}),
        result_hash=results_hash(rv.content_hash, per_bid),
        bid_input_hashes=fingerprints,
        bid_count=len(bids),
        started_by=actor.officer_id,
        created_at=clock.now(),
    )
    session.add(run)
    session.flush()
    for bid_id, results in per_bid.items():
        for r in results:
            session.add(
                CriterionResult(
                    run_id=run.id,
                    bid_id=uuid.UUID(bid_id),
                    criterion_id=r.criterion_id,
                    outcome=r.outcome.value,
                    mandatory=r.mandatory,
                    actual=r.actual,
                    expected=r.expected,
                    explanation=r.explanation,
                    revision_ids=list(r.revision_ids),
                )
            )
    session.flush()
    audit.record(
        session,
        actor,
        "TECHNICAL_EVALUATION_RUN",
        "evaluation_run",
        run.id,
        tender_id=tender.id,
        after={
            "rulebook_version_id": str(rv.id),
            "rulebook_content_hash": rv.content_hash,
            "engine_version": ENGINE_VERSION,
            "bids": len(bids),
            "result_hash": run.result_hash,
            "input_hash": run.input_hash,
        },
    )
    return run


def _latest_run(session: Session, tender_id: uuid.UUID) -> EvaluationRun | None:
    return session.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.tender_id == tender_id)
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
    ).first()


def _label(session: Session, officer_id: uuid.UUID) -> str:
    u = session.get(OfficerUser, officer_id)
    return f"{u.display_name} ({u.username})" if u else str(officer_id)


def _decision_out(session: Session, d: OfficerDecisionRecord) -> DecisionOut:
    return DecisionOut(
        id=d.id,
        decision=d.decision,
        reason=d.reason,
        cited_criteria=d.cited_criteria,
        overridden_criteria=d.overridden_criteria,
        decided_by_label=_label(session, d.decided_by),
        decided_at=d.decided_at,
        evaluation_run_id=d.evaluation_run_id,
    )


def list_runs(session: Session, actor: Actor, tender: Tender) -> list[RunSummaryOut]:
    actor.require(*OFFICER_ROLES)
    require_unsealed(tender)
    runs = session.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.tender_id == tender.id)
        .order_by(EvaluationRun.created_at.desc())
    ).all()
    return [
        RunSummaryOut(
            id=r.id,
            created_at=r.created_at,
            result_hash=r.result_hash,
            bid_count=r.bid_count,
            started_by_label=_label(session, r.started_by),
        )
        for r in runs
    ]


def run_detail(session: Session, actor: Actor, run_id: uuid.UUID) -> RunOut:
    actor.require(*OFFICER_ROLES)
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise NotFound("Evaluation run not found")
    tender = session.get(Tender, run.tender_id)
    assert tender is not None
    require_unsealed(tender)
    _rv, content = pinned_content(session, tender)
    latest = _latest_run(session, tender.id)
    results = session.scalars(select(CriterionResult).where(CriterionResult.run_id == run.id)).all()
    order = {c.criterion_id: i for i, c in enumerate(content.criteria)}
    by_bid: dict[uuid.UUID, list[CriterionResult]] = {}
    for r in results:
        by_bid.setdefault(r.bid_id, []).append(r)
    bids_out: list[BidResultsOut] = []
    for bid in session.scalars(
        select(Bid).where(Bid.tender_id == tender.id).order_by(Bid.submitted_at)
    ).all():
        rows = sorted(by_bid.get(bid.id, []), key=lambda r: order.get(r.criterion_id, 999))
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.outcome] = counts.get(r.outcome, 0) + 1
        decision = session.scalar(
            select(OfficerDecisionRecord).where(
                OfficerDecisionRecord.bid_id == bid.id, OfficerDecisionRecord.is_current.is_(True)
            )
        )
        stale = run.bid_input_hashes.get(str(bid.id)) != bid_input_fingerprint(session, bid)
        bids_out.append(
            BidResultsOut(
                bid_id=bid.id,
                bid_reference=bid.bid_reference,
                bidder_legal_name=bid.bidder_legal_name,
                technical_outcome=bid.technical_outcome,
                stale=stale,
                counts=counts,
                results=[
                    CriterionResultOut(
                        criterion_id=r.criterion_id,
                        outcome=r.outcome,
                        mandatory=r.mandatory,
                        actual=r.actual,
                        expected=r.expected,
                        explanation=r.explanation,
                        revision_ids=r.revision_ids,
                    )
                    for r in rows
                ],
                decision=_decision_out(session, decision) if decision else None,
            )
        )
    return RunOut(
        id=run.id,
        tender_id=run.tender_id,
        rulebook_version_id=run.rulebook_version_id,
        rulebook_content_hash=run.rulebook_content_hash,
        engine_version=run.engine_version,
        input_hash=run.input_hash,
        result_hash=run.result_hash,
        bid_count=run.bid_count,
        created_at=run.created_at,
        started_by_label=_label(session, run.started_by),
        is_latest=latest is not None and latest.id == run.id,
        criteria=[
            CriterionHeader(
                criterion_id=c.criterion_id,
                name=c.name,
                category=c.category.value,
                mandatory=c.mandatory,
                operator=c.operator.value,
                source="; ".join(
                    f"{s.document_title} p.{s.page}" + (f" {s.clause}" if s.clause else "")
                    for s in c.source_references
                ),
            )
            for c in content.criteria
        ],
        bids=bids_out,
    )


def record_decision(
    session: Session, actor: Actor, audit: AuditService, clock: Clock, bid_id: uuid.UUID, data: DecisionIn
) -> OfficerDecisionRecord:
    actor.require(Role.APPROVER)
    bid = session.get(Bid, bid_id)
    if bid is None:
        raise NotFound("Bid not found")
    tender = session.get(Tender, bid.tender_id)
    assert tender is not None
    if tender.status is not TenderStatus.TECHNICAL_EVALUATION:
        raise InvalidTransition("Technical decisions can only be recorded during TECHNICAL_EVALUATION")
    latest = _latest_run(session, tender.id)
    if latest is None or latest.id != data.evaluation_run_id:
        raise Conflict("Decisions must reference the latest evaluation run", code="EVALUATION_NOT_LATEST")
    if latest.bid_input_hashes.get(str(bid.id)) != bid_input_fingerprint(session, bid):
        raise Conflict(
            "Evidence changed after the latest run; re-run evaluation first", code="EVALUATION_STALE"
        )
    results = {
        r.criterion_id: r
        for r in session.scalars(
            select(CriterionResult).where(
                CriterionResult.run_id == latest.id, CriterionResult.bid_id == bid.id
            )
        ).all()
    }
    unknown = [c for c in data.cited_criteria if c not in results]
    if unknown:
        raise ValidationFailed(f"Unknown criteria cited: {', '.join(unknown)}")
    overridden: list[str] = []
    if data.decision is TechnicalDecision.RESPONSIVE:
        overridden = sorted(
            cid for cid, r in results.items() if r.mandatory and r.outcome not in ACCEPTABLE_FOR_RESPONSIVE
        )
        if overridden and not data.override_acknowledged:
            raise Conflict(
                "Mandatory criteria are not PASS/NOT_APPLICABLE: "
                + ", ".join(overridden)
                + ". Recording RESPONSIVE requires explicit override acknowledgement and reasons.",
                code="OVERRIDE_ACK_REQUIRED",
                details={"criteria": overridden},
            )
    elif not data.cited_criteria:
        raise ValidationFailed("A NON_RESPONSIVE decision must cite the criteria it is based on")

    previous = session.scalar(
        select(OfficerDecisionRecord).where(
            OfficerDecisionRecord.bid_id == bid.id, OfficerDecisionRecord.is_current.is_(True)
        )
    )
    if previous is not None:
        previous.is_current = False
        session.flush()
    record = OfficerDecisionRecord(
        tender_id=tender.id,
        bid_id=bid.id,
        decision=data.decision,
        evaluation_run_id=latest.id,
        cited_criteria=sorted(set(data.cited_criteria)),
        overridden_criteria=overridden,
        reason=data.reason,
        decided_by=actor.officer_id,
        decided_at=clock.now(),
        supersedes_id=previous.id if previous else None,
    )
    session.add(record)
    before_outcome = bid.technical_outcome
    bid.technical_outcome = TechnicalOutcome(data.decision.value)
    session.flush()
    audit.record(
        session,
        actor,
        "TECHNICAL_DECISION_RECORDED",
        "officer_decision",
        record.id,
        tender_id=tender.id,
        bid_id=bid.id,
        reason=data.reason,
        before={"technical_outcome": before_outcome.value},
        after={
            "technical_outcome": bid.technical_outcome.value,
            "evaluation_run_id": str(latest.id),
            "result_hash": latest.result_hash,
            "cited_criteria": record.cited_criteria,
            "overridden_criteria": overridden,
        },
    )
    return record
