"""Crash subprocesses so finally blocks cannot mask restart bugs."""
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from PIL import Image
from app import db, importer, worker
from test_workflows import client

RAW = {'category': 'twitter', 'tweet_id': '123', 'num': 1,
       'author': {'name': 'alice'}, 'date': '2026-01-01T00:00:00Z'}


def crash(tmp_path, code):
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
        timeout=30, env={**os.environ, 'DATA_DIR': str(tmp_path),
                        'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    assert result.returncode == 73, result.stderr


def source(tmp_path, name='source.png', compress=6):
    path = tmp_path / name
    image = Image.new('RGB', (64, 64))
    image.putdata([(x * 4, y * 4, (x + y) * 2) for y in range(64) for x in range(64)])
    image.save(path, compress_level=compress)
    return path


@pytest.mark.parametrize('folder', ['images', 'thumbs', 'originals'])
@pytest.mark.parametrize('refresh', [False, True])
def test_asset_crash_and_restart(client, tmp_path, folder, refresh):
    path = source(tmp_path)
    digest = db.file_hash(path)
    target = tmp_path / folder / (digest + ('.png' if folder == 'originals' else '.jpg'))
    previous = None
    if refresh:
        importer.import_file(path, RAW)
        if folder == 'originals':
            target.write_bytes(b'old damaged original')
        previous = target.read_bytes()
    crash(tmp_path, f'''
import os
from pathlib import Path
from PIL import Image
from app import db, importer
db.init()
original_save = Image.Image.save
def save(image, fp, *args, **kwargs):
    if Path(fp).parent.name == {folder!r}:
        Path(fp).write_bytes(b'partial image')
        os._exit(73)
    return original_save(image, fp, *args, **kwargs)
def copy(src, dst):
    Path(dst).write_bytes(b'partial original')
    os._exit(73)
Image.Image.save = save
if {folder!r} == 'originals':
    importer.shutil.copyfile = copy
with db.connect(True):
    importer.write_assets(Path({str(path)!r}), {digest!r}, refresh={refresh!r})
''')
    if refresh:
        assert target.read_bytes() == previous
    else:
        assert not target.exists()
    assert list((tmp_path / folder).glob('.asset-*'))
    db.init()
    worker.cleanup_interrupted_files()
    worker.recover_tasks()
    identifier = importer.import_file(path, RAW)
    assert not list((tmp_path / folder).glob('.asset-*'))
    with db.connect() as conn:
        row = conn.execute('SELECT * FROM images WHERE id=?', (identifier,)).fetchone()
    assert db.file_hash(tmp_path / 'originals' / row['original_filename']) == digest
    for directory, column in (('images', 'image_sha256'), ('thumbs', 'thumbnail_sha256')):
        asset = tmp_path / directory / row['filename']
        with Image.open(asset) as image:
            image.load()
        assert db.file_hash(asset) == row[column]


def test_retry_repairs_legacy_partial_assets(client, tmp_path):
    path = source(tmp_path)
    digest = db.file_hash(path)
    for folder, suffix in (('images', '.jpg'), ('thumbs', '.jpg'), ('originals', '.png')):
        (tmp_path / folder / (digest + suffix)).write_bytes(b'partial')
    importer.import_file(path, RAW)
    assert db.file_hash(tmp_path / 'originals' / (digest + '.png')) == digest
    for folder in ('images', 'thumbs'):
        with Image.open(tmp_path / folder / (digest + '.jpg')) as image:
            image.load()


def test_committed_import_resumes_deduplication_without_reimport(client, tmp_path):
    first = importer.import_file(source(tmp_path, 'first.png', 0), {**RAW, 'tweet_id': '122'})
    path = source(tmp_path)
    crash(tmp_path, f'''
import os
from pathlib import Path
from app import db, importer
db.init()
importer.deduplicate = lambda _: os._exit(73)
importer.import_file(Path({str(path)!r}), {RAW!r})
''')
    db.init()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM pending_deduplications').fetchone()[0] == 1
    importer.recover_deduplications(threading.Event())
    with db.connect() as conn:
        assert conn.execute('SELECT count(DISTINCT group_id) FROM images').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM pending_deduplications').fetchone()[0] == 0
        assert conn.execute('SELECT decision FROM duplicate_decisions WHERE a=?', (first,)).fetchone()[0] == 'auto'
    importer.recover_deduplications(threading.Event())


def test_failed_deduplication_remains_retryable(client, tmp_path, monkeypatch):
    path = source(tmp_path)
    original = importer.deduplicate
    def fail(_):
        raise OSError('temporary failure')
    monkeypatch.setattr(importer, 'deduplicate', fail)
    with pytest.raises(OSError):
        importer.import_file(path, RAW)
    importer.recover_deduplications(threading.Event())
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM pending_deduplications').fetchone()[0] == 1
    monkeypatch.setattr(importer, 'deduplicate', original)
    importer.import_file(path, RAW)
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM pending_deduplications').fetchone()[0] == 0


def test_crashed_download_cleanup_and_requeue(client, tmp_path):
    crash(tmp_path, '''
import os
from app import db, worker
db.init()
with db.connect(True) as conn:
    conn.execute("INSERT INTO tasks(kind) VALUES('download')")
def interrupted(task, attempt):
    (attempt / 'cookies.txt').write_text('placeholder')
    (attempt / 'partial.jpg').write_bytes(b'partial')
    os._exit(73)
worker._import_task = interrupted
worker.import_task(worker.claim(('download',)))
''')
    downloads = tmp_path / 'downloads'
    assert list(downloads.glob('attempt-*'))
    for prefix in ('restore-local-', 'restore-remote-'):
        directory = downloads / (prefix + 'interrupted')
        directory.mkdir()
        (directory / 'partial').write_bytes(b'partial')
    untouched = downloads / 'unrelated'
    untouched.mkdir()
    db.init()
    worker.cleanup_interrupted_files()
    worker.recover_tasks()
    assert list(downloads.iterdir()) == [untouched]
    assert worker.claim(('download',)) is not None
    worker.cleanup_interrupted_files()
