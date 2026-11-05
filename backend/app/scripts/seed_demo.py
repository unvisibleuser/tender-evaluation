"""Seed SYNTHETIC demo data: officers, one published tender with an approved rulebook, optional bids.

Usage:
    python -m app.scripts.seed_demo                      # officers + published tender (open for bids)
    python -m app.scripts.seed_demo --with-bids          # also submit the three synthetic bids (still open)
    python -m app.scripts.seed_demo --stage technical    # walkthrough state: bids submitted, submissions closed,
                                                         # processed, evaluated; two decided, one in review queue
    python -m app.scripts.seed_demo --write-samples ../examples/synthetic  # write PDFs for manual upload
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alembic import command
from app.audit.service import AuditService
from app.authz.identity import Actor
from app.container import Container, InlineTaskRunner, build_container
from app.core.config import BACKEND_DIR, get_settings
from app.db.models import Bid, EvaluationRun, OfficerDecisionRecord, OfficerUser, Tender
from app.demo import synthetic
from app.modules.bids.service import submit_bid
from app.modules.evaluation import service as evaluation
from app.modules.processing.service import process_bid
from app.modules.rulebooks import service as rulebooks
from app.modules.rulebooks.schemas import RulebookContent
from app.modules.tenders import artifacts
from app.modules.tenders import service as tenders
from app.modules.tenders.schemas import TenderCreate
from app.shared.enums import ActorKind, CommercialMethod, Role, TechnicalDecision, TenderStatus

DEMO_OFFICERS = [
    ("admin", "A. Mehta", "Tender Administrator (Executive Engineer)", [Role.TENDER_ADMIN]),
    ("approver", "R. Iyer", "Approver / Committee Chair (Superintending Engineer)", [Role.APPROVER]),
    ("evaluator", "S. Patel", "Technical Evaluator (Deputy Engineer)", [Role.TECHNICAL_EVALUATOR]),
    ("commercial1", "K. Desai", "Commercial Opening Officer (Accounts)", [Role.COMMERCIAL_OFFICER]),
    ("commercial2", "N. Shah", "Commercial Opening Officer (Purchase)", [Role.COMMERCIAL_OFFICER]),
    ("auditor", "P. Rao", "Internal Auditor", [Role.AUDITOR]),
]


def migrate() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


def ensure_officers(session: Session) -> dict[str, OfficerUser]:
    users: dict[str, OfficerUser] = {}
    for username, name, designation, roles in DEMO_OFFICERS:
        user = session.scalar(select(OfficerUser).where(OfficerUser.username == username))
        if user is None:
            user = OfficerUser(
                username=username, display_name=name, designation=designation, roles=[r.value for r in roles]
            )
            session.add(user)
        users[username] = user
    session.flush()
    return users


def actor_for(user: OfficerUser) -> Actor:
    return Actor(
        ActorKind.OFFICER,
        str(user.id),
        f"{user.display_name} ({user.username})",
        frozenset(Role(r) for r in user.roles),
    )


def _create_published_tender(
    s: Session, container: Container, audit: AuditService, users: dict[str, OfficerUser]
) -> Tender:
    clock, settings = container.clock, container.settings
    admin, approver = actor_for(users["admin"]), actor_for(users["approver"])
    tender = tenders.create_tender(
        s,
        admin,
        audit,
        clock,
        TenderCreate(
            reference_no=synthetic.TENDER_REF,
            title=synthetic.TENDER_TITLE,
            description="Synthetic demonstration tender. One combined technical PDF + one sealed price bid PDF.",
            authority="Demo Distribution Company Ltd (synthetic)",
            submission_deadline=clock.now() + timedelta(days=7),
            timezone="Asia/Kolkata",
            commercial_envelope_required=True,
            commercial_evaluation_method=CommercialMethod.LOWEST_QUOTED_TOTAL,
            opening_quorum=2,
        ),
    )
    spec = artifacts.upload(
        s,
        container,
        admin,
        audit,
        tender,
        synthetic.SPEC_TITLE,
        "demo-tender-spec.pdf",
        synthetic.tender_spec_pdf(),
    )
    rv = rulebooks.create_version(s, admin, audit, clock, tender, None)
    rulebooks.update_content(
        s, admin, audit, rv, RulebookContent.model_validate(synthetic.demo_rulebook(spec.id)), rv.row_version
    )
    rulebooks.submit(s, admin, audit, clock, rv, "Draft prepared from tender specification sections 2-4")
    rulebooks.approve(s, approver, audit, clock, rv, "Criteria verified against tender clauses")
    rulebooks.pin(s, admin, audit, tender, rv, "Initial approved rulebook")
    tenders.transition(s, admin, audit, clock, settings, tender, "publish", "Published for submissions")
    s.commit()
    return tender


def _submit_sample_bids(s: Session, container: Container, tender: Tender) -> None:
    for b in synthetic.all_bids():
        submit_bid(
            s,
            container,
            tender,
            legal_name=b.legal_name,
            email=b.email,
            phone=b.phone,
            declaration_accepted=True,
            technical_pdf=b.technical_pdf,
            technical_filename=f"bidder-{b.key}-technical.pdf",
            commercial_pdf=b.commercial_pdf,
            quoted_total=b.quoted_total,
            idempotency_key=None,
        )
        s.commit()


def _advance_to_technical(
    s: Session, container: Container, audit: AuditService, users: dict[str, OfficerUser], tender: Tender
) -> None:
    """Walkthrough state: A responsive (override acknowledged), B non-responsive, C left in the review queue."""
    clock, settings = container.clock, container.settings
    admin, approver, evaluator = (actor_for(users[k]) for k in ("admin", "approver", "evaluator"))

    if tender.status is TenderStatus.OPEN_FOR_SUBMISSION:
        if not s.scalar(select(func.count()).select_from(Bid).where(Bid.tender_id == tender.id)):
            _submit_sample_bids(s, container, tender)
        tenders.transition(
            s, admin, audit, clock, settings, tender, "close", "Demo walkthrough: submissions closed early"
        )
        s.commit()
        for bid_id in tenders.bid_ids(s, tender.id):  # synchronous here; the API uses background workers
            process_bid(container, bid_id)
        s.expire_all()
    if tender.status is TenderStatus.SUBMISSION_CLOSED:
        tenders.transition(
            s, admin, audit, clock, settings, tender, "start-technical", "Begin technical scrutiny"
        )
        s.commit()
    if tender.status is not TenderStatus.TECHNICAL_EVALUATION:
        return
    run = s.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.tender_id == tender.id)
        .order_by(EvaluationRun.created_at.desc())
    ).first()
    if run is None:
        run = evaluation.run_technical_evaluation(s, evaluator, audit, clock, tender)
        s.commit()
    if s.scalar(
        select(func.count())
        .select_from(OfficerDecisionRecord)
        .where(OfficerDecisionRecord.tender_id == tender.id)
    ):
        return  # decisions already recorded

    by_email = {b.bidder_email: b for b in s.scalars(select(Bid).where(Bid.tender_id == tender.id)).all()}
    bid_a = by_email[synthetic.bidder_a().email]
    bid_b = by_email[synthetic.bidder_b().email]
    evaluation.record_decision(
        s,
        approver,
        audit,
        clock,
        bid_a.id,
        evaluation.DecisionIn(
            decision=TechnicalDecision.RESPONSIVE,
            evaluation_run_id=run.id,
            reason="All automated criteria PASS; type-test reports examined by committee and found acceptable.",
            override_acknowledged=True,
        ),
    )
    evaluation.record_decision(
        s,
        approver,
        audit,
        clock,
        bid_b.id,
        evaluation.DecisionIn(
            decision=TechnicalDecision.NON_RESPONSIVE,
            evaluation_run_id=run.id,
            reason=(
                "Average turnover below Rs. 5 Crore (cl. 2.3) and ISO 9001 certificate "
                "expired before the deadline (cl. 2.4)."
            ),
            cited_criteria=["FIN-TURNOVER", "SUP-ISO-VALID"],
        ),
    )
    s.commit()


def seed(container: Container, with_bids: bool, stage: str = "open") -> Tender:
    audit = AuditService(clock=container.clock)
    with container.session_factory() as s:
        users = ensure_officers(s)
        s.commit()
        tender = s.scalar(select(Tender).where(Tender.reference_no == synthetic.TENDER_REF))
        if tender is None:
            tender = _create_published_tender(s, container, audit, users)
            if with_bids and stage == "open":
                _submit_sample_bids(s, container, tender)
        else:
            print(f"Demo tender already exists: {tender.reference_no} ({tender.status})")
        if stage == "technical":
            _advance_to_technical(s, container, audit, users, tender)
        s.refresh(tender)
        bids = s.scalar(select(func.count()).select_from(Bid).where(Bid.tender_id == tender.id))
        print(f"Tender {tender.reference_no}: status {tender.status}; bids: {bids}")
        return tender


def write_samples(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "demo-tender-spec.pdf").write_bytes(synthetic.tender_spec_pdf())
    for b in synthetic.all_bids():
        (target / f"bidder-{b.key}-technical.pdf").write_bytes(b.technical_pdf)
        (target / f"bidder-{b.key}-price-bid.pdf").write_bytes(b.commercial_pdf)
        (target / f"bidder-{b.key}-details.txt").write_text(
            f"Legal name: {b.legal_name}\nEmail: {b.email}\nPhone: {b.phone}\nQuoted total (INR): {b.quoted_total}\n",
            encoding="utf-8",
        )
    print(f"Wrote synthetic sample PDFs to {target.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic demo data")
    parser.add_argument("--with-bids", action="store_true")
    parser.add_argument("--stage", choices=["open", "technical"], default="open")
    parser.add_argument("--write-samples", type=Path, default=None)
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to seed demo data in production")
    if args.write_samples:
        write_samples(args.write_samples)
    migrate()
    seed(build_container(settings, tasks=InlineTaskRunner()), args.with_bids, args.stage)


if __name__ == "__main__":
    main()
