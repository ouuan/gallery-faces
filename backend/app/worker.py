import argparse
import os
import signal
import threading
import math
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
import tempfile
from .security import download_url, cookie_bytes, save_cookie
import time
from pathlib import Path
from .db import DATA, connect, init, settings, unknown_sql, cleanup_deleted_files, ACTIVE_REFERENCE
from .vision import (
    Vision,
    MODEL_VERSION,
    candidates,
    install_models,
    validate_embedding,
    DetectionCancelled,
    release_idle_memory,
)
from .importer import EXTENSIONS, import_file, safe_directory
from .download_round import KINDS as DOWNLOAD_KINDS, ROUND_SECONDS, EMPTY_RESULT, STALL_LIMIT, RoundProgress, YieldRound, cleanup_ready, item_error_summary


def rematch(task):
    started = time.monotonic()
    refresh_all = json.loads(task.get("payload", "{}")).get("refresh_all", False)
    scope = "faces.ignored=0" if refresh_all else unknown_sql()
    eligible = f"{scope} AND embedding IS NOT NULL"
    if refresh_all:
        eligible += " AND length(embedding)>0"
    while True:
        with connect(True) as db:
            config = settings(db)
            version = int(config["reference_version"])
            refs = db.execute(
                f"SELECT person_id,embedding,model_version FROM reference_images WHERE model_version=? AND {ACTIVE_REFERENCE}",
                (MODEL_VERSION,),
            ).fetchall()
            faces = db.execute(
                f"SELECT * FROM faces WHERE image_id=? AND {eligible}",
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
                        "UPDATE tasks SET status='cancelled',finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),stage='已取消' WHERE id=?",
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
                # A completed match need not change the face. Compare values,
                # including the identity that will actually be saved for locked faces.
                saved_person = face["person_id"] if face["locked"] else person
                if json.loads(face["candidates"]) == result and face["person_id"] == saved_person:
                    continue
                db.execute(
                    f"UPDATE faces SET candidates=?,person_id=CASE WHEN locked=0 THEN ? ELSE person_id END,revision=revision+1 WHERE id=? AND revision=? AND {eligible}",
                    (json.dumps(result), person, face["id"], face["revision"]),
                )
        with connect(True) as db:
            if db.execute(
                "SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],)
            ).fetchone()[0]:
                raise DetectionCancelled()
            latest = int(settings(db)["reference_version"])
            remaining = db.execute(
                f"SELECT 1 FROM faces WHERE image_id=? AND {eligible}",
                (task["image_id"],),
            ).fetchone()
            db.execute(
                "UPDATE tasks SET processed_version=?,done=total WHERE id=?",
                (version, task["id"]),
            )
            if latest <= version or not remaining:
                db.execute(
                    "UPDATE tasks SET status='done',finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),stage='已完成' WHERE id=?",
                    (task["id"],),
                )
                return
            # Reuse this same running task when references changed during work.


def detect(task):
    started = time.monotonic()
    mode = json.loads(task["payload"]).get("mode", "auto")
    with connect() as db:
        row = db.execute(
            "SELECT * FROM images WHERE id=?", (task["image_id"],)
        ).fetchone()
        detection_threshold = float(settings(db)["detection_threshold"])
    from .media_cache import asset
    with asset(row, 'image') as path:
        faces = Vision().detect(path, mode=mode, cancel=lambda: cancelled(task["id"]), threshold=detection_threshold)
    with connect(True) as db:
        if db.execute(
            "SELECT cancel_requested FROM tasks WHERE id=?", (task["id"],)
        ).fetchone()[0]:
            raise DetectionCancelled()
        # Preserve manual boxes and labeled faces; rematching may revise unlocked labels.
        db.execute(
            "DELETE FROM faces WHERE image_id=? AND locked=0 AND person_id IS NULL AND ignored=0 AND embedding IS NOT NULL AND length(embedding)>0",
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
        scope = (
            "ignored=0 AND embedding IS NOT NULL AND length(embedding)>0"
            if mode == "highres"
            else f"{unknown_sql()} AND embedding IS NOT NULL AND length(embedding)>0"
        )
        db.execute(
            f"""
            INSERT OR IGNORE INTO tasks(kind,image_id,target_version)
            SELECT 'rematch', ?, ?
            WHERE EXISTS(SELECT 1 FROM faces WHERE image_id=? AND {scope})
            """,
            (row["id"], version, row["id"]),
        )
        if mode == "highres":
            # Detection and matching are serialized per image. Upgrade any queued
            # rematch in place so deduplication cannot lose the full refresh request.
            db.execute(
                "UPDATE tasks SET payload=json_set(payload,'$.refresh_all',json('true')),target_version=? WHERE kind='rematch' AND image_id=? AND status='queued'",
                (version, row["id"]),
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
    if task["kind"] in ("download", "monitor"):
        root = DATA / "downloads"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root, prefix="attempt-") as attempt:
            return _import_task(task, Path(attempt))
    return _import_task(task)


def download_media(task, payload, attempt, restore_id=None):
    sliced = task is not None and task['kind'] in DOWNLOAD_KINDS
    payload = dict(payload)
    platform, payload["url"] = download_url(payload["url"])
    directory = attempt / "media"
    directory.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "app.downloader",
        "--ignore-config",
        "-D",
        str(directory),
        "-o",
        "skip=false",
        "--filter",
        (f"extension.lower() in {tuple(sorted(ext[1:] for ext in EXTENSIONS))!r}" if sliced else "extension not in ('mp4', 'webm', 'gif')"),
    ]
    if not sliced:
        command.insert(3, '--write-metadata')
    from .downloader import date_options
    command += date_options(payload.get("start"), payload.get("end"))
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
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=sliced,
        env={
            **os.environ,
            "DATA_DIR": str(DATA),
            'GALLERY_FACES_PARENT': str(os.getpid()),
            'GALLERY_FACES_ROUND': f"{task['id']}:{task['rounds']}" if sliced else '',
            'GALLERY_FACES_MEDIA_DIR': str(directory),
            "GALLERY_FACES_POLICY_REPORT": str(policy_report),
            "GALLERY_FACES_SKIPPED_REPORT": str(attempt / "skipped.jsonl"),
            "GALLERY_FACES_HASHTAGS": json.dumps(payload.get("hashtags", [])),
            "GALLERY_FACES_RESTORE_IMAGE": str(restore_id) if restore_id is not None else "",
            "GALLERY_FACES_CACHE_POST": payload['url'] if task is None and restore_id is not None else '',
        },
    ) as process:
        deadline = task['_deadline'] if sliced else time.monotonic() + 120 if task is None else None
        while process.poll() is None:
            if (deadline is not None and time.monotonic() >= deadline) or (task is not None and cancelled(task["id"])):
                if sliced:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    cleanup_asset_temporaries()
                    if cancelled(task['id']):
                        raise DetectionCancelled()
                    if policy_report.is_file():
                        raise ValueError(policy_report.read_text().strip() or '下载被安全策略拒绝')
                    raise YieldRound()
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                if task is None:
                    raise ValueError('缓存原图下载超时')
                raise DetectionCancelled()
            time.sleep(0.5 if deadline is None else max(0, min(0.5, deadline - time.monotonic())))
        if sliced and process.returncode == 75 and not policy_report.exists():
            raise YieldRound()
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
    return directory


def _import_task(task, attempt=None):
    payload = json.loads(task["payload"])
    counts = {"imported": 0, "skipped_existing": 0, "skipped_trashed": 0}
    if task['kind'] in DOWNLOAD_KINDS:
        download_media(task, payload, attempt)
        return
    directory = safe_directory(payload['directory'])
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
            import_file(path, raw, payload.get("start"), payload.get("end"), counts=counts)
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
    with connect(True) as db:
        db.execute("UPDATE tasks SET result=? WHERE id=?", (json.dumps(counts), task["id"]))
    if errors:
        raise ValueError(
            f"{len(errors)} 张图片导入失败；成功项目已保留。" + "\n".join(errors)
        )


def restore_task(task):
    from . import importer
    from .trash import restore_file
    from .db import queue_image_cleanup
    import shutil

    with connect() as db:
        row = db.execute("SELECT * FROM images WHERE id=?", (task["image_id"],)).fetchone()
        locations = [r[0] for r in db.execute("SELECT path FROM import_locations WHERE image_id=? ORDER BY path", (task["image_id"],))]
        urls = [r[0] for r in db.execute("SELECT DISTINCT p.url FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=? AND p.url IS NOT NULL ORDER BY p.id", (task["image_id"],))]
    if not row:
        raise ValueError("图片记录不存在")
    if not row["hidden"]:
        with connect(True) as db:
            db.execute("UPDATE tasks SET status='done',stage='已恢复',finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (task["id"],))
        return
    with connect(True) as db:
        db.execute("UPDATE tasks SET stage='查找原文件',total=1 WHERE id=?", (task["id"],))
    try:
        for path in (DATA / "originals").glob(row["sha256"] + ".*"):
            if restore_file(task, path):
                return
        payload = json.loads(task["payload"])
        directory = safe_directory(payload["directory"]) if payload.get("directory") is not None else None
        candidates = ((importer.IMPORT / path).resolve() for path in locations)
        if directory is not None:
            from itertools import chain
            candidates = chain(candidates, directory.rglob("*"))
        with tempfile.TemporaryDirectory(dir=DATA / "downloads", prefix="restore-local-") as attempt:
            for path in candidates:
                if cancelled(task["id"]):
                    raise DetectionCancelled()
                if not path.resolve().is_relative_to(importer.IMPORT) or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                    continue
                snapshot = Path(attempt) / ("source" + path.suffix.lower())
                try:
                    shutil.copyfile(path, snapshot)
                except OSError:
                    continue
                if restore_file(task, snapshot):
                    with connect(True) as db:
                        importer.record_location(db, row["id"], path)
                    return
                snapshot.unlink(missing_ok=True)
        errors = []
        for url in urls:
            if cancelled(task["id"]):
                raise DetectionCancelled()
            with tempfile.TemporaryDirectory(dir=DATA / "downloads", prefix="restore-remote-") as attempt:
                with connect(True) as db:
                    db.execute("UPDATE tasks SET stage='重新获取原图' WHERE id=?", (task["id"],))
                try:
                    directory = download_media(task, {"url": url}, Path(attempt), restore_id=row["id"])
                except ValueError as error:
                    errors.append(str(error))
                    continue
                for path in directory.rglob("*"):
                    if path.suffix.lower() in EXTENSIONS and path.is_file() and path.resolve().is_relative_to(directory.resolve()):
                        if restore_file(task, path):
                            return
                errors.append("来源未返回与原 SHA-256 一致的图片，文件可能已变化或失效")
        raise ValueError("无法恢复原文件；可选择挂载目录查找原文件后重试。" + ("；".join(dict.fromkeys(errors)) if errors else "没有可用的来源文件。"))
    finally:
        # Even an interrupted/failed asset write remains eligible for cleanup.
        with connect(True) as db:
            current = db.execute("SELECT * FROM images WHERE id=?", (task["image_id"],)).fetchone()
            if current and current["hidden"]:
                queue_image_cleanup(db, current)


def claim(kinds=("detect", "rematch", "import", "download", "restore", "monitor")):
    with connect(True) as db:
        placeholders = ",".join("?" for _ in kinds)
        ordering = 't.id' if set(kinds) <= {'detect', 'rematch'} else 't.queue_rank_at,t.rounds,t.id'
        if 'rematch' in kinds and 'detect' in kinds:
            ordering = "(t.kind='rematch') DESC," + ordering
        task = db.execute(
            f"""
            SELECT t.* FROM tasks t WHERE t.status='queued' AND t.kind IN ({placeholders})
            AND (t.kind NOT IN ('detect','rematch') OR EXISTS(SELECT 1 FROM images i WHERE i.id=t.image_id AND i.hidden=0))
            AND NOT EXISTS (SELECT 1 FROM tasks prior WHERE prior.image_id=t.image_id
                AND prior.status IN ('queued','running') AND prior.id<t.id)
            AND NOT EXISTS (SELECT 1 FROM tasks running WHERE running.image_id=t.image_id AND running.status='running')
            ORDER BY {ordering} LIMIT 1
        """,
            kinds,
        ).fetchone()
        if not task:
            return None
        task = dict(task)
        if task['kind'] in DOWNLOAD_KINDS:
            task['rounds'] += 1
            task['_deadline'] = time.monotonic() + ROUND_SECONDS
            db.execute("""UPDATE tasks SET status='running',rounds=?,round_started_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),
                runtime_seconds=CASE WHEN rounds=0 OR stage='等待重试' THEN 0 ELSE runtime_seconds END,
                started_at=CASE WHEN rounds=0 OR stage='等待重试' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE started_at END,
                finished_at=NULL,stage='下载并导入',speed=0,
                done=CASE WHEN rounds=0 THEN 0 ELSE done END,total=0,
                result=CASE WHEN rounds=0 OR result='{}' THEN ? ELSE result END WHERE id=?""",
                       (task['rounds'], json.dumps(EMPTY_RESULT), task['id']))
            task['_progress'] = RoundProgress.read(db, task['id'])
            return task
        db.execute(
            "UPDATE tasks SET status='running',runtime_seconds=CASE WHEN started_at IS NULL THEN 0 ELSE runtime_seconds END,started_at=coalesce(started_at,strftime('%Y-%m-%dT%H:%M:%SZ','now')),finished_at=NULL,stage=?,done=0,speed=0,total=CASE WHEN kind='detect' THEN 1 ELSE 0 END WHERE id=?",
            ("检测人脸" if task["kind"] == "detect" else "开始处理", task["id"]),
        )
        return task


def step():
    task = claim()
    if task is None:
        return False
    execute(task)
    return True


def requeue_round(db, task_id):
    return db.execute("""UPDATE tasks SET status='queued',finished_at=NULL,stage='等待下一轮',speed=0,
        queue_rank_at=unixepoch()+? WHERE id=? AND status='running' AND cancel_requested=0""",
                      (ROUND_SECONDS, task_id)).rowcount


def execute_download(task):
    status, error = 'done', None
    try:
        if cancelled(task['id']):
            raise DetectionCancelled()
        import_task(task)
    except YieldRound:
        status = 'queued'
    except DetectionCancelled:
        status = 'cancelled'
    except Exception as exc:
        status, error = 'failed', str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    with connect(True) as db:
        row = db.execute("SELECT cancel_requested FROM tasks WHERE id=? AND rounds=? AND status='running'",
                         (task['id'], task['rounds'])).fetchone()
        if not row:
            return
        if row['cancel_requested']:
            status, error = 'cancelled', None
        if status == 'queued':
            progress = RoundProgress.read(db, task['id'])
            stalled = 0 if progress.advanced_from(task['_progress']) else task['stalled_rounds'] + 1
            db.execute('UPDATE tasks SET stalled_rounds=? WHERE id=?', (stalled, task['id']))
            if stalled < STALL_LIMIT:
                requeue_round(db, task['id'])
                return
            status, error = 'failed', f'连续 {stalled} 轮没有可恢复的下载进度，请检查网络或来源后重试'
        elif status == 'done' and (error := item_error_summary(db, task['id'])):
            status = 'failed'
        stage = {'done': '已完成', 'cancelled': '已取消', 'failed': '处理失败'}[status]
        db.execute("""UPDATE tasks SET status=?,stage=?,error=?,total=CASE WHEN ?='done' THEN done ELSE total END,
            finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?""", (status, stage, error, status, task['id']))
        if task['kind'] == 'monitor':
            from .monitors import finish
            finish(db, task)


def execute(task):
    if task['kind'] in DOWNLOAD_KINDS:
        execute_download(task)
        return True
    try:
        if cancelled(task["id"]):
            raise DetectionCancelled()
        if task["kind"] == "rematch":
            rematch(task)
            return True
        if task["kind"] == "detect":
            detect(task)
        elif task["kind"] == "restore":
            restore_task(task)
            return True
        else:
            import_task(task)
        with connect(True) as db:
            db.execute(
                "UPDATE tasks SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'done' END,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),stage=CASE WHEN cancel_requested THEN '已取消' ELSE '已完成' END WHERE id=?",
                (task["id"],),
            )
    except DetectionCancelled:
        with connect(True) as db:
            db.execute(
                "UPDATE tasks SET status='cancelled',finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),stage='已取消' WHERE id=?",
                (task["id"],),
            )
    except Exception as error:
        with connect(True) as db:
            message = (
                str(error) if isinstance(error, ValueError) else type(error).__name__
            )
            db.execute(
                "UPDATE tasks SET status='failed',finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'),stage='处理失败',error=? WHERE id=?",
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
        from .media_cache import watermarks
        from .cache_status import report_config
        report_config(watermarks())
        stop = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        recover_tasks()
        cleanup_interrupted_files()
        from .importer import recover_deduplications
        recover_deduplications(stop)
        run_worker(stop)


def cleanup_interrupted_files():
    """Only run with the exclusive worker lock, before dispatching any work."""
    import shutil
    from .media_cache import cleanup_fetches

    cleanup_fetches()
    cleanup_ready()

    for path in (DATA / "downloads").iterdir():
        if path.name.startswith(("attempt-", "restore-local-", "restore-remote-")):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
    cleanup_asset_temporaries()


def cleanup_asset_temporaries():
    # Asset writers and cleanup share the database write lock.
    with connect(True):
        for folder in ("images", "thumbs", "originals"):
            for path in (DATA / folder).glob(".asset-*"):
                path.unlink(missing_ok=True)


def recover_tasks():
    with connect(True) as db:
        db.execute("UPDATE tasks SET runtime_seconds=NULL WHERE status='running'")
        for row in db.execute("SELECT id FROM tasks WHERE kind IN ('download','monitor') AND status='running' AND cancel_requested=0").fetchall():
            requeue_round(db, row['id'])
        db.execute(
            "UPDATE tasks SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'queued' END,stage=CASE WHEN cancel_requested THEN '已取消' ELSE '等待处理' END,finished_at=CASE WHEN cancel_requested THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE NULL END WHERE status='running'"
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


def worker_idle_timeout():
    value = os.environ.get("WORKER_IDLE_TIMEOUT_SECONDS", "300")
    if not value.isascii() or not value.isdecimal():
        raise ValueError("WORKER_IDLE_TIMEOUT_SECONDS must be a non-negative integer")
    return int(value)


def run_worker(stop):
    from .media_cache import watermarks, clean
    limits = watermarks()
    next_clean = 0
    cleaning = None
    concurrency = worker_concurrency()
    idle_timeout = worker_idle_timeout()
    idle_since = None
    idle_released = False
    with (
        ThreadPoolExecutor(max_workers=concurrency) as compute,
        ThreadPoolExecutor(max_workers=1) as io,
        (ThreadPoolExecutor(max_workers=1) if limits else nullcontext()) as maintenance,
    ):
        running = {compute: set(), io: set()}
        next_schedule = 0.0
        while not stop.is_set():
            if limits and time.monotonic() >= next_clean and (cleaning is None or cleaning.done()):
                if cleaning is not None:
                    cleaning.result()
                cleaning = maintenance.submit(clean, *limits)
                next_clean = time.monotonic() + 60
            if time.monotonic() >= next_schedule:
                from .monitors import schedule_due
                schedule_due()
                cleanup_ready()
                next_schedule = time.monotonic() + 30
            for executor, limit, kinds in (
                (compute, concurrency, ("detect", "rematch")),
                (io, 1, ("download", "import", "restore", "monitor")),
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
            if any(running.values()):
                idle_since = None
                idle_released = False
            elif idle_timeout and not idle_released and not stop.is_set():
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                elif now - idle_since >= idle_timeout:
                    release_idle_memory()
                    idle_released = True
            stop.wait(0.1)


if __name__ == "__main__":
    main()
