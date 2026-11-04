"""Commercial-leakage detector for technical bid pages.

If a technical page appears to contain price-bid content, its text is NOT stored on the technical
side and the page image is withheld from all officers until an approver explicitly releases it
or the commercial envelope is opened. Indicators returned here never include the amounts themselves.
"""

from __future__ import annotations

import re

DETECTOR_VERSION = "leak-1.0"

_PRICE_CONTEXT = re.compile(
    r"\b(price\s*bid|price\s*schedule|financial\s*bid|commercial\s*bid|quoted\s*(rate|price|amount)"
    r"|unit\s*rate|rate\s*per\s*(unit|metre|meter|km|no|set)|total\s*bid\s*(value|amount|price)"
    r"|bill\s*of\s*quantit(y|ies)|\bboq\b|our\s*offer\s*(price|amount)|total\s*quoted)",
    re.IGNORECASE,
)
_CURRENCY_FIGURE = re.compile(r"(₹|\brs\.?|\binr)\s*[0-9][0-9,]*(\.[0-9]+)?", re.IGNORECASE)


def detect_price_content(text: str) -> list[str]:
    """Return non-sensitive indicator labels; empty list means no leakage suspected."""
    contexts = sorted({m.group(0).lower() for m in _PRICE_CONTEXT.finditer(text)})
    figures = len(_CURRENCY_FIGURE.findall(text))
    if contexts and figures >= 1:
        return [f"price-context:{c}" for c in contexts] + [f"currency-figures:{figures}"]
    return []
