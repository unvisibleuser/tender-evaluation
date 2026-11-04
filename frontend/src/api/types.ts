// Types mirror backend Pydantic response models (app/api.py and module schemas).
// Money and exact quantities are transported as strings; never parse them into JS numbers for comparison.

export type Role = "TENDER_ADMIN" | "APPROVER" | "TECHNICAL_EVALUATOR" | "COMMERCIAL_OFFICER" | "AUDITOR";

export type TenderStatus =
  | "DRAFT"
  | "OPEN_FOR_SUBMISSION"
  | "SUBMISSION_CLOSED"
  | "TECHNICAL_EVALUATION"
  | "TECHNICAL_COMPLETED"
  | "COMMERCIAL_OPENED"
  | "COMMERCIAL_EVALUATED"
  | "CANCELLED";

export interface Officer {
  id: string;
  username: string;
  display_name: string;
  designation: string;
  roles: Role[];
}

export interface LoginOut {
  token: string;
  officer: Officer;
  environment: string;
}

export interface Tender {
  id: string;
  reference_no: string;
  title: string;
  description: string;
  authority: string;
  status: TenderStatus;
  timezone: string;
  submission_deadline: string;
  commercial_envelope_required: boolean;
  commercial_evaluation_method: string | null;
  opening_quorum: number;
  pinned_rulebook_version_id: string | null;
  pinned_rulebook_version_no: number | null;
  created_at: string;
  closed_at: string | null;
  row_version: number;
  bid_count: number;
  allowed_actions: string[];
}

export interface PublicTender {
  id: string;
  reference_no: string;
  title: string;
  description: string;
  authority: string;
  timezone: string;
  submission_deadline: string;
  accepting_submissions: boolean;
  commercial_envelope_required: boolean;
  required_documents: { name: string; mandatory: boolean }[];
}

export interface FileReceipt {
  filename: string;
  sha256: string;
  size_bytes: number;
  page_count: number | null;
}

export interface BidReceipt {
  bid_reference: string;
  tender_reference: string;
  tender_title: string;
  bidder_legal_name: string;
  received_at: string;
  technical: FileReceipt;
  commercial: FileReceipt | null;
  commercial_sealed: boolean;
  package_sha256: string;
  notice: string;
}

export interface TenderDocument {
  id: string;
  title: string;
  original_filename: string;
  sha256: string;
  size_bytes: number;
  page_count: number;
  uploaded_at: string;
}

// ---------------------------------------------------------------- rulebook

export type JsonValue = string | number | boolean | null | JsonValue[] | { [k: string]: JsonValue };

export interface FieldDefinition {
  field_key: string;
  label: string;
  data_type: string;
  unit?: string | null;
  aliases: string[];
  doc_classes?: string[];
  critical?: boolean;
}

export interface DocumentRequirement {
  doc_class: string;
  name: string;
  keywords: string[];
  mandatory: boolean;
}

export interface SourceReference {
  artifact_id?: string | null;
  document_title: string;
  page: number;
  clause?: string | null;
  quote?: string | null;
}

export interface Criterion {
  criterion_id: string;
  name: string;
  description?: string;
  category: string;
  stage?: string;
  mandatory: boolean;
  operator: string;
  field_key?: string | null;
  doc_class?: string | null;
  expected?: JsonValue;
  evaluation_date_basis?: string | null;
  basis_fixed_date?: string | null;
  applies_if?: { field_key: string; operator: string; value: JsonValue; if_unknown: string } | null;
  interpretation: string;
  failure_consequence: string;
  source_references: SourceReference[];
  scoring?: null;
}

export interface RulebookContent {
  schema_version: "1.0";
  fields: FieldDefinition[];
  document_requirements: DocumentRequirement[];
  criteria: Criterion[];
}

export interface ValidationIssue {
  code: string;
  severity: "BLOCKING" | "WARNING";
  path: string;
  message: string;
}

export interface RulebookVersion {
  id: string;
  tender_id: string;
  version_no: number;
  status: "DRAFT" | "IN_REVIEW" | "APPROVED" | "SUPERSEDED";
  content: RulebookContent;
  content_hash: string;
  based_on_id: string | null;
  created_by: string;
  created_at: string;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_reason: string | null;
  row_version: number;
  is_pinned: boolean;
  issues: ValidationIssue[];
}

// ---------------------------------------------------------------- bids & evidence

export interface BidSummary {
  id: string;
  tender_id: string;
  bid_reference: string;
  bidder_legal_name: string;
  submitted_at: string;
  processing_status: string;
  processing_error: string | null;
  technical_outcome: string;
  page_count: number;
  open_review_tasks: number;
  withheld_pages: number;
  unreadable_pages: number;
}

export interface Paged<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PageInfo {
  page_no: number;
  width: number;
  height: number;
  text_status: "TEXT_LAYER" | "NO_TEXT_LAYER" | "WITHHELD_COMMERCIAL";
  doc_class: string | null;
  classification_method: string;
  classification_confidence: number | null;
  matched_keywords: string[];
  leakage_indicators: string[];
}

export interface Candidate {
  raw_value: string;
  normalized: string | null;
  unit: string | null;
  page_no: number;
  bbox: number[];
  confidence: number;
  flags: string[];
}

export interface ExtractedField {
  id: string;
  field_key: string;
  label: string;
  data_type: string;
  revision_no: number;
  status: "EXTRACTED" | "MISSING" | "AMBIGUOUS" | "UNREADABLE";
  raw_value: string | null;
  source_line: string | null;
  normalized_value: string | null;
  unit: string | null;
  confidence: number | null;
  method: string;
  page_no: number | null;
  bbox: number[] | null;
  flags: string[];
  candidates: Candidate[];
  review_state: string;
  provenance: string;
  created_at: string;
  created_by_label: string;
  reason: string | null;
}

export interface DocumentPresence {
  doc_class: string;
  name: string;
  mandatory: boolean;
  presence: "FOUND" | "NOT_FOUND" | "UNCERTAIN";
  pages: number[];
}

export interface BidDetail {
  bid: BidSummary;
  bidder_email: string;
  bidder_phone: string;
  technical_sha256: string | null;
  technical_filename: string | null;
  pages: PageInfo[];
  documents: DocumentPresence[];
  fields: ExtractedField[];
}

export interface ReviewTask {
  id: string;
  tender_id: string;
  bid_id: string;
  bid_reference: string;
  bidder_legal_name: string;
  reason: string;
  field_key: string | null;
  page_no: number | null;
  detail: string;
  status: "OPEN" | "RESOLVED";
  created_at: string;
  resolved_at: string | null;
  resolution: string | null;
  resolution_path: string;
}

// ---------------------------------------------------------------- evaluation

export interface CriterionResult {
  criterion_id: string;
  outcome: string;
  mandatory: boolean;
  actual: string | null;
  expected: string | null;
  explanation: string;
  revision_ids: string[];
}

export interface Decision {
  id: string;
  decision: "RESPONSIVE" | "NON_RESPONSIVE";
  reason: string;
  cited_criteria: string[];
  overridden_criteria: string[];
  decided_by_label: string;
  decided_at: string;
  evaluation_run_id: string;
}

export interface BidResults {
  bid_id: string;
  bid_reference: string;
  bidder_legal_name: string;
  technical_outcome: string;
  stale: boolean;
  counts: Record<string, number>;
  results: CriterionResult[];
  decision: Decision | null;
}

export interface CriterionHeader {
  criterion_id: string;
  name: string;
  category: string;
  mandatory: boolean;
  operator: string;
  source: string;
}

export interface EvaluationRun {
  id: string;
  tender_id: string;
  rulebook_version_id: string;
  rulebook_content_hash: string;
  engine_version: string;
  input_hash: string;
  result_hash: string;
  bid_count: number;
  created_at: string;
  started_by_label: string;
  is_latest: boolean;
  criteria: CriterionHeader[];
  bids: BidResults[];
}

export interface RunSummary {
  id: string;
  created_at: string;
  result_hash: string;
  bid_count: number;
  started_by_label: string;
}

// ---------------------------------------------------------------- commercial

export interface CommercialStatus {
  tender_status: TenderStatus;
  sealed: boolean;
  envelopes_received: number;
  eligible_bids: number;
  quorum: number;
  authorizations: { officer_id: string; officer_label: string; created_at: string; reason: string }[];
  can_authorize: boolean;
  can_open: boolean;
  opened_at: string | null;
  opened_by: string | null;
  evaluation_method: string | null;
}

export interface Offer {
  bid_id: string;
  bid_reference: string;
  bidder_legal_name: string;
  quoted_total: string;
  currency: string;
  source: string;
}

export interface Ranking {
  id: string;
  method: string;
  method_label: string;
  created_at: string;
  rows: {
    rank: number;
    bid_id: string;
    bid_reference: string;
    bidder_legal_name: string;
    quoted_total: string;
    currency: string;
    tie: boolean;
  }[];
  notes: string[];
}

// ---------------------------------------------------------------- audit

export interface AuditEvent {
  id: string;
  created_at: string;
  actor_kind: string;
  actor_label: string;
  actor_roles: string[];
  action: string;
  object_type: string;
  object_id: string | null;
  bid_id: string | null;
  reason: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  hash: string;
}
