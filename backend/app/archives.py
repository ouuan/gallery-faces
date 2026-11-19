"""Write ZIPs incrementally, keeping only one file chunk and the ZIP directory."""
from collections import deque
from pathlib import Path
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


def stream_zip(files: list[tuple[str, Path]]):
    # No seek/tell: zipfile uses data descriptors instead of rewriting headers.
    sink = ChunkWriter()
    with ZipFile(sink, "w", compression=ZIP_STORED) as archive:
        for name, path in files:
            info = ZipInfo.from_file(path, arcname=name, strict_timestamps=False)
            with path.open("rb") as source, archive.open(info, "w", force_zip64=True) as entry:
                yield from sink.drain()
                while chunk := source.read(CHUNK_SIZE):
                    entry.write(chunk)
                    yield from sink.drain()
            yield from sink.drain()
    yield from sink.drain()
