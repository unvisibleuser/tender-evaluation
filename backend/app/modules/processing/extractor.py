"""Deterministic label/value field extraction with page + bounding-box evidence.

Searches configured aliases ("retrieval hints, not proof") on the pages in scope. Distinct values
are never silently reconciled: more than one distinct normalised value => AMBIGUOUS.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.modules.processing.normalize import REVIEW_FLAGS, normalize
from app.modules.processing.pdf import PdfLine
from app.shared.enums import FieldStatus
from rule_engine import DataType

EXTRACTOR_VERSION = "label-1.0"

_SEPARATORS = " \t:-–—=|."


@dataclass(frozen=True)
class PageView:
    page_no: int
    lines: tuple[PdfLine, ...]
    doc_class: str | None


@dataclass(frozen=True)
class FieldSpec:
    field_key: str
    data_type: DataType
    unit: str | None
    aliases: tuple[str, ...]
    doc_classes: tuple[str, ...]


@dataclass
class Candidate:
    raw_value: str
    source_line: str
    normalized: str | None
    unit: str | None
    page_no: int
    bbox: list[float]
    confidence: float
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_value": self.raw_value,
            "normalized": self.normalized,
            "unit": self.unit,
            "page_no": self.page_no,
            "bbox": self.bbox,
            "confidence": self.confidence,
            "flags": self.flags,
        }


@dataclass
class FieldExtraction:
    field_key: str
    status: FieldStatus
    chosen: Candidate | None
    candidates: list[Candidate]
    flags: list[str]


def _alias_pattern(alias: str) -> re.Pattern[str]:
    words = [re.escape(w) for w in alias.lower().split()]
    return re.compile(r"(?<![a-z0-9])" + r"[\s\-_]*".join(words) + r"(?![a-z0-9])", re.IGNORECASE)


def _union(a: tuple[float, ...], b: tuple[float, ...]) -> list[float]:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _find_on_page(spec: FieldSpec, page: PageView, patterns: list[re.Pattern[str]]) -> list[Candidate]:
    found: list[Candidate] = []
    for idx, line in enumerate(page.lines):
        best: re.Match[str] | None = None
        for pat in patterns:
            m = pat.search(line.text)
            if m and (best is None or len(m.group(0)) > len(best.group(0))):
                best = m
        if best is None:
            continue
        value_text = line.text[best.end() :].strip(_SEPARATORS + " ")
        bbox = list(line.bbox)
        confidence = 0.97
        extra_flags: list[str] = []
        if not value_text and idx + 1 < len(page.lines):
            nxt = page.lines[idx + 1]
            value_text = nxt.text.strip()
            bbox = _union(line.bbox, nxt.bbox)
            confidence = 0.85
            extra_flags.append("VALUE_ON_NEXT_LINE")
        if not value_text:
            continue
        norm = normalize(value_text, spec.data_type, spec.unit)
        flags = [*extra_flags, *norm.flags]
        if norm.value is None:
            confidence = 0.3
        elif any(f in REVIEW_FLAGS for f in flags):
            confidence = min(confidence, 0.85)
        found.append(
            Candidate(
                raw_value=value_text,
                source_line=line.text,
                normalized=norm.value,
                unit=norm.unit,
                page_no=page.page_no,
                bbox=[round(v, 2) for v in bbox],
                confidence=confidence,
                flags=flags,
            )
        )
    return found


def extract_field(
    spec: FieldSpec, pages: Sequence[PageView], *, unreadable_in_scope: bool
) -> FieldExtraction:
    patterns = [_alias_pattern(a) for a in spec.aliases if a.strip()]
    scope = [p for p in pages if not spec.doc_classes or p.doc_class in spec.doc_classes]
    candidates: list[Candidate] = []
    for page in scope:
        candidates.extend(_find_on_page(spec, page, patterns))

    parsed = [c for c in candidates if c.normalized is not None]
    if not candidates:
        if unreadable_in_scope:
            return FieldExtraction(
                spec.field_key, FieldStatus.UNREADABLE, None, [], ["UNREADABLE_PAGES_IN_SCOPE"]
            )
        return FieldExtraction(spec.field_key, FieldStatus.MISSING, None, [], [])
    if not parsed:
        best = max(candidates, key=lambda c: c.confidence)
        return FieldExtraction(spec.field_key, FieldStatus.AMBIGUOUS, best, candidates, ["VALUE_UNPARSEABLE"])

    distinct = {c.normalized for c in parsed}
    if spec.data_type is DataType.STRING:
        distinct = {" ".join(str(v).split()).casefold() for v in distinct}
    if len(distinct) > 1:
        best = max(parsed, key=lambda c: c.confidence)
        return FieldExtraction(spec.field_key, FieldStatus.AMBIGUOUS, best, parsed, ["CONFLICTING_VALUES"])

    best = max(parsed, key=lambda c: (c.confidence, -c.page_no))
    flags = list(best.flags)
    if len(parsed) > 1:
        flags.append(f"CORROBORATED_ON_{len(parsed)}_LOCATIONS")
    return FieldExtraction(spec.field_key, FieldStatus.EXTRACTED, best, parsed, flags)
