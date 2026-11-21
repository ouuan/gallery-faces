import json
import os
import select
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest
from app import db, worker
from app.download_part import verified_part
from app.download_round import DownloadRound, EMPTY_RESULT, STALL_LIMIT, YieldRound, cleanup_ready
from app.metadata import metadata
from test_workflows import client
from test_restart_recovery import RAW, source


def enqueue(client, name='alice'):
    return client.post('/api/v1/admin/import', json={'urls': [f'https://x.com/{name}']}).json()[0]['task_id']


def test_bounded_head_start(client, monkeypatch):
    first = enqueue(client)
    task = worker.claim(('download',))
    def pause(task):
        raise YieldRound()
    monkeypatch.setattr(worker, 'import_task', pause)
    worker.execute(task)
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (first,)).fetchone()
        assert row['rounds'] == 1 and row['status'] == 'queued' and not row['finished_at']
        rank = row['queue_rank_at']
    before, equal, after = [enqueue(client, name) for name in ('bob', 'carol', 'dave')]
    with db.connect(True) as conn:
        conn.executemany('UPDATE tasks SET queue_rank_at=? WHERE id=?', [(rank-1, before), (rank, equal), (rank+1, after)])
    worker.recover_tasks()
    assert [worker.claim(('download',))['id'] for _ in range(4)] == [before, equal, first, after]


@pytest.mark.parametrize('at', ['partial', 'ready', 'uncommitted', 'committed', 'cursor'])
def test_killed_download_resumes_once(client, tmp_path, at):
    identifier = enqueue(client)
    photo = source(tmp_path)
    program = f'''
import os, signal
from pathlib import Path
from app import worker
from app.download_round import DownloadRound
from app.metadata import metadata
task = worker.claim(('download',))
active = DownloadRound(task['id'], task['rounds'])
meta = metadata({RAW!r}, '')
def die(*args, **kwargs): os.kill(os.getpid(), signal.SIGKILL)
directory = Path({str(tmp_path)!r}) / 'downloads' / 'attempt-killed'
directory.mkdir()
path = directory / 'photo.png'
if {at!r} == 'partial':
    path.write_bytes(b'partial')
    die()
path.write_bytes(Path({str(photo)!r}).read_bytes())
assert not active.skip(meta)
active.stage(path, meta, directory)
if {at!r} == 'ready': die()
if {at!r} == 'uncommitted': active.record = die
if {at!r} == 'committed': Path.unlink = die
active.import_ready()
active.checkpoint('next-page')
die()
'''
    result = subprocess.run([sys.executable, '-c', program], env={**os.environ, 'DATA_DIR': str(tmp_path)}, timeout=30)
    assert result.returncode == -signal.SIGKILL
    for _ in range(2):
        worker.recover_tasks()
        worker.cleanup_interrupted_files()
        task = worker.claim(('download',))
        active = DownloadRound(identifier, task['rounds'])
        with pytest.raises(ValueError):
            DownloadRound(identifier, 1)
        active.resume()
        meta = metadata(RAW, '')
        if not active.skip(meta):
            assert at == 'partial'
            path = source(tmp_path, 'retry.png')
            active.stage(path, meta, tmp_path)
            active.import_ready()
        assert active.skip(meta)
        assert active.cursor == ('next-page' if at == 'cursor' else None)
    with db.connect() as conn:
        row = conn.execute('SELECT done,result FROM tasks WHERE id=?', (identifier,)).fetchone()
        assert row['done'] == json.loads(row['result'])['imported'] == 1
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='detect'").fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM sources').fetchone()[0] == 1
    assert not list((tmp_path / 'downloads').iterdir())


@pytest.mark.parametrize('changed', [False, True])
def test_partial_requires_same_representation(client, tmp_path, changed):
    identifier = enqueue(client)
    worker.claim(('download',))
    active = DownloadRound(identifier, 1)
    responses = []
    def request(method, url, headers):
        responses.append(dict(headers))
        partial = 'Range' in headers
        return SimpleNamespace(status_code=206 if partial else 200, url=url, close=lambda: None,
                               headers={'ETag': '"new"' if changed and len(responses)>1 else '"old"',
                                        'Content-Length': '3' if partial else '6', 'Content-Range': 'bytes 3-5/6'})
    session = SimpleNamespace(request=request)
    fmt = SimpleNamespace(part_enable=lambda: None)
    url = 'https://pbs.twimg.com/one?token=secret'
    with verified_part(active, session, fmt, metadata(RAW, '')):
        session.request('GET', url, headers={})
        Path(fmt.temppath).write_bytes(b'abc')
    worker.recover_tasks()
    worker.claim(('download',))
    with verified_part(DownloadRound(identifier, 2), session, fmt, metadata(RAW, '')):
        response = session.request('GET', url, headers={'Range': 'bytes=3-'})
        assert response.status_code == (200 if changed else 206)
        assert len(responses) == (3 if changed else 2)
        assert Path(fmt.temppath).exists() != changed
    with db.connect() as conn:
        assert 'secret' not in repr(tuple(conn.execute('SELECT * FROM download_parts').fetchone()))
    client.post(f'/api/v1/admin/tasks/{identifier}/cancel')
    worker.recover_tasks()
    cleanup_ready()
    assert not list((tmp_path / 'downloads').iterdir())


def test_kill_blocked_process_at_deadline(client, monkeypatch):
    identifier = enqueue(client)
    task = worker.claim(('download',))
    task['_deadline'] = worker.time.monotonic() + 0.1
    popen = subprocess.Popen
    children = []
    remnants = [db.DATA / folder / '.asset-interrupted' for folder in ('images', 'thumbs', 'originals')]
    def sleeper(command, **kwargs):
        for path in remnants:
            path.write_bytes(b'incomplete')
        child = popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(worker.subprocess, 'Popen', sleeper)
    worker.execute(task)
    assert children[0].returncode == -signal.SIGKILL
    assert not any(path.exists() for path in remnants)
    assert worker.claim(('download',))['id'] == identifier


def test_media_timeline_only_resumes_photos(monkeypatch):
    from gallery_dl.extractor.twitter import TwitterExtractor, TwitterMediaExtractor
    from gallery_dl.extractor.instagram import InstagramExtractor
    from app.downloader import install_cursors
    for cls in (TwitterExtractor, InstagramExtractor):
        for name in ('_init_cursor', '_update_cursor'):
            monkeypatch.setattr(cls, name, getattr(cls, name))
    monkeypatch.setattr(TwitterMediaExtractor, 'tweets', TwitterMediaExtractor.tweets)
    monkeypatch.setattr(TwitterMediaExtractor, 'pattern', TwitterMediaExtractor.pattern)
    active = SimpleNamespace(cursor='photo-page-2', started_from_cursor=False)
    install_cursors(active, lambda: False)
    extractor = TwitterMediaExtractor.from_url('https://x.com/alice/media')
    extractor.api = SimpleNamespace(user_media_photos=lambda name: [(name, extractor._init_cursor())])
    assert list(extractor.tweets()) == [('alice', 'photo-page-2')]
    assert active.started_from_cursor


@pytest.mark.parametrize('mode', ['no-etag', 'restarted', 'resumed'])
def test_stalled_transfer_bound_and_retry(client, monkeypatch, mode):
    identifier = enqueue(client)
    path = db.DATA / 'downloads' / 'partial-test-file'
    def transfer(task):
        with db.connect(True) as conn:
            offset = path.stat().st_size if mode == 'resumed' and path.exists() else 0
            conn.execute('INSERT OR REPLACE INTO download_parts VALUES(?,?,?,?,?)',
                         (identifier, 'media', path.name, None if mode == 'no-etag' else 'etag', offset))
            path.write_bytes(b'x' * task['rounds'])
        raise YieldRound()
    monkeypatch.setattr(worker, 'import_task', transfer)
    for _ in range(STALL_LIMIT + 2):
        task = worker.claim(('download',))
        if not task:
            break
        worker.execute(task)
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
    if mode == 'resumed':
        assert row['status'] == 'queued' and row['stalled_rounds'] == 0
    else:
        assert row['status'] == 'failed' and '没有可恢复' in row['error']
        assert row['rounds'] == STALL_LIMIT + (mode == 'restarted')
        assert client.post(f'/api/v1/admin/tasks/{identifier}/retry').status_code == 200
        assert worker.claim(('download',))['stalled_rounds'] == 0


def test_legacy_counters_reset_only_on_first_claim(client):
    identifier = enqueue(client)
    with db.connect(True) as conn:
        conn.execute('UPDATE tasks SET done=7,total=9,result=? WHERE id=?', (json.dumps({'imported': 7}), identifier))
    worker.claim(('download',))
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
        assert (row['done'], row['total'], json.loads(row['result'])) == (0, 0, EMPTY_RESULT)


@pytest.mark.parametrize('status', ['done', 'cancelled', 'failed'])
def test_terminal_monitor_releases_items(client, status):
    with db.connect(True) as conn:
        task_id = conn.execute("INSERT INTO tasks(kind) VALUES('monitor')").lastrowid
        conn.execute("INSERT INTO download_items VALUES(?,'x','123','1',NULL)", (task_id,))
        conn.execute('UPDATE tasks SET status=? WHERE id=?', (status, task_id))
        assert not conn.execute('SELECT 1 FROM download_items WHERE task_id=?', (task_id,)).fetchone()


def test_corrupt_item_between_good_ones_is_retried_separately(client, tmp_path, monkeypatch):
    identifier = enqueue(client)
    attempted = []
    def collect(task):
        active = DownloadRound(identifier, task['rounds'])
        for number in (1, 2, 2, 3):
            meta = metadata({**RAW, 'num': number}, '')
            if active.skip(meta):
                continue
            attempted.append(number)
            path = source(tmp_path, f'{number}.png')
            if number == 2 and task['rounds'] == 1:
                path.write_bytes(b'broken')
            active.stage(path, meta, tmp_path)
            active.import_ready()
    monkeypatch.setattr(worker, 'import_task', collect)
    worker.execute(worker.claim(('download',)))
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
        assert row['status'] == 'failed' and '1 张图片导入失败' in row['error']
        assert row['done'] == 2 and attempted == [1, 2, 3]
    assert client.post(f'/api/v1/admin/tasks/{identifier}/retry').status_code == 200
    worker.execute(worker.claim(('download',)))
    with db.connect() as conn:
        row = conn.execute('SELECT status,done FROM tasks WHERE id=?', (identifier,)).fetchone()
        assert tuple(row) == ('done', 3) and attempted == [1, 2, 3, 2]


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux parent death signal')
def test_downloader_exits_when_worker_is_killed():
    code = "from app.downloader import bind_parent; import sys,time; bind_parent(int(sys.argv[1])); print('ready',flush=True); time.sleep(30)"
    parent = subprocess.Popen([sys.executable, '-c',
        'import os,subprocess,sys; subprocess.run([sys.executable,"-c",sys.argv[1],str(os.getpid())])', code],
        stdout=subprocess.PIPE, start_new_session=True)
    try:
        assert select.select([parent.stdout], [], [], 5)[0] and parent.stdout.readline() == b'ready\n'
        parent.kill()
        parent.wait(timeout=5)
        assert select.select([parent.stdout], [], [], 5)[0] and parent.stdout.read() == b''
    finally:
        try:
            os.killpg(parent.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        parent.wait(timeout=5)
        parent.stdout.close()


@pytest.mark.parametrize('expired_cursor', [False, True])
def test_gallery_dl_keeps_checked_media_before_policy_denial(client, tmp_path, monkeypatch, expired_cursor):
    photo = source(tmp_path)
    identifier = enqueue(client)
    script = '''
import sys
from pathlib import Path
from datetime import datetime
from urllib3.response import HTTPResponse
from requests import Response
from requests.adapters import HTTPAdapter
from gallery_dl.extractor.twitter import TwitterExtractor, TwitterAPI
from app.downloader import main
photo = Path(sys.argv.pop(1)).read_bytes()
TwitterExtractor.login = lambda self: None
TwitterAPI.user_by_screen_name = lambda self, name: {'protected': False}
def timeline(self, name):
    if self.extractor._init_cursor() == 'expired':
        raise ValueError('expired test cursor')
    for identifier in ('123', '124'):
        yield {'id_str': identifier, 'user': {'protected': identifier == '124'}}
TwitterAPI.user_original_timeline = timeline
TwitterExtractor._transform_tweet = lambda self, tweet: {'tweet_id': tweet['id_str'], 'author': {'name': 'alice'}, 'date': datetime(2026, 1, 1)}
TwitterExtractor._extract_files = lambda self, data, tweet: [{'url': 'https://pbs.twimg.com/' + data['id_str'] + '.png'}]
def send(self, req, **kwargs):
    assert req.url == 'https://pbs.twimg.com/123.png', req.url
    import io
    response = Response()
    response.url = req.url
    response.status_code = 200
    response.headers.update({'Content-Length': str(len(photo)), 'ETag': '"original"'})
    response.raw = HTTPResponse(body=io.BytesIO(photo), preload_content=False)
    return response
HTTPAdapter.send = send
raise SystemExit(main())
'''
    popen = subprocess.Popen
    def mocked(command, **kwargs):
        return popen([sys.executable, '-c', script, str(photo), *command[3:]], **kwargs)
    monkeypatch.setattr(worker.subprocess, 'Popen', mocked)
    task = worker.claim(('download',))
    if expired_cursor:
        DownloadRound(identifier, task['rounds']).checkpoint('expired')
        worker.execute(task)
        with db.connect() as conn:
            assert conn.execute('SELECT status FROM tasks WHERE id=?', (identifier,)).fetchone()[0] == 'queued'
            assert not conn.execute('SELECT cursor FROM download_cursors WHERE task_id=?', (identifier,)).fetchone()
        task = worker.claim(('download',))
    worker.execute(task)
    with db.connect() as conn:
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
        assert (task['status'], task['error']) == ('failed', '账号非公开或无法确认公开状态')
        assert task['done'] == json.loads(task['result'])['imported'] == 1
        assert [row[0] for row in conn.execute('SELECT post_key FROM posts')] == ['123']
