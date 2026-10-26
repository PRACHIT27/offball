"""Write the Data Ingestion contracts in contracts/ingestion/ as JSON Schema, from the Pydantic models.

The models are the source of truth; tests/engine/test_contracts.py fails if the files drift.
Usage: python -m engine.contracts
"""

import json
from pathlib import Path

from pydantic import TypeAdapter

from engine.merge.outputs import MergeOutput
from ingest.clean import CleanEvent, CleanFrameBatch
from ingest.raw import Prematch

SCHEMA_VERSION = "1.0.0"
OUT = Path(__file__).resolve().parent.parent / "contracts" / "ingestion"
BASE_ID = "https://github.com/PRACHIT27/offball/blob/main/contracts/ingestion/"

CONTRACTS = {
    "clean-event": CleanEvent,
    "clean-frame-batch": CleanFrameBatch,
    "prematch": Prematch,
    "merge-output": MergeOutput,
}


def schemas() -> dict[str, str]:
    out = {}
    for name, model in CONTRACTS.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{BASE_ID}{name}.schema.json",
            "version": SCHEMA_VERSION,
            **TypeAdapter(model).json_schema(),
        }
        schema.setdefault("title", name)
        out[f"{name}.schema.json"] = json.dumps(schema, indent=2) + "\n"
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in schemas().items():
        (OUT / name).write_text(text)
        print(f"wrote contracts/ingestion/{name}")


if __name__ == "__main__":
    main()
