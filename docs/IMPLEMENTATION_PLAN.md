# Implementation plan — hackathon to production path

## Phase 0 — Foundation
- Monorepo, Docker Compose, FastAPI, React, PostgreSQL, Redis, MinIO.
- Authentication/RBAC skeleton and tender-scoped authorization.
- Audit event service.
- CI, formatting, linting, type checks, tests.

Acceptance: login, create tender, upload tender artifact, list artifacts, audit event recorded.

## Phase 1 — Tender ingestion and rulebook
- PDF text extraction and page rendering.
- OCR adapter and document manifest.
- Rulebook drafting agent with strict JSON schema.
- Rulebook editor with source citations.
- Officer approval and immutable versioning.

Acceptance: given a tender pack, produce a draft checklist and fields; every criterion has source page/section or is marked unresolved; no rule can run before approval.

## Phase 2 — Bid intake and document extraction
- Bidder upload and immutable submission snapshot.
- Technical/commercial segregation.
- Document classifier.
- Field extraction with evidence references.
- Confidence-based review queue.
- Human correction and version history.

Acceptance: upload a synthetic bidder pack; show documents, extracted fields, evidence page, and manual correction.

## Phase 3 — Deterministic compliance
- Rule operators and validation.
- Same rulebook version across bidders.
- Criterion result table and explanations.
- Cross-document mismatch detection.
- Technical evaluation dashboard.

Acceptance: all bidders receive consistent deterministic evaluation; tests prove same inputs and rulebook yield same result.

## Phase 4 — Commercial opening
- Commercial vault and role separation.
- Tender-specific opening policy.
- Opening authorization and audit.
- Commercial extraction and evaluated-price calculation.
- Technical, commercial, and combined views only when supported by tender rules.

Acceptance: technical user cannot access commercial file before opening; authorized opening creates auditable event.

## Phase 5 — Hardening and demonstration
- Threat model, abuse cases, PDF fuzz tests.
- Performance tests on large scanned documents.
- Accessibility pass.
- Backup/restore.
- Demo data and scripted walkthrough.
- Deployment guide.

## Recommended hackathon demo

Use synthetic bidder documents and one fully reviewed rulebook:
1. Upload a tender pack.
2. Generate draft rulebook with source page citations.
3. Officer edits and approves.
4. Upload three synthetic bids with different document quality.
5. Show extraction and a low-confidence handwriting/manual-review case.
6. Show consistent compliance results.
7. Show commercial tab locked before opening.
8. Officer performs opening action.
9. Show commercial ranking and (only if configured) combined comparison.
10. Officer records final decision with reason; audit timeline updates.

Do not claim the demo is legally production-ready or connected to a live government procurement portal.
