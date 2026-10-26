"""Silver on Azure (LLD §8): events, notices, pre-match and counts in Cosmos DB `events`
(partition `match_id`); frames as Parquet in Blob `silver-frames`. Every write is an upsert."""

from azure.core.exceptions import ResourceNotFoundError

from engine.frames_parquet import ChunkBuffer, ChunkKey, chunk_name, from_bytes, to_bytes
from engine.merge.outputs import EventDelete, EventUpsert, FramesOut, MergeOutput, Notice, Prematch


class AzureStore:
    def __init__(self, match_id: str, cosmos_container, frames_container) -> None:
        self.match_id = match_id
        self.cosmos = cosmos_container
        self.blobs = frames_container
        self.frames = ChunkBuffer()

    def _upsert(self, doc_id: str, doc_type: str, body: dict) -> None:
        self.cosmos.upsert_item({**body, "id": doc_id, "match_id": self.match_id,
                                 "doc_type": doc_type})

    def write(self, outputs: list[MergeOutput]) -> None:
        for o in outputs:
            match o:
                case EventUpsert() | EventDelete():
                    ev = o.event
                    self._upsert(f"{ev.event_id}:{ev.version}", "event", ev.model_dump(mode="json"))
                case Notice():
                    self._upsert(o.notice_id, "notice", o.model_dump(mode="json"))
                case Prematch():
                    self._upsert("prematch", "prematch", {"prematch": o.prematch})
                case FramesOut():
                    for key in self.frames.add(o):
                        self._write_chunk(key)
                        del self.frames.chunks[key]

    def _write_chunk(self, key: ChunkKey) -> None:
        blob = self.blobs.get_blob_client(chunk_name(self.match_id, key))
        try:  # a chunk can span a restart: merge with what is already written
            rows = from_bytes(blob.download_blob().readall())
        except ResourceNotFoundError:
            rows = {}
        rows.update(self.frames.chunks[key])
        blob.upload_blob(to_bytes(rows), overwrite=True)

    def flush(self, counts: dict | None = None) -> None:
        for key in self.frames.chunks:
            self._write_chunk(key)
        if counts is not None:
            self._upsert("counts", "counts", {"counts": counts})


class BlobSnapshots:
    """Snapshots in Blob `checkpoints/{prefix}/{match_id}.json`: `engine` for the merge stage,
    `metrics` for Performance Metrics."""

    def __init__(self, container, prefix: str = "engine") -> None:
        self.container = container
        self.prefix = prefix

    def load(self, match_id: str) -> str | None:
        try:
            return self.container.download_blob(f"{self.prefix}/{match_id}.json").readall().decode()
        except ResourceNotFoundError:
            return None

    def save(self, match_id: str, state_json: str) -> None:
        self.container.upload_blob(f"{self.prefix}/{match_id}.json", state_json, overwrite=True)
