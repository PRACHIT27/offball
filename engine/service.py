"""Match engine service on Container Apps (LLD §9): reads `normalized`, runs the merge stage,
stores Silver, runs Performance Metrics (to the `stats` hub and Cosmos `metrics`), and
checkpoints so a restart resumes without loss (FR-27).

METRICS_ENABLED=0 runs the merge stage alone (e.g. before the `stats` hub and the Cosmos
`metrics` container exist; see engine/metrics/README.md).

Signs in as the user-assigned identity id-engine (AZURE_CLIENT_ID); no keys.

    python -m engine.service
"""

import asyncio
import logging
import os
import time

from azure.cosmos import CosmosClient
from azure.eventhub import EventHubProducerClient
from azure.eventhub.aio import EventHubConsumerClient
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore
from azure.identity import ManagedIdentityCredential
from azure.identity.aio import ManagedIdentityCredential as AsyncManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

from engine.core import EngineCore
from engine.metrics.publisher import Publisher
from engine.metrics.service import MetricsRouter
from engine.metrics.sinks_azure import CosmosMetricsSink, StatsHubSink
from engine.store_azure import AzureStore, BlobSnapshots

# Full checkpoints (frames, snapshots, hub position) are I/O inside the processing lock, so not
# too often; a restart replays at most this much, and replays are dropped as duplicates
CHECKPOINT_EVERY_S = 30.0
PREFETCH = 300
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


async def run() -> None:
    client_id = os.environ["AZURE_CLIENT_ID"]
    cred = ManagedIdentityCredential(client_id=client_id)
    account = os.environ["STORAGE_ACCOUNT_URL"]
    blobs = BlobServiceClient(account, credential=cred)
    db = CosmosClient(os.environ["COSMOS_ENDPOINT"], credential=cred).get_database_client("offball")
    cosmos = db.get_container_client("events")
    frames = blobs.get_container_client("silver-frames")
    checkpoints = blobs.get_container_client("checkpoints")
    # Performance Metrics runs inside core.handle (the worker thread), so its sends block like
    # the Cosmos and Blob calls do
    metrics = None
    if os.environ.get("METRICS_ENABLED", "1") != "0":
        stats_hub = EventHubProducerClient(
            fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"], eventhub_name="stats",
            credential=cred)
        metrics = MetricsRouter(
            Publisher([StatsHubSink(stats_hub),
                       CosmosMetricsSink(db.get_container_client("metrics"))]),
            BlobSnapshots(checkpoints, prefix="metrics"))
    core = EngineCore(lambda match_id: AzureStore(match_id, cosmos, frames),
                      BlobSnapshots(checkpoints), **({"router": metrics} if metrics else {}))

    def checkpoint() -> None:
        core.checkpoint()
        if metrics:
            metrics.checkpoint()

    # The engine core and its Cosmos/Blob calls are blocking: they run in a worker thread, one
    # message at a time (the lock), so the receive loop keeps pulling from the hub meanwhile
    lock = asyncio.Lock()
    # Per partition, so a busy partition can't keep postponing a quiet one's checkpoint
    last_checkpoint: dict[str, float] = {}

    # Async client, one message at a time. Measured on `normalized`: the sync client hands over
    # about one callback per second whatever its size (200-message batches: ~3.3 s median delay;
    # per message: 1 msg/s), the async client ~0.1 s median at the full rate.
    async def on_event(ctx, e) -> None:
        if e is None:
            return
        props = _props(e)
        async with lock:
            try:
                await asyncio.to_thread(core.handle, e.body_as_str(), props, time.time() * 1000)
            except Exception:
                log.exception("could not handle message %s", props)
            part = ctx.partition_id
            if time.monotonic() - last_checkpoint.setdefault(part, time.monotonic()) \
                    >= CHECKPOINT_EVERY_S:
                await asyncio.to_thread(checkpoint)
                await ctx.update_checkpoint(e)
                last_checkpoint[part] = time.monotonic()

    async def ticker() -> None:
        logged: dict[str, dict] = {}
        last_counts = time.monotonic()
        while True:
            await asyncio.sleep(1)
            try:
                async with lock:
                    if await asyncio.to_thread(core.tick, time.time() * 1000):
                        await asyncio.to_thread(checkpoint)
                if time.monotonic() - last_counts >= COUNTS_EVERY_S:
                    last_counts = time.monotonic()
                    for match_id, stage in list(core.stages.items()):
                        counts = dict(stage.counts) | {"clock_offset_ms": stage.offset_ms}
                        if counts != logged.get(match_id):
                            logged[match_id] = counts
                            log.info("match %s counts %s", match_id, counts)
                    async with lock:  # handle() appends from the worker thread
                        lags = {f: sorted(v) for f, v in core.arrival_lag.items() if v}
                        core.arrival_lag = {"A": [], "B": []}
                    for feed, v in lags.items():
                        log.info("arrival lag feed %s: n=%d p50=%.0f ms p95=%.0f ms max=%.0f ms",
                                 feed, len(v), v[len(v) // 2], v[int(len(v) * 0.95)], v[-1])
            except Exception:
                log.exception("engine timer failed")

    acred = AsyncManagedIdentityCredential(client_id=client_id)
    client = EventHubConsumerClient(
        fully_qualified_namespace=os.environ["EVENTHUB_NAMESPACE"], eventhub_name="normalized",
        consumer_group="engine", credential=acred,
        checkpoint_store=BlobCheckpointStore(account, "checkpoints", credential=acred))
    timer = asyncio.create_task(ticker())
    log.info("engine listening on normalized (consumer group engine)")
    try:
        async with client:
            await client.receive(on_event=on_event, prefetch=PREFETCH, starting_position="-1")
    finally:
        timer.cancel()
        await acred.close()


def main() -> None:
    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
