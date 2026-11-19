import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from app import archives, db
from test_workflows import client, image


def seed(*, group=None, original=True, size=100):
    with db.connect(True) as conn:
        identifier = image(conn, group=group)
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
    stream = archives.stream_zip([("one.jpg", first), ("two.jpg", second)])
    assert next(stream).startswith(b"PK")
    assert len(opened) == 1 and opened[0].tell() == 0
    assert next(stream) == content[:archives.CHUNK_SIZE]
    assert opened[0].tell() == archives.CHUNK_SIZE
    stream.close()
    assert len(opened) == 1 and opened[0].closed
    chunks = list(archives.stream_zip([("one.jpg", first), ("two.jpg", second)]))
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
    content = b"".join(archives.stream_zip([("large.jpg", path)]))
    assert b"PK\x06\x06" in content
    with ZipFile(io.BytesIO(content)) as archive:
        assert archive.read("large.jpg") == b"x" * 200
