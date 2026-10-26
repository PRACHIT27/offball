from azure.core.exceptions import ResourceNotFoundError

from engine.frames_parquet import from_bytes
from engine.merge.outputs import FramesOut
from engine.store_azure import AzureStore
from ingest.clean import CleanFrame, CleanFrameBatch, Point3


class FakeBlobs:
    def __init__(self):
        self.data, self.downloads = {}, 0

    def get_blob_client(self, name):
        store = self

        class Blob:
            def download_blob(self):
                store.downloads += 1
                if name not in store.data:
                    raise ResourceNotFoundError("missing")
                return type("D", (), {"readall": lambda _: store.data[name]})()

            def upload_blob(self, data, overwrite):
                store.data[name] = data

        return Blob()


class FakeCosmos:
    def upsert_item(self, item):
        pass


def _frames(first, n):
    return FramesOut(batch=CleanFrameBatch(match_id="m", period=1, emitted_at="t", frames=[
        CleanFrame(frame=f, match_clock_ms=f * 40, ball=Point3(x=1, y=2, z=0), players=[])
        for f in range(first, first + n)]))


def test_partial_chunk_is_downloaded_once_and_written_whole():
    blobs = FakeBlobs()
    store = AzureStore("m", FakeCosmos(), blobs)
    for start in range(0, 600, 100):  # several checkpoints within one 5-minute chunk
        store.write([_frames(start, 100)])
        store.flush()
    assert blobs.downloads == 1
    assert sorted(from_bytes(blobs.data["m/1/0.parquet"])) == list(range(600))


def test_restart_merges_with_rows_an_earlier_process_wrote():
    blobs = FakeBlobs()
    first = AzureStore("m", FakeCosmos(), blobs)
    first.write([_frames(0, 300)])
    first.flush()
    second = AzureStore("m", FakeCosmos(), blobs)  # new process after a restart
    second.write([_frames(300, 300)])
    second.flush()
    assert sorted(from_bytes(blobs.data["m/1/0.parquet"])) == list(range(600))
