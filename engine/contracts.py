"""Write the shared contracts in contracts/ as JSON Schema, from the Pydantic models:
contracts/ingestion/ (Data Ingestion) and contracts/broadcast/ (the overlay cue and the `stats`
hub message, from Performance Metrics).

The models are the source of truth; tests/engine/test_contracts.py fails if the files drift.
Usage: python -m engine.contracts
"""

import json
from pathlib import Path

from pydantic import TypeAdapter

from engine.merge.outputs import MergeOutput
from engine.metrics.models import CUE_SCHEMA_VERSION, Cue, StatsMessage
from ingest.clean import CleanEvent, CleanFrameBatch
from ingest.raw import Prematch

SCHEMA_VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent.parent / "contracts"
OUT = ROOT / "ingestion"
BASE_ID = "https://github.com/PRACHIT27/offball/blob/main/contracts/"

# folder -> (version, {name: model})
CONTRACTS = {
    "ingestion": (SCHEMA_VERSION, {
        "clean-event": CleanEvent,
        "clean-frame-batch": CleanFrameBatch,
        "prematch": Prematch,
        "merge-output": MergeOutput,
    }),
    "broadcast": (CUE_SCHEMA_VERSION, {
        "cue": Cue,
        "stats-message": StatsMessage,
    }),
}


def schemas() -> dict[str, str]:
    """{path relative to contracts/: JSON Schema text}"""
    out = {}
    for folder, (version, models) in CONTRACTS.items():
        for name, model in models.items():
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"{BASE_ID}{folder}/{name}.schema.json",
                "version": version,
                **TypeAdapter(model).json_schema(),
            }
            schema.setdefault("title", name)
            out[f"{folder}/{name}.schema.json"] = json.dumps(schema, indent=2) + "\n"
    return out


def main() -> None:
    for rel, text in schemas().items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote contracts/{rel}")


if __name__ == "__main__":
    main()
