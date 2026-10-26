import importlib.util
import typing
from pathlib import Path

FUNCTION_APP = Path(__file__).resolve().parents[2] / "ingest/functionapp/function_app.py"


def test_function_app_indexes_without_settings_or_sdks():
    spec = importlib.util.spec_from_file_location("function_app", FUNCTION_APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # no AZURE_* settings needed at load time
    functions = {f.get_function_name(): f for f in module.app.get_functions()}
    assert sorted(functions) == ["normalize_feed_a", "normalize_feed_b"]
    for f in functions.values():
        hint = f.get_user_function().__annotations__["events"]
        # The Functions worker rejects list[...] here ("invalid non-type annotation")
        assert typing.get_origin(hint) is list and repr(hint).startswith("typing.List")
