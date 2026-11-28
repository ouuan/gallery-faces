import hashlib
import logging
import os
import secrets
import time
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from . import group_index
from .metadata import post_identity

DATA = Path(os.environ.get("DATA_DIR", "./data")).resolve()
IMPORT = Path(os.environ.get("IMPORT_DIR", "./imports")).resolve()

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS game_matches(id TEXT PRIMARY KEY, code TEXT NOT NULL, game TEXT NOT NULL, solo INTEGER NOT NULL, phase TEXT NOT NULL, touched REAL NOT NULL, state TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS game_room_current ON game_matches(code);
CREATE INDEX IF NOT EXISTS game_match_activity ON game_matches(touched DESC);
CREATE TABLE IF NOT EXISTS game_boards(id TEXT PRIMARY KEY, game TEXT NOT NULL, settings TEXT NOT NULL, filters TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS game_board_scope ON game_boards(game,filters);
CREATE TABLE IF NOT EXISTS game_records(board TEXT NOT NULL REFERENCES game_boards, nickname TEXT NOT NULL, correct INTEGER NOT NULL, cells INTEGER NOT NULL, deviation INTEGER NOT NULL, rounds INTEGER NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(board,nickname));
CREATE TABLE IF NOT EXISTS game_uploads(match_id TEXT NOT NULL REFERENCES game_matches ON DELETE CASCADE, player INTEGER NOT NULL, nickname TEXT NOT NULL, PRIMARY KEY(match_id,player));
INSERT OR IGNORE INTO settings VALUES('reference_version','0'),('threshold','0.5'),('margin','0.1'),('phash_distance','4'),('aspect_tolerance','0.01'),('ssim_threshold','0.98');
INSERT OR IGNORE INTO settings VALUES('site_title','Gallery Faces');
INSERT OR IGNORE INTO settings VALUES('agent_review_rules','');
INSERT OR IGNORE INTO settings VALUES('og_title',''),('og_description',''),('og_image',''),('og_url',''),('og_title_ja',''),('og_description_ja',''),('og_image_ja',''),('og_url_ja','');
INSERT OR IGNORE INTO settings VALUES('detection_threshold','0.5');
INSERT OR IGNORE INTO settings SELECT 'review_ssim_threshold',CAST(min(0.5,CAST(value AS REAL)) AS TEXT) FROM settings WHERE key='ssim_threshold';
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT NOT NULL CHECK(length(trim(name))>0));
CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE CHECK(length(trim(name))>0));
CREATE TABLE IF NOT EXISTS person_groups(person_id INTEGER REFERENCES people ON DELETE CASCADE, group_id INTEGER REFERENCES groups ON DELETE CASCADE, PRIMARY KEY(person_id,group_id));
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, person_id INTEGER REFERENCES people ON DELETE CASCADE, platform TEXT NOT NULL, username TEXT NOT NULL, UNIQUE(person_id,platform,username));
CREATE TABLE IF NOT EXISTS duplicate_groups(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS daily_picks(filter_key TEXT PRIMARY KEY, day TEXT NOT NULL, group_id INTEGER NOT NULL) WITHOUT ROWID;
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
CREATE INDEX IF NOT EXISTS decision_right_image ON duplicate_decisions(b,a);
CREATE TABLE IF NOT EXISTS review_history(id INTEGER PRIMARY KEY, face_id INTEGER REFERENCES faces, before_json TEXT NOT NULL, after_revision INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS review_batches(id TEXT PRIMARY KEY, status TEXT NOT NULL, instructions TEXT NOT NULL, total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, expires REAL, error TEXT);
CREATE TABLE IF NOT EXISTS review_imports(id TEXT PRIMARY KEY, status TEXT NOT NULL, extension TEXT NOT NULL, upload BLOB, added INTEGER NOT NULL DEFAULT 0, recorded INTEGER NOT NULL DEFAULT 0, duplicates INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS review_snapshots(batch TEXT REFERENCES review_batches, image_id INTEGER NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(batch,image_id));
CREATE TABLE IF NOT EXISTS review_roster(batch TEXT REFERENCES review_batches, exported_id INTEGER NOT NULL, person_id INTEGER REFERENCES people ON DELETE SET NULL, PRIMARY KEY(batch,exported_id));
CREATE TABLE IF NOT EXISTS review_group_roster(batch TEXT REFERENCES review_batches, exported_id INTEGER NOT NULL, group_id INTEGER REFERENCES groups ON DELETE SET NULL, name TEXT NOT NULL, name_ja TEXT, PRIMARY KEY(batch,exported_id));
CREATE TABLE IF NOT EXISTS review_face_identity(face_id INTEGER PRIMARY KEY REFERENCES faces ON DELETE CASCADE, token TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))));
CREATE TABLE IF NOT EXISTS review_attachments(digest TEXT PRIMARY KEY, jpeg BLOB NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS review_detections(id INTEGER PRIMARY KEY, attachment TEXT NOT NULL REFERENCES review_attachments, model TEXT NOT NULL, threshold REAL, detections TEXT NOT NULL, UNIQUE(attachment,model,threshold));
CREATE TABLE IF NOT EXISTS review_suggestions(id INTEGER PRIMARY KEY, batch TEXT NOT NULL, key TEXT NOT NULL, image_id INTEGER NOT NULL, payload TEXT NOT NULL, fingerprint TEXT NOT NULL, attachment TEXT REFERENCES review_attachments, detection_id INTEGER REFERENCES review_detections, chosen_face INTEGER, status TEXT NOT NULL DEFAULT 'pending', created_person INTEGER REFERENCES people ON DELETE SET NULL, UNIQUE(batch,key), UNIQUE(batch,fingerprint), FOREIGN KEY(batch,image_id) REFERENCES review_snapshots(batch,image_id));
CREATE INDEX IF NOT EXISTS review_suggestions_page ON review_suggestions(status,image_id,id);
CREATE INDEX IF NOT EXISTS review_queue_page ON review_suggestions(image_id,id) WHERE status IN ('pending','recorded');
CREATE INDEX IF NOT EXISTS review_outcomes ON review_suggestions(status,batch,image_id) WHERE json_extract(payload,'$.kind')='review_outcome';
CREATE TABLE IF NOT EXISTS review_result_keys(batch TEXT NOT NULL, key TEXT NOT NULL, content TEXT NOT NULL, suggestion INTEGER NOT NULL REFERENCES review_suggestions, PRIMARY KEY(batch,key));
CREATE UNIQUE INDEX IF NOT EXISTS review_person_keys ON review_suggestions(batch,json_extract(payload,'$.person_id')) WHERE json_extract(payload,'$.kind')='create_person';
CREATE TABLE IF NOT EXISTS pending_file_deletions(path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, filename TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pending_deduplications(image_id INTEGER PRIMARY KEY REFERENCES images ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS pending_restore_checks(image_id INTEGER PRIMARY KEY REFERENCES images ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, image_id INTEGER NOT NULL REFERENCES images ON DELETE CASCADE, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','resolved')), created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), resolved_at TEXT);
CREATE INDEX IF NOT EXISTS feedback_image_status ON feedback(image_id,status,id);
CREATE TABLE IF NOT EXISTS private_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_cache_activity(minute INTEGER NOT NULL, variant TEXT NOT NULL, hits INTEGER NOT NULL, misses INTEGER NOT NULL, recoveries INTEGER NOT NULL, PRIMARY KEY(minute,variant));
CREATE TRIGGER IF NOT EXISTS expire_media_cache_activity AFTER INSERT ON media_cache_activity BEGIN
    DELETE FROM media_cache_activity WHERE minute <= NEW.minute - 1440;
END;
CREATE TABLE IF NOT EXISTS feedback_submissions(ip_hash TEXT NOT NULL, submitted_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_submission_ip ON feedback_submissions(ip_hash,submitted_at);
CREATE INDEX IF NOT EXISTS feedback_submission_time ON feedback_submissions(submitted_at);
CREATE INDEX IF NOT EXISTS source_image ON sources(image_id);
CREATE INDEX IF NOT EXISTS face_image ON faces(image_id);
CREATE INDEX IF NOT EXISTS image_group ON images(group_id);
CREATE INDEX IF NOT EXISTS post_date ON posts(published_at,id);
CREATE INDEX IF NOT EXISTS post_account ON posts(platform,lower(author));
CREATE TABLE IF NOT EXISTS publisher_rules(platform TEXT NOT NULL,username TEXT NOT NULL COLLATE NOCASE,label TEXT NOT NULL,blocked TEXT NOT NULL,PRIMARY KEY(platform,username)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS publisher_avatars(platform TEXT NOT NULL,username TEXT NOT NULL,digest TEXT,image BLOB,next_check INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(platform,username));
CREATE INDEX IF NOT EXISTS avatar_digest ON publisher_avatars(digest);
CREATE UNIQUE INDEX IF NOT EXISTS active_avatar ON tasks(payload) WHERE kind='avatar' AND status IN ('queued','running');
CREATE TABLE IF NOT EXISTS monitors(id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL, username TEXT NOT NULL COLLATE NOCASE, interval_minutes INTEGER NOT NULL DEFAULT 60 CHECK(interval_minutes>=5), paused INTEGER NOT NULL DEFAULT 0, start_at TEXT NOT NULL, progress_at TEXT, next_check_at TEXT NOT NULL, last_checked_at TEXT, last_task_id INTEGER, generation INTEGER NOT NULL DEFAULT 0, UNIQUE(platform,username));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_monitor ON tasks(json_extract(payload,'$.monitor_id')) WHERE kind='monitor' AND status IN ('queued','running');
DELETE FROM settings WHERE key='timezone';
CREATE TABLE IF NOT EXISTS import_locations(image_id INTEGER NOT NULL REFERENCES images ON DELETE CASCADE, path TEXT NOT NULL, PRIMARY KEY(image_id,path));
"""

# Uploaded references have no owning image and remain available independently.
ACTIVE_REFERENCE = "(image_id IS NULL OR EXISTS(SELECT 1 FROM images ri WHERE ri.id=reference_images.image_id AND ri.hidden=0))"


@contextmanager
def connect(write=False, *, wait=True):
    DATA.mkdir(parents=True, exist_ok=True)
    from .request_guard import public_query
    public = public_query.get()
    db = sqlite3.connect(DATA / "gallery.sqlite3", timeout=(1 if public else 30) if wait else 0)
    db.row_factory = sqlite3.Row
    db.create_function('post_identity', 2, post_identity, deterministic=True)
    db.execute("PRAGMA foreign_keys=ON")
    if public:
        from time import monotonic
        deadline = monotonic() + 2
        db.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        if write:
            group_index.refresh(db)
        db.commit()
    except sqlite3.OperationalError as error:
        db.rollback()
        if public and wait and any(word in str(error) for word in ("locked", "interrupted", "busy")):
            logging.getLogger(__name__).warning('Public database request rejected: %s', error.sqlite_errorname)
            from fastapi import HTTPException
            raise HTTPException(503, "查询繁忙，请稍后重试", headers={"Retry-After": "1"}) from None
        raise
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def startup_phase(name):
    started = time.monotonic()
    yield
    logging.getLogger('uvicorn.error').info('Startup: %s took %.3fs', name, time.monotonic() - started)


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
    with startup_phase('database schema'), connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    with startup_phase('database migrations'), connect(True) as db:
        if 'face_revision' not in {row[1] for row in db.execute('PRAGMA table_info(feedback)')}:
            for column in ('face_id INTEGER REFERENCES faces ON DELETE SET NULL', 'face_revision INTEGER',
                           'original_name TEXT', 'suggested_person_id INTEGER REFERENCES people ON DELETE SET NULL',
                           'suggested_name TEXT'):
                db.execute(f'ALTER TABLE feedback ADD COLUMN {column}')
        if 'not_face' not in {row[1] for row in db.execute('PRAGMA table_info(feedback)')}:
            db.execute('ALTER TABLE feedback ADD COLUMN not_face INTEGER NOT NULL DEFAULT 0 CHECK(not_face IN (0,1))')
        db.execute("UPDATE review_suggestions SET status='recorded' WHERE status='pending' AND json_extract(payload,'$.kind')='review_outcome'")
        if 'detection_id' not in {row[1] for row in db.execute('PRAGMA table_info(review_suggestions)')}:
            db.execute('ALTER TABLE review_suggestions ADD COLUMN detection_id INTEGER REFERENCES review_detections')
            db.execute('INSERT INTO review_detections(attachment,model,detections) SELECT digest,model,detections FROM review_attachments')
            db.execute('UPDATE review_suggestions SET detection_id=(SELECT id FROM review_detections d WHERE d.attachment=review_suggestions.attachment) WHERE attachment IS NOT NULL')
            db.execute('ALTER TABLE review_attachments DROP COLUMN detections')
            db.execute('ALTER TABLE review_attachments DROP COLUMN model')
        if 'hashtags' not in {row[1] for row in db.execute('PRAGMA table_info(monitors)')}:
            db.execute("ALTER TABLE monitors ADD COLUMN hashtags TEXT NOT NULL DEFAULT '[]'")
        if 'scope' not in {row[1] for row in db.execute('PRAGMA table_info(monitors)')}:
            db.execute("ALTER TABLE monitors ADD COLUMN scope TEXT NOT NULL DEFAULT '{}'")
        if 'list_title' not in {row[1] for row in db.execute('PRAGMA table_info(monitors)')}:
            db.execute('ALTER TABLE monitors ADD COLUMN list_title TEXT')
        for table in ('people', 'groups'):
            if 'name_ja' not in {row[1] for row in db.execute(f'PRAGMA table_info({table})')}:
                db.execute(f'ALTER TABLE {table} ADD COLUMN name_ja TEXT')
        task_columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        if 'rounds' not in task_columns:
            db.execute('ALTER TABLE tasks ADD COLUMN rounds INTEGER NOT NULL DEFAULT 0')
        if 'queue_rank_at' not in task_columns:
            db.execute('ALTER TABLE tasks ADD COLUMN queue_rank_at INTEGER')
            db.execute('UPDATE tasks SET queue_rank_at=unixepoch(created_at)')
        from .task_queue import migrate
        migrate(db, task_columns)
        db.execute('CREATE TABLE IF NOT EXISTS download_cursors(task_id INTEGER PRIMARY KEY REFERENCES tasks ON DELETE CASCADE, cursor TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS download_items(task_id INTEGER REFERENCES tasks ON DELETE CASCADE,
            platform TEXT, post_key TEXT, media TEXT, image_id INTEGER REFERENCES images,
            PRIMARY KEY(task_id,platform,post_key,media)) WITHOUT ROWID''')
        db.execute('''CREATE TABLE IF NOT EXISTS download_ready(task_id INTEGER PRIMARY KEY REFERENCES tasks ON DELETE CASCADE,
            filename TEXT NOT NULL UNIQUE, meta TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS download_parts(task_id INTEGER PRIMARY KEY REFERENCES tasks ON DELETE CASCADE,
            media TEXT NOT NULL, filename TEXT NOT NULL UNIQUE, validator TEXT)''')
        if 'resume_offset' not in {row[1] for row in db.execute('PRAGMA table_info(download_parts)')}:
            db.execute('ALTER TABLE download_parts ADD COLUMN resume_offset INTEGER NOT NULL DEFAULT 0')
        db.execute('''CREATE TABLE IF NOT EXISTS download_item_errors(task_id INTEGER REFERENCES tasks ON DELETE CASCADE,
            platform TEXT, post_key TEXT, media TEXT, reason TEXT NOT NULL,
            PRIMARY KEY(task_id,platform,post_key,media)) WITHOUT ROWID''')
        if 'stalled_rounds' not in task_columns:
            db.execute('ALTER TABLE tasks ADD COLUMN stalled_rounds INTEGER NOT NULL DEFAULT 0')
            db.execute('DROP TRIGGER IF EXISTS download_terminal')
            db.execute("DELETE FROM download_items WHERE task_id IN (SELECT id FROM tasks WHERE kind='monitor' AND status IN ('done','cancelled','failed'))")
            db.execute("DELETE FROM download_cursors WHERE task_id IN (SELECT id FROM tasks WHERE rtrim(json_extract(payload,'$.url'),'/') LIKE '%/media')")
        db.execute('''CREATE TRIGGER IF NOT EXISTS download_terminal AFTER UPDATE OF status ON tasks
            WHEN NEW.kind IN ('download','monitor') AND NEW.status IN ('done','cancelled','failed') BEGIN
            DELETE FROM download_ready WHERE task_id=NEW.id;
            DELETE FROM download_parts WHERE task_id=NEW.id;
            DELETE FROM download_cursors WHERE task_id=NEW.id;
            DELETE FROM download_item_errors WHERE task_id=NEW.id;
            DELETE FROM download_items WHERE task_id=NEW.id AND (NEW.status='done' OR NEW.kind='monitor'); END''')
        for column in ("started_at", "round_started_at", "finished_at"):
            if column not in task_columns:
                db.execute(f"ALTER TABLE tasks ADD COLUMN {column} TEXT")
        if 'runtime_seconds' not in task_columns:
            db.execute('ALTER TABLE tasks ADD COLUMN runtime_seconds INTEGER')
        db.execute('''CREATE TRIGGER IF NOT EXISTS task_runtime AFTER UPDATE OF status ON tasks
            WHEN OLD.status='running' AND NEW.status!='running' AND OLD.runtime_seconds IS NOT NULL BEGIN
            UPDATE tasks SET runtime_seconds=OLD.runtime_seconds + max(0,unixepoch()-unixepoch(coalesce(OLD.round_started_at,OLD.started_at)))
            WHERE id=NEW.id; END''')
        if "author_name" not in {row[1] for row in db.execute("PRAGMA table_info(posts)")}:
            db.execute("ALTER TABLE posts ADD COLUMN author_name TEXT")
        db.execute("CREATE INDEX IF NOT EXISTS post_publisher ON posts(platform,lower(author),author_name) WHERE author IS NOT NULL AND TRIM(author) <> ''")
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
        db.execute("CREATE INDEX IF NOT EXISTS image_public_group ON images(group_id,file_size DESC,id) WHERE hidden=0 AND detection='done'")
        columns = {row[1] for row in db.execute("PRAGMA table_info(images)")}
        for variant in ('image', 'original'):
            for suffix, definition in [('used', 'REAL'), ('evicted', 'INTEGER NOT NULL DEFAULT 0')]:
                column = f'{variant}_{suffix}'
                if column not in columns:
                    db.execute(f'ALTER TABLE images ADD COLUMN {column} {definition}')
        if 'cache_retry_at' not in columns:
            db.execute('ALTER TABLE images ADD COLUMN cache_retry_at REAL NOT NULL DEFAULT 0')
        for column in ('original_failures', 'original_lost'):
            if column not in columns:
                db.execute(f'ALTER TABLE images ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0')
        for column in ("image_sha256", "thumbnail_sha256", "original_filename"):
            if column not in columns:
                db.execute(f"ALTER TABLE images ADD COLUMN {column} TEXT")
        if "trashed_at" not in columns:
            db.execute("ALTER TABLE images ADD COLUMN trashed_at TEXT")
        if "result" not in task_columns:
            db.execute("ALTER TABLE tasks ADD COLUMN result TEXT NOT NULL DEFAULT '{}'")
        db.execute("CREATE INDEX IF NOT EXISTS image_trash ON images(hidden,trashed_at,id)")
        if db.execute("SELECT version FROM schema_version").fetchone()[0] < 9:
            db.execute("UPDATE images SET trashed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE hidden=1 AND trashed_at IS NULL")
            db.execute("UPDATE tasks SET status='cancelled',cancel_requested=1,finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE image_id IN (SELECT id FROM images WHERE hidden=1) AND kind IN ('detect','rematch') AND status IN ('queued','running')")
            if db.execute("SELECT 1 FROM reference_images r JOIN images i ON i.id=r.image_id WHERE i.hidden=1").fetchone():
                schedule_rematch(db)
            db.execute("UPDATE schema_version SET version=9 WHERE version<9")
        if 'embed_id' not in {row[1] for row in db.execute('PRAGMA table_info(posts)')}:
            db.execute('ALTER TABLE posts ADD COLUMN embed_id TEXT')
            db.execute('UPDATE posts SET embed_id=post_identity(platform,url)')
        db.execute('CREATE INDEX IF NOT EXISTS post_embed ON posts(platform,embed_id,id) WHERE embed_id IS NOT NULL')
        db.execute('''CREATE TRIGGER IF NOT EXISTS post_embed_insert AFTER INSERT ON posts BEGIN
            UPDATE posts SET embed_id=post_identity(NEW.platform,NEW.url) WHERE id=NEW.id; END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS post_embed_update AFTER UPDATE OF platform,url ON posts
            WHEN OLD.platform IS NOT NEW.platform OR OLD.url IS NOT NEW.url BEGIN
            UPDATE posts SET embed_id=post_identity(NEW.platform,NEW.url) WHERE id=NEW.id; END''')
        db.execute('CREATE INDEX IF NOT EXISTS image_review_group ON images(group_id,file_size DESC,id) WHERE hidden=0')
        if db.execute('SELECT version FROM schema_version').fetchone()[0] < 14:
            group_index.install(db)
            db.execute('UPDATE schema_version SET version=14')
        if db.execute('SELECT version FROM schema_version').fetchone()[0] < 15:
            db.execute('''UPDATE download_cursors AS checkpoint SET cursor=CASE
                WHEN NOT json_extract(task.payload,'$.scope.quoted') AND NOT json_extract(task.payload,'$.scope.retweets')
                    THEN json_array(0,checkpoint.cursor)
                WHEN json_extract(checkpoint.cursor,'$[0]') > 0 THEN json_array(1,NULL)
                ELSE checkpoint.cursor END
                FROM tasks AS task WHERE task.id=checkpoint.task_id AND json_type(task.payload,'$.scope.retweets') IS NOT NULL
                AND json_extract(task.payload,'$.url') NOT LIKE '%/i/lists/%' ''')
            db.execute('UPDATE schema_version SET version=15')
        for column in ("image_sha256", "thumbnail_sha256"):
            db.execute(f"CREATE INDEX IF NOT EXISTS image_{column} ON images({column})")
        db.execute('''CREATE INDEX IF NOT EXISTS image_pending_backfill ON images(id) WHERE hidden=0
            AND (image_sha256 IS NULL OR thumbnail_sha256 IS NULL OR original_filename IS NULL)''')
        if db.execute('SELECT version FROM schema_version').fetchone()[0] < 16:
            db.execute('INSERT OR IGNORE INTO pending_restore_checks SELECT id FROM images WHERE hidden=1')
            db.execute('UPDATE schema_version SET version=16')
    with startup_phase('interrupted restore cleanup scan'), connect(True) as db:
        recover_hidden_files(db)
    with startup_phase('media hash backfill'):
        backfill_media_hashes()


def recover_hidden_files(db):
    if not db.execute('SELECT 1 FROM pending_restore_checks LIMIT 1').fetchone():
        return
    hidden = {row['sha256']: row for row in db.execute('''SELECT sha256,filename FROM pending_restore_checks c
        CROSS JOIN images i ON i.id=c.image_id WHERE i.hidden=1''')}
    originals = {}
    if hidden:
        with os.scandir(DATA / 'originals') as entries:
            for entry in entries:
                digest, separator, _ = entry.name.partition('.')
                if separator and digest in hidden:
                    originals.setdefault(digest, []).append(Path(entry.path))
    for digest, row in hidden.items():
        paths = originals.get(digest, ())
        if paths or (DATA / 'images' / row['filename']).exists():
            queue_image_cleanup(db, row, paths)
    db.execute('''DELETE FROM pending_restore_checks WHERE NOT EXISTS (SELECT 1 FROM tasks
        WHERE tasks.image_id=pending_restore_checks.image_id AND kind='restore' AND status='running')''')


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
                "SELECT * FROM images INDEXED BY image_pending_backfill WHERE hidden=0 AND id>? AND (image_sha256 IS NULL OR thumbnail_sha256 IS NULL OR original_filename IS NULL) ORDER BY id LIMIT ?",
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


def queue_image_cleanup(db, image, originals=None, *, thumbnail=False):
    paths = [DATA / "images" / image["filename"]]
    if thumbnail:
        paths.append(DATA / 'thumbs' / image['filename'])
    paths.extend((DATA / "originals").glob(image["sha256"] + ".*") if originals is None else originals)
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
    db.execute(f'''INSERT INTO tasks(kind,image_id,target_version)
        SELECT DISTINCT 'rematch',image_id,? FROM faces WHERE {unknown_sql()} AND length(embedding)>0
        AND EXISTS(SELECT 1 FROM images i WHERE i.id=faces.image_id AND i.hidden=0)
        ON CONFLICT(image_id) WHERE kind='rematch' AND status IN ('queued','running')
        DO UPDATE SET target_version=excluded.target_version''', (version,))


def schedule_detection(db, image_id, mode="auto", tier=None):
    import json
    from .task_queue import TIERS
    tier = tier or ('single' if mode == 'highres' else 'bulk')
    active = db.execute("SELECT * FROM tasks WHERE kind='detect' AND image_id=? AND status IN ('queued','running') ORDER BY id", (image_id,)).fetchall()
    for task in active:
        if json.loads(task['payload']).get('mode', 'auto') == 'highres' or mode == 'auto':
            if TIERS.index(tier) < TIERS.index(task['tier']):
                db.execute('UPDATE tasks SET tier=? WHERE id=?', (tier, task['id']))
            return task['id']
    for task in active:
        if task['status'] == 'queued':
            payload = json.loads(task['payload'])
            payload['mode'] = mode
            merged = min((tier, task['tier']), key=TIERS.index)
            db.execute('UPDATE tasks SET payload=?,tier=? WHERE id=?', (json.dumps(payload), merged, task['id']))
            return task['id']
    return db.execute("INSERT INTO tasks(kind,image_id,payload,tier) VALUES('detect',?,?,?)", (image_id, json.dumps({'mode': mode}), tier)).lastrowid
