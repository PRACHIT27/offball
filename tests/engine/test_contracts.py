"""contracts/ingestion/ and contracts/broadcast/ must match the Pydantic models they come from."""

from engine.contracts import ROOT, schemas


def test_contract_files_match_models():
    for name, text in schemas().items():
        path = ROOT / name
        assert path.exists(), f"missing {path}; run python -m engine.contracts"
        assert path.read_text() == text, f"{name} is stale; run python -m engine.contracts"
