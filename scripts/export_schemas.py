"""Regenerate reviewable JSON Schemas from the versioned public contracts."""

import json
from pathlib import Path

from deepseek_bridge import contracts

root = Path(__file__).resolve().parents[1] / "schemas"
for name in ("Ask", "CodingRequest", "Handoff", "Envelope", "ReviewReport", "ResearchReport"):
    model = getattr(contracts, name)
    (root / f"{name}.json").write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
