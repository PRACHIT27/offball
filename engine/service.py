"""Match engine service on Container Apps (LLD §9): reads `normalized`, runs the merge stage,
stores Silver, and checkpoints so a restart resumes without loss (FR-27).

Signs in as the user-assigned identity id-engine (AZURE_CLIENT_ID); no keys.

    python -m engine.service
"""

import logging
import os
import threading
import time

from azure.cosmos import CosmosClient
from azure.eventhub import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblob import BlobCheckpointStore
from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

from engine.core import EngineCore
from engine.store_azure import AzureStore, BlobSnapshots

CHECKPOINT_EVERY_S = 5.0
log = logging.getLogger("offball.engine")


def _props(event) -> dict:
    return {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in (event.properties or {}).items()}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(logger_name="offball")

    cred = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"])
    account = os.environ["STORAGE_ACCOUNT_URL"]
    blobs = BlobServiceClient(account, credential=cred)
    cosmos = (CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=cred)
              .get_database_client("offball").get_container_client("events"))
    frames = blobs.get_container_client("silver-frames")
    core = EngineCore(lambda match_id: AzureStore(match_id, cosmos, frames),
                      BlobSnapshots(blobs.get_container_client("checkpoints")))

    lock = threading.Lock()
    last_checkpoint = {"t": time.monotonic()}

    def on_batch(ctx, events) -> None:
        if not events:
            return
        with lock:
            now = time.time() * 1000
            for e in events:
                props = _props(e)
                try:
                    core.handle(e.body_as_str(), props, now)
                except Exception:
                    log.exception("could not handle message %s", props)
            if time.monotonic() - last_checkpoint["t"] >= CHECKPOINT_EVERY_S:
                core.checkpoint()
                ctx.update_checkpoint(events[-1])
                last_checkpoint["t"] = time.monotonic()

    def ticker() -> None:
        while True:
            time.sleep(1)
            with lock:
                if core.tick(time.time() * 1000):
                    core.checkpoint()
            for match_id, stage in list(core.stages.items()):
                log.info("match %s counts %s", match_id, dict(stage.counts))

    threading.Thread(target=ticker, daemon=True).start()
    client = EventHubConsumerClient(
        fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"], eventhub_name="normalized",
        consumer_group="engine", credential=cred,
        checkpoint_store=BlobCheckpointStore(account, "checkpoints", credential=cred))
    log.info("engine listening on normalized")
    with client:
        client.receive_batch(on_event_batch=on_batch, max_batch_size=200, max_wait_time=1,
                             starting_position="-1")


if __name__ == "__main__":
    main()
