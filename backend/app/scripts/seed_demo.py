"""Seed SYNTHETIC demo data: officers, one published tender with an approved rulebook, optional bids.

Usage:
    python -m app.scripts.seed_demo              # officers + published tender
    python -m app.scripts.seed_demo --with-bids  # also submit the three synthetic bids
    python -m app.scripts.seed_demo --write-samples ../examples/synthetic  # write PDFs for manual upload
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from alembic import command
from app.audit.service import AuditService
from app.authz.identity import Actor
from app.container import Container, InlineTaskRunner, build_container
from app.core.config import BACKEND_DIR, get_settings
from app.db.models import OfficerUser, Tender
from app.demo import synthetic
from app.modules.bids.service import submit_bid
from app.modules.rulebooks import service as rulebooks
from app.modules.rulebooks.schemas import RulebookContent
from app.modules.tenders import artifacts
from app.modules.tenders import service as tenders
from app.modules.tenders.schemas import TenderCreate
from app.shared.enums import ActorKind, CommercialMethod, Role

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


def seed(container: Container, with_bids: bool) -> Tender:
    clock, settings = container.clock, container.settings
    audit = AuditService(clock=clock)
    with container.session_factory() as s:
        users = ensure_officers(s)
        s.commit()
        existing = s.scalar(select(Tender).where(Tender.reference_no == synthetic.TENDER_REF))
        if existing is not None:
            print(f"Demo tender already exists: {existing.reference_no} ({existing.status})")
            return existing
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
            s,
            admin,
            audit,
            rv,
            RulebookContent.model_validate(synthetic.demo_rulebook(spec.id)),
            rv.row_version,
        )
        rulebooks.submit(s, admin, audit, clock, rv, "Draft prepared from tender specification sections 2-4")
        rulebooks.approve(s, approver, audit, clock, rv, "Criteria verified against tender clauses")
        rulebooks.pin(s, admin, audit, tender, rv, "Initial approved rulebook")
        tenders.transition(s, admin, audit, clock, settings, tender, "publish", "Published for submissions")
        s.commit()
        if with_bids:
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
        print(
            f"Seeded tender {tender.reference_no} ({tender.status}); bids submitted: {3 if with_bids else 0}"
        )
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
    parser.add_argument("--write-samples", type=Path, default=None)
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment == "production":
        raise SystemExit("Refusing to seed demo data in production")
    if args.write_samples:
        write_samples(args.write_samples)
    migrate()
    seed(build_container(settings, tasks=InlineTaskRunner()), args.with_bids)


if __name__ == "__main__":
    main()
