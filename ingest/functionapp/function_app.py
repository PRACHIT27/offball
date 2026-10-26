"""Azure Functions entry points for normalizers A and B (ingestion LLD §6.1, §10).

Thin wiring only: triggers on the raw hubs call ingest.service.NormalizerService, which
publishes to `normalized` (partition key = match_id) and writes dead letters and team sheets
to Blob Storage. Signs in as the user-assigned identity id-ingest; no keys.

Only azure.functions is imported at load time, so indexing never depends on the SDKs or on
settings; clients are built on first use and any failure is logged with its traceback.
"""

import functools
import json
import logging
import os
from typing import List  # noqa: UP035 - the Functions worker rejects list[...] on trigger params

import azure.functions as func

app = func.FunctionApp()


@functools.cache
def _service():
    from azure.core.exceptions import ResourceNotFoundError
    from azure.eventhub import EventData, EventHubProducerClient
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import BlobServiceClient

    from ingest.service import NormalizerService

    credential = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
    blobs = BlobServiceClient(os.environ["STORAGE_ACCOUNT_URL"], credential=credential)
    producer = EventHubProducerClient(os.environ["EventHubConnection__fullyQualifiedNamespace"],
                                      "normalized", credential=credential)

    class BlobSheets:
        container = blobs.get_container_client("teamsheets")

        def load(self, match_id: str) -> str | None:
            try:
                return self.container.download_blob(f"{match_id}.json").readall().decode()
            except ResourceNotFoundError:
                return None

        def save(self, match_id: str, sheet_json: str) -> None:
            self.container.upload_blob(f"{match_id}.json", sheet_json, overwrite=True)

    class BlobDeadLetters:
        container = blobs.get_container_client("dead-letter")

        def write(self, path: str, record: dict) -> None:
            self.container.upload_blob(path, json.dumps(record), overwrite=True)

    def publish(messages: list[tuple[str, dict, str]]) -> None:
        by_key: dict[str, list] = {}
        for body, headers, key in messages:
            event = EventData(body)
            event.properties = headers
            by_key.setdefault(key, []).append(event)
        for key, events in by_key.items():
            batch = producer.create_batch(partition_key=key)
            for event in events:
                try:
                    batch.add(event)
                except ValueError:  # batch full
                    producer.send_batch(batch)
                    batch = producer.create_batch(partition_key=key)
                    batch.add(event)
            producer.send_batch(batch)

    return NormalizerService(BlobSheets(), BlobDeadLetters(), publish)


def _text(v):
    return v.decode() if isinstance(v, bytes) else v


def _messages(events: list[func.EventHubEvent]) -> list[tuple[bytes, dict]]:
    """Bodies with their application properties. With cardinality=many every event shares the
    batch metadata, where event i's properties are PropertiesArray[i]."""
    meta = (events[0].metadata or {}) if events else {}
    per_event = meta.get("PropertiesArray") or []
    out = []
    for i, e in enumerate(events):
        props = per_event[i] if i < len(per_event) else (meta.get("Properties") or {})
        out.append((e.get_body(), {_text(k): _text(v) for k, v in (props or {}).items()}))
    return out


def _run(feed: str, events: list[func.EventHubEvent]) -> None:
    try:
        logging.info("feed %s %s", feed, _service().handle_batch(feed, _messages(events)))
    except Exception:
        logging.exception("normalizer %s failed", feed)
        raise  # let the host retry the batch


# data_type binary: hand bodies over untouched, so a broken record reaches our dead-letter
# handling instead of failing the host's JSON parsing for the whole batch
@app.event_hub_message_trigger(arg_name="events", event_hub_name="raw-events",
                               connection="EventHubConnection", consumer_group="ingest",
                               cardinality="many", data_type=func.DataType.BINARY)
def normalize_feed_a(events: List[func.EventHubEvent]) -> None:  # noqa: UP006
    _run("A", events)


@app.event_hub_message_trigger(arg_name="events", event_hub_name="raw-tracking",
                               connection="EventHubConnection", consumer_group="ingest",
                               cardinality="many", data_type=func.DataType.BINARY)
def normalize_feed_b(events: List[func.EventHubEvent]) -> None:  # noqa: UP006
    _run("B", events)
