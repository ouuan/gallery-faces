"""Durable checkpoints for a single claimed download round."""
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import db as storage
from .metadata import publisher_blocked, save_source, source_image
from .feed_scope import feeds


ROUND_SECONDS = 300
STALL_LIMIT = 3
KINDS = ('download', 'monitor')
EMPTY_RESULT = {'imported': 0, 'skipped_existing': 0, 'skipped_trashed': 0}


class YieldRound(Exception):
    pass


@dataclass
class RoundProgress:
    done: int
    errors: int
    cursor: str | None
    ready: str | None
    validator: str | None
    offset: int
    size: int

    @classmethod
    def read(cls, db, task_id):
        row = db.execute('''SELECT t.done,(SELECT count(*) FROM download_item_errors WHERE task_id=t.id),
            c.cursor,r.filename,p.validator,p.resume_offset,p.filename FROM tasks t
            LEFT JOIN download_cursors c ON c.task_id=t.id LEFT JOIN download_ready r ON r.task_id=t.id
            LEFT JOIN download_parts p ON p.task_id=t.id WHERE t.id=?''', (task_id,)).fetchone()
        size = 0
        if row[4]:
            try:
                size = (storage.DATA / 'downloads' / row[6]).stat().st_size
            except FileNotFoundError:
                pass
        return cls(*tuple(row)[:6], size)

    def advanced_from(self, previous):
        return (self.done > previous.done or self.errors > previous.errors
                or bool(self.cursor and self.cursor != previous.cursor)
                or bool(self.ready and self.ready != previous.ready)
                or (self.size > previous.size and (not previous.size or
                    (self.validator == previous.validator and self.offset >= previous.size))))


def item_error_summary(db, task_id):
    count = db.execute('SELECT count(*) FROM download_item_errors WHERE task_id=?', (task_id,)).fetchone()[0]
    if count:
        rows = db.execute('SELECT platform,post_key,media,reason FROM download_item_errors WHERE task_id=? ORDER BY platform,post_key,media LIMIT 10', (task_id,))
        details = '；'.join(f'{platform}/{post}/{media}: {reason}' for platform, post, media, reason in rows)
        return f'{count} 张图片导入失败，其他已入库图片保留：{details}'


class DownloadRound:
    def __init__(self, task_id, number):
        self.task_id = task_id
        self.number = number
        self.started = time.monotonic()
        self.processed = 0
        with storage.connect() as db:
            row = self.owner(db)
            self.payload = json.loads(row['payload'])
            saved = db.execute('SELECT cursor FROM download_cursors WHERE task_id=?', (task_id,)).fetchone()
        self.cursor = saved[0] if saved else None
        self.feeds = feeds(self.payload)
        self.feed_index = 0
        if self.cursor and len(self.feeds) > 1:
            self.feed_index, self.cursor = json.loads(self.cursor)
        self.started_from_cursor = False
        self.advanced = False
        self.saw_item = False

    def owner(self, db):
        row = db.execute("SELECT payload,tier FROM tasks WHERE id=? AND rounds=? AND status='running' AND cancel_requested=0",
                         (self.task_id, self.number)).fetchone()
        if not row:
            raise ValueError('下载轮次已结束')
        return row

    def checkpoint(self, cursor):
        if len(self.feeds) > 1 and (cursor or self.feed_index):
            cursor = json.dumps([self.feed_index, cursor])
        with storage.connect(True) as db:
            self.owner(db)
            if cursor:
                db.execute('INSERT OR REPLACE INTO download_cursors VALUES(?,?)', (self.task_id, cursor))
            else:
                db.execute('DELETE FROM download_cursors WHERE task_id=?', (self.task_id,))
        self.advanced = True

    def next_feed(self):
        if self.feed_index + 1 == len(self.feeds):
            return False
        self.feed_index += 1
        self.checkpoint(None)
        return True

    def identity(self, meta):
        if meta['key'].startswith('incomplete:') or not meta['media']:
            raise ValueError('缺少下载来源标识')
        return self.task_id, meta['platform'], meta['key'], meta['media']

    def record(self, db, meta, image_id, outcome):
        db.execute('INSERT INTO download_items VALUES(?,?,?,?,?)', (*self.identity(meta), image_id))
        field = '$.' + outcome
        self.processed += 1
        speed = self.processed / max(0.01, time.monotonic() - self.started)
        db.execute('UPDATE tasks SET done=done+1,speed=?,result=json_set(result,?,coalesce(json_extract(result,?),0)+1) WHERE id=?',
                   (speed, field, field, self.task_id))

    def skip(self, meta):
        self.saw_item = True
        meta['collected'] = urlsplit(self.payload['url']).path.strip('/').split('/')[0]
        if meta['url']:
            meta['url'] = urlsplit(meta['url'])._replace(query='', fragment='').geturl()
        with storage.connect(True) as db:
            self.owner(db)
            if publisher_blocked(db, meta):
                return True
            if db.execute('''SELECT 1 FROM download_items WHERE (task_id,platform,post_key,media)=(?1,?2,?3,?4)
                UNION ALL SELECT 1 FROM download_item_errors WHERE (task_id,platform,post_key,media)=(?1,?2,?3,?4) LIMIT 1''',
                          self.identity(meta)).fetchone():
                return True
            known = source_image(db, meta)
            if known:
                save_source(db, known['id'], meta)
                self.record(db, meta, known['id'], 'skipped_trashed' if known['hidden'] else 'skipped_existing')
                return True
        return False

    def stage(self, path, meta, directory):
        from .importer import EXTENSIONS
        path = Path(path).resolve(strict=True)
        if not path.is_relative_to(directory.resolve()) or path.suffix.lower() not in EXTENSIONS:
            raise ValueError('下载文件路径或类型无效')
        filename = f'ready-{self.task_id}-{uuid.uuid4().hex}{path.suffix.lower()}'
        target = storage.DATA / 'downloads' / filename
        with storage.connect(True) as db:
            self.owner(db)
            with path.open('rb') as handle:
                os.fsync(handle.fileno())
            path.replace(target)
            descriptor = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            db.execute('INSERT INTO download_ready VALUES(?,?,?)', (self.task_id, filename, json.dumps(meta)))
            db.execute('DELETE FROM download_parts WHERE task_id=?', (self.task_id,))

    def import_ready(self):
        from .importer import import_media, finish_deduplication
        from PIL import Image
        with storage.connect(True) as db:
            owner = self.owner(db)
            row = db.execute('SELECT * FROM download_ready WHERE task_id=?', (self.task_id,)).fetchone()
            if not row:
                return
            path = storage.DATA / 'downloads' / row['filename']
            meta = json.loads(row['meta'])
            db.execute('SAVEPOINT import_item')
            try:
                image_id, outcome = import_media(db, path, meta, tier=owner['tier'])
            except (ValueError, OSError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
                if isinstance(exc, OSError) and exc.errno is not None:
                    raise
                db.execute('ROLLBACK TO import_item')
                db.execute('INSERT INTO download_item_errors VALUES(?,?,?,?,?)', (*self.identity(meta), type(exc).__name__))
                image_id = None
            else:
                if image_id is not None:
                    self.record(db, meta, image_id, outcome)
            db.execute('RELEASE import_item')
            db.execute('DELETE FROM download_ready WHERE task_id=?', (self.task_id,))
        path.unlink(missing_ok=True)
        if image_id is not None and outcome != 'skipped_trashed':
            finish_deduplication(image_id)

    def resume(self):
        from .importer import finish_deduplication
        with storage.connect() as db:
            pending = db.execute('''SELECT DISTINCT item.image_id FROM download_items item
                JOIN pending_deduplications USING(image_id) WHERE task_id=?''', (self.task_id,)).fetchall()
        for row in pending:
            finish_deduplication(row[0])
        self.import_ready()


def cleanup_ready():
    for prefix, table in [('ready', 'download_ready'), ('partial', 'download_parts')]:
        for path in (storage.DATA / 'downloads').glob(f'{prefix}-*-*'):
            with storage.connect(True) as db:
                if not db.execute(f'SELECT 1 FROM {table} WHERE filename=?', (path.name,)).fetchone():
                    path.unlink(missing_ok=True)
