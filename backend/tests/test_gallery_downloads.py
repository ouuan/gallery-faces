import io
from datetime import datetime, timezone
from pathlib import Path
import struct
from zipfile import ZipFile

import pytest

from app import archives, db, main
from test_workflows import client, image


PUBLISHED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def seed(*, group=None, original=True, size=100, date="2026-01-01T00:00:00Z"):
    with db.connect(True) as conn:
        identifier = image(conn, group=group, date=date)
        filename = f"photo-{identifier}.jpg"
        original_filename = f"original-{identifier}.png" if original else None
        conn.execute(
            "UPDATE images SET filename=?,original_filename=?,file_size=? WHERE id=?",
            (filename, original_filename, size, identifier),
        )
        group_id = conn.execute("SELECT group_id FROM images WHERE id=?", (identifier,)).fetchone()[0]
    (db.DATA / "images" / filename).write_bytes(f"display {identifier}".encode())
    if original:
        (db.DATA / "originals" / original_filename).write_bytes(f"original {identifier}".encode())
    return identifier, group_id


def test_download_public_representatives_original_fallback_and_deduplication(client):
    first, group = seed()
    representative, _ = seed(group=group, size=200)
    second, other_group = seed(original=False)
    client.cookies.clear()
    prepared = client.post("/api/v1/gallery/downloads", json={"group_ids": [group, other_group, group]})
    assert prepared.status_code == 200
    response = client.get(prepared.json()["download_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith('attachment; filename="gallery-')
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-store"
    assert "content-length" not in response.headers
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [f"{group}-original-{representative}.png", f"{other_group}-photo-{second}.jpg"]
        assert archive.read(archive.namelist()[0]) == f"original {representative}".encode()
        assert archive.read(archive.namelist()[1]) == f"display {second}".encode()
        assert archive.testzip() is None


def test_archive_budget_released_after_requests(client, monkeypatch):
    first, group = seed()
    _, other = seed()
    monkeypatch.setattr(main.resource, 'getrlimit', lambda _: (16, 16))
    url = f'/api/v1/gallery/download.zip?groups={group},{other}'
    with main.MediaRead() as concurrent:
        main.archive_budget.reserve(concurrent, 3)
        assert client.post('/api/v1/gallery/downloads', json={'group_ids': [group, other]}).status_code == 200
        busy = client.get(url)
        assert busy.status_code == 503 and 'retry-after' in busy.headers
        assert client.get(f'/api/v1/media/{first}').status_code == 200
    assert client.get(url).status_code == 200
    assert main.archive_budget.used == 0


@pytest.mark.parametrize("original", [True, False])
def test_download_uses_earliest_public_post_time(client, original):
    _, group = seed(date="2024-05-06T07:08:09Z")
    representative, _ = seed(group=group, size=200, original=original)
    with db.connect(True) as conn:
        hidden = image(conn, group=group, date="2020-01-01T00:00:00Z")
        conn.execute("UPDATE images SET hidden=1 WHERE id=?", (hidden,))
        pending = image(conn, group=group, date="2021-01-01T00:00:00Z")
        conn.execute("UPDATE images SET detection='pending' WHERE id=?", (pending,))
        image(conn, group=group, date="2022-01-01T00:00:00Z", author=None)
    response = client.get(f"/api/v1/gallery/download.zip?groups={group}")
    assert response.status_code == 200
    with ZipFile(io.BytesIO(response.content)) as archive:
        info, = archive.infolist()
        filename = f"original-{representative}.png" if original else f"photo-{representative}.jpg"
        assert info.filename == f"{group}-{filename}"
        assert info.date_time == (2024, 5, 6, 7, 8, 8)
        timestamp = int(datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone.utc).timestamp())
        assert info.extra == struct.pack("<HHBI", 0x5455, 5, 1, timestamp)


@pytest.mark.parametrize("unavailable", ["hidden", "pending", "source", "missing", "deleted"])
def test_download_rechecks_visibility_and_missing_files(client, unavailable):
    identifier, group = seed()
    other, other_group = seed()
    url = client.post("/api/v1/gallery/downloads", json={"group_ids": [other_group, group]}).json()["download_url"]
    with db.connect(True) as conn:
        if unavailable == "hidden":
            conn.execute("UPDATE images SET hidden=1 WHERE id=?", (identifier,))
        elif unavailable == "pending":
            conn.execute("UPDATE images SET detection='pending' WHERE id=?", (identifier,))
        elif unavailable == "source":
            conn.execute("UPDATE posts SET author=NULL WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (identifier,))
        elif unavailable == "deleted":
            conn.execute("DELETE FROM sources WHERE image_id=?", (identifier,))
            conn.execute("DELETE FROM faces WHERE image_id=?", (identifier,))
            conn.execute("DELETE FROM images WHERE id=?", (identifier,))
        else:
            (db.DATA / "images" / f"photo-{identifier}.jpg").unlink()
            (db.DATA / "originals" / f"original-{identifier}.png").unlink()
    for response in [client.get(url), client.post("/api/v1/gallery/downloads", json={"group_ids": [group]})]:
        assert response.status_code == 404
        assert "content-disposition" not in response.headers
        assert response.headers["cache-control"] == "no-store"


def test_missing_original_uses_display_and_colliding_names_are_unique(client):
    first, group = seed()
    second, other = seed(original=False)
    (db.DATA / "originals" / f"original-{first}.png").unlink()
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET filename=? WHERE id=?", (f"photo-{first}.jpg", second))
    response = client.get(f"/api/v1/gallery/download.zip?groups={group},{other}")
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [f"{group}-photo-{first}.jpg", f"{other}-photo-{first}.jpg"]
        assert all(archive.read(name) == f"display {first}".encode() for name in archive.namelist())


@pytest.mark.parametrize("groups", ["", "0", "-1", "1,,2", "abc", "1.1", "9223372036854775808", ",".join(["1"] * 201)])
def test_invalid_download_query(client, groups):
    assert client.get("/api/v1/gallery/download.zip", params={"groups": groups}).status_code in (400, 422)


@pytest.mark.parametrize("ids", [[], [0], [-1], [True], [1.1], ["1"], [2**63], [1] * 201])
def test_invalid_download_selection(client, ids):
    assert client.post("/api/v1/gallery/downloads", json={"group_ids": ids}).status_code == 422


def test_zip_streams_before_reading_files_and_closes_on_cancel(tmp_path, monkeypatch):
    first, second = tmp_path / "one.jpg", tmp_path / "two.jpg"
    content = b"x" * (archives.CHUNK_SIZE * 4 + 17)
    first.write_bytes(content)
    second.write_bytes(b"second")
    opened = []
    original_open = Path.open

    def track_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        opened.append(handle)
        return handle

    monkeypatch.setattr(Path, "open", track_open)
    files = [("one.jpg", first, PUBLISHED_AT), ("two.jpg", second, PUBLISHED_AT)]
    stream = archives.stream_zip(files)
    assert next(stream).startswith(b"PK")
    assert len(opened) == 1 and opened[0].tell() == 0
    assert next(stream) == content[:archives.CHUNK_SIZE]
    assert opened[0].tell() == archives.CHUNK_SIZE
    stream.close()
    assert len(opened) == 1 and opened[0].closed
    chunks = list(archives.stream_zip(files))
    assert max(map(len, chunks)) <= archives.CHUNK_SIZE
    with ZipFile(io.BytesIO(b"".join(chunks))) as archive:
        assert archive.read("one.jpg") == content
        assert archive.read("two.jpg") == b"second"
        assert archive.testzip() is None


def test_zip64_directory(tmp_path, monkeypatch):
    import zipfile
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 100)
    path = tmp_path / "large.jpg"
    path.write_bytes(b"x" * 200)
    content = b"".join(archives.stream_zip([("large.jpg", path, PUBLISHED_AT)]))
    assert b"PK\x06\x06" in content
    with ZipFile(io.BytesIO(content)) as archive:
        assert archive.read("large.jpg") == b"x" * 200


@pytest.mark.parametrize("published_at,expected_date", [
    ("2024-05-06T07:08:09+08:00", (2024, 5, 5, 23, 8, 8)),
    ("1975-05-06T07:08:09Z", (1980, 1, 1, 0, 0, 0)),
    ("1960-05-06T07:08:09Z", (1980, 1, 1, 0, 0, 0)),
    ("2200-05-06T07:08:09Z", (2107, 12, 31, 23, 59, 58)),
])
def test_zip_timestamp_timezone_and_range(tmp_path, published_at, expected_date):
    path = tmp_path / "photo.jpg"
    path.write_bytes(b"photo")
    date = datetime.fromisoformat(published_at)
    content = b"".join(archives.stream_zip([("photo.jpg", path, date)]))
    with ZipFile(io.BytesIO(content)) as archive:
        info = archive.getinfo("photo.jpg")
        assert info.date_time == expected_date
        timestamp = int(date.timestamp())
        if 0 <= timestamp <= 0xFFFFFFFF:
            assert struct.unpack("<HHBI", info.extra) == (0x5455, 5, 1, timestamp)
        else:
            assert info.extra == b""
        assert archive.read(info) == b"photo"
