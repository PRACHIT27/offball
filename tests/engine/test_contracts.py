"""contracts/ingestion/ must match the Pydantic models it is generated from."""

from engine.contracts import OUT, schemas


def test_contract_files_match_models():
    for name, text in schemas().items():
        path = OUT / name
        assert path.exists(), f"missing {path}; run python -m engine.contracts"
        assert path.read_text() == text, f"{name} is stale; run python -m engine.contracts"
