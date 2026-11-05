# Progress tracker

Last updated: 2026-11-05. Status key: ✅ done · 🟡 partial · ⬜ not started.
Details of scope and deviations: `docs/MVP_IMPLEMENTATION.md`.

## Verification status (last run)
- Backend: 87 tests passing; ruff clean; mypy `--strict` clean; Alembic migration matches models.
- Frontend: `tsc` strict clean; `vite build` succeeds.
- Not done: manual browser click-through of the UI (layout/styling unchecked).

## Done
### Foundation
- ✅ Backend skeleton (FastAPI, Pydantic v2, SQLAlchemy 2, Alembic), config, errors, UTC clock, opaque IDs, redacting logger
- ✅ Dev officer login with roles (tender admin, approver, technical evaluator, commercial officer, auditor)
- ✅ Hash-chained append-only audit trail (DB triggers block update/delete) + verify endpoint
- ✅ Idempotency keys on bid submission
- ✅ Synthetic demo data + seed script (3 bidders, sample PDFs in `examples/synthetic/`); `--stage technical` walkthrough state for demo video (A responsive, B non-responsive, C in review queue)

### Rulebook & rules
- ✅ Rulebook schema (Pydantic is source of truth; JSON schema generated + drift test)
- ✅ Validation that blocks approval (missing source, threshold, unit, date basis, etc.)
- ✅ Versioning: draft → in review → approved (immutable) → superseded; author cannot approve; pin to tender
- ✅ Deterministic rule engine (pure package, no I/O): comparison, range, list, date-validity, document-present, manual-review operators; applicability conditions; unknown never becomes FAIL; reproducible result hash

### Bidder portal
- ✅ Public submission: combined technical PDF + separate sealed price PDF + declared total, no bidder login
- ✅ Server-side checks: deadline, PDF signature/corruption/encryption, size and page limits, duplicate bidder
- ✅ Receipt with SHA-256 hashes

### Document processing & scrutiny
- ✅ Technical bids sealed from officers until submissions close
- ✅ PDF parsing, page classification, label/value field extraction with page + bounding box evidence
- ✅ Price-leakage detection: page text not stored, page image withheld; approver can release (audited)
- ✅ Review queue; officer verify/correct creates new revision (original preserved); page reclassification
- ✅ Scanned pages flagged for manual reading (no OCR)

### Evaluation & decisions
- ✅ Evaluation runs over all bids against the same pinned rulebook; stale-evidence protection
- ✅ Officer technical decisions (override acknowledgement, cited criteria); only way bid outcome changes

### Commercial
- ✅ Envelope encryption (AES-256-GCM, wrapped per-envelope key); cannot decrypt without an opening event
- ✅ Two-officer authorisation (quorum) and opening; only technically responsive bids opened
- ✅ L1 ranking only when tender configures the method; no combined ranking

### Packaging
- 🟡 Docker: `docker-compose.yml` + backend/frontend Dockerfiles (API + nginx, data volume, non-root, read-only FS). **Written but not yet built or run** — Docker was not installed on the dev machine

### Frontend
- ✅ Landing, bidder portal (list, submit, printable receipt), officer sign-in
- ✅ Tender list/create, workspace with stage actions, documents, rulebook view/JSON editor, bids, review queue, evaluation matrix + decisions, commercial tab, audit trail
- ✅ Evidence viewer with highlighted region; status labels use text + glyph, not colour alone

## Not done / known gaps
### Needed before any real use
- ⬜ Isolated, no-network sandbox for PDF parsing (currently runs in the API process)
- ⬜ Proper task queue (currently in-process threads)
- ⬜ KMS/HSM for the encryption key (currently local file / env var)
- ⬜ Real identity provider with MFA (currently demo login); officer-machine/network restriction (deferred by request)
- ⬜ S3/MinIO object storage (currently local disk); Postgres deployment
- ⬜ Per-tender role assignment and multiple organisations (roles are global)
- ⬜ Threat model, penetration test, PDF fuzzing, backup/restore, accessibility audit

### Features
- ⬜ OCR for scanned pages
- ⬜ LLM-assisted rulebook drafting, document classification, explanations (must return schema-validated proposals only)
- ⬜ Rulebook form editor (JSON editor only today)
- ⬜ Corrigenda, clarifications, tender fee/EMD instrument tracking
- ⬜ Bidder status check / withdrawal; bidder authentication (deferred by request)
- ⬜ Commercial price-schedule extraction (only the bidder-declared total is used)
- ⬜ Combined technical-commercial ranking (needs a tender-published formula)
- ⬜ Exports, frontend automated tests, CI pipeline, `make` targets

### Test gaps
- ⬜ Golden-document tests on real electricity tender PDFs
- ⬜ OCR test matrix (skew, low resolution, handwriting, rotation, stamps)
- ⬜ Prompt-injection tests against an LLM path (no LLM yet; extraction treats text as data)
