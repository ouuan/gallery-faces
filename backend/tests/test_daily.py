import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from fastapi import HTTPException

from app import daily, db, main
from test_workflows import client, image


DAILY = '/api/v1/gallery/daily'


def photo(conn, **kwargs):
    identifier = image(conn, **kwargs)
    name = f'{identifier}.jpg'
    conn.execute('UPDATE images SET filename=? WHERE id=?', (name, identifier))
    (db.DATA / 'images' / name).write_bytes(name.encode())
    return identifier


def test_rotation_persistence_and_bytes(client, monkeypatch):
    day = '2026-11-01'
    monkeypatch.setattr(daily, 'local_day', lambda: day)
    assert client.get(DAILY).status_code == 404
    with db.connect(True) as conn:
        first = photo(conn)
    for day in ('2026-11-01', '2026-11-03'):
        picked = client.get(DAILY).json()
        assert picked['date'] == day and picked['group_id'] == first
    with db.connect(True) as conn:
        other = photo(conn)
    db.init()
    after_restart = client.get(DAILY).json()
    assert (after_restart['date'], after_restart['group_id']) == (day, first)
    for day, expected in [('2026-11-08', other), ('2026-11-09', first)]:
        direct = client.get(DAILY + '/image', follow_redirects=False)
        meta = client.get(DAILY)
        assert direct.status_code == meta.status_code == 200
        assert direct.headers['content-type'] == 'image/jpeg'
        assert direct.headers['cache-control'] == meta.headers['cache-control'] == 'no-store'
        assert direct.content == client.get(meta.json()['image_url']).content == f'{expected}.jpg'.encode()
        assert meta.json()['group_id'] == expected


def test_filter_identity_and_gallery_eligibility(client):
    with db.connect(True) as conn:
        group = photo(conn)
        photo(conn, group=group, author='Bob')
        photo(conn, faces=False)
        conn.execute("INSERT INTO people(name) VALUES('Alice')")
        conn.execute('UPDATE faces SET person_id=1')
    base = dict(people='1', publishers='x:Bob,x:Alice', start='2026-01-01T00:00:00Z')
    equivalent = dict(people='1,1', publishers='x:ALICE,x:bob,x:bob', match='all', include_no_faces='true',
                      sort='oldest', start='2026-01-01T08:00:00+08:00')
    for params in (base, equivalent):
        assert client.get(DAILY, params=params).json()['group_id'] == group
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM daily_picks').fetchone()[0] == 1
    assert client.get(DAILY, params={'publishers': 'x:bob'}).json()['group_id'] == group
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM daily_picks').fetchone()[0] == 2
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET person_id=NULL')
    assert client.get(DAILY, params=base).status_code == 404
    assert client.get(DAILY, params={'people': '-1'}).status_code == 400


def test_unavailable_and_missing_media(client, monkeypatch):
    with db.connect(True) as conn:
        first = photo(conn)
    assert client.get(DAILY).json()['group_id'] == first
    with db.connect(True) as conn:
        second = photo(conn)
    def unavailable(*args):
        raise HTTPException(503, 'recovering')
    with monkeypatch.context() as patch:
        patch.setattr(main, 'pin_public', unavailable)
        assert client.get(DAILY + '/image').status_code == 503
    assert client.get(DAILY).json()['group_id'] == first
    (db.DATA / 'images' / f'{first}.jpg').unlink()
    assert client.get(DAILY).json()['group_id'] == second
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (second,))
    assert client.get(DAILY + '/image').status_code == 404


def test_simultaneous_web_and_image_requests(client):
    with db.connect(True) as conn:
        for _ in range(8):
            photo(conn)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(client.get, [DAILY, DAILY + '/image'] * 3))
    assert all(response.status_code == 200 for response in responses)
    group = responses[0].json()['group_id']
    assert all(response.json()['group_id'] == group for response in responses[::2])
    assert all(response.content == f'{group}.jpg'.encode() for response in responses[1::2])


def test_day_uses_local_midnight(monkeypatch):
    class TestDate(date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(instant.timestamp())

    monkeypatch.setattr(daily, 'date', TestDate)
    try:
        with monkeypatch.context() as patch:
            patch.setenv('TZ', 'Asia/Shanghai')
            time.tzset()
            instant = datetime(2026, 11, 21, 15, 59, 59, tzinfo=timezone.utc)
            assert daily.local_day() == '2026-11-21'
            instant = instant.replace(hour=16, minute=0, second=0)
            assert daily.local_day() == '2026-11-22'
    finally:
        time.tzset()
