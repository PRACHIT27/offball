from ingest.service import NormalizerService
from tests import factories


class Memory(dict):
    def load(self, key):
        return self.get(key)

    def save(self, key, value):
        self[key] = value

    def write(self, path, record):
        self[path] = record


def test_match_id_falls_back_to_the_body_when_properties_are_missing():
    import json

    hub, dead, sheets = [], Memory(), Memory()
    svc = NormalizerService(sheets, dead, hub.extend, now=lambda: "t")
    pre = json.dumps({"msgType": "prematch", "matchId": "m001", "prematch": factories.prematch()})
    lineup = json.dumps(factories.lineup())
    svc.handle_batch("A", [(pre, {}), (lineup, {})])
    assert "m001" in sheets and not dead
    assert hub[0][2] == "m001"
