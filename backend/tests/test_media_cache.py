import hashlib

import pytest
from PIL import Image

from app import db, importer, main
from test_workflows import recycle, client, image


def seed():
    with db.connect(True) as conn:
        identifier = image(conn)
        row = conn.execute('SELECT * FROM images WHERE id=?', (identifier,)).fetchone()
    for folder, content in [('images', b'display bytes'), ('thumbs', b'thumbnail bytes')]:
        (db.DATA / folder / row['filename']).write_bytes(content)
    original = b'original bytes'
    digest = hashlib.sha256(original).hexdigest()
    (db.DATA / 'originals' / (digest + '.png')).write_bytes(original)
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET sha256=? WHERE id=?', (digest, identifier))
    db.backfill_media_hashes()
    return identifier, row['group_id']


def test_admin_review_thumbnail(client):
    identifier, _ = seed()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (identifier,))
    url = f'/api/v1/admin/media/{identifier}'
    assert client.get(url).status_code == 404
    assert client.get(url + '?thumbnail=true').content == b'thumbnail bytes'
    client.cookies.clear()
    assert client.get(url + '?thumbnail=true').status_code == 401


def test_hash_media_and_http(client):
    identifier, group = seed()
    detail = client.get(f'/api/v1/gallery/{group}').json()
    assert client.get('/api/v1/gallery').json()['items'][0]['image_url'] == detail['image_url']
    for field in ('image_url', 'thumbnail_url', 'download_url'):
        url = detail[field]
        response = client.get(url)
        digest = hashlib.sha256(response.content).hexdigest()
        assert url.endswith(digest)
        assert response.headers['etag'] == f'"{digest}"'
        assert response.headers['cache-control'] == main.IMMUTABLE
        assert client.head(url).content == b''
        assert client.head(url).headers['content-length'] == str(len(response.content))
        for tag in (response.headers['etag'], 'W/' + response.headers['etag'], '*', '"other", W/' + response.headers['etag']):
            cached = client.get(url, headers={'If-None-Match': tag})
            assert cached.status_code == 304
            assert cached.headers['cache-control'] == main.IMMUTABLE
        assert client.get(url, headers={'If-Modified-Since': response.headers['last-modified']}).status_code == 304
        assert client.get(url, headers={'If-None-Match': '"other"', 'If-Modified-Since': response.headers['last-modified']}).status_code == 200
        partial = client.get(url, headers={'Range': 'bytes=0-3'})
        assert partial.status_code == 206 and partial.content == response.content[:4]
        assert client.get(url, headers={'Range': 'bytes=99999-'}).headers['cache-control'] == 'no-store'
    assert client.get(detail['download_url']).headers['content-disposition'] == 'attachment; filename="' + detail['download_url'].split('/')[-1] + '.png"'
    assert 'attachment;' in client.get(detail['image_url'] + '?download=true').headers['content-disposition']
    assert client.get(f'/api/v1/media/{identifier}').headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/gallery').headers['cache-control'] == 'no-store'
    client.cookies.clear()
    assert client.get(detail['image_url']).headers['etag'] == client.head(detail['image_url']).headers['etag']
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (identifier,))
    denied = client.get(detail['image_url'], headers={'If-None-Match': '*'})
    assert denied.status_code == 404 and denied.headers['cache-control'] == 'no-store'


def test_missing_original_and_shared_hash(client):
    identifier, group = seed()
    detail = client.get(f'/api/v1/gallery/{group}').json()
    for path in (db.DATA / 'originals').iterdir():
        path.unlink()
    fallback = client.get(f'/api/v1/gallery/{group}').json()['download_url']
    assert fallback == detail['image_url'] + '?download=true'
    assert client.get(detail['download_url']).status_code == 404
    with db.connect(True) as conn:
        other = image(conn)
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (identifier,))
    db.backfill_media_hashes()
    assert client.get(detail['image_url']).status_code == 200
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET filename='missing.jpg',hidden=0 WHERE id=?", (identifier,))
    assert client.get(detail['image_url']).status_code == 200
    (db.DATA / 'images' / 'fixture.jpg').unlink()
    assert client.get(detail['image_url'], headers={'If-None-Match': '*'}).status_code == 404
    assert client.get(f'/api/v1/gallery/{other}').json()['image_url'] == f'/api/v1/media/{other}'
    assert client.get(f'/api/v1/media/{other}').status_code == 404
    for path in ('image/nope', 'unknown/' + 'a'*64, 'image/' + 'A'*64):
        response = client.get('/api/v1/media/by-hash/' + path)
        assert response.status_code in (404, 422) and response.headers['cache-control'] == 'no-store'


def test_migration_resume(client, monkeypatch):
    with db.connect(True) as conn:
        first, second = image(conn), image(conn)
    (db.DATA / 'images' / 'fixture.jpg').write_bytes(b'image')
    real_hash = db.file_hash
    calls = 0
    def interrupted(path):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError('interrupted')
        return real_hash(path)
    monkeypatch.setattr(db, 'file_hash', interrupted)
    with pytest.raises(RuntimeError):
        db.backfill_media_hashes(batch_size=1)
    with db.connect() as conn:
        assert conn.execute('SELECT image_sha256 FROM images WHERE id=?', (first,)).fetchone()[0]
        assert conn.execute('SELECT image_sha256 FROM images WHERE id=?', (second,)).fetchone()[0] is None
    monkeypatch.setattr(db, 'file_hash', real_hash)
    (db.DATA / 'thumbs' / 'fixture.jpg').write_bytes(b'thumb')
    db.init()
    monkeypatch.setattr(db, 'file_hash', lambda path: pytest.fail('completed hashes recomputed'))
    db.init()


def test_import_stable_and_changed_derivatives(client, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, 'deduplicate', lambda _: None)
    path = tmp_path / 'input.png'
    Image.new('RGB', (20, 20), 'red').save(path)
    raw = dict(platform='x', author='alice', tweet_id='123', date='2026-01-01', url='https://x.com/alice/status/123')
    identifier = importer.import_file(path, raw)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (identifier,))
        row = conn.execute('SELECT * FROM images WHERE id=?', (identifier,)).fetchone()
    before = main.media_urls(row)
    assert importer.import_file(path, raw) == identifier
    with db.connect() as conn:
        assert main.media_urls(conn.execute('SELECT * FROM images WHERE id=?', (identifier,)).fetchone()) == before
    Image.new('RGB', (20, 20), 'blue').save(db.DATA / 'images' / row['filename'])
    importer.import_file(path, raw)
    with db.connect() as conn:
        after = main.media_urls(conn.execute('SELECT * FROM images WHERE id=?', (identifier,)).fetchone())
    assert before['image_url'] != after['image_url']
    assert client.get(before['image_url']).status_code == 404
    assert hashlib.sha256(client.get(after['image_url']).content).hexdigest() == after['image_url'].split('/')[-1]


def test_deleted_hash_rejected(client):
    identifier, group = seed()
    url = client.get(f'/api/v1/gallery/{group}').json()['image_url']
    response = recycle(client, [identifier])
    # Use the same deletion endpoint as the management UI.
    assert response.status_code == 200
    assert client.get(url, headers={'If-None-Match': '*'}).status_code == 404


def test_static_cache(tmp_path):
    import os
    import subprocess
    import sys
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'index-abc123.js').write_text('export {}')
    (tmp_path / 'index.html').write_text('<html>app</html>')
    subprocess.run([sys.executable, '-c', '''
from app.main import app
from fastapi.testclient import TestClient
client = TestClient(app)
for url in ('/', '/gallery/route'):
    response = client.get(url)
    assert response.headers['cache-control'] == 'no-cache'
    assert response.headers['cloudflare-cdn-cache-control'] == 'no-store'
    assert client.head(url).content == b''
    assert client.get(url, headers={'If-None-Match': response.headers['etag']}).status_code == 304
    assert client.get(url, headers={'If-None-Match': '"different"', 'If-Modified-Since': response.headers['last-modified']}).status_code == 200
assert client.get('/assets/index-abc123.js').headers['cache-control'] == 'public, max-age=31536000, immutable'
for url in ('/assets/missing.js', '/api/missing'):
    response = client.get(url)
    assert response.status_code == 404
    assert response.headers['cache-control'] == 'no-store'
'''], check=True, env={**os.environ, 'FRONTEND_DIR': str(tmp_path)})


def test_uncaught_errors_never_cached(client, monkeypatch):
    from fastapi.testclient import TestClient
    _, group = seed()
    url = client.get(f'/api/v1/gallery/{group}').json()['image_url']
    def broken(*args, **kwargs):
        raise OSError('storage unavailable')
    monkeypatch.setattr(main, 'conditional_file', broken)
    with TestClient(main.app, raise_server_exceptions=False) as anonymous:
        response = anonymous.get(url)
        assert response.status_code == 500
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['cloudflare-cdn-cache-control'] == 'no-store'
