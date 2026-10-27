import os
from datetime import UTC, datetime
from typing import Protocol

HUBS = {"A": "raw-events", "B": "raw-tracking"}


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Sender(Protocol):
    def send(self, feed: str, items: list[tuple[str, dict]]) -> None: ...

    def close(self) -> None: ...


class EventHubSender:
    def __init__(self):
        from azure.eventhub import EventHubProducerClient

        conn = os.environ.get("EVENTHUB_CONNECTION")
        if conn:
            self.producers = {f: EventHubProducerClient.from_connection_string(
                conn, eventhub_name=h) for f, h in HUBS.items()}
        else:
            from azure.identity import DefaultAzureCredential

            namespace = os.environ["EVENTHUB_NAMESPACE"]
            credential = DefaultAzureCredential()
            self.producers = {f: EventHubProducerClient(
                fully_qualified_namespace=namespace, eventhub_name=h, credential=credential)
                for f, h in HUBS.items()}

    def send(self, feed: str, items: list[tuple[str, dict]]) -> None:
        from azure.eventhub import EventData

        if not items:
            return
        producer = self.producers[feed]
        match_id = items[0][1]["match_id"]
        batch = producer.create_batch(partition_key=match_id)
        for body, props in items:
            event = EventData(body)
            event.properties = {**props, "emitted_at": now_iso()}
            try:
                batch.add(event)
            except ValueError:
                producer.send_batch(batch)
                batch = producer.create_batch(partition_key=match_id)
                batch.add(event)
        producer.send_batch(batch)

    def close(self) -> None:
        for p in self.producers.values():
            p.close()


class CountingSender:
    def __init__(self):
        self.sent: dict[str, int] = {"A": 0, "B": 0}

    def send(self, feed: str, items: list[tuple[str, dict]]) -> None:
        self.sent[feed] += len(items)

    def close(self) -> None:
        pass


def make_sender() -> Sender:
    if os.environ.get("STREAM_TARGET", "eventhubs") == "dry-run":
        return CountingSender()
    return EventHubSender()
