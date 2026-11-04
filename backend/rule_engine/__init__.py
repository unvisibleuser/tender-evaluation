"""Deterministic, pure tender rule engine. Must never import app, database, network or LLM code."""

from .engine import canonical_hash, evaluate, evaluate_criterion, results_hash
from .models import (
    ENGINE_VERSION,
    BidEvidence,
    Condition,
    CriterionEvaluation,
    DataType,
    DocumentEvidence,
    DocumentPresence,
    EvidenceStatus,
    FieldEvidence,
    Operator,
    RuleOutcome,
    RuleSpec,
    UnknownApplicability,
)

__all__ = [
    "ENGINE_VERSION",
    "BidEvidence",
    "Condition",
    "CriterionEvaluation",
    "DataType",
    "DocumentEvidence",
    "DocumentPresence",
    "EvidenceStatus",
    "FieldEvidence",
    "Operator",
    "RuleOutcome",
    "RuleSpec",
    "UnknownApplicability",
    "canonical_hash",
    "evaluate",
    "evaluate_criterion",
    "results_hash",
]
