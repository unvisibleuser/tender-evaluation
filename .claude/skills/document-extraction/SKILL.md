# Skill: Bid Document Extraction

Use this skill when extracting fields from bidder submissions.

## Procedure
1. Confirm bidder, tender, submission snapshot, stage, and allowed artifact scope.
2. Classify documents and page ranges; retain unknowns.
3. Determine text-PDF vs scanned page; OCR only as needed.
4. Extract requested fields only.
5. Attach source page and region for each field.
6. Preserve raw and normalized values separately.
7. Validate type, units, date, identity, and allowed value.
8. Cross-check linked supporting documents.
9. Flag conflicts and low-confidence/handwritten content for review.
10. Persist only through application service with immutable revision and audit event.

Do not evaluate the bid or make final procurement decisions.
