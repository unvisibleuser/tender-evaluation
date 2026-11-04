"""Keyword-based page classification against the rulebook's document requirements.

Proposals only; officers may reclassify any page. Unknown pages remain visible (doc_class=None).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.shared.enums import ClassificationMethod

CLASSIFIER_VERSION = "kw-1.0"


@dataclass(frozen=True)
class DocClassSpec:
    doc_class: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PageClassification:
    doc_class: str | None
    method: ClassificationMethod
    confidence: float | None
    matched_keywords: tuple[str, ...]


def classify_page(
    text: str, specs: Sequence[DocClassSpec], previous: PageClassification | None
) -> PageClassification:
    haystack = " ".join(text.lower().split())
    scored: list[tuple[int, str, tuple[str, ...]]] = []
    for spec in specs:
        hits = tuple(k for k in spec.keywords if k.lower() in haystack)
        if hits:
            scored.append((len(hits), spec.doc_class, hits))
    if scored:
        scored.sort(key=lambda s: (-s[0], s[1]))
        best = scored[0]
        tie = len(scored) > 1 and scored[1][0] == best[0]
        if not tie:
            confidence = 0.95 if best[0] >= 2 else 0.8
            return PageClassification(best[1], ClassificationMethod.KEYWORD, confidence, best[2])
        # Tied classes: do not guess.
        return PageClassification(
            None, ClassificationMethod.NONE, None, tuple(k for s in scored[:2] for k in s[2])
        )
    if previous is not None and previous.doc_class is not None:
        return PageClassification(previous.doc_class, ClassificationMethod.CONTINUATION, 0.6, ())
    return PageClassification(None, ClassificationMethod.NONE, None, ())
