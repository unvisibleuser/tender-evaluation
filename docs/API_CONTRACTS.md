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
