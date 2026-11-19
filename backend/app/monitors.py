"""Persistent publisher scheduling; mutations hold BEGIN IMMEDIATE transactions."""
import json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from .db import connect
from .security import download_url

def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def instant(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None or 'T' not in value:
            raise ValueError()
        return date.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    except (ValueError, OverflowError):
        raise HTTPException(400, '请选择带时区的日期时间；旧日期链接请重新选择') from None

def active(db, mid):
    return db.execute("SELECT * FROM tasks WHERE kind='monitor' AND json_extract(payload,'$.monitor_id')=? AND status IN ('queued','running')", (mid,)).fetchone()

def enqueue(db, mid, start=None, end=None, retry=None):
    row = db.execute('SELECT * FROM monitors WHERE id=?', (mid,)).fetchone()
    if not row:
        raise HTTPException(404, '监控不存在')
    old = active(db, mid)
    if old:
        if start or retry:
            raise HTTPException(409, '已有活动任务，本项未提交；任务结束后重试')
        return old['id']
    if retry:
        payload = json.loads(retry['payload'])
        if payload.get('generation') != row['generation']:
            raise HTTPException(409, '监控起点已更改，请立刻更新')
    else:
        lower = start or row['start_at']
        if not start and row['progress_at']:
            overlap = (datetime.fromisoformat(row['progress_at'].replace('Z', '+00:00')) - timedelta(minutes=5)).isoformat().replace('+00:00', 'Z')
            lower = max(lower, overlap)
        payload = dict(monitor_id=mid, generation=row['generation'], mode='backfill' if start else 'incremental', start=lower, end=end or now(),
                       url=f"https://{'x.com' if row['platform'] == 'x' else 'www.instagram.com'}/{row['username']}/")
    return db.execute("INSERT INTO tasks(kind,payload) VALUES('monitor',?)", (json.dumps(payload),)).lastrowid

def cancel(db, mid):
    db.execute("UPDATE tasks SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,finished_at=CASE WHEN status='queued' THEN ? ELSE finished_at END WHERE kind='monitor' AND json_extract(payload,'$.monitor_id')=? AND status IN ('queued','running')", (now(), mid))

def finish(db, task):
    payload = json.loads(task['payload'])
    current = db.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone()
    completed = now()
    row = db.execute('SELECT * FROM monitors WHERE id=? AND generation=?', (payload['monitor_id'], payload['generation'])).fetchone()
    if not row:
        return
    due = (datetime.fromisoformat(completed.replace('Z', '+00:00')) + timedelta(minutes=row['interval_minutes'])).isoformat().replace('+00:00', 'Z')
    db.execute('UPDATE monitors SET last_checked_at=?,last_task_id=?,next_check_at=? WHERE id=?', (completed, task['id'], due if payload['mode'] == 'incremental' else row['next_check_at'], row['id']))
    if current['status'] == 'done' and payload['mode'] == 'incremental':
        db.execute('UPDATE monitors SET progress_at=max(coalesce(progress_at,start_at),?) WHERE id=?', (payload['end'], row['id']))

def schedule_due():
    with connect(True) as db:
        for row in db.execute('SELECT id FROM monitors WHERE paused=0 AND next_check_at<=?', (now(),)).fetchall():
            enqueue(db, row['id'])

class Create(BaseModel):
    platform: Literal['instagram', 'x']
    username: str = Field(min_length=1, max_length=100)
    interval_minutes: int = Field(default=60, ge=5)
    start: str = ''

class Edit(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=5)
    paused: bool | None = None

class Resume(BaseModel):
    mode: Literal['catch_up', 'new', 'start'] = 'catch_up'
    start: str = ''

class Batch(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal['delete', 'update', 'backfill', 'interval']
    start: str = ''
    interval_minutes: int | None = Field(default=None, ge=5)

class TaskResult(BaseModel):
    task_id: int

class Created(TaskResult):
    id: int

class BatchResult(BaseModel):
    id: int
    status: Literal['deleted', 'queued', 'updated', 'error']
    task_id: int | None = None
    error: str | None = None

class Candidate(BaseModel):
    platform: str
    username: str
    label: str | None

class Monitor(BaseModel):
    id: int
    platform: str
    username: str
    interval_minutes: int
    paused: int
    start_at: str
    progress_at: str | None
    next_check_at: str
    last_checked_at: str | None
    last_task_id: int | None
    generation: int
    last_status: str | None
    last_result: str | None
    last_error: str | None
    active_task_id: int | None

def listing() -> list[Monitor]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT m.*,t.status AS last_status,t.result AS last_result,t.error AS last_error,(SELECT id FROM tasks WHERE kind='monitor' AND json_extract(payload,'$.monitor_id')=m.id AND status IN ('queued','running')) AS active_task_id FROM monitors m LEFT JOIN tasks t ON t.id=m.last_task_id ORDER BY m.id DESC")]

def candidates(q: str = '') -> list[Candidate]:
    with connect() as db:
        rows = db.execute("SELECT a.platform,a.username,p.name AS label FROM accounts a JOIN people p ON p.id=a.person_id UNION ALL SELECT platform,author,coalesce(author_name,author) FROM posts WHERE author IS NOT NULL").fetchall()
    unique = {}
    for row in rows:
        if row['platform'] in ('x', 'instagram') and q.casefold() in (' '.join(str(v or '') for v in row)).casefold():
            unique.setdefault((row['platform'], row['username'].lower()), dict(row))
    return list(unique.values())[:100]

def create(body: Create) -> Created:
    username = body.username.strip().lstrip('@').lower()
    # Lists use their canonical path as the monitor key, distinct from usernames.
    if body.platform == 'x' and username.startswith('https://'):
        try:
            platform, url = download_url(username)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        if platform != 'x' or not url.startswith('https://x.com/i/lists/'):
            raise HTTPException(400, '请输入 Twitter List 链接或账号用户名')
        username = url.removeprefix('https://x.com/')
    import re
    if not (re.fullmatch(r'[a-z0-9_.]{1,100}', username) or
            (body.platform == 'x' and re.fullmatch(r'i/lists/[0-9]+', username))):
        raise HTTPException(400, '请输入有效用户名')
    try:
        download_url(f"https://{'x.com' if body.platform == 'x' else 'www.instagram.com'}/{username}/")
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    timestamp = now()
    start = instant(body.start) if body.start else timestamp
    if start > timestamp:
        raise HTTPException(400, '起始时间不能晚于当前时间')
    with connect(True) as db:
        if db.execute('SELECT 1 FROM monitors WHERE platform=? AND username=? COLLATE NOCASE', (body.platform, username)).fetchone():
            raise HTTPException(409, '该发布者已在监控列表中')
        mid = db.execute('INSERT INTO monitors(platform,username,interval_minutes,start_at,next_check_at) VALUES(?,?,?,?,?)', (body.platform, username, body.interval_minutes, start, timestamp)).lastrowid
        tid = enqueue(db, mid, end=timestamp)
    return {'id': mid, 'task_id': tid}

def edit(monitor_id: int, body: Edit):
    with connect(True) as db:
        if not db.execute('SELECT 1 FROM monitors WHERE id=?', (monitor_id,)).fetchone():
            raise HTTPException(404, '监控不存在')
        if body.paused is False:
            raise HTTPException(400, '请选择恢复方式')
        if body.interval_minutes is not None:
            db.execute('UPDATE monitors SET interval_minutes=? WHERE id=?', (body.interval_minutes, monitor_id))
        if body.paused:
            db.execute('UPDATE monitors SET paused=1 WHERE id=?', (monitor_id,))
            cancel(db, monitor_id)
    return {'ok': True}

def resume(monitor_id: int, body: Resume) -> TaskResult:
    timestamp = now()
    start = instant(body.start) if body.mode == 'start' else timestamp
    if start > timestamp:
        raise HTTPException(400, '起始时间不能晚于当前时间')
    with connect(True) as db:
        row = db.execute('SELECT * FROM monitors WHERE id=?', (monitor_id,)).fetchone()
        if not row:
            raise HTTPException(404, '监控不存在')
        if active(db, monitor_id):
            raise HTTPException(409, '请等待活动任务结束后恢复')
        if not row['paused']:
            raise HTTPException(409, '监控已恢复')
        if body.mode != 'catch_up':
            db.execute('UPDATE monitors SET start_at=?,progress_at=NULL,generation=generation+1 WHERE id=?', (start, monitor_id))
        db.execute('UPDATE monitors SET paused=0,next_check_at=? WHERE id=?', (timestamp, monitor_id))
        tid = enqueue(db, monitor_id, end=timestamp)
    return {'task_id': tid}

def batch(body: Batch) -> list[BatchResult]:
    if body.action == 'interval' and body.interval_minutes is None:
        raise HTTPException(400, '请输入检查间隔（分钟）')
    timestamp = now()
    start = instant(body.start) if body.action == 'backfill' else None
    if start and start >= timestamp:
        raise HTTPException(400, '补齐起始时间必须早于提交时刻')
    results = []
    for mid in dict.fromkeys(body.ids):
        try:
            with connect(True) as db:
                if not db.execute('SELECT 1 FROM monitors WHERE id=?', (mid,)).fetchone():
                    raise HTTPException(404, '监控不存在')
                if body.action == 'delete':
                    cancel(db, mid)
                    db.execute('DELETE FROM monitors WHERE id=?', (mid,))
                    tid = None
                elif body.action == 'interval':
                    db.execute('UPDATE monitors SET interval_minutes=? WHERE id=?', (body.interval_minutes, mid))
                    tid = None
                else:
                    tid = enqueue(db, mid, start=start, end=timestamp)
            status = {'delete': 'deleted', 'interval': 'updated'}.get(body.action, 'queued')
            results.append(dict(id=mid, status=status, task_id=tid))
        except HTTPException as error:
            results.append(dict(id=mid, status='error', error=error.detail, task_id=None))
    return results

def install(app, admin):
    from fastapi import Depends
    for path, method, endpoint in [
        ('/monitors', 'GET', listing), ('/publisher-candidates', 'GET', candidates),
        ('/monitors', 'POST', create), ('/monitors/{monitor_id}', 'PATCH', edit),
        ('/monitors/{monitor_id}/resume', 'POST', resume), ('/monitors/batch', 'POST', batch),
    ]:
        app.add_api_route('/api/v1/admin' + path, endpoint, methods=[method], dependencies=[Depends(admin)])
