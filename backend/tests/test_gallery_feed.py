import subprocess
from types import SimpleNamespace
from xml.etree import ElementTree as XML

from app import db, publisher_avatars, worker
from test_workflows import client, image


def test_feed_matching_images_and_complete_post(client):
    with db.connect(True) as conn:
        for _ in range(5):
            image(conn)
        conn.execute("UPDATE posts SET url='https://twitter.com/alice/status/1/photo/1' WHERE id=2")
        conn.execute("UPDATE posts SET post_text='<tag> & 正文\n下一行' WHERE id=1")
        conn.executemany("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,?)", [(3,'3'), (4,'4'), (5,'5')])
        conn.execute('UPDATE images SET hidden=1 WHERE id=5')
        conn.execute("INSERT INTO people(id,name) VALUES(1,'Alice')")
        conn.execute('UPDATE faces SET person_id=1 WHERE image_id=1')
    client.cookies.clear()
    response = client.get('/api/v1/gallery/rss.xml?people=1&match=exact&photo=3&sort=oldest')
    assert response.headers['content-type'].startswith('application/rss+xml')
    channel = XML.fromstring(response.content).find('channel')
    item, = channel.findall('item')
    assert item.findtext('link') == 'http://testserver/posts/x:1?people=1&match=exact'
    assert channel.findtext('link') == 'http://testserver/?people=1&match=exact'
    description = item.findtext('description')
    assert description.count('<img ') == 1 and 'Alice' in description
    assert '&lt;tag&gt; &amp; 正文<br>下一行' in description
    assert 'publishers=x%3Aalice' in description
    detail = client.get('/api/v1/posts/x:1?people=1').json()
    assert {picture['id'] for picture in detail['images']} == {1,2,3,4}
    assert client.get('/api/v1/gallery/2').json()['sources'][0]['key'] == detail['key']
    assert item.findtext('guid') in [entry.text for entry in XML.fromstring(client.get('/api/v1/gallery/rss.xml').content).findall('.//guid')]
    assert not XML.fromstring(client.get('/api/v1/gallery/rss.xml?people=2').content).findall('.//item')
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1')
    assert client.get('/api/v1/posts/x:1').status_code == 404


def test_post_retains_only_eligible_trash_thumbnails(client):
    with db.connect(True) as conn:
        for _ in range(7):
            image(conn)
        conn.execute("UPDATE posts SET url='https://x.com/alice/status/1/photo/2' WHERE id=2")
        conn.executemany('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,?)',
                         [(identifier, str(identifier)) for identifier in (3, 4, 5, 6)])
        conn.execute("UPDATE images SET hidden=1,filename=printf('%d.jpg',id) WHERE id IN (2,4,5,6)")
        conn.execute("UPDATE images SET detection='pending' WHERE id=6")
        conn.execute('UPDATE images SET group_id=3 WHERE id=5')
    for name in ('2.jpg', '5.jpg', '6.jpg'):
        (db.DATA / 'thumbs' / name).write_bytes(name.encode())
    client.cookies.clear()
    detail = '/api/v1/posts/x:1'
    pictures = client.get(detail).json()['images']
    assert [picture['id'] for picture in pictures] == [1, 2, 3]
    assert pictures[0]['image_url'] and pictures[2]['image_url']
    assert pictures[1]['image_url'] is None and pictures[1]['people'] == []
    url = pictures[1]['thumbnail_url']
    response = client.get(url)
    assert response.content == b'2.jpg' and response.headers['cache-control'] == 'no-store'
    for path in ('/api/v1/posts/x:7/thumbnails/2', '/api/v1/media/2?thumbnail=true', '/api/v1/media/2',
                 '/api/v1/gallery/2', *(f'{detail}/thumbnails/{group}' for group in (3, 4, 6))):
        assert client.get(path).status_code == 404
    feed = XML.fromstring(client.get('/api/v1/gallery/rss.xml').content)
    entry = next(item for item in feed.findall('.//item') if item.findtext('link').endswith('/posts/x:1'))
    assert entry.findtext('description').count('<img ') == 2
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id IN (1,3)')
    assert client.get(detail).status_code == client.get(url).status_code == 404


def test_feed_latest_twenty_after_dedup_and_fallback_identity(client):
    with db.connect(True) as conn:
        for day in range(1, 24):
            image(conn, date=f'2026-01-{day:02}T00:00:00Z')
        conn.execute("UPDATE posts SET url='https://x.com/alias/status/22' WHERE id=23")
        conn.execute("UPDATE posts SET url='https://x.com/alice' WHERE id=21")
    items = XML.fromstring(client.get('/api/v1/gallery/rss.xml').content).findall('.//item')
    assert len(items) == 20
    assert [item.findtext('link').split('/')[-1] for item in items[:2]] == ['x:22', 'x:record:21']
    assert items[-1].findtext('link').endswith('/x:3')
    assert client.get('/api/v1/posts/x:record:21').json()['images'][0]['id'] == 21


def test_avatar_refresh_lifecycle(client, monkeypatch):
    endpoint = '/api/v1/publisher-avatars/x/ALICE'
    assert client.get(endpoint).status_code == 404
    with db.connect(True) as conn:
        image(conn)
    client.cookies.clear()
    for _ in range(3):
        assert client.get(endpoint).json() == {'pending': True, 'image_url': None}
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='avatar'").fetchone()[0] == 1
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kw: SimpleNamespace(stdout=b'avatar'))
    worker.execute(worker.claim(('avatar',)))
    state = client.get(endpoint).json()
    assert not state['pending']
    image_url = state['image_url']
    assert client.get(image_url).content == b'avatar'
    with db.connect() as conn:
        deadline = conn.execute('SELECT next_check FROM publisher_avatars').fetchone()[0]
        assert abs(deadline - publisher_avatars.time.time() - 86400) < 5
    with monkeypatch.context() as clock:
        clock.setattr(publisher_avatars.time, 'time', lambda: deadline - 1)
        assert not client.get(endpoint).json()['pending']
        clock.setattr(publisher_avatars.time, 'time', lambda: deadline)
        assert client.get(endpoint).json() == {'image_url': image_url, 'pending': True}
    def unavailable(*args, **kwargs):
        raise subprocess.TimeoutExpired('avatar', 45)
    monkeypatch.setattr(subprocess, 'run', unavailable)
    worker.execute(worker.claim(('avatar',)))
    assert client.get(endpoint).json() == state
    with db.connect(True) as conn:
        conn.execute('UPDATE publisher_avatars SET next_check=0')
    client.get(endpoint)
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kw: SimpleNamespace(stdout=b'new avatar'))
    worker.execute(worker.claim(('avatar',)))
    changed = client.get(endpoint).json()['image_url']
    assert changed != image_url and client.get(changed).content == b'new avatar'
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1')
    assert client.get(changed).status_code == client.get(endpoint).status_code == 404
