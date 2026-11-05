"""Deterministic value normalisation from raw document text.

Raw text is always preserved separately; these functions only propose a canonical value plus flags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from rule_engine import DataType

_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
_MULTIPLIERS = {
    "crore": Decimal(10_000_000),
    "crores": Decimal(10_000_000),
    "cr": Decimal(10_000_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "lac": Decimal(100_000),
    "lacs": Decimal(100_000),
    "million": Decimal(1_000_000),
}
_UNIT_ALIASES: dict[str, set[str]] = {
    "mm2": {"mm2", "mm²", "sq.mm", "sq mm", "sqmm", "sq. mm", "mm^2"},
    "kv": {"kv"},
    "kva": {"kva"},
    "mva": {"mva"},
    "km": {"km", "rkm", "ckm"},
    "a": {"a", "amp", "amps", "ampere"},
    "mm": {"mm"},
    "m": {"m", "mtr", "metre", "meter"},
    "kg": {"kg", "kgs"},
    "%": {"%", "percent"},
    "years": {"year", "years", "yrs"},
    "days": {"day", "days"},
}
_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}


@dataclass
class Normalized:
    value: str | None  # canonical string or None if unparseable
    unit: str | None = None
    flags: list[str] = field(default_factory=list)


def canonical_unit(text: str) -> str | None:
    token = text.strip().strip(".,;:()").lower()
    for canon, aliases in _UNIT_ALIASES.items():
        if token in aliases:
            return canon
    return None


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _fmt(d: Decimal) -> str:
    return format(d.normalize() if d == d.to_integral_value() else d, "f")


def normalize_number(raw: str, data_type: DataType, expected_unit: str | None) -> Normalized:
    match = _NUMBER.search(raw)
    if not match:
        return Normalized(None, flags=["NO_NUMBER_FOUND"])
    number = _decimal(match.group(0))
    if number is None:
        return Normalized(None, flags=["NO_NUMBER_FOUND"])
    flags: list[str] = []
    if len(_NUMBER.findall(raw)) > 1:
        flags.append("MULTIPLE_NUMBERS_IN_VALUE")
    rest = raw[match.end() :].strip()
    unit_token = rest.split()[0] if rest.split() else ""
    # Two-token units such as "sq mm"
    two_tokens = " ".join(rest.split()[:2])
    unit = canonical_unit(two_tokens) or canonical_unit(unit_token)
    if expected_unit:
        want = canonical_unit(expected_unit) or expected_unit.lower()
        if unit is None:
            flags.append("UNIT_NOT_STATED")
            unit = want
        elif unit != want:
            flags.append("UNIT_MISMATCH")
            return Normalized(None, unit=unit, flags=flags)
    if data_type is DataType.INTEGER and number != number.to_integral_value():
        return Normalized(None, unit=unit, flags=[*flags, "NOT_AN_INTEGER"])
    return Normalized(_fmt(number), unit=unit, flags=flags)


def normalize_money(raw: str) -> Normalized:
    match = _NUMBER.search(raw)
    if not match:
        return Normalized(None, flags=["NO_NUMBER_FOUND"])
    number = _decimal(match.group(0))
    if number is None:
        return Normalized(None, flags=["NO_NUMBER_FOUND"])
    flags: list[str] = []
    rest = raw[match.end() :].strip().lower()
    word = re.split(r"[\s/.\-]+", rest)[0] if rest else ""
    if word in _MULTIPLIERS:
        number = number * _MULTIPLIERS[word]
        flags.append(f"MULTIPLIER_{word.upper()}")
    if not re.search(r"(₹|\brs\b|\brs\.|\binr\b|rupees)", raw.lower()):
        flags.append("CURRENCY_NOT_STATED")
    if re.search(r"(\$|usd|eur|€)", raw.lower()):
        return Normalized(None, unit=None, flags=[*flags, "FOREIGN_CURRENCY"])
    return Normalized(_fmt(number), unit="INR", flags=flags)


_DMY = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_D_MON_Y = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})\b")
_MON_D_Y = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")


def normalize_date(raw: str) -> Normalized:
    flags: list[str] = []
    try:
        if m := _ISO.search(raw):
            return Normalized(date(int(m[1]), int(m[2]), int(m[3])).isoformat())
        if m := _DMY.search(raw):
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
            if d <= 12 and mo <= 12 and d != mo:
                flags.append("DATE_FORMAT_ASSUMED_DMY")  # Indian convention; flagged for review
            return Normalized(date(y, mo, d).isoformat(), flags=flags)
        if m := _D_MON_Y.search(raw):
            mon = _MONTHS.get(m[2].lower())
            if mon:
                return Normalized(date(int(m[3]), mon, int(m[1])).isoformat())
        if m := _MON_D_Y.search(raw):
            mon = _MONTHS.get(m[1].lower())
            if mon:
                return Normalized(date(int(m[3]), mon, int(m[2])).isoformat())
    except ValueError:
        return Normalized(None, flags=["INVALID_CALENDAR_DATE"])
    return Normalized(None, flags=["NO_DATE_FOUND"])


_TRUE = {"yes", "y", "true", "registered", "available", "applicable"}
_FALSE = {"no", "n", "false", "not registered", "not available", "not applicable", "nil", "none"}


def normalize_boolean(raw: str) -> Normalized:
    text = " ".join(raw.lower().strip(" .:-").split())
    if text in _FALSE or text.startswith(("no ", "not ")):
        return Normalized("false")
    if text in _TRUE or text.startswith("yes"):
        return Normalized("true")
    return Normalized(None, flags=["NOT_A_BOOLEAN"])


def normalize_string(raw: str) -> Normalized:
    text = " ".join(raw.split()).strip(" :-–")
    return Normalized(text or None, flags=[] if text else ["EMPTY_VALUE"])


def normalize(raw: str, data_type: DataType, unit: str | None) -> Normalized:
    match data_type:
        case DataType.MONEY:
            return normalize_money(raw)
        case DataType.INTEGER | DataType.DECIMAL:
            return normalize_number(raw, data_type, unit)
        case DataType.DATE:
            return normalize_date(raw)
        case DataType.BOOLEAN:
            return normalize_boolean(raw)
        case _:
            return normalize_string(raw)


# Flags that make a value uncertain enough to require human review regardless of confidence.
REVIEW_FLAGS = {
    "UNIT_NOT_STATED",
    "MULTIPLE_NUMBERS_IN_VALUE",
    "DATE_FORMAT_ASSUMED_DMY",
    "CURRENCY_NOT_STATED",
    "VALUE_ON_NEXT_LINE",
}
