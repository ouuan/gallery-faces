import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app import db, importer, worker, main
from app.downloader import install_library_filter
from test_workflows import client, image, recycle


def photo(tmp_path, monkeypatch, key="1", color="red"):
    monkeypatch.setattr(importer, "deduplicate", lambda _: None)
    path = tmp_path / f"source-{key}.png"
    Image.new("RGB", (32, 24), color).save(path)
    raw = {"category": "twitter", "tweet_id": key, "num": 1, "author": {"name": "alice"}, "date": "2026-01-01T00:00:00Z"}
    identifier = importer.import_file(path, raw)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (identifier,))
    return identifier, path, raw


def run_restore(client, identifier, directory=None):
    result = client.post("/api/v1/admin/images/actions", json={"action": "restore", "ids": [identifier], "directory": directory})
    assert result.status_code == 200
    task = worker.claim(("restore",))
    assert task
    worker.execute(task)
    with db.connect() as conn:
        return dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone())


@pytest.mark.parametrize('action', ['delete_a', 'delete_b', 'delete_both'])
def test_recycle_duplicate_pair_without_deciding(client, tmp_path, monkeypatch, action):
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    first, _, _ = photo(tmp_path, monkeypatch)
    second, _, _ = photo(tmp_path, monkeypatch, '2', 'blue')
    with db.connect(True) as conn:
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (first,)).fetchone()[0]
        third = image(conn, group=group)
        conn.execute("INSERT INTO duplicate_decisions VALUES(?,?,'pending',.9)", (first, second))
        original_groups = conn.execute('SELECT id,group_id FROM images ORDER BY id').fetchall()
    url = '/api/v1/admin/duplicates'
    selected = {'delete_a': [first], 'delete_b': [second], 'delete_both': [first, second]}[action]
    response = client.post(url, json={'a': first, 'b': second, 'action': action})
    assert response.status_code == 200 and response.json()['ids'] == selected
    assert client.get(url).json() == []
    with db.connect() as conn:
        assert [row[0] for row in conn.execute('SELECT id FROM images WHERE hidden=1 ORDER BY id')] == selected
        assert conn.execute('SELECT hidden FROM images WHERE id=?', (third,)).fetchone()[0] == 0
        assert conn.execute('SELECT id,group_id FROM images ORDER BY id').fetchall() == original_groups
        assert conn.execute('SELECT decision FROM duplicate_decisions').fetchone()[0] == 'pending'
    for identifier in selected:
        assert run_restore(client, identifier)['status'] == 'done'
    assert [(row['a'], row['b']) for row in client.get(url).json()] == [(first, second)]


def test_recycle_duplicate_pair_is_atomic(client):
    with db.connect(True) as conn:
        first, second = image(conn), image(conn)
        conn.execute("INSERT INTO tasks(kind,image_id,status) VALUES('detect',?,'running')", (second,))
    pair = {'a': first, 'b': second}
    url = '/api/v1/admin/duplicates'
    assert client.post(url, json={**pair, 'action': 'delete_both'}).status_code == 409
    assert client.get('/api/v1/admin/trash').json()['total'] == 0
    assert client.post(url, json={**pair, 'action': 'delete_a'}).status_code == 200
    assert client.post(url, json={**pair, 'action': 'delete_b'}).status_code == 409


def test_group_scope_over_page_limit_and_stale_confirmation(client):
    with db.connect(True) as conn:
        first = image(conn, faces=False)
        for _ in range(505):
            image(conn, faces=False, group=first)
        other = image(conn, faces=False)
    preview = client.post("/api/v1/admin/images/recycle-preview", json={"ids": [first, first]}).json()
    assert preview["total"] == 506 and preview["groups"] == 1
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET group_id=? WHERE id=?", (first, other))
    result = client.post("/api/v1/admin/images/actions", json={"action": "delete", "ids": [first], "scope_token": preview["scope_token"]})
    assert result.status_code == 409
    assert recycle(client, [first]).json()["deleted"] == 507
    assert recycle(client, [first]).json()["deleted"] == 0
    last = client.get("/api/v1/admin/trash?page=999").json()
    assert last["total"] == 507 and last["page"] == 11 and len(last["items"]) == 7
    assert client.get("/api/v1/admin/images?state=all").json() == []


def test_group_running_member_blocks_entire_recycle(client):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn, group=first)
        conn.execute("INSERT INTO tasks(kind,image_id,status) VALUES('detect',?,'running')", (second,))
    assert recycle(client, [first]).status_code == 409
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM images WHERE hidden=1").fetchone()[0] == 0


def test_reimport_never_resurrects_and_remembers_new_source(client, tmp_path, monkeypatch):
    identifier, path, raw = photo(tmp_path, monkeypatch)
    assert recycle(client, [identifier]).status_code == 200
    with db.connect() as conn:
        before = dict(conn.execute("SELECT * FROM images WHERE id=?", (identifier,)).fetchone())
    assert not (db.DATA / "images" / before["filename"]).exists()
    assert not list((db.DATA / "originals").iterdir())
    assert (db.DATA / "thumbs" / before["filename"]).exists()
    counts = {"imported": 0, "skipped_existing": 0, "skipped_trashed": 0}
    assert importer.import_file(path, raw, counts=counts) == identifier
    assert importer.import_file(path, {**raw, "tweet_id": "2"}, counts=counts) == identifier
    assert counts["skipped_trashed"] == 2
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sources WHERE image_id=?", (identifier,)).fetchone()[0] == 2
        assert dict(conn.execute("SELECT * FROM images WHERE id=?", (identifier,)).fetchone()) == before
    assert not (db.DATA / "images" / before["filename"]).exists()
    assert client.get(f"/api/v1/admin/media/{identifier}").status_code == 404
    assert client.get(f"/api/v1/admin/media/{identifier}?thumbnail=true").status_code == 200


@pytest.mark.parametrize("platform,post", [("twitter", {"tweet_id": "1"}), ("instagram", {"post_id": "1"})])
def test_skip_before_media_request_and_restore_only_target(client, monkeypatch, tmp_path, platform, post):
    from gallery_dl.job import DownloadJob
    with db.connect(True) as conn:
        existing = image(conn)
        trashed = image(conn)
        conn.execute("UPDATE images SET hidden=1 WHERE id=?", (trashed,))
        conn.execute("UPDATE posts SET platform=?", ("x" if platform == "twitter" else platform,))
    calls = []
    monkeypatch.setattr(DownloadJob, "handle_url", lambda self, url, raw: calls.append(raw["num"]))
    original = DownloadJob.handle_url
    report = tmp_path / "skipped.jsonl"
    install_library_filter(report)
    job = SimpleNamespace(extractor=SimpleNamespace(category=platform))
    raw = {**post, "num": 1, "date": "2026-01-01", "author": {"name": "alice"}}
    DownloadJob.handle_url(job, "https://cdn.invalid/known", raw)
    key = next(iter(post))
    DownloadJob.handle_url(job, "https://cdn.invalid/trashed", {**raw, key: "2"})
    DownloadJob.handle_url(job, "https://cdn.invalid/new", {**raw, "num": 2})
    assert calls == [2]
    assert len(report.read_text().splitlines()) == 2
    monkeypatch.setattr(DownloadJob, "handle_url", original)
    install_library_filter(restore_id=trashed)
    DownloadJob.handle_url(job, "https://cdn.invalid/other", raw)
    DownloadJob.handle_url(job, "https://cdn.invalid/target", {**raw, key: "2"})
    DownloadJob.handle_url(job, "https://cdn.invalid/new", {**raw, "num": 3})
    assert calls == [2, 1]


def test_restore_local_retains_identity_reviews_and_references(client, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "IMPORT", tmp_path)
    identifier, path, raw = photo(tmp_path, monkeypatch)
    other, _, _ = photo(tmp_path, monkeypatch, "2", "blue")
    person = client.post("/api/v1/admin/people", json={"name": "Alice"}).json()["id"]
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET group_id=(SELECT group_id FROM images WHERE id=?) WHERE id=?", (identifier, other))
        conn.execute("INSERT INTO faces(image_id,box,person_id,locked,embedding,model_version) VALUES(?, '[0,0,10,10]', ?,1,?,?)", (identifier, person, bytes(2048), worker.MODEL_VERSION))
        face = conn.execute("SELECT id FROM faces WHERE image_id=?", (identifier,)).fetchone()[0]
        conn.execute("INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(?,?,?,?,?)", (person, identifier, face, bytes(2048), worker.MODEL_VERSION))
        conn.execute("INSERT INTO review_history(face_id,before_json,after_revision) VALUES(?,'{}',0)", (face,))
    assert recycle(client, [identifier]).json()["deleted"] == 2
    assert client.get("/api/v1/people").json()[0]["reference_count"] == 0
    trashed = {item["id"]: item for item in client.get("/api/v1/admin/trash").json()["items"]}
    assert trashed[identifier]["has_references"] is True
    assert trashed[other]["has_references"] is False
    assert client.put(f"/api/v1/admin/faces/{face}", json={"person_id": person, "revision": 0}).status_code == 409
    assert client.post("/api/v1/admin/images/actions", json={"action": "redetect", "ids": [identifier]}).status_code == 409
    result = run_restore(client, identifier)
    assert result["status"] == "done", result
    assert client.get("/api/v1/people").json()[0]["reference_count"] == 1
    with db.connect() as conn:
        restored = conn.execute("SELECT * FROM images WHERE id=?", (identifier,)).fetchone()
        assert not restored["hidden"] and restored["trashed_at"] is None
        assert conn.execute("SELECT hidden FROM images WHERE id=?", (other,)).fetchone()[0] == 1
        assert conn.execute("SELECT person_id,locked FROM faces WHERE id=?", (face,)).fetchone()[:] == (person, 1)
        assert conn.execute("SELECT count(*) FROM review_history").fetchone()[0] == 1
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    assert path.exists()
    assert client.get(f"/api/v1/admin/media/{identifier}").status_code == 200


def test_restore_scans_selected_directory_and_fails_for_changed_bytes(client, tmp_path, monkeypatch):
    identifier, path, raw = photo(tmp_path, monkeypatch)
    monkeypatch.setattr(importer, "IMPORT", tmp_path)
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET url=NULL")
    assert recycle(client, [identifier]).status_code == 200
    path.unlink()
    Image.new("RGB", (32, 24), "blue").save(path)
    result = run_restore(client, identifier, ".")
    assert result["status"] == "failed"
    assert "原文件" in result["error"]
    Image.new("RGB", (32, 24), "red").save(path)
    result = run_restore(client, identifier, ".")
    assert result["status"] == "done", result


def test_restore_remote_checks_hash_and_scopes_download(client, tmp_path, monkeypatch):
    identifier, path, raw = photo(tmp_path, monkeypatch)
    assert recycle(client, [identifier]).status_code == 200
    calls = []
    def download(task, payload, attempt, restore_id=None):
        calls.append(restore_id)
        folder = attempt / "media"
        folder.mkdir()
        Image.new("RGB", (32, 24), "blue" if len(calls) == 1 else "red").save(folder / "target.png")
        return folder
    monkeypatch.setattr(worker, "download_media", download)
    assert run_restore(client, identifier)["status"] == "failed"
    assert run_restore(client, identifier)["status"] == "done"
    assert calls == [identifier, identifier]


def test_cancel_duplicate_restore_and_late_cleanup(client, tmp_path, monkeypatch):
    identifier, path, raw = photo(tmp_path, monkeypatch)
    monkeypatch.setattr(db, "cleanup_deleted_files", lambda: 2)
    assert recycle(client, [identifier]).status_code == 200
    body = {"action": "restore", "ids": [identifier]}
    first = client.post("/api/v1/admin/images/actions", json=body).json()["tasks"][0]["task_id"]
    assert client.post("/api/v1/admin/images/actions", json=body).json()["tasks"][0]["task_id"] == first
    assert client.post(f"/api/v1/admin/tasks/{first}/cancel").status_code == 200
    assert client.post(f"/api/v1/admin/tasks/{first}/retry").status_code == 200
    task = worker.claim(("restore",))
    assert client.post(f"/api/v1/admin/tasks/{first}/cancel").status_code == 200
    worker.execute(task)
    with db.connect() as conn:
        assert conn.execute("SELECT hidden FROM images WHERE id=?", (identifier,)).fetchone()[0] == 1
    assert run_restore(client, identifier)["status"] == "done"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM pending_file_deletions").fetchone()[0] == 0


def test_migration_only_existing_hidden_members_and_idempotent(client, tmp_path, monkeypatch):
    first, _, _ = photo(tmp_path, monkeypatch)
    second, _, _ = photo(tmp_path, monkeypatch, "2", "blue")
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET group_id=(SELECT group_id FROM images WHERE id=?) WHERE id=?", (first, second))
        conn.execute("UPDATE images SET hidden=1 WHERE id=?", (first,))
        conn.execute("UPDATE schema_version SET version=8")
    db.init()
    db.cleanup_deleted_files()
    db.init()
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM images ORDER BY id").fetchall()
        assert rows[0]["hidden"] and rows[0]["trashed_at"]
        assert not rows[1]["hidden"]
        assert conn.execute("SELECT count(*) FROM pending_file_deletions").fetchone()[0] == 0
    assert not (db.DATA / "images" / rows[0]["filename"]).exists()
    assert (db.DATA / "thumbs" / rows[0]["filename"]).exists()
    assert (db.DATA / "images" / rows[1]["filename"]).exists()


def test_download_skip_updates_metadata_and_zero_files_is_success(client, tmp_path, monkeypatch):
    from app.download_round import DownloadRound
    _, _, raw = photo(tmp_path, monkeypatch)
    def download(task, payload, attempt, restore_id=None):
        meta = importer.metadata({**raw, "content": "updated caption"}, "")
        active = DownloadRound(task['id'], task['rounds'])
        assert active.skip(meta) and active.skip(meta)
    monkeypatch.setattr(worker, "download_media", download)
    task_id = client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]}).json()[0]["task_id"]
    worker.execute(worker.claim(("download",)))
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert task["status"] == "done"
        assert json.loads(task["result"]) == {"imported": 0, "skipped_existing": 1, "skipped_trashed": 0}
        assert conn.execute("SELECT post_text FROM posts").fetchone()[0] == "updated caption"


def test_legacy_actions_cannot_delete_files(client):
    with db.connect(True) as conn:
        identifier = image(conn)
    for action in ("hide", "show", "delete"):
        assert client.post("/api/v1/admin/images/actions", json={"action": action, "ids": [identifier]}).status_code == 409
    client.cookies.clear()
    assert client.get("/api/v1/admin/trash").status_code == 401
    assert client.post("/api/v1/admin/images/recycle-preview", json={"ids": [identifier]}).status_code == 401


def test_cleanup_serializes_with_restore_commit(client, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    identifier, path, _ = photo(tmp_path, monkeypatch)
    original_unlink = Path.unlink
    def blocked(file, *args, **kwargs):
        if file.parent in (db.DATA / "images", db.DATA / "originals"):
            raise PermissionError("busy")
        return original_unlink(file, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", blocked)
    assert recycle(client, [identifier]).json()["cleanup_pending"] == 2
    monkeypatch.setattr(Path, "unlink", original_unlink)
    client.post("/api/v1/admin/images/actions", json={"action": "restore", "ids": [identifier]})
    task = worker.claim(("restore",))
    written, release, cleaning = Event(), Event(), Event()
    original_write = importer.write_assets
    def pause_after_write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        written.set()
        assert release.wait(10)
        return result
    monkeypatch.setattr(importer, "write_assets", pause_after_write)
    def cleanup():
        cleaning.set()
        return db.cleanup_deleted_files()
    with ThreadPoolExecutor(max_workers=2) as executor:
        restoring = executor.submit(worker.execute, task)
        try:
            assert written.wait(10)
            removing = executor.submit(cleanup)
            assert cleaning.wait(10)
            assert not removing.done()
        finally:
            release.set()
        restoring.result(timeout=10)
        assert removing.result(timeout=10) == 0
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id=?", (identifier,)).fetchone()
        assert not row["hidden"]
    assert (db.DATA / "originals" / row["original_filename"]).read_bytes() == path.read_bytes()
    assert (db.DATA / "images" / row["filename"]).is_file()


def test_startup_cleans_assets_left_by_interrupted_restore(client, tmp_path, monkeypatch):
    identifier, path, _ = photo(tmp_path, monkeypatch)
    assert recycle(client, [identifier]).status_code == 200
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id=?", (identifier,)).fetchone()
    # Simulate a process exit after writing files but before committing activation.
    importer.write_assets(path, row["sha256"])
    db.init()
    assert db.cleanup_deleted_files() == 0
    assert not (db.DATA / "images" / row["filename"]).exists()
    assert not list((db.DATA / "originals").iterdir())
    assert (db.DATA / "thumbs" / row["filename"]).exists()


def test_missing_group_member_prevents_automatic_merge(client, monkeypatch):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn)
        missing = image(conn, group=second)
        conn.execute("UPDATE images SET phash='0'")
        conn.execute("UPDATE images SET hidden=1,filename='missing.jpg' WHERE id=?", (missing,))
    (db.DATA / "images" / "fixture.jpg").write_bytes(b"fixture")
    monkeypatch.setattr(importer, "similarity", lambda *args: 1)
    importer.deduplicate(first)
    with db.connect() as conn:
        assert conn.execute("SELECT count(DISTINCT group_id) FROM images").fetchone()[0] == 2
        assert conn.execute("SELECT decision FROM duplicate_decisions WHERE a=? AND b=?", (first, second)).fetchone()[0] == "pending"
        assert not conn.execute("SELECT 1 FROM duplicate_decisions WHERE a=? OR b=?", (missing, missing)).fetchone()
