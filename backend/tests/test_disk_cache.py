import errno
import fcntl
import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

from app import db, importer, main, media_cache as cache, worker
from app import cache_status
from test_workflows import client, recycle


def photo(tmp_path, number=1, color='red'):
    source = tmp_path / f'input-{number}.png'
    Image.new('RGB', (32, 32), color).save(source)
    raw = dict(platform='x', author='alice', tweet_id=str(number), date='2026-01-01',
               url=f'https://x.com/alice/status/{number}')
    identifier = importer.import_file(source, raw)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done', image_used=1, original_used=1 WHERE id=?", (identifier,))
        row = cache.active(conn, identifier)
    return row, source


def evict(row, variant):
    path = cache.asset_path(row, variant)
    now = time.time()
    cache.evict(row['id'], variant, path.stat().st_dev, now, now - cache.DAY)
    return path


def test_corrupt_only_original_preserves_display(client, tmp_path):
    row, source = photo(tmp_path)
    source.unlink()
    with db.connect(True) as conn:
        conn.execute('UPDATE posts SET url=NULL')
    cache.asset_path(row, 'original').write_bytes(b'bad')
    assert db.file_hash(evict(row, 'image')) == row['image_sha256']


@pytest.mark.parametrize('platform,url,raw,other', [
    ('twitter', 'https://x.com/alice/status/1', {'tweet_id': '1'}, {'tweet_id': '2'}),
    ('instagram', 'https://www.instagram.com/p/SomePost/', {'post_id': '56', 'shortcode': 'SomePost'}, {'post_id': '56', 'shortcode': 'OtherPost'}),
])
def test_cache_filter_checks_all_media_from_requested_post(client, monkeypatch, platform, url, raw, other):
    from app.downloader import install_library_filter
    from gallery_dl.job import DownloadJob
    calls = []
    monkeypatch.setattr(DownloadJob, 'handle_url', lambda self, url, raw: calls.append(raw['num']))
    install_library_filter(restore_id=1, cache_post=url)
    job = SimpleNamespace(extractor=SimpleNamespace(category=platform))
    for number, post in [(1, raw), (2, raw), (3, other)]:
        DownloadJob.handle_url(job, 'unused', {**post, 'num': number})
    assert calls == [1, 2]


def test_present_public_file_with_database_writer(client, tmp_path):
    row, _ = photo(tmp_path)
    url = main.media_urls(row)['image_url']
    client.cookies.clear()
    with db.connect(True) as writer:
        assert client.get(url).status_code == 200
        assert writer.execute('SELECT image_used FROM images WHERE id=?', (row['id'],)).fetchone()[0] == 1
    assert client.get(url).status_code == 200
    with db.connect() as conn:
        assert cache.active(conn, row['id'])['image_used'] > 1


@pytest.mark.parametrize('backup', ['local', 'remote'])
def test_unreadable_source_does_not_block_recovery(client, tmp_path, monkeypatch, backup):
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    row, source = photo(tmp_path)
    content = source.read_bytes()
    path = evict(row, 'original')
    if backup == 'local':
        second = tmp_path / 'second.png'
        second.write_bytes(content)
        with db.connect(True) as conn:
            importer.record_location(conn, row['id'], second)
    def download(task, payload, attempt, restore_id):
        assert backup == 'remote'
        (attempt / 'match.png').write_bytes(content)
        return attempt
    monkeypatch.setattr(worker, 'download_media', download)
    real_open = type(path).open
    def deny_first(candidate, *args, **kwargs):
        if candidate == source:
            raise PermissionError('unreadable source')
        return real_open(candidate, *args, **kwargs)
    monkeypatch.setattr(type(path), 'open', deny_first)
    with cache.asset(row, 'original'):
        assert path.read_bytes() == content


def test_cleanup_skips_inaccessible_candidate(client, tmp_path, monkeypatch):
    accessible, _ = photo(tmp_path)
    denied, _ = photo(tmp_path, 2, 'blue')
    blocked = cache.asset_path(denied, 'image')
    available = cache.asset_path(accessible, 'image')
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_used=10')
        conn.execute('UPDATE images SET image_used=1 WHERE id=?', (denied['id'],))
    real_open = type(blocked).open
    def deny(candidate, *args, **kwargs):
        if candidate == blocked:
            raise PermissionError('inaccessible cold file')
        return real_open(candidate, *args, **kwargs)
    monkeypatch.setattr(type(blocked), 'open', deny)
    monkeypatch.setattr(cache, 'free_bytes', lambda root: 1 if available.exists() else 10)
    cache.clean(5, 10, cache.DAY)
    assert blocked.exists() and not available.exists()


def test_unavailable_duplicate_deferred_without_blocking_import(client, tmp_path, monkeypatch):
    cold, _ = photo(tmp_path)
    warm, _ = photo(tmp_path, 2, 'blue')
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET phash='1',image_used=1")
    evict(cold, 'image')
    original = evict(cold, 'original')
    original.unlink(missing_ok=True)
    monkeypatch.setattr(worker, 'download_media', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('gone')))
    monkeypatch.setattr(importer, 'phash', lambda _: '1')
    new, _ = photo(tmp_path, 3, 'green')
    with db.connect() as conn:
        assert conn.execute('SELECT 1 FROM pending_deduplications WHERE image_id=?', (new['id'],)).fetchone()
        assert conn.execute('SELECT 1 FROM duplicate_decisions WHERE a=? AND b=?', (warm['id'], new['id'])).fetchone()
        assert not conn.execute('SELECT 1 FROM duplicate_decisions WHERE a=? AND b=?', (cold['id'], new['id'])).fetchone()
    original.write_bytes((tmp_path / 'input-1.png').read_bytes())
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET cache_retry_at=0')
    importer.recover_deduplications(threading.Event())
    with db.connect() as conn:
        assert not conn.execute('SELECT 1 FROM pending_deduplications').fetchone()
        assert conn.execute('SELECT 1 FROM duplicate_decisions WHERE a=? AND b=?', (cold['id'], new['id'])).fetchone()


def test_admin_cache_inventory_and_cleanup_history(client, tmp_path, monkeypatch):
    endpoint = '/api/v1/admin/media-cache'
    row, _ = photo(tmp_path)
    now = time.time()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_used=?,original_used=?', (now - 7 * cache.DAY, now))
    assert client.get(endpoint).json()['config'] is None
    cache_status.record('config', dict(reported_at=now, low_bytes=5, target_bytes=10))
    assert 'min_idle_seconds' not in client.get(endpoint).json()['config']
    cache_status.report_config((5, 10), 1800)
    path = cache.asset_path(row, 'image')
    monkeypatch.setattr(cache, 'free_bytes', lambda root: 4 if path.exists() else 12)
    cache.clean(5, 10, cache.DAY)
    result = client.get(endpoint).json()
    assert result['config']['low_bytes'] == 5 and result['config']['target_bytes'] == 10
    assert result['config']['min_idle_seconds'] == 1800
    volume, = result['volumes']
    assert volume['folders'] == ['data', 'images', 'originals'] and volume['free_bytes'] == 12
    history = volume['last_cleanup']
    assert history['outcome'] == 'target' and (history['before_bytes'], history['after_bytes']) == (4, 12)
    removed = history['removals']['images']
    assert removed['count'] == 1 and removed['min_idle_days'] == pytest.approx(7) and removed['min_score'] == pytest.approx(28)
    assert history['removals']['originals'] == dict(count=0, min_score=None, min_idle_days=None)
    assert result['inventory'][0] == dict(folder='images', present=0, evicted=1, lost=0, missing=0, unknown=0)
    assert not path.exists()
    cache.clean(5, 10, cache.DAY)
    with cache.asset(row, 'image'):
        pass
    cache.asset_path(row, 'original').unlink()
    cache_status.report_config(None, 0)
    result = client.get(endpoint).json()
    assert result['config']['low_bytes'] is None
    assert result['config']['min_idle_seconds'] == 0
    assert result['volumes'][0]['last_cleanup'] == history
    assert result['inventory'][0]['present'] == result['inventory'][1]['missing'] == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1')
    assert all(not any(item[key] for key in ('present', 'missing', 'evicted', 'unknown')) for item in client.get(endpoint).json()['inventory'])
    client.cookies.clear()
    assert client.get(endpoint).status_code == 401


def test_cache_activity_counts_reads_and_successful_writes(client, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    row, _ = photo(tmp_path)
    endpoint = '/api/v1/admin/media-cache'
    empty = [dict(folder=folder, hits=0, misses=0, recoveries=0) for folder in ('images', 'originals')]
    assert client.get(endpoint).json()['activity_24h'] == empty
    evict(row, 'image')
    evict(row, 'original')
    for variant in ('image', 'image', 'original', 'thumbnail'):
        with cache.asset(row, variant):
            pass
    cache.asset_path(row, 'original').unlink()
    with pytest.raises(FileNotFoundError), cache.asset(row, 'original'):
        pass
    db.init()
    assert client.get(endpoint).json()['activity_24h'] == [dict(folder='images', hits=1, misses=1, recoveries=1),
                                                          dict(folder='originals', hits=1, misses=1, recoveries=1)]
    later = time.time() + cache.DAY
    monkeypatch.setattr(time, 'time', lambda: later)
    assert cache_status.status()['activity_24h'] == empty
    with cache.asset(row, 'image'):
        pass
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM media_cache_activity').fetchone()[0] == 1


def test_cache_status_distinguishes_volumes_and_unreadable_files(client, tmp_path, monkeypatch):
    photo(tmp_path)
    monkeypatch.setattr(cache, 'device', lambda path: 2 if path.name == 'originals' else 1)
    monkeypatch.setattr(cache, 'free_bytes', lambda path: 1 if path.name == 'originals' else 100)
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET original_used=?', (time.time(),))
    cache.clean(5, 10, cache.DAY)
    (db.DATA / 'images').rename(db.DATA / 'offline')
    result = client.get('/api/v1/admin/media-cache').json()
    assert result['inventory'][0]['unknown'] == 1
    shared, originals = result['volumes']
    assert shared['last_cleanup'] is None
    assert originals['last_cleanup']['outcome'] == 'exhausted'
    assert originals['last_cleanup']['removals']['originals']['min_score'] is None


@pytest.mark.parametrize('layout,low_disk,removed', [
    ((1, 1, 1), 1, 'image'), ((1, 2, 1), 2, 'image'), ((1, 2, 1), 1, 'original'),
    ((1, 1, 2), 2, 'original'), ((1, 2, 2), 1, None), ((1, 2, 2), 2, 'image'),
    ((1, 2, 3), 1, None), ((1, 2, 3), 2, 'image'), ((1, 2, 3), 3, 'original'),
])
def test_filesystem_local_watermarks(client, tmp_path, monkeypatch, layout, low_disk, removed):
    row, _ = photo(tmp_path)
    paths = {variant: cache.asset_path(row, variant) for variant in cache.FOLDERS}
    devices = dict(zip(('.', 'images', 'originals'), layout))

    def device(path):
        return devices[next(iter(path.relative_to(db.DATA).parts), '.')]

    monkeypatch.setattr(cache, 'device', device)
    monkeypatch.setattr(cache, 'free_bytes', lambda root: 1 if device(root) == low_disk and all(path.exists() for path in paths.values()) else 10)
    cache.clean(5, 10, cache.DAY)
    assert {variant for variant, path in paths.items() if not path.exists()} == ({removed} if removed else set())
    assert (db.DATA / 'thumbs' / row['filename']).exists()


def test_pressure_with_no_recovery_source_or_active_reader(client, tmp_path, monkeypatch):
    row, source = photo(tmp_path)
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET url='https://x.com/alice'")
        importer.record_location(conn, row['id'], source)
    with cache.asset(row, 'original'):
        with db.connect(True) as conn:
            conn.execute('UPDATE images SET original_used=1')
        assert evict(row, 'original').exists()
    good = source.read_bytes()
    source.write_bytes(b'wrong')
    assert evict(row, 'original').exists()
    source.write_bytes(good)
    path = evict(row, 'original')
    assert not path.exists()
    with cache.asset(row, 'original') as restored:
        assert restored.read_bytes() == good
    assert evict(row, 'original').exists()


def test_publication_and_legacy_access_time(client, tmp_path):
    now = 1800000000
    used = now - 28 * cache.DAY
    row, _ = photo(tmp_path)
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET original_used=NULL,created_at=datetime(?,\'unixepoch\')', (now,))
        conn.execute('UPDATE posts SET published_at=NULL')
    original = cache.asset_path(row, 'original')
    os.utime(original, (used, used))
    assert cache.candidates(['original'], now, now - cache.DAY)[0][0] == 7
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET published_at=datetime(?, 'unixepoch')", (now - 40 * cache.DAY,))
    assert cache.candidates(['original'], now, now - cache.DAY)[0][0] == 28
    assert cache.cold_score('image', now - 7 * cache.DAY, now, now) == 28
    with db.connect(True) as conn:
        post = conn.execute("INSERT INTO posts(platform,post_key,published_at) VALUES('x','new',datetime(?,'unixepoch'))", (now + 100,)).lastrowid
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,'1')", (row['id'], post))
    assert cache.candidates(['original'], now, now - cache.DAY)[0][0] == 7


@pytest.mark.parametrize('hours,seconds', [(None, cache.DAY), ('0', 0), ('0.5', 1800), ('48', 172800)])
def test_min_idle_cutoff(client, tmp_path, monkeypatch, hours, seconds):
    if hours is None:
        monkeypatch.delenv('MEDIA_CACHE_MIN_IDLE_HOURS', raising=False)
    else:
        monkeypatch.setenv('MEDIA_CACHE_MIN_IDLE_HOURS', hours)
    now = time.time()
    row, _ = photo(tmp_path)
    cutoff = now - seconds
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_used=?, original_used=?', (cutoff, cutoff + 1))
    monkeypatch.setattr(time, 'time', lambda: now)
    monkeypatch.setattr(cache, 'free_bytes', lambda root: 1)
    cache.clean(5, 10, cache.min_idle_seconds())
    assert not cache.asset_path(row, 'image').exists()
    original = cache.asset_path(row, 'original')
    cache.evict(row['id'], 'original', original.stat().st_dev, now, cutoff)
    assert original.exists()


@pytest.mark.parametrize('value', ['-1', 'invalid', 'nan', 'inf', '1e308'])
def test_invalid_min_idle_hours(monkeypatch, value):
    monkeypatch.setenv('MEDIA_CACHE_MIN_IDLE_HOURS', value)
    with pytest.raises(ValueError, match='MEDIA_CACHE_MIN_IDLE_HOURS'):
        cache.min_idle_seconds()


def test_evicted_image_urls_and_local_dedup(client, tmp_path, monkeypatch):
    row, _ = photo(tmp_path)
    before = main.media_urls(row)
    path = evict(row, 'image')
    assert not path.exists()
    monkeypatch.setattr(worker, 'download_media', lambda *args, **kwargs: pytest.fail('unnecessary network fetch'))
    assert client.get(f'/api/v1/gallery/{row["group_id"]}').json()['image_url'] == before['image_url']
    assert not path.exists()
    other, _ = photo(tmp_path, number=2, color=(254, 0, 0))
    assert path.exists()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM duplicate_decisions WHERE a=? AND b=?', (row['id'], other['id'])).fetchone()[0] == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_used=1')
    expected = path.read_bytes()[:4]
    evict(row, 'image')
    partial = client.get(before['image_url'], headers={'Range': 'bytes=0-3'})
    assert partial.status_code == 206 and partial.content == expected
    assert not path.exists()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (other['id'],))
    assert client.head(before['image_url'], headers={'If-None-Match': '*'}).status_code == 304
    assert path.exists()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_used=1')
    evict(row, 'image')
    monkeypatch.setattr(importer, 'encode_display', lambda original, target: Image.new('RGB', (32, 32), 'blue').save(target, 'JPEG'))
    assert client.get(before['image_url']).status_code == 404
    with db.connect() as conn:
        new_url = main.media_urls(cache.active(conn, row['id']))['image_url']
    assert new_url != before['image_url'] and client.get(new_url).content == path.read_bytes()


def test_joint_remote_recovery_and_zip(client, tmp_path, monkeypatch):
    row, source = photo(tmp_path)
    original_url = main.media_urls(row)['download_url']
    evict(row, 'image')
    evict(row, 'original')
    started, release = threading.Event(), threading.Event()
    calls = []

    def download(task, payload, attempt, restore_id):
        calls.append(restore_id)
        started.set()
        assert release.wait(5)
        (attempt / 'download.png').write_bytes(source.read_bytes())
        return attempt

    monkeypatch.setattr(worker, 'download_media', download)
    with ThreadPoolExecutor(max_workers=2) as pool:
        display = pool.submit(client.get, main.media_urls(row)['image_url'])
        assert started.wait(5)
        batch = pool.submit(client.get, f'/api/v1/gallery/download.zip?groups={row["group_id"]}')
        release.set()
        assert display.result().status_code == 200
        response = batch.result()
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.read(archive.namelist()[0]) == source.read_bytes()
    assert calls == [row['id']]
    assert client.get(original_url).content == source.read_bytes()


@pytest.mark.parametrize('failure', ['changed', 'download-full', 'target-full', 'trash'])
def test_recovery_failures_do_not_publish_bytes(client, tmp_path, monkeypatch, failure):
    row, source = photo(tmp_path)
    url = main.media_urls(row)['download_url']
    original = evict(row, 'original')
    assert not original.exists()
    calls = []

    def download(task, payload, attempt, restore_id):
        calls.append(restore_id)
        if failure == 'download-full':
            raise OSError(errno.ENOSPC, 'full')
        if failure == 'trash':
            assert recycle(client, [restore_id]).status_code == 200
        (attempt / 'remote.png').write_bytes(b'changed' if failure == 'changed' else source.read_bytes())
        return attempt

    if failure == 'target-full':
        open_file = type(original).open
        def fail_write(path, mode='r', *args, **kwargs):
            if path.parent == original.parent and mode == 'wb':
                raise OSError(errno.ENOSPC, 'full')
            return open_file(path, mode, *args, **kwargs)
        monkeypatch.setattr(type(original), 'open', fail_write)
    monkeypatch.setattr(worker, 'download_media', download)
    for _ in range(2):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == (404 if failure == 'trash' else 307)
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['cloudflare-cdn-cache-control'] == 'no-store'
        if failure != 'trash':
            assert response.headers['location'] == main.media_urls(row)['image_url'] + '?download=true'
            assert client.get(response.headers['location']).content == cache.asset_path(row, 'image').read_bytes()
            with db.connect() as conn:
                assert cache.active(conn, row['id'])['original_failures'] == int(failure == 'changed')
    assert calls == [row['id']] and not original.exists()
    assert not list(original.parent.glob('.cache-stage-*'))


def test_timeout_leaves_recovery_running(client, tmp_path, monkeypatch):
    row, _ = photo(tmp_path)
    path = evict(row, 'image')
    started, finish = threading.Event(), threading.Event()
    real = importer.encode_display

    def slow(source, target):
        started.set()
        assert finish.wait(5)
        real(source, target)

    monkeypatch.setattr(importer, 'encode_display', slow)
    try:
        with pytest.raises(cache.Unavailable), cache.asset(row, 'image', timeout=0.01):
            pass
        assert started.wait(5)
        stats = cache_status.status()['activity_24h'][0]
        assert stats == dict(folder='images', hits=0, misses=1, recoveries=0)
    finally:
        finish.set()
    with cache.asset(row, 'image', timeout=5):
        assert path.exists()
    stats = cache_status.status()['activity_24h'][0]
    assert stats['hits'] + stats['misses'] == 2 and stats['recoveries'] == 1


def test_original_wait_timeout_falls_back_without_counting(client, tmp_path, monkeypatch):
    row, source = photo(tmp_path)
    urls = main.media_urls(row)
    evict(row, 'original')
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow(task, payload, attempt, restore_id):
        calls.append(restore_id)
        started.set()
        assert release.wait(5)
        (attempt / 'original.png').write_bytes(source.read_bytes())
        return attempt

    monkeypatch.setattr(worker, 'download_media', slow)
    init = main.MediaRead.__init__
    def short_wait(reads):
        init(reads)
        reads.deadline = time.monotonic() + 0.01
    monkeypatch.setattr(main.MediaRead, '__init__', short_wait)
    try:
        for method in (client.get, client.head):
            redirect = method(urls['download_url'], headers={'If-None-Match': '*'}, follow_redirects=False)
            assert redirect.status_code == 307 and 'etag' not in redirect.headers
            assert redirect.headers['location'] == urls['image_url'] + '?download=true'
            assert redirect.headers['cache-control'] == redirect.headers['cloudflare-cdn-cache-control'] == 'no-store'
        assert started.wait(5)
        response = client.get(f'/api/v1/media/{row["id"]}?download=true')
        assert response.content == cache.asset_path(row, 'image').read_bytes()
        assert row['filename'] in response.headers['content-disposition']
        with db.connect() as conn:
            latest = cache.active(conn, row['id'])
            assert latest['original_failures'] == latest['cache_retry_at'] == 0
    finally:
        release.set()
    with cache.asset(row, 'original', timeout=5):
        assert client.get(urls['download_url']).content == source.read_bytes()
    assert calls == [row['id']]


def test_exponential_backoff_lost_fallback_and_reimport(client, tmp_path, monkeypatch):
    row, source = photo(tmp_path)
    urls = main.media_urls(row)
    evict(row, 'image')
    evict(row, 'original')
    calls = []
    def failed(task, payload, attempt, restore_id):
        calls.append(restore_id)
        raise ValueError('source timed out')
    monkeypatch.setattr(worker, 'download_media', failed)
    now = time.time()
    monkeypatch.setattr(cache, 'time', SimpleNamespace(time=lambda: now, monotonic=time.monotonic))
    for attempt in range(1, 13):
        response = client.get(urls['download_url'], follow_redirects=False)
        with db.connect() as conn:
            latest = cache.active(conn, row['id'])
        assert latest['original_failures'] == len(calls) == attempt
        if attempt < 12:
            assert response.status_code == 503 and int(response.headers['retry-after']) == 60 * 2 ** (attempt - 1)
            assert not latest['original_lost'] and latest['cache_retry_at'] == now + 60 * 2 ** (attempt - 1)
            now = latest['cache_retry_at'] - 1
            cooling = client.get(urls['image_url'])
            assert cooling.status_code == 503 and cooling.headers['retry-after'] == '1'
            now += 1
        else:
            assert latest['original_lost'] and latest['cache_retry_at'] == 0
            assert response.status_code == 307 and response.headers['location'] == urls['thumbnail_url'] + '?download=true'
    db.init()
    thumb = db.DATA / 'thumbs' / row['filename']
    assert client.get(urls['image_url']).content == thumb.read_bytes()
    detail = client.get(f'/api/v1/gallery/{row["group_id"]}').json()
    assert detail['image_url'] == urls['thumbnail_url'] and detail['download_url'] == urls['thumbnail_url'] + '?download=true'
    assert 'attachment' in client.head(detail['download_url']).headers['content-disposition']
    prepared = client.post('/api/v1/gallery/downloads', json={'group_ids': [row['group_id']]})
    with ZipFile(io.BytesIO(client.get(prepared.json()['download_url']).content)) as archive:
        assert archive.read(f'{row["group_id"]}-{row["filename"]}') == thumb.read_bytes()
    inventory = client.get('/api/v1/admin/media-cache').json()['inventory'][1]
    assert inventory['lost'] == 1 and inventory['missing'] == inventory['evicted'] == 0
    thumb.unlink()
    assert client.get(urls['download_url']).status_code == 404
    assert len(calls) == 12
    importer.import_file(source, dict(platform='x', author='alice', tweet_id='1', date='2026-01-01', url='https://x.com/alice/status/1'))
    assert client.get(urls['download_url']).content == source.read_bytes()
    with db.connect() as conn:
        latest = cache.active(conn, row['id'])
        assert latest['original_failures'] == latest['original_lost'] == latest['cache_retry_at'] == 0


def test_keep_remaining_display_after_source_failure(client, tmp_path, monkeypatch):
    row, _ = photo(tmp_path)
    urls = main.media_urls(row)
    evict(row, 'original')
    monkeypatch.setattr(worker, 'download_media', lambda *args, **kwargs: pytest.fail('unexpected recovery'))
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET original_failures=1')
    display = evict(row, 'image')
    assert display.exists()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET original_lost=1,original_failures=12,image_evicted=1')
    redirect = client.head(urls['download_url'], follow_redirects=False)
    assert redirect.headers['location'] == urls['image_url'] + '?download=true'
    assert client.get(redirect.headers['location']).content == display.read_bytes()
    with db.connect() as conn:
        assert not cache.active(conn, row['id'])['image_evicted']


@pytest.mark.parametrize('matching', [True, False])
def test_reimport_wins_over_inflight_original_recovery(client, tmp_path, monkeypatch, matching):
    row, source = photo(tmp_path)
    original = evict(row, 'original')
    installed = []
    def download(task, payload, attempt, restore_id):
        importer.import_file(source, dict(platform='x', author='alice', tweet_id='1', date='2026-01-01', url=payload['url']))
        installed.append(original.stat())
        (attempt / 'download.png').write_bytes(source.read_bytes() if matching else b'wrong')
        return attempt
    monkeypatch.setattr(worker, 'download_media', download)
    with cache.asset(row, 'original') as recovered:
        assert os.path.samestat(recovered.stat(), installed[0]) and recovered.read_bytes() == source.read_bytes()
    with db.connect() as conn:
        latest = cache.active(conn, row['id'])
        assert latest['original_failures'] == latest['cache_retry_at'] == latest['original_evicted'] == 0


@pytest.mark.parametrize('work', ['copy', 'encode', 'eviction-hash'])
def test_public_write_during_slow_cache_work(client, tmp_path, monkeypatch, work):
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    row, source = photo(tmp_path)
    started, release = threading.Event(), threading.Event()
    def pause():
        started.set()
        assert release.wait(5)
    if work == 'eviction-hash':
        with db.connect(True) as conn:
            conn.execute('UPDATE posts SET url=?', ('https://x.com/alice',))
        file_hash = db.file_hash
        def slow_hash(path):
            digest = file_hash(path)
            if path == source:
                pause()
            return digest
        monkeypatch.setattr(db, 'file_hash', slow_hash)
        action = lambda: evict(row, 'original')
    else:
        variant = 'original' if work == 'copy' else 'image'
        path = evict(row, variant)
        if work == 'copy':
            original_open = type(path).open
            def slow_open(candidate, mode='r', *args, **kwargs):
                if candidate.parent == path.parent and mode == 'wb':
                    pause()
                return original_open(candidate, mode, *args, **kwargs)
            monkeypatch.setattr(type(path), 'open', slow_open)
        else:
            encode = importer.encode_display
            def slow_encode(image, target):
                pause()
                encode(image, target)
            monkeypatch.setattr(importer, 'encode_display', slow_encode)
        action = lambda: cache.recover(row['id'], variant)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(action)
        try:
            assert started.wait(5)
            assert client.post(f'/api/v1/images/{row["id"]}/feedback', json={'content': 'check'}).status_code == 201
            if work == 'eviction-hash':
                source.write_bytes(b'replaced after hashing')
            elif work == 'copy':
                worker.cleanup_interrupted_files()
                assert len(list(path.parent.glob('.cache-stage-*'))) == 1
            else:
                assert recycle(client, [row['id']]).status_code == 200
        finally:
            release.set()
        if work == 'encode':
            with pytest.raises(FileNotFoundError):
                future.result()
        else:
            future.result()
    if work == 'eviction-hash':
        assert cache.asset_path(row, 'original').exists()
    elif work == 'encode':
        assert not path.exists()
    else:
        assert path.read_bytes() == source.read_bytes()
    assert not list(db.DATA.glob('*/.cache-stage-*'))


@pytest.mark.parametrize('low,target,expected', [('', '', None), ('0.5', '2', (2**29, 2**31)), ('', '2', False), ('2', '1', False), ('0', '1', False), ('nan', 'inf', False)])
def test_configuration(monkeypatch, low, target, expected):
    monkeypatch.setenv('MEDIA_CACHE_LOW_FREE_GIB', low)
    monkeypatch.setenv('MEDIA_CACHE_TARGET_FREE_GIB', target)
    if expected is False:
        with pytest.raises(ValueError):
            cache.watermarks()
    else:
        assert cache.watermarks() == expected


def test_restart_preserves_active_fetch_and_resumes_eviction(client, tmp_path):
    row, _ = photo(tmp_path)
    active = db.DATA / 'downloads' / 'cache-fetch-1-live'
    stale = db.DATA / 'downloads' / 'cache-fetch-2-orphan'
    active.mkdir()
    stale.mkdir()
    with cache.stripe_lock(1) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        worker.cleanup_interrupted_files()
        assert active.is_dir() and not stale.exists()
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET image_evicted=1')
    db.init()
    with cache.asset(row, 'image') as path:
        assert db.file_hash(path) == row['image_sha256']
    with db.connect() as conn:
        assert not cache.active(conn, row['id'])['image_evicted']
