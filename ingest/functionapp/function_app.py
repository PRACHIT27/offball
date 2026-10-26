"""Azure Functions entry points for normalizers A and B (ingestion LLD §6.1, §10).

Thin wiring only: triggers on the raw hubs call ingest.service.NormalizerService, which
publishes to `normalized` (partition key = match_id) and writes dead letters and team sheets
to Blob Storage. Signs in as the user-assigned identity id-ingest; no keys.
"""

import json
import logging
import os

import azure.functions as func
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
    by_key: dict[str, list[EventData]] = {}
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


service = NormalizerService(BlobSheets(), BlobDeadLetters(), publish)
app = func.FunctionApp()


def _messages(events: list[func.EventHubEvent]) -> list[tuple[bytes, dict]]:
    out = []
    for e in events:
        props = {k: (v.decode() if isinstance(v, bytes) else v)
                 for k, v in (e.metadata.get("Properties") or {}).items()}
        out.append((e.get_body(), props))
    return out


@app.event_hub_message_trigger(arg_name="events", event_hub_name="raw-events",
                               connection="EventHubConnection", consumer_group="ingest",
                               cardinality="many")
def normalize_feed_a(events: list[func.EventHubEvent]) -> None:
    logging.info("feed A %s", service.handle_batch("A", _messages(events)))


@app.event_hub_message_trigger(arg_name="events", event_hub_name="raw-tracking",
                               connection="EventHubConnection", consumer_group="ingest",
                               cardinality="many")
def normalize_feed_b(events: list[func.EventHubEvent]) -> None:
    logging.info("feed B %s", service.handle_batch("B", _messages(events)))
