# Rulebook specification

## Purpose

The rulebook is the canonical, tender-specific, officer-approved contract between tender language and evaluation logic. It must be machine-readable and human-readable.

## Rulebook generation process

1. Ingest all tender files, not only the file named `tender-declaration.pdf`.
2. Extract tender metadata, eligibility/QR, technical specs, declarations, annexures, commercial conditions, fee/EMD, deadlines, corrigenda, and price schedules.
3. Draft each requirement as a criterion with exact source references.
4. Identify contradictions and cross-document dependencies.
5. Ask officer to resolve missing thresholds, weights, precedence, and ambiguous interpretations.
6. Validate schema and rule completeness.
7. Officer approves and publishes immutable version.
8. Evaluate all bids against the exact same published version.

## Criterion fields

Every criterion must have:
- stable `criterion_id`;
- `name` and human-readable `description`;
- `category`: eligibility / administrative / technical / experience / financial_capacity / declaration / supporting_document / commercial;
- `stage`: pre_check / technical / commercial / final;
- `mandatory`;
- `document_requirements`;
- `field_key`;
- `data_type`;
- `unit` (when applicable);
- `operator`;
- `expected_value` or `threshold`;
- `normalization_policy`;
- `evaluation_date_basis` for validity;
- `source_references` (artifact, page, clause, text quote);
- `interpretation`: explicit / normalized / officer_defined;
- `review_policy`;
- `failure_consequence` as stated by tender, otherwise `OFFICER_DECISION`;
- `scoring` only if tender explicitly defines it;
- `precedence` only if tender states how conflicting documents are resolved.

## Example criterion

```yaml
criterion_id: TECH-CONDUCTOR-AREA-001
name: Conductor cross-sectional area
category: technical
stage: technical
mandatory: true
field_key: conductor_cross_section_area
data_type: decimal
unit: mm2
operator: GTE
expected_value: 484.5
normalization_policy:
  accepted_units: [mm2]
  conversions_allowed: false
source_references:
  - artifact: approved_tender_specification.pdf
    page: 18
    clause: "Technical specification — conductor"
    quote: "..."
interpretation: explicit
review_policy:
  low_confidence: manual_review
  conflicting_values: manual_review
failure_consequence: OFFICER_DECISION
scoring: null
```

This is an illustrative schema example, not a claim that 484.5 mm² is required by any supplied tender. Only populate values from the actual tender.

## Rulebook validation checks

Block approval if:
- mandatory criterion lacks source reference;
- numeric criterion lacks operator, threshold, or unit;
- criterion has a scoring weight not found in tender;
- commercial criterion is assigned to technical stage;
- commercial file access is not gated;
- expiry rule lacks an evaluation date basis;
- document requirement is missing submission channel;
- criterion's failure consequence is not stated and is incorrectly auto-configured as rejection;
- duplicate or contradictory criteria are unresolved;
- amendment supersession is unclear.

## Synonyms and semantic field mapping

Maintain aliases per field:
```yaml
field_key: conductor_material
display_name: Conductor material
aliases:
  - conductor material
  - conductor details
  - conductor-stuff
  - conductor type
```
Aliases are retrieval hints, not proof. The extraction agent must attach evidence and may return `AMBIGUOUS` if a label could refer to another property.

## Document-level and field-level completeness

Track separately:
- required file uploaded?
- expected document class found?
- prescribed form/annexure present?
- required section filled?
- field extracted?
- value valid?
- supporting evidence attached?
- signature/stamp detected where required?
- supporting document cross-check passed?

A document may be present but not duly filled. A field may be present but unreadable. A certificate may exist but be expired or not cover the required scope.

## Rule execution

Rule engine accepts normalized evidence and a published rulebook version. It returns result and explanation. It must be deterministic, unit-tested, and independent of LLM calls.

## No inferred combined score

If tender defines pass/fail technical responsiveness and lowest evaluated commercial offer, show those. Do not invent a weighted technical-commercial score. Combined ranking is disabled until a tender-defined formula is configured and approved.
