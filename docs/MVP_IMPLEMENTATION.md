# MVP implementation notes

This describes what the MVP implements, the decisions taken, and known limitations. It complements
`ARCHITECTURE.md`; where they differ, the differences are listed under "Deviations".

## Scope decisions (product owner)

- **Bidder self-upload portal**, no bidder login (MVP). A bidder submits:
  - one **combined technical PDF** containing all required documents, and
  - a **separate sealed price-bid PDF** plus the declared total amount (when the tender requires a price envelope).
  Prices are kept out of the combined PDF so that commercial confidentiality can be enforced server-side
  (CLAUDE.md principle 7). Pages in the technical PDF that look like price content are withheld automatically.
- **Officer dashboard** uses a demo identity mode (select a seeded officer, signed bearer token, 8 h TTL).
  This keeps server-side role checks real. It is refused by configuration in `production`.
  Network restriction of the dashboard to officer machines is deferred.

## Workflow implemented

```
Tender DRAFT → (approved rulebook pinned) → OPEN_FOR_SUBMISSION → SUBMISSION_CLOSED
  → TECHNICAL_EVALUATION → TECHNICAL_COMPLETED → COMMERCIAL_OPENED → COMMERCIAL_EVALUATED
  (CANCELLED reachable from any non-terminal state, reason required)
```

1. Tender admin creates the tender, uploads tender documents, drafts the rulebook (JSON editor).
2. Admin submits the rulebook; a **different** officer (approver) approves it — the author/editor can never approve.
   Approved versions are immutable (service check + ORM guard). Admin pins it and publishes.
3. Bidders submit through `/portal`. The server checks deadline (server clock), PDF signature, parseability,
   encryption, size and page limits. The technical PDF is stored with its SHA-256; the price bid and amount are
   encrypted (AES-256-GCM, per-envelope key wrapped by a KEK). A receipt with hashes is issued. Idempotency keys
   prevent double submission.
4. Bid contents are **sealed for officers until submissions close** (`TECHNICAL_SEALED`).
5. On close, each bid is processed: page parsing → price-leakage detection (page text not stored, image withheld)
   → keyword page classification → label/value field extraction with page + bounding box → review queue.
6. Evaluators verify/correct fields (new revisions; originals preserved), reclassify pages, acknowledge
   unreadable pages. Approvers may release a withheld page (recorded as exposure-risk acceptance).
7. Evaluator runs the deterministic engine: **all bids**, the pinned rulebook, result hash recorded.
8. Approver records a decision per bid. RESPONSIVE with non-PASS mandatory criteria requires explicit override
   acknowledgement; NON_RESPONSIVE must cite criteria. Decisions against stale evidence are refused.
9. Commercial: N distinct commercial officers authorise (quorum, default 2); opening decrypts **only** envelopes of
   bids recorded RESPONSIVE. Ranking uses only the tender-configured method (L1); otherwise
   `REQUIRES_OFFICER_CONFIGURATION`. Combined ranking is not offered.
10. Every state change is in a hash-chained, append-only audit trail (DB triggers block UPDATE/DELETE).

## Security boundaries enforced in code

| Boundary | Enforcement |
|---|---|
| Technical bid sealed before close | `bids.service.require_unsealed` on every bid/review/evaluation read |
| Commercial data | separate tables, separate storage namespace, envelope encryption; `CommercialVault.open` requires an opening event; only `COMMERCIAL_OFFICER`/`AUDITOR` reach commercial routes; technical roles get 403 at every stage |
| Price leakage in technical PDF | `processing/leakage.py`; withheld page text never stored; image returns `COMMERCIAL_SEALED` |
| No AI/automation decisions | rule outcomes stored separately; `Bid.technical_outcome` changes only in `evaluation.service.record_decision` |
| Unknown ≠ fail | rule engine maps MISSING/UNREADABLE/AMBIGUOUS/PENDING to their own outcomes; tests assert it |
| Separation of duties | rulebook author ≠ approver; decisions by APPROVER only; quorum of distinct officers |
| Audit integrity | SHA-256 chain + `/audit/verify`; triggers; forbidden payload keys (prices, text, tokens) |
| Hostile documents | magic-byte check, encrypted/corrupt PDFs rejected, no JS/actions/attachments executed, opaque storage keys, document text treated as data |
| Logs | redacting log filter (PAN, GSTIN, amounts, bearer tokens) |
| Caching | `cache-control: no-store` on all API responses; officer token in sessionStorage; query cache cleared on login/logout; price queries not retained (`gcTime: 0`) |

## Deviations from ARCHITECTURE.md (intentional, MVP)

- Background processing uses an in-process thread pool (`ThreadTaskRunner`), not Celery/Redis, and PDF parsing runs
  in the API process, not an isolated no-network sandbox container. **Required before production.**
- Local filesystem object store (`storage/local.py`) instead of MinIO/S3; same interface.
- KEK in a local file (demo) or env var; production must use a KMS/HSM.
- SQLite by default; models and migrations are Postgres-compatible (`TENDER_DATABASE_URL`).
- Single organisation; roles are global, not per-tender assignments.
- No OCR engine: image-only pages are flagged `NO_TEXT_LAYER` and routed to manual transcription.
- No LLM: extraction is deterministic label matching. The provider-neutral LLM adapter, rulebook-drafting agent
  and explanation agent are future work and must return schema-validated proposals only.
- Rulebook editing is a validated JSON editor plus read-only tables (form editor is future work).
- Bidders cannot view status or withdraw; clarifications and corrigenda are not implemented.

## Running

See `README.md` → "Running the MVP".

Regenerate the JSON schema after changing rulebook models:

```
cd backend
.venv/Scripts/python -c "import json; from app.modules.rulebooks.schemas import RulebookContent as R; s=R.model_json_schema(); s['$schema']='https://json-schema.org/draft/2020-12/schema'; s['title']='Tender Rulebook Content (generated from app.modules.rulebooks.schemas.RulebookContent)'; open('../schemas/rulebook.schema.json','w').write(json.dumps(s, indent=2)+'\n')"
```
