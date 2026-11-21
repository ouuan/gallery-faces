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
    cache.evict(row['id'], variant, path.stat().st_dev, time.time())
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
    cache.clean(5, 10)
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
    cache_status.report_config((5, 10))
    path = cache.asset_path(row, 'image')
    monkeypatch.setattr(cache, 'free_bytes', lambda root: 4 if path.exists() else 12)
    cache.clean(5, 10)
    result = client.get(endpoint).json()
    assert result['config']['low_bytes'] == 5 and result['config']['target_bytes'] == 10
    volume, = result['volumes']
    assert volume['folders'] == ['data', 'images', 'originals'] and volume['free_bytes'] == 12
    history = volume['last_cleanup']
    assert history['outcome'] == 'target' and (history['before_bytes'], history['after_bytes']) == (4, 12)
    removed = history['removals']['images']
    assert removed['count'] == 1 and removed['min_idle_days'] == pytest.approx(7) and removed['min_score'] == pytest.approx(28)
    assert history['removals']['originals'] == dict(count=0, min_score=None, min_idle_days=None)
    assert result['inventory'][0] == dict(folder='images', present=0, evicted=1, missing=0, unknown=0)
    assert not path.exists()
    cache.clean(5, 10)
    with cache.asset(row, 'image'):
        pass
    cache.asset_path(row, 'original').unlink()
    cache_status.report_config(None)
    result = client.get(endpoint).json()
    assert result['config']['low_bytes'] is None
    assert result['volumes'][0]['last_cleanup'] == history
    assert result['inventory'][0]['present'] == result['inventory'][1]['missing'] == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1')
    assert all(not any(item[key] for key in ('present', 'missing', 'evicted', 'unknown')) for item in client.get(endpoint).json()['inventory'])
    client.cookies.clear()
    assert client.get(endpoint).status_code == 401


def test_cache_status_distinguishes_volumes_and_unreadable_files(client, tmp_path, monkeypatch):
    photo(tmp_path)
    monkeypatch.setattr(cache, 'device', lambda path: 2 if path.name == 'originals' else 1)
    monkeypatch.setattr(cache, 'free_bytes', lambda path: 1 if path.name == 'originals' else 100)
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET original_used=?', (time.time(),))
    cache.clean(5, 10)
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
    cache.clean(5, 10)
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
    assert cache.candidates(['original'], now)[0][0] == 7
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET published_at=datetime(?, 'unixepoch')", (now - 40 * cache.DAY,))
    assert cache.candidates(['original'], now)[0][0] == 28
    assert cache.cold_score('image', now - 7 * cache.DAY, now, now) == 28
    with db.connect(True) as conn:
        post = conn.execute("INSERT INTO posts(platform,post_key,published_at) VALUES('x','new',datetime(?,'unixepoch'))", (now + 100,)).lastrowid
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,'1')", (row['id'], post))
    assert cache.candidates(['original'], now)[0][0] == 7


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
        response = client.get(url)
        assert response.status_code == (404 if failure == 'trash' else 503)
        assert response.headers['cache-control'] == 'no-store'
        if failure != 'trash':
            assert 'retry-after' in response.headers
    assert calls == [row['id']] and not original.exists()
    assert not list(original.parent.glob('.asset-*'))


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
    finally:
        finish.set()
    with cache.asset(row, 'image', timeout=5):
        assert path.exists()


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
