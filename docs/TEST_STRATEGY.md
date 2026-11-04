# Test strategy

## Rule engine
- Every operator: equal, boundaries, nulls, units, date comparisons.
- Unknown and missing values never become fail implicitly.
- Same approved rulebook + same evidence revisions = same result hash.
- No LLM call in deterministic evaluation path.

## Document processing
- Text PDF, scanned PDF, mixed PDF, rotated pages, skew, low DPI, handwriting, tables, stamps, corrupt/encrypted files.
- Evidence page and bounding box map correctly to rendered page.
- Unknown documents remain visible.

## Workflow
- Rulebook draft cannot be published without officer approval.
- Published version immutable.
- Corrigendum creates new version or explicitly scoped amendment.
- Bid locked after deadline.
- Clarification cannot silently replace original submission.

## Security
- Cross-tenant access denied.
- Bidder cannot view competitors.
- Technical role cannot access commercial files before opening through any API/export/cache.
- Commercial opening only by authorized role and at allowed stage.
- Prompt injection in document text cannot change system instructions or trigger tools.
- File parser cannot access network or host filesystem.

## UI
- Keyboard navigation.
- Status accessible without colour.
- Evidence panel links to correct source.
- Commercial tab and payload remain absent/locked before opening.
