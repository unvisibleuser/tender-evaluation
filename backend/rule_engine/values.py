"""Canonical value parsing used by the rule engine. Exact Decimal arithmetic only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .models import DataType


class ValueError_(ValueError):
    """Raised when a canonical value cannot be parsed for its declared data type."""


Comparable = Decimal | date | str | bool


def parse_canonical(value: object, data_type: DataType) -> Comparable:
    if value is None:
        raise ValueError_("value is null")
    if data_type in (DataType.INTEGER, DataType.DECIMAL, DataType.MONEY):
        if isinstance(value, bool) or isinstance(value, float):
            # floats are rejected to avoid binary rounding in thresholds
            raise ValueError_("numeric values must be given as strings or integers, not floats/booleans")
        try:
            number = Decimal(str(value).strip())
        except InvalidOperation as exc:
            raise ValueError_(f"not a number: {value!r}") from exc
        if not number.is_finite():
            raise ValueError_("number must be finite")
        if data_type is DataType.INTEGER and number != number.to_integral_value():
            raise ValueError_(f"not an integer: {value!r}")
        return number
    if data_type is DataType.DATE:
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value).strip())
        except ValueError as exc:
            raise ValueError_(f"not an ISO date: {value!r}") from exc
    if data_type is DataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes"):
            return True
        if text in ("false", "no"):
            return False
        raise ValueError_(f"not a boolean: {value!r}")
    if not isinstance(value, str | int):
        raise ValueError_(f"not a string: {value!r}")
    return " ".join(str(value).split()).casefold()


def display(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(display(v) for v in value) + "]"
    return str(value)
