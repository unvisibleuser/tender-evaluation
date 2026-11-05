# API contract outline

Use `/api/v1`. All endpoints require authenticated identity except explicitly public tender information.

## Tender administration
- `POST /tenders`
- `GET /tenders`
- `GET /tenders/{tender_id}`
- `POST /tenders/{tender_id}/artifacts`
- `POST /tenders/{tender_id}/corrigenda`

## Rulebook
- `POST /tenders/{tender_id}/rulebook/draft` — enqueue drafting workflow.
- `GET /tenders/{tender_id}/rulebook/versions`
- `GET /rulebooks/{rulebook_version_id}`
- `PATCH /rulebooks/{rulebook_version_id}/criteria/{criterion_id}` — draft only.
- `POST /rulebooks/{rulebook_version_id}/submit-for-approval`
- `POST /rulebooks/{rulebook_version_id}/approve`
- `POST /rulebooks/{rulebook_version_id}/publish`

## Bid submissions
- `POST /tenders/{tender_id}/bids`
- `POST /bids/{bid_id}/technical-artifacts`
- `POST /bids/{bid_id}/commercial-artifacts` — separate permission and storage route.
- `POST /bids/{bid_id}/submit`
- `GET /tenders/{tender_id}/bids` — role-filtered, paginated.

## Extraction and review
- `GET /bids/{bid_id}/documents`
- `GET /documents/{artifact_id}/extractions`
- `GET /review-tasks`
- `POST /review-tasks/{task_id}/resolve`
- `POST /documents/{artifact_id}/extractions/{field_id}/corrections`

## Evaluation
- `POST /tenders/{tender_id}/evaluation-runs`
- `GET /evaluation-runs/{run_id}`
- `GET /bids/{bid_id}/technical-results`
- `POST /bids/{bid_id}/officer-technical-decision`

## Commercial
- `POST /tenders/{tender_id}/commercial-opening/authorize`
- `POST /tenders/{tender_id}/commercial-opening/execute`
- `GET /tenders/{tender_id}/commercial-results`
- `POST /tenders/{tender_id}/commercial-evaluation-runs`

## Audit
- `GET /tenders/{tender_id}/audit-events`
- `GET /bids/{bid_id}/audit-events`

## API rules

- Return typed response schemas and stable error codes.
- Never return commercial data before opening, even if caller guesses endpoint IDs.
- Every state-changing endpoint records audit event.
- Approvals require reason and authenticated actor.
- Use ETags/version fields for rulebook edits.
- Submission/opening/approval actions should be idempotent or protected from duplicate execution.
- Exports must enforce same authorization and redaction as normal APIs.

## Implemented in the MVP (`backend/app/api.py`)

Interactive OpenAPI docs: `http://localhost:8000/api/docs` (disabled in production).
Errors use `{code, message, correlation_id, details?}`. All responses are `cache-control: no-store`.

| Area | Endpoints |
|---|---|
| Auth (demo) | `GET /auth/demo-officers`, `POST /auth/dev-login`, `GET /auth/me` |
| Bidder portal (public) | `GET /public/tenders`, `GET /public/tenders/{id}`, `POST /public/tenders/{id}/bids` (multipart; `Idempotency-Key`) |
| Tenders | `GET/POST /tenders`, `GET/PUT /tenders/{id}`, `POST /tenders/{id}/actions/{publish\|close\|start-technical\|complete-technical\|cancel}` |
| Tender documents | `POST/GET /tenders/{id}/documents`, `GET /tender-documents/{aid}/pages/{n}/image` |
| Rulebooks | `GET/POST /tenders/{id}/rulebook/versions`, `GET /rulebook-versions/{v}`, `PUT /rulebook-versions/{v}/content` (row_version), `POST /rulebook-versions/{v}/{submit\|approve\|request-changes}`, `POST /tenders/{id}/rulebook/pin`, `POST /rulebook/validate` |
| Bids (after close) | `GET /tenders/{id}/bids`, `GET /bids/{b}`, `GET /bids/{b}/pages/{n}/image`, `GET /bids/{b}/fields/{k}/history`, `POST /bids/{b}/fields/{k}/revisions`, `POST /bids/{b}/pages/{n}/classification`, `POST /bids/{b}/pages/{n}/release`, `POST /bids/{b}/reprocess` |
| Review | `GET /tenders/{id}/review-tasks`, `POST /review-tasks/{t}/acknowledge` |
| Evaluation | `POST/GET /tenders/{id}/evaluation-runs`, `GET /evaluation-runs/{r}`, `POST /bids/{b}/technical-decision` |
| Commercial | `GET /tenders/{id}/commercial/status`, `POST .../authorizations`, `POST .../open`, `GET .../offers`, `GET .../bids/{b}/document`, `POST .../evaluation`, `GET .../ranking` |
| Audit | `GET /tenders/{id}/audit-events`, `GET /audit/verify` |
