"""Deterministic criterion evaluation.

Principles enforced here:
- Unknown is not fail: MISSING / UNREADABLE / AMBIGUOUS / PENDING_REVIEW evidence is never turned into FAIL.
- FAIL is only produced by a successful comparison that evaluates to false.
- Configuration errors yield NOT_EVALUATED with an explanation, never PASS/FAIL.
- No I/O, no randomness, no LLM calls.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from .models import (
    COMPARISON_OPERATORS,
    DATE_BASIS_OPERATORS,
    ENGINE_VERSION,
    ORDERED_OPERATORS,
    BidEvidence,
    Condition,
    CriterionEvaluation,
    DataType,
    DocumentPresence,
    EvidenceStatus,
    FieldEvidence,
    Operator,
    RuleOutcome,
    RuleSpec,
    UnknownApplicability,
)
from .values import Comparable, ValueError_, display, parse_canonical

_EVIDENCE_TO_OUTCOME = {
    EvidenceStatus.MISSING: RuleOutcome.MISSING,
    EvidenceStatus.UNREADABLE: RuleOutcome.UNREADABLE,
    EvidenceStatus.AMBIGUOUS: RuleOutcome.AMBIGUOUS,
    EvidenceStatus.PENDING_REVIEW: RuleOutcome.PENDING_REVIEW,
}


class _ConfigError(Exception):
    pass


def _as_list(expected: object, n: int | None = None) -> list[object]:
    if not isinstance(expected, list):
        raise _ConfigError("expected value must be a list for this operator")
    if n is not None and len(expected) != n:
        raise _ConfigError(f"expected value must contain exactly {n} items")
    if not expected:
        raise _ConfigError("expected list must not be empty")
    return list(expected)


def _parse_expected(expected: object, data_type: DataType) -> Comparable:
    try:
        return parse_canonical(expected, data_type)
    except ValueError_ as exc:
        raise _ConfigError(f"expected value invalid: {exc}") from exc


def compare(operator: Operator, actual: Comparable, expected: object, data_type: DataType) -> bool:
    """Pure comparison. Raises _ConfigError on invalid configuration."""
    if operator in ORDERED_OPERATORS and data_type in (DataType.STRING, DataType.BOOLEAN):
        raise _ConfigError(f"{operator} is not valid for {data_type} values")
    if operator is Operator.BETWEEN:
        low, high = (_parse_expected(v, data_type) for v in _as_list(expected, 2))
        return bool(low <= actual <= high)  # type: ignore[operator]
    if operator in (Operator.IN, Operator.NOT_IN):
        options = [_parse_expected(v, data_type) for v in _as_list(expected)]
        hit = actual in options
        return hit if operator is Operator.IN else not hit
    if operator is Operator.CONTAINS:
        if data_type is not DataType.STRING:
            raise _ConfigError("CONTAINS is only valid for string values")
        needle = _parse_expected(expected, data_type)
        return str(needle) in str(actual)
    target = _parse_expected(expected, data_type)
    match operator:
        case Operator.EQ:
            return actual == target
        case Operator.NEQ:
            return actual != target
        case Operator.GT:
            return bool(actual > target)  # type: ignore[operator]
        case Operator.GTE:
            return bool(actual >= target)  # type: ignore[operator]
        case Operator.LT:
            return bool(actual < target)  # type: ignore[operator]
        case Operator.LTE:
            return bool(actual <= target)  # type: ignore[operator]
    raise _ConfigError(f"operator {operator} is not a comparison operator")


def _expected_text(spec: RuleSpec) -> str | None:
    if spec.operator in DATE_BASIS_OPERATORS:
        return f"{spec.operator} {spec.basis_date.isoformat() if spec.basis_date else '<no basis date>'}"
    if spec.operator is Operator.DOCUMENT_PRESENT:
        return f"document '{spec.doc_class}' present"
    if spec.operator is Operator.MANUAL_REVIEW_REQUIRED:
        return "officer judgement"
    return f"{spec.operator} {display(spec.expected)}"


def _check_applicability(
    condition: Condition, fields: Mapping[str, FieldEvidence]
) -> tuple[bool | None, str, tuple[str, ...]]:
    """Returns (applies, explanation, revision_ids). applies=None means undetermined -> review."""
    evidence = fields.get(condition.field_key)
    revs = (evidence.revision_id,) if evidence and evidence.revision_id else ()
    if evidence is None or evidence.status is not EvidenceStatus.AVAILABLE:
        status = evidence.status if evidence else EvidenceStatus.MISSING
        msg = f"applicability input '{condition.field_key}' is {status}"
        match condition.if_unknown:
            case UnknownApplicability.APPLIES:
                return True, msg + "; officer-configured policy: criterion applies", revs
            case UnknownApplicability.NOT_APPLICABLE:
                return False, msg + "; officer-configured policy: criterion not applicable", revs
            case _:
                return None, msg + "; officer review required", revs
    try:
        actual = parse_canonical(evidence.value, condition.data_type)
        applies = compare(condition.operator, actual, condition.value, condition.data_type)
    except (ValueError_, _ConfigError) as exc:
        return None, f"applicability could not be computed: {exc}", revs
    return (
        applies,
        f"applicability: {condition.field_key}={display(actual)} {condition.operator} "
        f"{display(condition.value)} is {applies}",
        revs,
    )


def evaluate_criterion(spec: RuleSpec, evidence: BidEvidence) -> CriterionEvaluation:
    def result(
        outcome: RuleOutcome, explanation: str, actual: str | None = None, revs: Iterable[str] = ()
    ) -> CriterionEvaluation:
        return CriterionEvaluation(
            criterion_id=spec.criterion_id,
            outcome=outcome,
            mandatory=spec.mandatory,
            actual=actual,
            expected=_expected_text(spec),
            explanation=explanation,
            revision_ids=tuple(sorted(set(revs))),
        )

    prefix = ""
    applicability_revs: tuple[str, ...] = ()
    if spec.applies_if is not None:
        applies, why, applicability_revs = _check_applicability(spec.applies_if, evidence.fields)
        if applies is None:
            return result(RuleOutcome.PENDING_REVIEW, why, revs=applicability_revs)
        if not applies:
            return result(RuleOutcome.NOT_APPLICABLE, why, revs=applicability_revs)
        prefix = why + ". "

    if spec.operator is Operator.MANUAL_REVIEW_REQUIRED:
        return result(
            RuleOutcome.PENDING_OFFICER_DECISION,
            prefix + "Criterion requires officer judgement; no automated outcome.",
            revs=applicability_revs,
        )

    if spec.operator is Operator.DOCUMENT_PRESENT:
        if not spec.doc_class:
            return result(RuleOutcome.NOT_EVALUATED, prefix + "Configuration error: doc_class not set.")
        doc = evidence.documents.get(spec.doc_class)
        presence = doc.presence if doc else DocumentPresence.NOT_FOUND
        pages = ", ".join(str(p) for p in doc.pages) if doc and doc.pages else ""
        if presence is DocumentPresence.FOUND:
            return result(
                RuleOutcome.PASS,
                prefix + f"Document '{spec.doc_class}' identified on page(s) {pages}.",
                actual=f"found on page(s) {pages}",
                revs=applicability_revs,
            )
        if presence is DocumentPresence.UNCERTAIN:
            return result(
                RuleOutcome.PENDING_REVIEW,
                prefix + f"Document '{spec.doc_class}' not identified, but unreadable/withheld pages exist; "
                "officer review required.",
                revs=applicability_revs,
            )
        return result(
            RuleOutcome.MISSING,
            prefix + f"Document '{spec.doc_class}' was not identified in the submission.",
            revs=applicability_revs,
        )

    # field-based operators
    if not spec.field_key or spec.data_type is None:
        return result(RuleOutcome.NOT_EVALUATED, prefix + "Configuration error: field_key/data_type not set.")
    field = evidence.fields.get(spec.field_key)
    revs = tuple(applicability_revs) + ((field.revision_id,) if field and field.revision_id else ())
    if field is None:
        return result(
            RuleOutcome.MISSING, prefix + f"No extraction exists for field '{spec.field_key}'.", revs=revs
        )
    if field.status is not EvidenceStatus.AVAILABLE:
        return result(
            _EVIDENCE_TO_OUTCOME[field.status],
            prefix + f"Field '{spec.field_key}' evidence status is {field.status}; not compared.",
            revs=revs,
        )
    try:
        actual = parse_canonical(field.value, spec.data_type)
    except ValueError_ as exc:
        return result(
            RuleOutcome.AMBIGUOUS,
            prefix + f"Field value could not be interpreted as {spec.data_type}: {exc}",
            actual=field.value,
            revs=revs,
        )
    actual_text = display(actual)

    try:
        if spec.operator in DATE_BASIS_OPERATORS:
            if spec.data_type is not DataType.DATE or spec.basis_date is None:
                raise _ConfigError("date-basis operator requires a date field and a resolved basis date")
            assert isinstance(actual, date)
            ok = (
                actual >= spec.basis_date
                if spec.operator is Operator.DATE_VALID_ON
                else actual <= spec.basis_date
            )
        elif spec.operator in COMPARISON_OPERATORS:
            ok = compare(spec.operator, actual, spec.expected, spec.data_type)
        else:
            raise _ConfigError(f"unsupported operator {spec.operator}")
    except _ConfigError as exc:
        return result(RuleOutcome.NOT_EVALUATED, prefix + f"Configuration error: {exc}", actual_text, revs)

    verdict = "satisfied" if ok else "not satisfied"
    return result(
        RuleOutcome.PASS if ok else RuleOutcome.FAIL,
        prefix + f"{spec.field_key} = {actual_text}; requirement {_expected_text(spec)} is {verdict}.",
        actual_text,
        revs,
    )


def evaluate(specs: Sequence[RuleSpec], evidence: BidEvidence) -> list[CriterionEvaluation]:
    return [evaluate_criterion(spec, evidence) for spec in specs]


def canonical_hash(payload: object) -> str:
    def default(o: object) -> str:
        if isinstance(o, Decimal):
            return format(o, "f")
        if isinstance(o, date):
            return o.isoformat()
        raise TypeError(type(o).__name__)

    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=default, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def results_hash(rulebook_hash: str, per_bid: Mapping[str, Sequence[CriterionEvaluation]]) -> str:
    """Hash over rulebook + engine version + every outcome. Same inputs => same hash."""
    payload = {
        "engine_version": ENGINE_VERSION,
        "rulebook_hash": rulebook_hash,
        "results": {
            bid: [[r.criterion_id, r.outcome.value, r.actual, list(r.revision_ids)] for r in rs]
            for bid, rs in sorted(per_bid.items())
        },
    }
    return canonical_hash(payload)
