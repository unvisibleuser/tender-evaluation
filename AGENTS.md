# AGENTS.md — Agent catalogue and contracts

Agents are bounded assistants. They do not own workflow state and do not make procurement decisions.

## 1. Rulebook Drafting Agent
**Purpose:** Convert tender declaration and related tender files into a draft structured rulebook.

Inputs:
- tender document manifest;
- extracted text/page references;
- authority-provided tender metadata;
- document taxonomy and rulebook schema.

Outputs:
- required documents and submission channels;
- criteria, fields, units, operators, thresholds, scope;
- source clause/page citations;
- dependencies and cross-document links;
- unresolved questions and contradictions;
- proposed workflow configuration.

Must:
- quote or cite source page/section for each proposed criterion;
- distinguish explicit tender language from inferred mapping;
- mark ambiguous rules `NEEDS_OFFICER_INPUT`;
- never invent thresholds, scoring weights, validity periods, or missing documents;
- flag technical/commercial content and potential commercial leakage.

Cannot:
- approve or publish rulebooks;
- create criteria without source support;
- change tender deadlines or corrigenda state.

## 2. Document Classification Agent
**Purpose:** Propose document type for each uploaded file/page group.

Outputs:
- document class;
- bidder identity candidates;
- page ranges;
- confidence;
- alternative classes and reasons.

Low confidence => human review. Classification must not hide or discard unknown files.

## 3. Field Extraction Agent
**Purpose:** Extract only fields defined in the approved document schema.

Inputs:
- page image/text;
- document class;
- field definitions and synonyms;
- relevant tender context;
- allowed unit conversions.

Outputs per field:
- raw value;
- normalized value;
- unit;
- evidence page and bounding box/text span;
- confidence;
- extraction method (`PDF_TEXT`, `OCR`, `VISION`, `HUMAN`);
- ambiguity/conflict flags;
- explanation.

Must preserve exact raw wording. It may map labels such as "conductor details" to a configured canonical field like `conductor_material` only when evidence supports the mapping. Semantic equivalence must not be guessed when it changes compliance.

## 4. Supporting Document Validation Agent
**Purpose:** Extract identity, issuer, issue date, expiry date, certificate number, scope, holder, and validity details from supporting certificates.

Must compare:
- certificate holder vs bidder legal identity;
- scope/product/item vs tender requirement;
- issue/expiry dates vs relevant evaluation date;
- issuer requirements vs allowed issuers;
- document authenticity metadata where available.

It cannot declare a certificate authentic solely from appearance. External verification requires an authorized integration or officer process.

## 5. OCR Triage Agent
**Purpose:** Identify pages/regions needing OCR or manual transcription.

Route to human if:
- handwriting is material and unreliable;
- OCR confidence below configured threshold;
- stamp/signature obscures content;
- table structure is ambiguous;
- page is skewed, blurred, cropped, or damaged;
- multiple readings could change compliance.

## 6. Evidence Reconciliation Agent
**Purpose:** Find conflicts between fields across documents (e.g. legal name, certificate number, capacity, dates).

Output conflicts with all source references. It must not silently choose one value. Rulebook defines precedence where tender states it; otherwise officer resolves.

## 7. Evaluation Explanation Agent
**Purpose:** Turn deterministic rule results into concise officer-readable explanations.

Input is the rule engine result, evidence, and clause references. It cannot change result status or score.

## 8. Commercial Extraction Agent
**Purpose:** Process commercial documents only after the authorized opening event and only for roles/workers permitted by the commercial access policy.

It must never be invoked during the technical-only stage.

## Agent common protocol

All agents return JSON matching Pydantic schemas. Common metadata:
- `task_id`
- `tender_id`
- `bidder_id` (when applicable)
- `artifact_id`
- `rulebook_version`
- `agent_name`
- `agent_version`
- `model_provider`
- `model_name`
- `prompt_version`
- `created_at`
- `warnings`

Agent output is a proposal. The application validates it, persists a revision, and records an audit event. Agents have no direct database credentials and no arbitrary network access.
