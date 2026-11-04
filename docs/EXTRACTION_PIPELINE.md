# PDF, OCR, extraction and human review pipeline

## 1. Intake and file safety

- Allow only approved file types and configured size/page limits.
- Validate MIME type from bytes, not extension.
- Scan for malware; reject or quarantine encrypted/password-protected PDFs unless the tender workflow explicitly permits them.
- Compute SHA-256 and preserve immutable original.
- Never execute embedded JavaScript, launch actions, attachments, macros, external links, or embedded files.
- Process in a non-root container with read-only filesystem where possible, CPU/memory/time limits, no network egress, and temporary storage cleanup.

## 2. PDF processing

For each page:
1. Detect whether extractable text exists.
2. Extract text and layout where available.
3. Render page image for visual inspection and OCR.
4. Detect rotation, skew, blur, low DPI, blank/cropped pages.
5. OCR only when needed; retain original text and OCR text separately.
6. Store page-level metadata and coordinate system.

Use both text and OCR where helpful; do not treat OCR output as authoritative without confidence/evidence.

## 3. Document classification

Classify whole files and page ranges. Common classes:
- tender form / bidder details;
- technical specification / technical data sheet;
- declaration / undertaking;
- experience / work order / completion certificate;
- registration / license / BIS / ISI;
- financial statement / CA certificate;
- PAN / GST / Udyam / MSME;
- bank guarantee / EMD / fee receipt;
- integrity pact;
- commercial schedule / price bid;
- other / unknown.

Keep `unknown` documents visible to reviewers.

## 4. Extraction schema

Each field extraction stores:
- canonical field key;
- raw text/value;
- normalized value;
- normalized unit;
- source artifact and page;
- bounding box or text span;
- crop pointer (if generated);
- method;
- confidence;
- model/OCR metadata;
- ambiguity/conflict flags;
- review state;
- revision and timestamp.

For signatures and stamps, store detection as `PRESENT / NOT_DETECTED / UNCERTAIN`; do not claim legal validity based only on image detection.

## 5. OCR and confidence policy

Confidence thresholds must be configurable and calibrated against representative documents. Example initial triage bands for a prototype (not legal or procurement standards):
- high: >= 0.95, no conflict -> auto-propose extraction;
- medium: 0.80–0.949 -> reviewer queue for critical fields;
- low: < 0.80 -> manual review;
- any material handwriting, conflict, illegible text, unclear table mapping, or low-quality stamp -> manual review regardless of score.

Do not compare raw confidence scores across different OCR/model providers without calibration.

## 6. Duly-filled form detection

Model each prescribed form as a set of expected sections and fields. For every section record:
- `PRESENT`
- `FILLED`
- `PARTIALLY_FILLED`
- `BLANK`
- `NOT_FOUND`
- `UNREADABLE`
- `NOT_APPLICABLE`

Detect content, not merely presence of a page. For signature/date/seal requirements, check their visual presence and route uncertainty to officer.

Do not treat a generic remark such as "as per attached documents" as a filled form when the tender requires prescribed annexure fields. Apply the exact tender clause and its clarification policy.

## 7. Supporting document checks

For certificates and credentials extract:
- legal holder/name;
- certificate type and number;
- issuer;
- issue date;
- expiry date;
- covered product/work/scope;
- applicable standard/class/capacity;
- signatory and designation;
- verification identifier/QR/UDIN where applicable;
- source page and evidence.

Compare holder names using controlled normalization, but flag legal-entity mismatches for human review. Evaluate validity against the tender-defined date (e.g. bid submission date or technical opening date), not today's date unless the tender says so.

## 8. Cross-document consistency

Examples:
- bidder legal name across PAN/GST/registration/declarations;
- work order vs completion certificate contract number/value/dates;
- certificate holder vs bidder;
- technical schedule values vs supporting test reports;
- declared experience vs evidence documents.

Never silently select one conflicting value. Use tender-defined precedence or human review.

## 9. Human review UI

Show:
- source PDF page and highlighted region;
- original extracted text;
- normalized value and unit;
- confidence and extraction method;
- why it was flagged;
- other conflicting sources;
- editable correction field;
- reviewer identity, reason, timestamp;
- approve/reject extraction controls.

Manual corrections create a new revision; do not overwrite AI output or original file.
