from datetime import datetime

import pytest

from app import db, worker
from test_workflows import client


def record(client):
    return client.get("/api/v1/admin/tasks").json()["items"][0]


@pytest.mark.parametrize("outcome", ["done", "failed", "cancelled"])
def test_task_finish_time_and_retry(client, monkeypatch, outcome):
    task_id = client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]}).json()[0]["task_id"]
    created = record(client)["created_at"]
    assert record(client)["started_at"] is None
    assert record(client)["finished_at"] is None

    def process(task):
        assert record(client)["round_started_at"] == record(client)["started_at"]
        assert record(client)["started_at"] is not None
        assert record(client)["finished_at"] is None
        if outcome == "failed":
            raise ValueError("test failure")
        if outcome == "cancelled":
            client.post(f"/api/v1/admin/tasks/{task_id}/cancel")
            assert record(client)["finished_at"] is None

    monkeypatch.setattr(worker, "import_task", process)
    worker.step()
    result = record(client)
    assert result["status"] == outcome
    assert datetime.fromisoformat(created) <= datetime.fromisoformat(result["started_at"]) <= datetime.fromisoformat(result["finished_at"])
    if outcome != "done":
        client.post(f"/api/v1/admin/tasks/{task_id}/retry")
        assert record(client)["started_at"] is None
        assert record(client)["round_started_at"] is None
        assert record(client)["finished_at"] is None
        assert record(client)["created_at"] == created
        monkeypatch.setattr(worker, "import_task", lambda task: None)
        worker.step()
        assert record(client)["status"] == "done"
        assert record(client)["finished_at"]
        assert record(client)["round_started_at"] == record(client)["started_at"] is not None


def test_cancel_queued_task_time(client):
    task_id = client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]}).json()[0]["task_id"]
    client.post(f"/api/v1/admin/tasks/{task_id}/cancel")
    assert record(client)["finished_at"].endswith("Z")
    assert record(client)["started_at"] is None


def test_round_start_advances_independently(client):
    task_id = client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]}).json()[0]["task_id"]
    worker.claim()
    first = '2020-01-01T00:00:00Z'
    with db.connect(True) as conn:
        conn.execute("UPDATE tasks SET started_at=?,round_started_at=strftime('%Y-%m-%dT%H:%M:%SZ','now','-2 minutes') WHERE id=?", (first, task_id))
        worker.requeue_round(conn, task_id)
    paused = record(client)
    assert 120 <= paused['elapsed_seconds'] <= 121
    assert paused['round_seconds'] is None
    worker.claim()
    row = record(client)
    assert row['rounds'] == 2
    assert row['started_at'] == first < row['round_started_at']
    assert row['elapsed_seconds'] == paused['elapsed_seconds'] + row['round_seconds']


def test_directory_task_has_no_round_time(client):
    with db.connect(True) as conn:
        conn.execute("INSERT INTO tasks(kind) VALUES('import')")
    worker.claim()
    assert record(client)['started_at'] is not None
    assert record(client)['round_started_at'] is None


@pytest.mark.parametrize("cancel", [False, True])
def test_recovery_times(client, cancel):
    client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]})
    task = worker.claim()
    if cancel:
        client.post(f"/api/v1/admin/tasks/{task['id']}/cancel")
    worker.recover_tasks()
    assert record(client)["status"] == ("cancelled" if cancel else "queued")
    assert bool(record(client)["finished_at"]) == cancel


def test_task_time_migration_keeps_unknown_history(client):
    with db.connect(True) as conn:
        conn.execute('DROP TRIGGER task_runtime')
        conn.execute('ALTER TABLE tasks DROP COLUMN runtime_seconds')
        conn.execute("ALTER TABLE tasks DROP COLUMN finished_at")
        conn.execute("ALTER TABLE tasks DROP COLUMN started_at")
        conn.execute("ALTER TABLE tasks DROP COLUMN round_started_at")
        conn.execute("INSERT INTO tasks(kind,status) VALUES('download','done')")
    db.init()
    db.init()
    assert record(client)["status"] == "done"
    assert record(client)["started_at"] is None
    assert record(client)["round_started_at"] is None
    assert record(client)["elapsed_seconds"] is None
    assert record(client)["finished_at"] is None
