import hashlib
import logging
import os
import secrets
import time
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", "./data")).resolve()
IMPORT = Path(os.environ.get("IMPORT_DIR", "./imports")).resolve()

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES('reference_version','0'),('threshold','0.5'),('margin','0.1'),('phash_distance','4'),('aspect_tolerance','0.01'),('ssim_threshold','0.98');
INSERT OR IGNORE INTO settings VALUES('site_title','Gallery Faces');
INSERT OR IGNORE INTO settings VALUES('og_title',''),('og_description',''),('og_image',''),('og_url',''),('og_title_ja',''),('og_description_ja',''),('og_image_ja',''),('og_url_ja','');
INSERT OR IGNORE INTO settings VALUES('detection_threshold','0.5');
INSERT OR IGNORE INTO settings SELECT 'review_ssim_threshold',CAST(min(0.5,CAST(value AS REAL)) AS TEXT) FROM settings WHERE key='ssim_threshold';
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name))>0));
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK(length(trim(name))>0));
CREATE TABLE IF NOT EXISTS person_groups(person_id INTEGER REFERENCES people ON DELETE CASCADE, group_id INTEGER REFERENCES groups ON DELETE CASCADE, PRIMARY KEY(person_id,group_id));
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, person_id INTEGER REFERENCES people ON DELETE CASCADE, platform TEXT NOT NULL, username TEXT NOT NULL, UNIQUE(person_id,platform,username));
CREATE TABLE IF NOT EXISTS duplicate_groups(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS images(id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, filename TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, phash TEXT, group_id INTEGER NOT NULL REFERENCES duplicate_groups, detection TEXT NOT NULL DEFAULT 'pending', error TEXT, hidden INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, platform TEXT NOT NULL, post_key TEXT NOT NULL, author TEXT, author_name TEXT, published_at TEXT, url TEXT, post_text TEXT, collected_account TEXT, coauthors TEXT, UNIQUE(platform,post_key));
CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL REFERENCES images, post_id INTEGER NOT NULL REFERENCES posts, media_key TEXT NOT NULL, UNIQUE(post_id,media_key));
CREATE TABLE IF NOT EXISTS faces(id INTEGER PRIMARY KEY, image_id INTEGER NOT NULL REFERENCES images, box TEXT NOT NULL, embedding BLOB, model_version TEXT, person_id INTEGER REFERENCES people ON DELETE SET NULL, locked INTEGER NOT NULL DEFAULT 0, ignored INTEGER NOT NULL DEFAULT 0, candidates TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reference_images(id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES people ON DELETE CASCADE, image_id INTEGER REFERENCES images, face_id INTEGER REFERENCES faces, filename TEXT, box TEXT, embedding BLOB NOT NULL, model_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, image_id INTEGER REFERENCES images, payload TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'queued', stage TEXT NOT NULL DEFAULT '等待处理', target_version INTEGER NOT NULL DEFAULT 0, processed_version INTEGER NOT NULL DEFAULT -1, done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, speed REAL NOT NULL DEFAULT 0, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, finished_at TEXT, created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_rematch ON tasks(image_id) WHERE kind='rematch' AND status IN ('queued','running');
CREATE UNIQUE INDEX IF NOT EXISTS one_active_restore ON tasks(image_id) WHERE kind='restore' AND status IN ('queued','running');
CREATE INDEX IF NOT EXISTS task_image_status ON tasks(image_id,status,kind,id);
CREATE TABLE IF NOT EXISTS duplicate_decisions(a INTEGER REFERENCES images, b INTEGER REFERENCES images, decision TEXT NOT NULL, score REAL, PRIMARY KEY(a,b));
CREATE TABLE IF NOT EXISTS review_history(id INTEGER PRIMARY KEY, face_id INTEGER REFERENCES faces, before_json TEXT NOT NULL, after_revision INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pending_file_deletions(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, filename TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending_deduplications(image_id INTEGER PRIMARY KEY REFERENCES images ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER NOT NULL REFERENCES images ON DELETE CASCADE, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','resolved')), created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), resolved_at TEXT);
CREATE INDEX IF NOT EXISTS feedback_image_status ON feedback(image_id,status,id);
CREATE TABLE IF NOT EXISTS private_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback_submissions(ip_hash TEXT NOT NULL, submitted_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_submission_ip ON feedback_submissions(ip_hash,submitted_at);
CREATE INDEX IF NOT EXISTS feedback_submission_time ON feedback_submissions(submitted_at);
CREATE INDEX IF NOT EXISTS source_image ON sources(image_id);
CREATE INDEX IF NOT EXISTS face_image ON faces(image_id);
CREATE INDEX IF NOT EXISTS image_group ON images(group_id);
CREATE INDEX IF NOT EXISTS post_date ON posts(published_at,id);
CREATE TABLE IF NOT EXISTS monitors(id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, username TEXT NOT NULL COLLATE NOCASE, interval_minutes INTEGER NOT NULL DEFAULT 60 CHECK(interval_minutes>=5), paused INTEGER NOT NULL DEFAULT 0, start_at TEXT NOT NULL, progress_at TEXT, next_check_at TEXT NOT NULL, last_checked_at TEXT, last_task_id INTEGER, generation INTEGER NOT NULL DEFAULT 0, UNIQUE(platform,username));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_monitor ON tasks(json_extract(payload,'$.monitor_id')) WHERE kind='monitor' AND status IN ('queued','running');
DELETE FROM settings WHERE key='timezone';
CREATE TABLE IF NOT EXISTS import_locations(image_id INTEGER NOT NULL REFERENCES images ON DELETE CASCADE, path TEXT NOT NULL, PRIMARY KEY(image_id,path));
"""

# Uploaded references have no owning image and remain available independently.
ACTIVE_REFERENCE = "(image_id IS NULL OR EXISTS(SELECT 1 FROM images ri WHERE ri.id=reference_images.image_id AND ri.hidden=0))"


@contextmanager
def connect(write=False):
    DATA.mkdir(parents=True, exist_ok=True)
    from .request_guard import public_query
    public = public_query.get()
    db = sqlite3.connect(DATA / "gallery.sqlite3", timeout=1 if public else 30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=" + ("1000" if public else "30000"))
    if public:
        from time import monotonic
        deadline = monotonic() + 2
        db.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except sqlite3.OperationalError as error:
        db.rollback()
        if public and any(word in str(error) for word in ("locked", "interrupted", "busy")):
            from fastapi import HTTPException
            raise HTTPException(503, "查询繁忙，请稍后重试", headers={"Retry-After": "1"}) from None
        raise
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    for folder in (
        "images",
        "originals",
        "thumbs",
        "references",
        "models",
        "cookies",
        "downloads",
    ):
        (DATA / folder).mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    with connect(True) as db:
        for table in ('people', 'groups'):
            if 'name_ja' not in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN name_ja TEXT')
        task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        for column in ("finished_at",):
            if column not in task_columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
        if "author_name" not in {row[1] for row in db.execute("PRAGMA table_info(posts)")}:
            db.execute("ALTER TABLE posts ADD COLUMN author_name TEXT")
        if "coauthors" not in {row[1] for row in db.execute("PRAGMA table_info(posts)")}:
            db.execute("ALTER TABLE posts ADD COLUMN coauthors TEXT")
        if "box" not in {row[1] for row in db.execute("PRAGMA table_info(reference_images)")}:
            db.execute("ALTER TABLE reference_images ADD COLUMN box TEXT")
        db.execute("INSERT OR IGNORE INTO private_config VALUES('feedback_secret',?)", (secrets.token_hex(32),))
        db.execute("DELETE FROM feedback_submissions WHERE submitted_at<=?", (time.time() - 86400,))
        if "file_size" not in {row[1] for row in db.execute("PRAGMA table_info(images)")}:
            db.execute("ALTER TABLE images ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0")
            for image in db.execute("SELECT id,sha256 FROM images").fetchall():
                originals = sorted((DATA / "originals").glob(image["sha256"] + ".*"))
                try:
                    size = originals[0].stat().st_size if originals else 0
                except OSError:
                    size = 0
                if not size:
                    logging.getLogger(__name__).warning("Original unavailable for image %s", image["id"])
                db.execute("UPDATE images SET file_size=? WHERE id=?", (size, image["id"]))
        columns = {row[1] for row in db.execute("PRAGMA table_info(images)")}
        for column in ("image_sha256", "thumbnail_sha256", "original_filename"):
            if column not in columns:
                db.execute(f"ALTER TABLE images ADD COLUMN {column} TEXT")
        if "trashed_at" not in columns:
            db.execute("ALTER TABLE images ADD COLUMN trashed_at TEXT")
        if "result" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN result TEXT NOT NULL DEFAULT '{}'")
        db.execute("CREATE INDEX IF NOT EXISTS image_trash ON images(hidden,trashed_at,id)")
        if db.execute("SELECT version FROM schema_version").fetchone()[0] < 9:
            for row in db.execute("SELECT * FROM images WHERE hidden=1").fetchall():
                queue_image_cleanup(db, row)
            db.execute("UPDATE images SET trashed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE hidden=1 AND trashed_at IS NULL")
            db.execute("UPDATE tasks SET status='cancelled',cancel_requested=1,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE image_id IN (SELECT id FROM images WHERE hidden=1) AND kind IN ('detect','rematch') AND status IN ('queued','running')")
            if db.execute("SELECT 1 FROM reference_images r JOIN images i ON i.id=r.image_id WHERE i.hidden=1").fetchone():
                schedule_rematch(db)
            db.execute("UPDATE schema_version SET version=9 WHERE version<9")
        db.execute("UPDATE schema_version SET version=10 WHERE version<10")
        # Recover files written by a restore interrupted before its transaction
        # committed, including tasks cancelled during process recovery.
        for row in db.execute("SELECT * FROM images WHERE hidden=1").fetchall():
            if (DATA / "images" / row["filename"]).exists() or next((DATA / "originals").glob(row["sha256"] + ".*"), None):
                queue_image_cleanup(db, row)
        for column in ("image_sha256", "thumbnail_sha256"):
            db.execute(f"CREATE INDEX IF NOT EXISTS image_{column} ON images({column})")
    backfill_media_hashes()
    with connect(True) as db:
        db.execute("UPDATE schema_version SET version=10 WHERE version<10")


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def backfill_media_hashes(batch_size=100):
    # Commit each batch; completed fields survive interrupted upgrades. Missing
    # files remain NULL and can be retried after storage has been repaired.
    last_id = 0
    while True:
        with connect(True) as db:
            rows = db.execute(
                "SELECT * FROM images WHERE hidden=0 AND id>? AND (image_sha256 IS NULL OR thumbnail_sha256 IS NULL OR original_filename IS NULL) ORDER BY id LIMIT ?",
                (last_id, batch_size),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                for column, folder in (("image_sha256", "images"), ("thumbnail_sha256", "thumbs")):
                    if row[column] is None:
                        try:
                            digest = file_hash(DATA / folder / row["filename"])
                        except OSError:
                            logging.getLogger(__name__).warning("%s unavailable for image %s", folder, row["id"])
                        else:
                            db.execute(f"UPDATE images SET {column}=? WHERE id=?", (digest, row["id"]))
                if row["original_filename"] is None:
                    original = next((p for p in sorted((DATA / "originals").glob(row["sha256"] + ".*")) if p.is_file()), None)
                    if original:
                        db.execute("UPDATE images SET original_filename=? WHERE id=?", (original.name, row["id"]))
                    else:
                        logging.getLogger(__name__).warning("Original unavailable for image %s", row["id"])
            last_id = rows[-1]["id"]


def settings(db):
    return dict(db.execute("SELECT key,value FROM settings").fetchall())


def cleanup_deleted_files():
    # Serialize with imports so reimported bytes cannot be removed by old work.
    # Keep failed deletions durable for retry after a restart or permission fix.
    with connect(True) as db:
        for row in db.execute("SELECT * FROM pending_file_deletions").fetchall():
            if not db.execute(
                "SELECT 1 FROM images WHERE (sha256=? OR filename=?) AND (hidden=0 OR ? LIKE 'thumbs/%')",
                (row["sha256"], row["filename"], row["path"]),
            ).fetchone():
                path = DATA / row["path"]
                if path.parent not in (DATA / "images", DATA / "thumbs", DATA / "originals"):
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
            db.execute("DELETE FROM pending_file_deletions WHERE path=?", (row["path"],))
        return db.execute("SELECT count(*) FROM pending_file_deletions").fetchone()[0]


def queue_image_cleanup(db, image):
    paths = [DATA / "images" / image["filename"]]
    paths.extend((DATA / "originals").glob(image["sha256"] + ".*"))
    db.executemany(
        "INSERT OR IGNORE INTO pending_file_deletions(path,sha256,filename) VALUES(?,?,?)",
        [(str(path.relative_to(DATA)), image["sha256"], image["filename"]) for path in paths],
    )


def unknown_sql(alias="faces"):
    return f"{alias}.person_id IS NULL AND {alias}.locked=0 AND {alias}.ignored=0"


def schedule_rematch(db):
    version = int(settings(db)["reference_version"]) + 1
    db.execute(
        "UPDATE settings SET value=? WHERE key='reference_version'", (str(version),)
    )
    for row in db.execute(
        f"SELECT DISTINCT image_id FROM faces WHERE {unknown_sql()} AND embedding IS NOT NULL AND EXISTS(SELECT 1 FROM images i WHERE i.id=faces.image_id AND i.hidden=0)"
    ).fetchall():
        active = db.execute(
            "SELECT id FROM tasks WHERE kind='rematch' AND image_id=? AND status IN ('queued','running')",
            (row[0],),
        ).fetchone()
        if active:
            db.execute(
                "UPDATE tasks SET target_version=? WHERE id=?", (version, active[0])
            )
        else:
            db.execute(
                "INSERT INTO tasks(kind,image_id,target_version) VALUES('rematch',?,?)",
                (row[0], version),
            )


def schedule_detection(db, image_id, mode="auto"):
    import json
    active = db.execute("SELECT * FROM tasks WHERE kind='detect' AND image_id=? AND status IN ('queued','running') ORDER BY id", (image_id,)).fetchall()
    for task in active:
        if json.loads(task['payload']).get('mode', 'auto') == 'highres' or mode == 'auto':
            return task['id']
    for task in active:
        if task['status'] == 'queued':
            payload = json.loads(task['payload'])
            payload['mode'] = mode
            db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(payload), task['id']))
            return task['id']
    return db.execute("INSERT INTO tasks(kind,image_id,payload) VALUES('detect',?,?)", (image_id, json.dumps({'mode': mode}))).lastrowid
