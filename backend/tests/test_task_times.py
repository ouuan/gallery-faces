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
    assert record(client)["finished_at"] is None

    def process(task):
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
    assert datetime.fromisoformat(created) <= datetime.fromisoformat(result["finished_at"])
    if outcome != "done":
        client.post(f"/api/v1/admin/tasks/{task_id}/retry")
        assert record(client)["finished_at"] is None
        assert record(client)["created_at"] == created
        monkeypatch.setattr(worker, "import_task", lambda task: None)
        worker.step()
        assert record(client)["status"] == "done"
        assert record(client)["finished_at"]


def test_cancel_queued_task_time(client):
    task_id = client.post("/api/v1/admin/import", json={"urls": ["https://x.com/alice"]}).json()[0]["task_id"]
    client.post(f"/api/v1/admin/tasks/{task_id}/cancel")
    assert record(client)["finished_at"].endswith("Z")


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
        conn.execute("ALTER TABLE tasks DROP COLUMN finished_at")
        conn.execute("INSERT INTO tasks(kind,status) VALUES('download','done')")
    db.init()
    db.init()
    assert record(client)["status"] == "done"
    assert record(client)["finished_at"] is None
