# Tender Intelligence & Evaluation Platform — Claude Code Starter

A secure, human-governed tender scrutiny platform for electricity-sector procurement (DISCOMs, GETCO, GSECL, GUVNL).

## What this repository specification is

This is the project instruction/documentation pack for Claude Code. It is intentionally architecture-first: implement the platform in vertical slices, with deterministic evaluation and auditability before adding autonomous agent complexity.

## Core principle

**AI extracts and explains evidence. Approved rules evaluate evidence. Authorized officers decide.**

AI must never autonomously reject a bidder, alter tender criteria, open a commercial bid, rank bids using invented weights, or make an award decision.

## Read first

1. `CLAUDE.md` — mandatory coding instructions.
2. `ARCHITECTURE.md` — system boundaries and design.
3. `AGENTS.md` — agent responsibilities and contracts.
4. `docs/DOMAIN_MODEL.md` — tender and bid lifecycle.
5. `docs/RULEBOOK_SPEC.md` — structured criteria model.
6. `docs/SECURITY.md` — security and confidentiality.
7. `docs/IMPLEMENTATION_PLAN.md` — recommended build sequence.

## Proposed stack

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic.
- Database: PostgreSQL.
- Background jobs: Celery + Redis (or a replaceable task queue adapter).
- Object storage: MinIO for local development; S3-compatible private object storage in deployment.
- Frontend: React + TypeScript + Vite; React Router; TanStack Query; a mature accessible component system.
- PDF: PyMuPDF / pypdf for text and page rendering; OCR adapter (PaddleOCR or Tesseract) for scanned pages.
- AI: provider-neutral LLM adapter; do not hard-wire business logic to one model vendor.
- Runtime: Docker Compose for local development; isolated, non-networked document-processing workers.

Pin dependencies and use lockfiles. Verify current versions at implementation time.

## Important tender-specific guardrails

The supplied examples demonstrate that tender processes are not uniform:

- The KLTPS ME-308 tender uses uploaded technical PDFs and an online-only price bid; it also has a special route for tender fee/EMD submission. It specifies technical bid scan quality and says price information must not be included in the technical bid.
- The GETCO Jambuva example uses separate technical and price envelopes; only substantially technically responsive bidders proceed to price-bid opening.
- The GETCO technical-bid example also restricts post-deadline additions/substitutions and limits clarification to information/documents already submitted, subject to its stated conditions.

Therefore, model submission channels, opening gates, deadlines, clarification rules, fee/EMD rules, and commercial mechanisms as tender-configured settings. Do not hard-code one procurement workflow for every tender.

**Live price editing / reverse auction is not a universal tender feature.** Enable it only when the particular tender explicitly authorizes that mechanism and the authority configures its rules. Otherwise use sealed commercial submission and controlled opening.

## Development command conventions

The eventual repository should provide these root commands (implement them as part of the project):
- `make dev` — start local dependencies and services.
- `make test` — run unit and integration tests.
- `make lint` — run formatters, type checks and linters.
- `make migrate` — apply database migrations.
- `make seed-demo` — load synthetic demonstration data only.

Never seed real bidder data or real tender documents into a public demo environment.
