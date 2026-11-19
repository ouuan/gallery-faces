"""Write ZIPs incrementally, keeping only one file chunk and the ZIP directory."""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import struct
from zipfile import ZIP_STORED, ZipFile, ZipInfo

CHUNK_SIZE = 64 * 1024


class ChunkWriter:
    def __init__(self):
        self.chunks = deque()

    def write(self, data):
        if data:
            self.chunks.append(data)
        return len(data)

    def flush(self):
        pass

    def drain(self):
        while self.chunks:
            yield self.chunks.popleft()


def stream_zip(files: list[tuple[str, Path, datetime]]):
    # No seek/tell: zipfile uses data descriptors instead of rewriting headers.
    sink = ChunkWriter()
    with ZipFile(sink, "w", compression=ZIP_STORED) as archive:
        for name, path, published_at in files:
            info = ZipInfo.from_file(path, arcname=name, strict_timestamps=False)
            published_at = published_at.astimezone(timezone.utc)
            # DOS dates have no timezone and only support 1980–2107.
            date = min(
                max(published_at, datetime(1980, 1, 1, tzinfo=timezone.utc)),
                datetime(2107, 12, 31, 23, 59, 58, tzinfo=timezone.utc),
            )
            info.date_time = date.timetuple()[:6]
            timestamp = int(published_at.timestamp())
            if 0 <= timestamp <= 0xFFFFFFFF:
                # Extended timestamp: preserve UTC and odd seconds on extraction.
                info.extra = struct.pack("<HHBI", 0x5455, 5, 1, timestamp)
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as entry:
                yield from sink.drain()
                while chunk := source.read(CHUNK_SIZE):
                    entry.write(chunk)
                    yield from sink.drain()
            yield from sink.drain()
    yield from sink.drain()
