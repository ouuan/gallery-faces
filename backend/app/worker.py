import argparse
import os
import signal
import threading
import math
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import tempfile
from .security import download_url, cookie_bytes, save_cookie
import time
from pathlib import Path
from .db import DATA, connect, init, settings, unknown_sql, cleanup_deleted_files
from .vision import (
    Vision,
    MODEL_VERSION,
    candidates,
    install_models,
    validate_embedding,
    DetectionCancelled,
)
from .importer import EXTENSIONS, import_file, safe_directory


def rematch(task):
    started = time.monotonic()
    while True:
        with connect(True) as db:
            config = settings(db)
            version = int(config["reference_version"])
            refs = db.execute(
                "SELECT person_id,embedding,model_version FROM reference_images WHERE model_version=?",
                (MODEL_VERSION,),
            ).fetchall()
            faces = db.execute(
                f"SELECT * FROM faces WHERE image_id=? AND {unknown_sql()} AND embedding IS NOT NULL",
                (task["image_id"],),
            ).fetchall()
            db.execute(
                "UPDATE tasks SET target_version=?,stage='匹配人物',total=?,done=0,speed=0 WHERE id=?",
                (version, len(faces), task["id"]),
            )
        for index, face in enumerate(faces, start=1):
            if cancelled(task["id"]):
                raise DetectionCancelled()
            validate_embedding(face["embedding"], face["model_version"])
            result = candidates(face["embedding"], refs)
            person = (
                result[0]["person_id"]
                if result
                and result[0]["score"] >= float(config["threshold"])
                and result[0]["score"] - (result[1]["score"] if len(result) > 1 else -1)
                >= float(config["margin"])
                else None
            )
            with connect(True) as db:
                if db.execute(
                    "SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],)
                ).fetchone()[0]:
                    db.execute(
                        "UPDATE tasks SET status='cancelled',stage='已取消' WHERE id=?",
                        (task["id"],),
                    )
                    return
                db.execute(
                    "UPDATE tasks SET done=?,speed=? WHERE id=?",
                    (index, index / max(time.monotonic() - started, 0.01), task["id"]),
                )
                # References (including deleted people) may change while scoring.
                # Discard that result and let the next pass use current references.
                if int(settings(db)["reference_version"]) != version:
                    continue
                db.execute(
                    f"UPDATE faces SET candidates=?,person_id=?,revision=revision+1 WHERE id=? AND revision=? AND {unknown_sql()}",
                    (json.dumps(result), person, face["id"], face["revision"]),
                )
        with connect(True) as db:
            if db.execute(
                "SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()[0]:
                raise DetectionCancelled()
            latest = int(settings(db)["reference_version"])
            unknown = db.execute(
                f"SELECT 1 FROM faces WHERE image_id=? AND {unknown_sql()} AND embedding IS NOT NULL",
                (task["image_id"],),
            ).fetchone()
            db.execute(
                "UPDATE tasks SET processed_version=?,done=total WHERE id=?",
                (version, task["id"]),
            )
            if latest <= version or not unknown:
                db.execute(
                    "UPDATE tasks SET status='done',stage='已完成' WHERE id=?",
                    (task["id"],),
                )
                return
            # Reuse this same running task when references changed during work.


def detect(task):
    started = time.monotonic()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM images WHERE id=?", (task["image_id"],)
        ).fetchone()
        detection_threshold = float(settings(db)["detection_threshold"])
    faces = Vision().detect(
        DATA / "images" / row["filename"],
        mode=json.loads(task["payload"]).get("mode", "auto"),
        cancel=lambda: cancelled(task["id"]),
        threshold=detection_threshold,
    )
    with connect(True) as db:
        if db.execute(
            "SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],)
        ).fetchone()[0]:
            raise DetectionCancelled()
        # Retain all human decisions and accepted labels on explicit redetection.
        db.execute(
            "DELETE FROM faces WHERE image_id=? AND locked=0 AND person_id IS NULL AND ignored=0",
            (row["id"],),
        )
        preserved = db.execute(
            "SELECT box FROM faces WHERE image_id=?", (row["id"],)
        ).fetchall()
        for box, embedding in faces:

            def overlaps(old):
                x, y, w, h = json.loads(old[0])
                a, b, c, d = box
                intersection = max(0, min(x + w, a + c) - max(x, a)) * max(
                    0, min(y + h, b + d) - max(y, b)
                )
                return intersection / max(1, min(w * h, c * d)) > 0.5

            if any(overlaps(old) for old in preserved):
                continue
            db.execute(
                "INSERT INTO faces(image_id,box,embedding,model_version) VALUES(?,?,?,?)",
                (row["id"], json.dumps(box), embedding, MODEL_VERSION),
            )
        db.execute(
            "UPDATE images SET detection='done',error=NULL WHERE id=?", (row["id"],)
        )
        version = int(settings(db)["reference_version"])
        db.execute(
            "INSERT OR IGNORE INTO tasks(kind,image_id,target_version) VALUES('rematch',?,?)",
            (row["id"], version),
        )
        db.execute(
            "UPDATE tasks SET done=1,total=1,speed=? WHERE id=?",
            (1 / max(time.monotonic() - started, 0.01), task["id"]),
        )


def cancelled(task_id):
    with connect() as db:
        return bool(
            db.execute(
                "SELECT cancel_requested FROM tasks WHERE id=?", (task_id,)
            ).fetchone()[0]
        )


def import_task(task):
    if task["kind"] == "download":
        root = DATA / "downloads"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix="attempt-") as attempt:
            return _import_task(task, Path(attempt))
    return _import_task(task)


def _import_task(task, attempt=None):
    payload = json.loads(task["payload"])
    if task["kind"] == "download":
        platform, payload["url"] = download_url(payload["url"])
        directory = attempt / "media"
        directory.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "app.downloader",
            "--write-metadata",
            "--ignore-config",
            "-D",
            str(directory),
            "-o",
            "skip=false",
            "--filter",
            "extension not in ('mp4', 'webm', 'gif')",
        ]
        cookie = DATA / "cookies" / f"{platform}.txt"
        if cookie.exists():
            snapshot = attempt / "cookies.txt"
            save_cookie(snapshot, cookie_bytes(cookie.read_bytes(), platform))
            command += ["--cookies", str(snapshot)]
        command += [payload["url"]]
        policy_report = attempt / "policy-error.txt"
        # Never capture downloader output: it can contain cookies, signed URLs, or credentials.
        # The separate report contains only a policy reason and network destination.
        with subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "GALLERY_FACES_POLICY_REPORT": str(policy_report)},
        ) as process:
            while process.poll() is None:
                if cancelled(task["id"]):
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    return
                time.sleep(0.5)
            if process.returncode:
                try:
                    policy_reason = policy_report.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeError):
                    policy_reason = ""
                messages = {
                    20: "账号非公开或无法确认公开状态",
                    21: "下载被安全策略拒绝",
                }
                raise ValueError(
                    policy_reason or messages.get(
                        process.returncode,
                        "下载失败，请检查平台 cookies、链接和网络后重试",
                    )
                )
    else:
        directory = safe_directory(payload["directory"])
    paths = sorted(
        p
        for p in directory.rglob("*")
        if p.suffix.lower() in EXTENSIONS
        and p.resolve().is_relative_to(directory.resolve())
    )
    started = time.monotonic()
    errors = []
    with connect(True) as db:
        db.execute(
            "UPDATE tasks SET stage='导入图片',total=?,done=0 WHERE id=?",
            (len(paths), task["id"]),
        )
    for index, path in enumerate(paths):
        if cancelled(task["id"]):
            return
        try:
            sidecar = next(
                (
                    p
                    for p in (Path(str(path) + ".json"), path.with_suffix(".json"))
                    if p.exists()
                ),
                None,
            )
            if not sidecar:
                raise ValueError("缺少 JSON sidecar")
            if not sidecar.resolve().is_relative_to(directory.resolve()):
                raise ValueError("Sidecar 不在导入目录中")
            raw = json.loads(sidecar.read_text())
            if task["kind"] == "download":
                from urllib.parse import urlparse

                raw["collected_account"] = (
                    urlparse(payload["url"]).path.strip("/").split("/")[0]
                )
            import_file(path, raw, payload.get("start"), payload.get("end"))
        except Exception as error:
            errors.append(f"{path.name}: {type(error).__name__}")
        with connect(True) as db:
            db.execute(
                "UPDATE tasks SET done=?,speed=?,error=? WHERE id=?",
                (
                    index + 1,
                    (index + 1) / max(time.monotonic() - started, 0.01),
                    "\n".join(errors) or None,
                    task["id"],
                ),
            )
    if errors:
        raise ValueError(
            f"{len(errors)} 张图片导入失败；成功项目已保留。" + "\n".join(errors)
        )


def claim(kinds=("detect", "rematch", "import", "download")):
    with connect(True) as db:
        placeholders = ",".join("?" for _ in kinds)
        task = db.execute(
            f"""
            SELECT t.* FROM tasks t WHERE t.status='queued' AND t.kind IN ({placeholders})
            AND NOT EXISTS (SELECT 1 FROM tasks prior WHERE prior.image_id=t.image_id
                AND prior.status IN ('queued','running') AND prior.id<t.id)
            AND NOT EXISTS (SELECT 1 FROM tasks running WHERE running.image_id=t.image_id AND running.status='running')
            ORDER BY t.id LIMIT 1
        """,
            kinds,
        ).fetchone()
        if not task:
            return None
        task = dict(task)
        db.execute(
            "UPDATE tasks SET status='running',stage=?,done=0,speed=0,total=CASE WHEN kind='detect' THEN 1 ELSE 0 END WHERE id=?",
            ("检测人脸" if task["kind"] == "detect" else "开始处理", task["id"]),
        )
        return task


def step():
    task = claim()
    if task is None:
        return False
    execute(task)
    return True


def execute(task):
    try:
        if cancelled(task["id"]):
            raise DetectionCancelled()
        if task["kind"] == "rematch":
            rematch(task)
            return True
        if task["kind"] == "detect":
            detect(task)
        else:
            import_task(task)
        with connect(True) as db:
            db.execute(
                "UPDATE tasks SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'done' END,stage=CASE WHEN cancel_requested THEN '已取消' ELSE '已完成' END WHERE id=?",
                (task["id"],),
            )
    except DetectionCancelled:
        with connect(True) as db:
            db.execute(
                "UPDATE tasks SET status='cancelled',stage='已取消' WHERE id=?",
                (task["id"],),
            )
    except Exception as error:
        with connect(True) as db:
            message = (
                str(error) if isinstance(error, ValueError) else type(error).__name__
            )
            db.execute(
                "UPDATE tasks SET status='failed',stage='处理失败',error=? WHERE id=?",
                (message, task["id"]),
            )
            if task["kind"] == "detect":
                db.execute(
                    "UPDATE images SET detection='failed',error=? WHERE id=?",
                    (message, task["image_id"]),
                )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-models", action="store_true")
    args = parser.parse_args()
    init()
    if args.install_models:
        install_models()
        return
    # Exactly one worker owns recovery and dispatch. OS lock also protects accidental duplicate workers.
    import fcntl

    with (DATA / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover_tasks()
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        run_worker(stop)


def recover_tasks():
    with connect(True) as db:
        db.execute(
            "UPDATE tasks SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'queued' END WHERE status='running'"
        )


def worker_concurrency():
    value = os.environ.get("WORKER_CONCURRENCY", "auto")
    if value != "auto":
        if not value.isdecimal() or int(value) < 1:
            raise ValueError("WORKER_CONCURRENCY must be auto or a positive integer")
        return int(value)
    cpus = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else (os.cpu_count() or 1)
    )
    # Inspect all visible cgroup ancestors, including parent container quotas.
    for root in (Path("/sys/fs/cgroup"), Path("/sys/fs/cgroup/cpu")):
        paths = [root]
        try:
            for line in Path("/proc/self/cgroup").read_text().splitlines():
                _, controllers, relative = line.split(":", 2)
                if not controllers or "cpu" in controllers.split(","):
                    child = root / relative.lstrip("/")
                    if child.is_relative_to(root) and ".." not in child.parts:
                        paths.extend(
                            [
                                child,
                                *[p for p in child.parents if p.is_relative_to(root)],
                            ]
                        )
        except OSError:
            pass
        for path in paths:
            try:
                quota, period = (path / "cpu.max").read_text().split()
                if quota != "max":
                    cpus = min(cpus, max(1, math.floor(int(quota) / int(period))))
            except (OSError, ValueError):
                try:
                    quota = int((path / "cpu.cfs_quota_us").read_text())
                    period = int((path / "cpu.cfs_period_us").read_text())
                    if quota > 0:
                        cpus = min(cpus, max(1, math.floor(quota / period)))
                except (OSError, ValueError):
                    pass
    return max(1, min(4, cpus))


def run_worker(stop):
    concurrency = worker_concurrency()
    with (
        ThreadPoolExecutor(max_workers=concurrency) as compute,
        ThreadPoolExecutor(max_workers=1) as io,
    ):
        running = {compute: set(), io: set()}
        while not stop.is_set():
            for executor, limit, kinds in (
                (compute, concurrency, ("detect", "rematch")),
                (io, 1, ("download", "import")),
            ):
                finished = {future for future in running[executor] if future.done()}
                for future in finished:
                    future.result()
                running[executor] -= finished
                while len(running[executor]) < limit and not stop.is_set():
                    task = claim(kinds)
                    if task is None:
                        break
                    running[executor].add(executor.submit(execute, task))
            cleanup_deleted_files()
            stop.wait(0.1)


if __name__ == "__main__":
    main()
