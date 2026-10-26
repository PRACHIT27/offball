import importlib.util
import json
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


def _load():
    spec = importlib.util.spec_from_file_location("function_app", FUNCTION_APP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_batch_properties_come_from_properties_array():
    from azure.functions import EventHubEvent
    from azure.functions.meta import Datum

    module = _load()
    props = [{"match_id": "m1", "feed": "A", "emitted_at": "t1"},
             {"match_id": "m1", "feed": "A", "emitted_at": "t2"}]
    shared = {"PropertiesArray": Datum(json.dumps(props), "json")}
    events = [EventHubEvent(body=b'{"n": %d}' % i, trigger_metadata=shared) for i in range(2)]
    msgs = module._messages(events)
    assert [m[1]["emitted_at"] for m in msgs] == ["t1", "t2"]
    assert msgs[1][0] == b'{"n": 1}'
