from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from app import db, main
from test_workflows import recycle, client, image


def seed():
    with db.connect(True) as conn:
        target = image(conn)
        conn.execute('UPDATE faces SET locked=1 WHERE image_id=?', (target,))
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (target,)).fetchone()[0]
    return target, group


def submit(client, target, content='识别有误'):
    return client.post(f'/api/v1/images/{target}/feedback', json={'content': content})


def test_lifecycle(client):
    target, group = seed()
    cookies = dict(client.cookies)
    client.cookies.clear()
    response = submit(client, target, '  人物有误\n<script>alert(1)</script>  ')
    assert response.status_code == 201
    feedback = response.json()
    assert feedback['content'] == '人物有误\n<script>alert(1)</script>'
    path = f"/api/v1/admin/feedback/{feedback['id']}"
    assert client.put(path, json={'status': 'resolved'}).status_code == 401
    assert client.delete(path).status_code == 401
    assert client.get(f'/api/v1/admin/images/{target}/feedback').status_code == 401
    public = f'/api/v1/gallery/{group}/feedback'
    assert client.get(public).status_code == 404
    detail = client.get(f'/api/v1/gallery/{group}').json()
    assert detail['pending_feedback_count'] == 1
    assert feedback['content'] not in str(detail)
    assert set(feedback) == {'id', 'image_id', 'content', 'status', 'created_at', 'resolved_at'}
    client.cookies.update(cookies)
    assert client.get('/api/v1/admin/images?state=feedback').json()[0]['pending_feedback_count'] == 1
    assert client.get('/api/v1/admin/images').json()[0]['id'] == target
    assert client.put(path, json={'status': 'resolved'}).json()['resolved_at']
    assert client.get('/api/v1/admin/images').json() == []
    assert client.get(f'/api/v1/admin/images/{target}/feedback').json()['items'][0]['status'] == 'resolved'
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 0
    assert client.put(path, json={'status': 'pending'}).json()['resolved_at'] is None
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=0 WHERE image_id=?', (target,))
    client.put(path, json={'status': 'resolved'})
    assert client.get('/api/v1/admin/images').json()[0]['id'] == target
    assert client.delete(path).status_code == 200
    assert client.get(f'/api/v1/admin/images/{target}/feedback').json()['items'] == []
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 0
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback_submissions').fetchone()[0] == 1


def test_groups_visibility_pagination_delete(client):
    target, group = seed()
    other, _ = seed()
    first, second = submit(client, target).json(), submit(client, other).json()
    assert client.post('/api/v1/admin/duplicates', json={'a': target, 'b': other, 'action': 'merge'}).status_code == 200
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 2
    assert client.get(f'/api/v1/admin/images/{target}/feedback').json()['items'] == [first]
    assert client.get(f'/api/v1/admin/images/{other}/feedback').json()['items'] == [second]
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (other,))
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=0 WHERE id=?', (other,))
    client.post('/api/v1/admin/duplicates', json={'a': target, 'b': other, 'action': 'separate'})
    assert client.get(f'/api/v1/gallery/{group}').json()['pending_feedback_count'] == 1
    recycle(client, [target])
    assert client.get(f'/api/v1/gallery/{group}').status_code == 404
    assert submit(client, target).status_code == 404
    assert client.get(f'/api/v1/admin/images/{target}/feedback').json()['items'] == [first]
    assert target not in [r['id'] for r in client.get('/api/v1/admin/images?state=feedback').json()]
    assert client.get('/api/v1/admin/images').json()[0]['id'] == other
    assert recycle(client, [target]).status_code == 200
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback WHERE image_id=?', (target,)).fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM feedback_submissions').fetchone()[0] == 2


def test_admin_pagination(client):
    target, _ = seed()
    first, second = submit(client, target).json(), submit(client, target).json()
    path = f'/api/v1/admin/images/{target}/feedback'
    page = client.get(f'{path}?limit=1').json()
    assert page['items'] == [second]
    assert page['next_cursor'] == second['id']
    last = client.get(f"{path}?before_id={page['next_cursor']}").json()
    assert last['items'] == [first]
    assert last['next_cursor'] is None


@pytest.mark.parametrize('content', ['', ' \n ', 'x' * 1001, None])
def test_invalid_content(client, content):
    target, _ = seed()
    assert submit(client, target, content).status_code == 422
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback_submissions').fetchone()[0] == 0


def test_visibility_and_headers(client):
    target, group = seed()
    client.headers.pop('X-Gallery-Request')
    assert submit(client, target).status_code == 403
    client.headers['X-Gallery-Request'] = '1'
    for detection in ['pending', 'failed']:
        with db.connect(True) as conn:
            conn.execute('UPDATE images SET detection=? WHERE id=?', (detection, target))
        assert submit(client, target).status_code == 404
        assert client.get(f'/api/v1/gallery/{group}').status_code == 404
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (target,))
        conn.execute('DELETE FROM sources WHERE image_id=?', (target,))
    assert submit(client, target).status_code == 404
    assert submit(client, 999999).status_code == 404


def test_limits_restart_cleanup(client, monkeypatch):
    target, _ = seed()
    other, _ = seed()
    clock = SimpleNamespace(time=lambda: 2000000000.0, monotonic=monotonic)
    monkeypatch.setattr(main, 'time', clock)
    monkeypatch.setattr(db, 'time', clock)
    monkeypatch.setenv('FEEDBACK_RATE_LIMIT_PER_DAY', '6')
    for i in range(5):
        assert submit(client, target if i % 2 else other).status_code == 201
    blocked = submit(client, target)
    assert blocked.status_code == 429 and blocked.headers['Retry-After'] == '60'
    db.init()
    assert submit(client, target).status_code == 429
    clock.time = lambda: 2000000060.0
    assert submit(client, target).status_code == 201
    blocked = submit(client, target)
    assert blocked.status_code == 429 and blocked.headers['Retry-After'] == '86340'
    clock.time = lambda: 2000086400.0
    assert submit(client, target).status_code == 201
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback_submissions').fetchone()[0] == 2
        assert conn.execute('SELECT ip_hash FROM feedback_submissions').fetchone()[0] != 'testclient'


def test_concurrent_limit(client):
    target, _ = seed()
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(lambda _: submit(client, target).status_code, range(10)))
    assert codes.count(201) == 5 and codes.count(429) == 5


def test_proxy_trust(client, monkeypatch):
    target, _ = seed()
    monkeypatch.setenv('FEEDBACK_RATE_LIMIT_PER_MINUTE', '1')
    for trusted in [False, True]:
        app = ProxyHeadersMiddleware(main.app, trusted_hosts=['testclient'] if trusted else [])
        with TestClient(app) as public:
            for index, address in enumerate(['203.0.113.1', '203.0.113.2']):
                public.headers.update({'X-Gallery-Request': '1', 'X-Forwarded-For': address})
                assert submit(public, target).status_code == (201 if trusted or index == 0 else 429)


def test_failed_transaction_does_not_consume_quota(client):
    import sqlite3
    target, _ = seed()
    with db.connect(True) as conn:
        conn.execute("CREATE TRIGGER reject_submission BEFORE INSERT ON feedback_submissions BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        submit(client, target)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM feedback_submissions').fetchone()[0] == 0
