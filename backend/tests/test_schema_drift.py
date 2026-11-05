"""schemas/rulebook.schema.json must be regenerated from the Pydantic model (the source of truth)."""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.rulebooks.schemas import RulebookContent


def test_rulebook_json_schema_matches_pydantic() -> None:
    committed = json.loads(
        (Path(__file__).parents[2] / "schemas" / "rulebook.schema.json").read_text("utf-8")
    )
    generated = RulebookContent.model_json_schema()
    for key in ("$schema", "title"):
        committed.pop(key, None)
        generated.pop(key, None)
    assert committed == generated, "Regenerate schemas/rulebook.schema.json (see docs/MVP_IMPLEMENTATION.md)"
