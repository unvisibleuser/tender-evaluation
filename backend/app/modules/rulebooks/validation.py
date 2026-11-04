"""Rulebook completeness checks. Any BLOCKING issue prevents submission/approval."""

from __future__ import annotations

from app.modules.rulebooks.schemas import (
    DateBasis,
    FailureConsequence,
    Interpretation,
    RulebookContent,
    ValidationIssue,
)
from rule_engine import DataType, Operator
from rule_engine.models import COMPARISON_OPERATORS, DATE_BASIS_OPERATORS, ORDERED_OPERATORS
from rule_engine.values import ValueError_, parse_canonical

_NUMERIC = {DataType.INTEGER, DataType.DECIMAL, DataType.MONEY}


def _check_expected(op: Operator, dt: DataType, expected: object) -> str | None:
    try:
        if op is Operator.BETWEEN:
            if not isinstance(expected, list) or len(expected) != 2:
                return "BETWEEN requires a two-item list [low, high]"
            low, high = (parse_canonical(v, dt) for v in expected)
            if low > high:  # type: ignore[operator]
                return "BETWEEN low bound exceeds high bound"
        elif op in (Operator.IN, Operator.NOT_IN):
            if not isinstance(expected, list) or not expected:
                return f"{op} requires a non-empty list"
            for v in expected:
                parse_canonical(v, dt)
        else:
            parse_canonical(expected, dt)
    except ValueError_ as exc:
        return f"expected value invalid for {dt}: {exc}"
    return None


def validate_rulebook(content: RulebookContent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str, severity: str = "BLOCKING") -> None:
        issues.append(ValidationIssue(code=code, severity=severity, path=path, message=message))

    fields = content.field_map()
    doc_classes = {d.doc_class for d in content.document_requirements}

    seen: set[str] = set()
    for i, f in enumerate(content.fields):
        if f.field_key in seen:
            add("DUPLICATE_FIELD", f"fields[{i}]", f"Duplicate field_key '{f.field_key}'")
        seen.add(f.field_key)
        for dc in f.doc_classes:
            if dc not in doc_classes:
                add("UNKNOWN_DOC_CLASS", f"fields[{i}].doc_classes", f"Unknown document class '{dc}'")
        if f.data_type in (DataType.INTEGER, DataType.DECIMAL) and not f.unit:
            add(
                "UNIT_NOT_SPECIFIED",
                f"fields[{i}].unit",
                f"Numeric field '{f.field_key}' has no unit; confirm it is dimensionless",
                "WARNING",
            )

    seen = set()
    for i, d in enumerate(content.document_requirements):
        if d.doc_class in seen:
            add("DUPLICATE_DOC_CLASS", f"document_requirements[{i}]", f"Duplicate doc_class '{d.doc_class}'")
        seen.add(d.doc_class)

    if not content.criteria:
        add("NO_CRITERIA", "criteria", "Rulebook has no criteria")

    seen = set()
    for i, c in enumerate(content.criteria):
        p = f"criteria[{i}]"
        if c.criterion_id in seen:
            add("DUPLICATE_CRITERION", p, f"Duplicate criterion_id '{c.criterion_id}'")
        seen.add(c.criterion_id)

        if c.interpretation is Interpretation.UNRESOLVED:
            add(
                "NEEDS_OFFICER_INPUT", p, f"{c.criterion_id}: interpretation unresolved; officer input needed"
            )
        if c.mandatory and not c.source_references:
            add("MISSING_SOURCE_REFERENCE", p, f"{c.criterion_id}: mandatory criterion lacks a tender source")
        if c.failure_consequence is FailureConsequence.TENDER_STATED_REJECTION and not any(
            s.quote for s in c.source_references
        ):
            add(
                "REJECTION_NOT_QUOTED",
                p,
                f"{c.criterion_id}: rejection consequence must quote the tender clause stating it",
            )

        if c.applies_if is not None:
            af = fields.get(c.applies_if.field_key)
            if af is None:
                add(
                    "UNKNOWN_FIELD",
                    f"{p}.applies_if",
                    f"Unknown applicability field '{c.applies_if.field_key}'",
                )
            elif c.applies_if.operator not in COMPARISON_OPERATORS:
                add("INVALID_OPERATOR", f"{p}.applies_if", "Applicability must use a comparison operator")
            elif err := _check_expected(c.applies_if.operator, af.data_type, c.applies_if.value):
                add("INVALID_EXPECTED", f"{p}.applies_if", err)

        op = c.operator
        if op is Operator.MANUAL_REVIEW_REQUIRED:
            continue
        if op is Operator.DOCUMENT_PRESENT:
            if not c.doc_class:
                add("MISSING_DOC_CLASS", p, f"{c.criterion_id}: DOCUMENT_PRESENT requires doc_class")
            elif c.doc_class not in doc_classes:
                add("UNKNOWN_DOC_CLASS", p, f"{c.criterion_id}: unknown doc_class '{c.doc_class}'")
            continue

        if not c.field_key:
            add("MISSING_FIELD", p, f"{c.criterion_id}: {op} requires field_key")
            continue
        fd = fields.get(c.field_key)
        if fd is None:
            add("UNKNOWN_FIELD", p, f"{c.criterion_id}: unknown field '{c.field_key}'")
            continue
        dt = fd.data_type

        if op in DATE_BASIS_OPERATORS:
            if dt is not DataType.DATE:
                add("TYPE_MISMATCH", p, f"{c.criterion_id}: {op} requires a date field")
            if c.evaluation_date_basis is None:
                add("MISSING_DATE_BASIS", p, f"{c.criterion_id}: validity rule lacks evaluation_date_basis")
            elif c.evaluation_date_basis is DateBasis.FIXED_DATE and c.basis_fixed_date is None:
                add("MISSING_DATE_BASIS", p, f"{c.criterion_id}: FIXED_DATE basis requires basis_fixed_date")
            continue

        if op in ORDERED_OPERATORS and dt not in _NUMERIC | {DataType.DATE}:
            add("TYPE_MISMATCH", p, f"{c.criterion_id}: {op} requires a numeric or date field")
        elif op is Operator.CONTAINS and dt is not DataType.STRING:
            add("TYPE_MISMATCH", p, f"{c.criterion_id}: CONTAINS requires a string field")
        elif c.expected is None:
            add("MISSING_THRESHOLD", p, f"{c.criterion_id}: {op} requires an expected value/threshold")
        elif err := _check_expected(op, dt, c.expected):
            add("INVALID_EXPECTED", p, f"{c.criterion_id}: {err}")
        if dt in (DataType.INTEGER, DataType.DECIMAL) and not fd.unit:
            add(
                "UNIT_NOT_SPECIFIED", p, f"{c.criterion_id}: numeric criterion lacks unit on field", "WARNING"
            )
    return issues


def has_blocking(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == "BLOCKING" for i in issues)
