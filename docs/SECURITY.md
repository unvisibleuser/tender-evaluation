# Security, confidentiality and government deployment requirements

## Threat model

Protect against:
- unauthorized access across organizations/tenders;
- early disclosure of commercial offers;
- malicious or malformed PDFs;
- prompt injection in tender/bid documents;
- accidental leakage through logs, exports, AI prompts, caches, or backups;
- tampering with original submissions, rulebooks, or audit history;
- privilege escalation and insider misuse;
- model/provider retention of confidential procurement data.

## Identity and authorization

Implement RBAC plus resource-level authorization:
- bidder: own submissions only; no competitor access;
- tender officer: tender configuration and technical scrutiny as assigned;
- technical evaluator: technical artifacts/results only;
- commercial opening officer: authorized opening actions;
- commercial evaluator: commercial data only after opening;
- approver/committee member: decisions within assigned authority;
- auditor: read-only audit and evidence access according to mandate;
- system administrator: infrastructure operations; no automatic procurement decision privileges.

Use MFA for officers, strong session management, CSRF protection where relevant, secure cookies, rate limiting, and short-lived access tokens.

## Commercial data isolation

- Store commercial artifacts in a separate storage namespace/bucket and encryption key policy.
- Separate technical and commercial API permissions.
- Do not return commercial data in technical API payloads.
- Do not send commercial documents to AI workers before opening.
- Enforce opening gate in backend service and storage access layer.
- Record opening officer(s), timestamp, eligible bidder set, and artifact hashes.
- Consider dual-control approval for opening and key release.

## Data protection

- TLS in transit; encryption at rest with managed keys.
- Secrets in environment/secret manager, never in source control.
- No document text, PAN, bank details, bid prices, tokens, or credentials in ordinary logs.
- Redact model prompts and telemetry.
- Define retention, legal hold, archival, backup, and secure deletion policies with the authority.
- Restrict external AI providers unless data-processing terms and government policy authorize use. Provide a local/on-prem model adapter option.

## Document processing isolation

- Run parser/OCR in separate worker containers.
- No outbound network by default.
- Run as non-root.
- Apply CPU, memory, disk, page-count, and execution-time limits.
- Use temporary directories with cleanup.
- Keep parsers and OCR libraries patched.
- Treat extracted document instructions as untrusted data.

## Audit and integrity

Audit events should be append-only and tamper-evident. Include:
- actor and role;
- organization/tender/bid IDs;
- action and object;
- timestamp;
- reason;
- before/after hash or values where appropriate;
- source evidence and rulebook version;
- request/correlation ID.

For stronger assurance, chain audit-event hashes or export signed daily audit manifests to immutable storage. This is not a substitute for a full security audit.

## Production readiness

Before production use:
- threat modeling and security review;
- penetration testing;
- dependency/SBOM scanning;
- backup/restore drills;
- disaster recovery plan;
- access review and separation-of-duties review;
- audit log integrity validation;
- legal/procurement policy approval;
- data residency and AI-provider approval.
