"""Image lifecycle. Records outlive the full-size files they describe."""
import hashlib
import json

from fastapi import HTTPException
from . import db as storage


def require_active(db, image_id):
    row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        raise HTTPException(404, "图片不存在")
    if row["hidden"]:
        raise HTTPException(409, "图片在回收站中，请先恢复")
    return row


def require_active_face(db, face_id):
    row = db.execute("SELECT image_id FROM faces WHERE id=?", (face_id,)).fetchone()
    if not row:
        raise HTTPException(404, "人脸不存在")
    return require_active(db, row[0])


def scope(db, ids):
    ids = sorted(set(ids))
    marks = ",".join("?" for _ in ids)
    selected = db.execute(f"SELECT id,group_id FROM images WHERE id IN ({marks})", ids).fetchall()
    if len(selected) != len(ids):
        raise HTTPException(404, "部分图片已不存在，请刷新后重新选择")
    # Only input IDs are bound, so a group may contain more than 500 members.
    rows = db.execute(
        f"SELECT * FROM images WHERE group_id IN (SELECT group_id FROM images WHERE id IN ({marks})) ORDER BY id", ids,
    ).fetchall()
    signature = [(r["id"], r["group_id"], r["hidden"]) for r in rows]
    return rows, hashlib.sha256(json.dumps(signature).encode()).hexdigest()


def preview(db, ids):
    rows, token = scope(db, ids)
    return {
        "scope_token": token, "ids": [r["id"] for r in rows],
        "groups": len({r["group_id"] for r in rows}), "total": len(rows),
        "already_trashed": sum(bool(r["hidden"]) for r in rows),
    }


def has_references(db, image_ids):
    if not image_ids:
        return False
    marks = ",".join("?" for _ in image_ids)
    return bool(db.execute(
        f"SELECT 1 FROM reference_images WHERE image_id IN ({marks}) LIMIT 1",
        image_ids,
    ).fetchone())


def recycle(ids, token):
    with storage.connect(True) as db:
        rows, actual = scope(db, ids)
        if not token or token != actual:
            raise HTTPException(409, "重复组成员或回收状态已变化，请刷新后重新确认")
        if db.execute("SELECT 1 FROM tasks WHERE status='running' AND kind IN ('download','import')").fetchone():
            raise HTTPException(409, "下载或导入任务正在运行，请等待完成或取消后重试")
        for row in rows:
            if db.execute("SELECT 1 FROM tasks WHERE image_id=? AND status='running'", (row["id"],)).fetchone():
                raise HTTPException(409, "组内图片正在处理，请等待完成或取消后重试")
        changed = [r for r in rows if not r["hidden"]]
        references_changed = has_references(db, [row["id"] for row in changed])
        for row in rows:
            db.execute("UPDATE tasks SET status='cancelled',stage='已取消',cancel_requested=1,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE image_id=? AND status='queued'", (row["id"],))
        for row in changed:
            db.execute("UPDATE images SET hidden=1,trashed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (row["id"],))
            storage.queue_image_cleanup(db, row)
        if references_changed:
            storage.schedule_rematch(db)
    pending = storage.cleanup_deleted_files()
    return {"ok": True, "deleted": len(changed), "ids": [r["id"] for r in rows], "cleanup_pending": pending}


def enqueue_restore(ids, directory=None):
    from .importer import safe_directory
    if directory is not None:
        safe_directory(directory)
    with storage.connect(True) as db:
        rows = []
        for image_id in sorted(set(ids)):
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
            if not row:
                raise HTTPException(404, "图片不存在")
            rows.append(row)
        tasks = []
        for row in rows:
            if not row["hidden"]:
                continue
            active = db.execute("SELECT id FROM tasks WHERE image_id=? AND kind='restore' AND status IN ('queued','running')", (row["id"],)).fetchone()
            task_id = active[0] if active else db.execute(
                "INSERT INTO tasks(kind,image_id,payload) VALUES('restore',?,?)",
                (row["id"], json.dumps({"directory": directory})),
            ).lastrowid
            tasks.append({"image_id": row["id"], "task_id": task_id})
        return {"ok": True, "tasks": tasks}


def restore_file(task, path):
    from .importer import write_assets, record_location
    from .vision import DetectionCancelled
    # Serializes existing-original reuse, writes, and activation with cleanup.
    with storage.connect(True) as db:
        current = db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
        if not current or current["cancel_requested"] or current["status"] != "running":
            raise DetectionCancelled()
        row = db.execute("SELECT * FROM images WHERE id=?", (task["image_id"],)).fetchone()
        if not row or not row["hidden"]:
            return True
        if not path.is_file() or storage.file_hash(path) != row["sha256"]:
            return False
        references_changed = has_references(db, [row["id"]])
        filename, width, height, original = write_assets(path, row["sha256"], refresh=True)
        db.execute(
            "UPDATE images SET hidden=0,trashed_at=NULL,image_evicted=0,original_evicted=0,cache_retry_at=0,image_used=unixepoch(),original_used=unixepoch(),filename=?,width=?,height=?,original_filename=?,image_sha256=?,thumbnail_sha256=?,file_size=? WHERE id=?",
            (filename, width, height, original, storage.file_hash(storage.DATA / "images" / filename),
             storage.file_hash(storage.DATA / "thumbs" / filename), path.stat().st_size, row["id"]),
        )
        db.execute("DELETE FROM pending_file_deletions WHERE sha256=?", (row["sha256"],))
        record_location(db, row["id"], path)
        if row["detection"] != "done":
            storage.schedule_detection(db, row["id"])
        if references_changed:
            storage.schedule_rematch(db)
        # Commit completion with activation: a late cancellation cannot report a
        # successful restore as cancelled, or let a retry reapply old intent.
        db.execute("UPDATE tasks SET status='done',stage='已恢复',done=1,total=1,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (task["id"],))
    return True
