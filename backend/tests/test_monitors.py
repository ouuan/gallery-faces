import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import db, monitors, worker
from test_workflows import client, image

def create(client, **kwargs):
    response = client.post('/api/v1/admin/monitors', json={'platform': 'x', 'username': 'Alice', **kwargs})
    assert response.status_code == 200, response.text
    return response.json()

def get_task(tid):
    with db.connect() as conn:
        return dict(conn.execute('SELECT * FROM tasks WHERE id=?', (tid,)).fetchone())

def run(monkeypatch, failure=False):
    def download(task):
        if failure:
            raise ValueError('network failure')
    monkeypatch.setattr(worker, 'import_task', download)
    worker.step()

def test_create_deduplicate_and_concurrent_enqueue(client):
    item = create(client)
    assert client.post('/api/v1/admin/monitors', json={'platform':'x','username':'ALICE'}).status_code == 409
    def enqueue(_):
        with db.connect(True) as conn:
            return monitors.enqueue(conn, item['id'])
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(enqueue, range(20))) == {item['task_id']}
    monitors.schedule_due()
    assert client.get('/api/v1/admin/tasks?kind=monitor').json()['total'] == 1
    db.init()
    assert len(monitors.listing()) == 1
    with db.connect() as conn:
        assert conn.execute("SELECT 1 FROM settings WHERE key='timezone'").fetchone() is None

def test_monitor_nicknames_by_platform(client):
    create(client)
    create(client, platform='instagram')
    create(client, username='unknown')
    with db.connect(True) as conn:
        conn.execute("INSERT INTO people(id,name) VALUES (1,'已关联人物')")
        conn.executemany("INSERT INTO accounts(person_id,platform,username) VALUES (1,?,'ALICE')", [('x',), ('instagram',)])
        conn.executemany("INSERT INTO posts(platform,post_key,author,author_name) VALUES ('x',?,'Alice',?)",
                         [('1', '旧昵称'), ('2', ' 新昵称 '), ('3', ' ')])
    rows = client.get('/api/v1/admin/monitors').json()
    assert {(row['platform'], row['username']): row['nickname'] for row in rows} == {
        ('x', 'alice'): '新昵称', ('instagram', 'alice'): '已关联人物', ('x', 'unknown'): None,
    }

def test_list_title_refresh(client):
    from gallery_dl.exception import HttpError
    from app.download_round import DownloadRound
    from app.downloader import refresh_list_title

    create(client, username='i/lists/123')
    task = worker.claim()
    active = DownloadRound(task['id'], task['rounds'])
    api = Mock(root='https://x.com/i/api', headers={'x-twitter-auth-type': 'OAuth2Session'}, features={})
    extractor = SimpleNamespace(user='123', api=api, request=Mock())
    def title():
        return client.get('/api/v1/admin/monitors').json()[0]['nickname']
    assert title() is None
    for list_id, name, expected in [('123', ' 摄影 ', '摄影'), ('123', '街拍', '街拍'), ('123', ' ', '街拍'), ('456', '其他', '街拍')]:
        extractor.request.return_value.json.return_value = {'data': {'list': {'id_str': list_id, 'name': name}}}
        refresh_list_title(extractor, active)
        assert title() == expected
    assert json.loads(extractor.request.call_args.kwargs['params']['variables']) == {'listId': '123'}
    extractor.request.side_effect = HttpError('unavailable')
    refresh_list_title(extractor, active)
    assert title() == '街拍'

def test_success_overlap_backfill_and_failure(client, monkeypatch):
    monkeypatch.setattr(monitors, 'now', lambda: '2026-01-02T00:00:00Z')
    item = create(client, start='2026-01-01T00:00:00Z')
    assert get_task(item['task_id'])['tier'] == 'bulk'
    run(monkeypatch)
    row = monitors.listing()[0]
    assert row['progress_at'] == '2026-01-02T00:00:00Z'
    monkeypatch.setattr(monitors, 'now', lambda: '2026-01-03T00:00:00Z')
    monitors.schedule_due()
    tid = monitors.listing()[0]['active_task_id']
    assert json.loads(get_task(tid)['payload'])['start'] == '2026-01-01T23:55:00Z'
    run(monkeypatch, failure=True)
    assert monitors.listing()[0]['progress_at'] == row['progress_at']
    result = monitors.batch(monitors.Batch(ids=[item['id']], action='backfill', start='2025-01-01T00:00:00Z'))[0]
    assert result['task_id']
    run(monkeypatch)
    assert monitors.listing()[0]['progress_at'] == row['progress_at']
    assert monitors.listing()[0]['next_check_at'] == '2026-01-03T01:00:00Z'

def test_pause_resume_cancel_race_and_delete(client, monkeypatch):
    item = create(client, start='2025-01-01T00:00:00Z')
    task = worker.claim()
    monitors.edit(item['id'], monitors.Edit(paused=True))
    assert client.post(f"/api/v1/admin/monitors/{item['id']}/resume",json={}).status_code == 409
    worker.execute(task)
    assert monitors.listing()[0]['progress_at'] is None
    for mode in ['catch_up','new','start']:
        response = monitors.resume(item['id'], monitors.Resume(mode=mode, start='2024-01-01T00:00:00Z'))
        assert get_task(response['task_id'])['tier'] == 'bulk'
        monitors.edit(item['id'], monitors.Edit(paused=True))
    result = monitors.batch(monitors.Batch(ids=[item['id']], action='update'))[0]
    run(monkeypatch)
    assert monitors.listing()[0]['paused'] == 1
    with db.connect(True) as conn:
        photo = image(conn)
    monitors.batch(monitors.Batch(ids=[item['id']], action='delete'))
    assert not monitors.listing()
    with db.connect() as conn:
        assert conn.execute('SELECT 1 FROM images WHERE id=?',(photo,)).fetchone()
    assert client.post(f"/api/v1/admin/tasks/{result['task_id']}/retry", json={}).status_code == 400

def test_partial_batch_retry_and_recovery(client, monkeypatch):
    a = create(client)
    b = create(client, username='bob')
    monitors.edit(b['id'], monitors.Edit(paused=True))
    result = monitors.batch(monitors.Batch(ids=[a['id'],b['id'],999],action='backfill',start='2020-01-01T00:00:00Z'))
    assert [r['status'] for r in result] == ['error','queued','error']
    task = worker.claim()
    worker.recover_tasks()
    assert get_task(task['id'])['status'] == 'queued'
    assert monitors.listing()[1]['progress_at'] is None
    run(monkeypatch, failure=True)
    assert get_task(a['task_id'])['status'] == 'failed'
    assert get_task(result[1]['task_id'])['status'] == 'queued'
    run(monkeypatch)
    assert get_task(result[1]['task_id'])['status'] == 'done'
    response = client.post(f"/api/v1/admin/tasks/{task['id']}/retry",json={})
    assert response.status_code == 200
    assert json.loads(get_task(response.json()['task_id'])['payload']) == json.loads(task['payload'])
    assert client.post(f"/api/v1/admin/tasks/{task['id']}/retry",json={}).status_code == 409

def test_delete_during_completion_cannot_update_new_monitor(client, monkeypatch):
    a = create(client)
    task = worker.claim()
    monitors.batch(monitors.Batch(ids=[a['id']], action='delete'))
    b = create(client)
    monkeypatch.setattr(worker, 'import_task', lambda task: None)
    worker.execute(task)
    assert b['id'] != a['id']
    assert monitors.listing()[0]['last_checked_at'] is None

def test_validation_candidates_interval_and_source_roundtrip(client):
    assert client.post('/api/v1/admin/monitors', json={'platform':'x','username':'alice','interval_minutes':4}).status_code == 422
    assert client.post('/api/v1/admin/monitors', json={'platform':'x','username':'alice','start':'2099-01-01T00:00:00Z'}).status_code == 400
    item = create(client)
    monitors.edit(item['id'], monitors.Edit(interval_minutes=5))
    assert monitors.listing()[0]['interval_minutes'] == 5
    with db.connect(True) as conn:
        photo = image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('人物甲')").lastrowid
        conn.execute("INSERT INTO accounts(person_id,platform,username) VALUES(?,'x','ALICE')",(person,))
        post = conn.execute('SELECT post_id FROM sources WHERE image_id=?',(photo,)).fetchone()[0]
    candidates = client.get('/api/v1/admin/publisher-candidates?q=alice').json()
    assert len(candidates) == 1 and candidates[0]['label'] == '人物甲'
    payload = {'author':'alice','published_at':'2026-01-01T12:34:56+05:45','url':'https://x.com/alice/status/1'}
    assert client.put(f'/api/v1/admin/posts/{post}',json=payload).status_code == 200
    with db.connect() as conn:
        assert conn.execute('SELECT published_at FROM posts WHERE id=?',(post,)).fetchone()[0] == '2026-01-01T06:49:56Z'
    assert client.post('/api/v1/admin/monitors/batch',json={'ids':[item['id']],'action':'backfill','start':''}).status_code == 400
    client.post('/api/v1/logout',json={})
    assert client.get('/api/v1/admin/monitors').status_code == 401


@pytest.mark.parametrize('mode', ['catch_up', 'new', 'start'])
def test_batch_pause_resume_respects_task_state(client, monkeypatch, mode):
    timestamp = '2026-01-02T00:00:00Z'
    monkeypatch.setattr(monitors, 'now', lambda: timestamp)
    original_start = '2025-01-01T00:00:00Z'
    running = create(client, start=original_start)
    worker.claim()
    queued = create(client, username='bob', start=original_start)
    untouched = create(client, username='charlie')
    path = '/api/v1/admin/monitors/batch'
    ids = [running['id'], 999, queued['id'], queued['id']]
    paused = client.post(path, json={'action': 'pause', 'ids': ids}).json()
    assert [row['status'] for row in paused] == ['paused', 'error', 'paused']
    assert get_task(running['task_id'])['cancel_requested']
    assert get_task(queued['task_id'])['status'] == 'cancelled'
    assert get_task(untouched['task_id'])['status'] == 'queued'
    body = {'action': 'resume', 'ids': ids, 'mode': mode, 'start': '2024-01-01T00:00:00Z'}
    if mode == 'start':
        assert client.post(path, json=body | {'start': ''}).status_code == 400
        assert all(row['paused'] for row in monitors.listing() if row['id'] in ids)
    resumed = client.post(path, json=body).json()
    assert [row['status'] for row in resumed] == ['error', 'error', 'resumed']
    assert resumed[0]['error'] == '请等待活动任务结束后恢复'
    payload = json.loads(get_task(resumed[2]['task_id'])['payload'])
    assert payload['start'] == {'catch_up': original_start, 'new': timestamp, 'start': body['start']}[mode]
    assert {row['id']: row['paused'] for row in monitors.listing()} == {
        running['id']: 1, queued['id']: 0, untouched['id']: 0,
    }


def test_batch_interval_preserves_schedule_and_partial_results(client):
    a = create(client)
    b = create(client, username='bob')
    untouched = create(client, username='charlie')
    monitors.edit(b['id'], monitors.Edit(paused=True))
    before = {row['id']: row for row in monitors.listing()}
    response = client.post('/api/v1/admin/monitors/batch', json={
        'ids': [a['id'], b['id'], 999, a['id']], 'action': 'interval', 'interval_minutes': 5,
    })
    assert response.status_code == 200
    assert [r['status'] for r in response.json()] == ['updated', 'updated', 'error']
    for row in monitors.listing():
        expected = dict(before[row['id']])
        if row['id'] != untouched['id']:
            expected['interval_minutes'] = 5
        assert row == expected


@pytest.mark.parametrize('value', [None, 4, 5.5])
def test_batch_interval_rejects_invalid_values(client, value):
    item = create(client)
    body = {'ids': [item['id']], 'action': 'interval'}
    if value is not None:
        body['interval_minutes'] = value
    response = client.post('/api/v1/admin/monitors/batch', json=body)
    assert response.status_code == (400 if value is None else 422)
    assert monitors.listing()[0]['interval_minutes'] == 60


@pytest.mark.parametrize(('platform', 'scope'), [('x', {'quoted': True, 'retweets': True}),
                                                 ('instagram', {'tagged': True, 'stories': False})])
def test_batch_scope_only_changes_selected_monitors(client, platform, scope):
    targets = [create(client, username=name, platform=platform) for name in ['alice', 'bob']]
    untouched = create(client, platform='instagram' if platform == 'x' else 'x')
    before = monitors.listing()
    ids = [target['id'] for target in targets]
    path = '/api/v1/admin/monitors/batch'
    for invalid in [{'ids': [*ids, untouched['id']], 'scope': scope}, {'ids': ids},
                    {'ids': [untouched['id']], 'scope': scope}]:
        assert client.post(path, json={'action': 'scope', **invalid}).status_code in (400, 422)
        assert monitors.listing() == before
    response = client.post(path, json={'action': 'scope', 'scope': scope, 'ids': [*ids, 999, ids[0]]})
    assert [(row['id'], row['status']) for row in response.json()] == [(ids[0], 'updated'), (ids[1], 'updated'), (999, 'error')]
    assert monitors.listing() == [row | {'scope': scope} if row['id'] in ids else row for row in before]
    for target in targets:
        assert json.loads(get_task(target['task_id'])['payload'])['scope'] != scope


@pytest.mark.parametrize('host', ['x.com', 'twitter.com', 'www.twitter.com'])
def test_list_monitor_canonicalization_and_scheduling(client, monkeypatch, host):
    item = create(client, username=f'https://{host}/i/lists/123456/?s=20')
    assert monitors.listing()[0]['username'] == 'i/lists/123456'
    assert json.loads(get_task(item['task_id'])['payload'])['url'] == 'https://x.com/i/lists/123456/'
    assert client.post('/api/v1/admin/monitors', json={'platform': 'x', 'username': 'i/lists/123456'}).status_code == 409
    run(monkeypatch)
    result = monitors.batch(monitors.Batch(ids=[item['id']], action='backfill', start='2020-01-01T00:00:00Z'))[0]
    assert json.loads(get_task(result['task_id'])['payload'])['url'] == 'https://x.com/i/lists/123456/'
    run(monkeypatch)
    monitors.edit(item['id'], monitors.Edit(paused=True))
    resumed = monitors.resume(item['id'], monitors.Resume())
    assert json.loads(get_task(resumed['task_id'])['payload'])['url'] == 'https://x.com/i/lists/123456/'


@pytest.mark.parametrize('platform,username', [('instagram', 'i/lists/123'), ('x', 'i/lists/abc'), ('x', 'https://x.com/i/lists/123/members'), ('x', 'https://evil.com/i/lists/123'), ('x', 'https://x.com/alice/status/123')])
def test_invalid_list_monitors(client, platform, username):
    assert client.post('/api/v1/admin/monitors', json={'platform': platform, 'username': username}).status_code == 400
    assert not monitors.listing()
