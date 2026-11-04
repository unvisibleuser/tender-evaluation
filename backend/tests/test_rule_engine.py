"""Unit tests for every deterministic operator and boundary. No database, no I/O."""

from __future__ import annotations

from datetime import date

import pytest

from rule_engine import (
    BidEvidence,
    Condition,
    DataType,
    DocumentEvidence,
    DocumentPresence,
    EvidenceStatus,
    FieldEvidence,
    Operator,
    RuleOutcome,
    RuleSpec,
    UnknownApplicability,
    evaluate_criterion,
    results_hash,
)


def ev(value: str | None, status: EvidenceStatus = EvidenceStatus.AVAILABLE, key: str = "f") -> BidEvidence:
    return BidEvidence(
        fields={key: FieldEvidence(field_key=key, status=status, value=value, revision_id="r1")}
    )


def spec(op: Operator, dt: DataType, expected: object = None, **kw: object) -> RuleSpec:
    return RuleSpec(
        criterion_id="C1",
        name="c",
        operator=op,
        mandatory=True,
        field_key="f",
        data_type=dt,
        expected=expected,
        **kw,
    )  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("op", "actual", "expected", "outcome"),
    [
        (Operator.GTE, "50000000", "50000000", RuleOutcome.PASS),  # boundary equal
        (Operator.GTE, "49999999.99", "50000000", RuleOutcome.FAIL),
        (Operator.GT, "50000000", "50000000", RuleOutcome.FAIL),
        (Operator.GT, "50000000.01", "50000000", RuleOutcome.PASS),
        (Operator.LTE, "10", "10", RuleOutcome.PASS),
        (Operator.LT, "10", "10", RuleOutcome.FAIL),
        (Operator.EQ, "11", "11.0", RuleOutcome.PASS),  # Decimal equality, not string
        (Operator.NEQ, "11", "33", RuleOutcome.PASS),
        (Operator.BETWEEN, "300", ["300", "400"], RuleOutcome.PASS),
        (Operator.BETWEEN, "400.0001", ["300", "400"], RuleOutcome.FAIL),
    ],
)
def test_numeric_operators(op: Operator, actual: str, expected: object, outcome: RuleOutcome) -> None:
    assert evaluate_criterion(spec(op, DataType.DECIMAL, expected), ev(actual)).outcome is outcome


def test_money_uses_exact_decimal() -> None:
    # 0.1 + 0.2 style float error must not occur
    r = evaluate_criterion(spec(Operator.EQ, DataType.MONEY, "0.3"), ev("0.30"))
    assert r.outcome is RuleOutcome.PASS


def test_float_threshold_is_configuration_error() -> None:
    r = evaluate_criterion(spec(Operator.GTE, DataType.MONEY, 0.3), ev("1"))
    assert r.outcome is RuleOutcome.NOT_EVALUATED


@pytest.mark.parametrize(
    ("op", "actual", "expected", "outcome"),
    [
        (Operator.IN, "ALUMINIUM", ["Aluminium", "Copper"], RuleOutcome.PASS),  # case-insensitive
        (Operator.IN, "Steel", ["Aluminium"], RuleOutcome.FAIL),
        (Operator.NOT_IN, "Steel", ["Aluminium"], RuleOutcome.PASS),
        (Operator.CONTAINS, "XLPE insulated cable", "xlpe", RuleOutcome.PASS),
        (Operator.EQ, "  Aluminium   ", "aluminium", RuleOutcome.PASS),
    ],
)
def test_string_operators(op: Operator, actual: str, expected: object, outcome: RuleOutcome) -> None:
    assert evaluate_criterion(spec(op, DataType.STRING, expected), ev(actual)).outcome is outcome


@pytest.mark.parametrize(
    ("op", "actual", "basis", "outcome"),
    [
        (Operator.DATE_VALID_ON, "2026-12-01", date(2026, 12, 1), RuleOutcome.PASS),  # valid on the day
        (Operator.DATE_VALID_ON, "2026-11-30", date(2026, 12, 1), RuleOutcome.FAIL),
        (Operator.DATE_NOT_AFTER, "2026-12-01", date(2026, 12, 1), RuleOutcome.PASS),
        (Operator.DATE_NOT_AFTER, "2026-12-02", date(2026, 12, 1), RuleOutcome.FAIL),
    ],
)
def test_date_basis_operators(op: Operator, actual: str, basis: date, outcome: RuleOutcome) -> None:
    assert evaluate_criterion(spec(op, DataType.DATE, basis_date=basis), ev(actual)).outcome is outcome


def test_date_basis_missing_is_not_evaluated() -> None:
    r = evaluate_criterion(spec(Operator.DATE_VALID_ON, DataType.DATE), ev("2027-01-01"))
    assert r.outcome is RuleOutcome.NOT_EVALUATED


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (EvidenceStatus.MISSING, RuleOutcome.MISSING),
        (EvidenceStatus.UNREADABLE, RuleOutcome.UNREADABLE),
        (EvidenceStatus.AMBIGUOUS, RuleOutcome.AMBIGUOUS),
        (EvidenceStatus.PENDING_REVIEW, RuleOutcome.PENDING_REVIEW),
    ],
)
def test_unknown_is_never_fail(status: EvidenceStatus, outcome: RuleOutcome) -> None:
    r = evaluate_criterion(spec(Operator.GTE, DataType.MONEY, "1"), ev(None, status))
    assert r.outcome is outcome
    assert r.outcome is not RuleOutcome.FAIL


def test_absent_field_is_missing_not_fail() -> None:
    r = evaluate_criterion(spec(Operator.GTE, DataType.MONEY, "1"), BidEvidence())
    assert r.outcome is RuleOutcome.MISSING


def test_unparseable_available_value_is_ambiguous() -> None:
    r = evaluate_criterion(spec(Operator.GTE, DataType.MONEY, "1"), ev("about five crore"))
    assert r.outcome is RuleOutcome.AMBIGUOUS


@pytest.mark.parametrize(
    ("presence", "outcome"),
    [
        (DocumentPresence.FOUND, RuleOutcome.PASS),
        (DocumentPresence.NOT_FOUND, RuleOutcome.MISSING),
        (DocumentPresence.UNCERTAIN, RuleOutcome.PENDING_REVIEW),
    ],
)
def test_document_present(presence: DocumentPresence, outcome: RuleOutcome) -> None:
    s = RuleSpec(
        criterion_id="D", name="d", operator=Operator.DOCUMENT_PRESENT, mandatory=True, doc_class="pan"
    )
    e = BidEvidence(documents={"pan": DocumentEvidence(doc_class="pan", presence=presence, pages=(2,))})
    assert evaluate_criterion(s, e).outcome is outcome


def test_manual_review_never_auto_decides() -> None:
    s = RuleSpec(criterion_id="M", name="m", operator=Operator.MANUAL_REVIEW_REQUIRED, mandatory=True)
    assert evaluate_criterion(s, BidEvidence()).outcome is RuleOutcome.PENDING_OFFICER_DECISION


def _emd(
    msme: FieldEvidence | None, policy: UnknownApplicability = UnknownApplicability.REVIEW
) -> RuleOutcome:
    s = spec(
        Operator.GTE,
        DataType.MONEY,
        "200000",
        applies_if=Condition(
            field_key="msme", data_type=DataType.BOOLEAN, operator=Operator.EQ, value=False, if_unknown=policy
        ),
    )
    fields = {
        "f": FieldEvidence(field_key="f", status=EvidenceStatus.AVAILABLE, value="200000", revision_id="r")
    }
    if msme:
        fields["msme"] = msme
    return evaluate_criterion(s, BidEvidence(fields=fields)).outcome


def test_applicability() -> None:
    yes = FieldEvidence(field_key="msme", status=EvidenceStatus.AVAILABLE, value="true")
    no = FieldEvidence(field_key="msme", status=EvidenceStatus.AVAILABLE, value="false")
    assert _emd(yes) is RuleOutcome.NOT_APPLICABLE
    assert _emd(no) is RuleOutcome.PASS
    assert _emd(None) is RuleOutcome.PENDING_REVIEW
    assert _emd(None, UnknownApplicability.APPLIES) is RuleOutcome.PASS
    assert _emd(None, UnknownApplicability.NOT_APPLICABLE) is RuleOutcome.NOT_APPLICABLE


def test_ordered_operator_on_string_is_config_error() -> None:
    assert (
        evaluate_criterion(spec(Operator.GT, DataType.STRING, "a"), ev("b")).outcome
        is RuleOutcome.NOT_EVALUATED
    )


def test_deterministic_hash() -> None:
    s = [spec(Operator.GTE, DataType.MONEY, "5")]
    e = ev("6")
    r1 = {"bidA": [evaluate_criterion(x, e) for x in s]}
    r2 = {"bidA": [evaluate_criterion(x, e) for x in s]}
    assert results_hash("rb", r1) == results_hash("rb", r2)
    assert results_hash("rb", r1) != results_hash("rb2", r1)


def test_rule_engine_is_pure() -> None:
    import ast
    import pathlib

    forbidden = {"app", "sqlalchemy", "fastapi", "httpx", "requests", "pymupdf", "anthropic", "openai"}
    for path in pathlib.Path(__file__).parents[1].joinpath("rule_engine").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            else:
                continue
            assert not forbidden.intersection(names), f"{path.name} imports {names}"
