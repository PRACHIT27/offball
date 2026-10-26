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

# Full checkpoints (frames, snapshots, hub position) are I/O inside the processing lock, so not
# too often; a restart replays at most this much, and replays are dropped as duplicates
CHECKPOINT_EVERY_S = 30.0
RECEIVE_WAIT_S = 0.2
COUNTS_EVERY_S = 30.0
log = logging.getLogger("offball.engine")


def setup_logging() -> None:
    """Logs to stdout and, when APPLICATIONINSIGHTS_CONNECTION_STRING is set, to Application
    Insights as role `offball-engine`: our own logs at INFO, every other library at WARNING
    (so Azure SDK sign-in or permission errors show up too)."""
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("offball").setLevel(logging.INFO)
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    os.environ.setdefault("OTEL_SERVICE_NAME", "offball-engine")
    # Skip the Azure VM metadata probe: there is no VM endpoint on Container Apps, and the
    # failed probe was being logged as an exception
    os.environ.setdefault("OTEL_EXPERIMENTAL_RESOURCE_DETECTORS", "otel")
    os.environ.setdefault("APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL", "true")
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="")


def _props(event) -> dict:
    return {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in (event.properties or {}).items()}


def main() -> None:
    setup_logging()

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
        logged: dict[str, dict] = {}
        last_counts = time.monotonic()
        while True:
            time.sleep(1)
            try:
                with lock:
                    if core.tick(time.time() * 1000):
                        core.checkpoint()
                if time.monotonic() - last_counts >= COUNTS_EVERY_S:
                    last_counts = time.monotonic()
                    for match_id, stage in list(core.stages.items()):
                        counts = dict(stage.counts) | {"clock_offset_ms": stage.offset_ms}
                        if counts != logged.get(match_id):
                            logged[match_id] = counts
                            log.info("match %s counts %s", match_id, counts)
                    with lock:
                        lags = {f: sorted(v) for f, v in core.arrival_lag.items() if v}
                        core.arrival_lag = {"A": [], "B": []}
                    for feed, v in lags.items():
                        log.info("arrival lag feed %s: n=%d p50=%.0f ms p95=%.0f ms max=%.0f ms",
                                 feed, len(v), v[len(v) // 2], v[int(len(v) * 0.95)], v[-1])
            except Exception:
                log.exception("engine timer failed")

    threading.Thread(target=ticker, daemon=True).start()
    client = EventHubConsumerClient(
        fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"], eventhub_name="normalized",
        consumer_group="engine", credential=cred,
        checkpoint_store=BlobCheckpointStore(account, "checkpoints", credential=cred))
    log.info("engine listening on normalized (consumer group engine)")
    with client:
        client.receive_batch(on_event_batch=on_batch, max_batch_size=200,
                             max_wait_time=RECEIVE_WAIT_S,
                             starting_position="-1")


if __name__ == "__main__":
    main()
