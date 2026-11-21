"""On-demand media leases and filesystem-local eviction for active library photos."""
import fcntl
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

from PIL import Image, ImageOps

from . import db as storage
from .cache_status import Cleanup, Evictions, record
from .security import download_url

FOLDERS = {'image': 'images', 'original': 'originals'}
PRIVATE_FIELDS = {'image_used', 'original_used', 'image_evicted', 'original_evicted', 'cache_retry_at'}
DAY = 86400
logger = logging.getLogger(__name__)
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='media-cache')
pending = {}
pending_lock = threading.Lock()


class Unavailable(Exception):
    pass


class SourceUnavailable(Exception):
    pass


class StaleRecovery(Exception):
    pass


def file_signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def stamp(path):
    try:
        return file_signature(path.stat())
    except FileNotFoundError:
        return None


def matches_original(path, digest, *, excluding=None):
    try:
        return path.is_file() and (excluding is None or not path.samefile(excluding)) and storage.file_hash(path) == digest
    except OSError as error:
        logger.warning('Cannot verify recovery source %s: %s', path, error)
        return False


def watermarks():
    values = [os.getenv('MEDIA_CACHE_' + suffix + '_FREE_GIB', '') for suffix in ('LOW', 'TARGET')]
    if not any(values):
        return None
    try:
        low, target = [int(float(value) * 2**30) for value in values]
        if 0 < low < target:
            return low, target
    except (ValueError, OverflowError):
        pass
    raise ValueError('MEDIA_CACHE_LOW_FREE_GIB and MEDIA_CACHE_TARGET_FREE_GIB must satisfy 0 < low < target')


def asset_path(row, variant):
    name = row['filename' if variant == 'image' else 'original_filename']
    if not name or '/' in name or name in ('.', '..'):
        return None
    return storage.DATA / FOLDERS[variant] / name


def locations(db, row):
    from .importer import IMPORT
    for relative, in db.execute('SELECT path FROM import_locations WHERE image_id=? ORDER BY path', (row['id'],)):
        try:
            path = (IMPORT / relative).resolve()
            if path.is_relative_to(IMPORT) and path.is_file():
                yield relative, path
        except (OSError, RuntimeError) as error:
            logger.warning('Cannot inspect import location %s: %s', relative, error)


def post_urls(db, row):
    for url, in db.execute('SELECT DISTINCT p.url FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=? AND p.url IS NOT NULL ORDER BY p.url', (row['id'],)):
        try:
            platform, canonical = download_url(url)
        except ValueError:
            continue
        if (platform == 'x' and '/status/' in canonical) or (platform == 'instagram' and re.search(r'instagram\.com/(p|reel|tv)/', canonical)):
            yield canonical


def active(db, identifier):
    row = db.execute('SELECT * FROM images WHERE id=? AND hidden=0', (identifier,)).fetchone()
    if row is None:
        raise FileNotFoundError(identifier)
    return row


def check_snapshot(db, row):
    latest = active(db, row['id'])
    if any(latest[key] != row[key] for key in ('filename', 'original_filename', 'sha256', 'image_sha256',
                                               'image_evicted', 'original_evicted')):
        raise StaleRecovery


@contextmanager
def staged_asset(row, variant):
    target = asset_path(row, variant)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f'.cache-stage-{row["id"] % 256}-', delete=False) as stream:
        temporary = Path(stream.name)
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


def publish(row, variant, before, *, temporary=None, digest=None, original_stamp=None):
    target = asset_path(row, variant)
    def validate(db, expected):
        check_snapshot(db, row)
        if stamp(target) != expected or (original_stamp and stamp(asset_path(row, 'original')) != original_stamp):
            raise StaleRecovery
    if temporary:
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        with storage.connect(True) as db:
            validate(db, before)
            temporary.replace(target)
            before = stamp(target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    with storage.connect(True) as db:
        validate(db, before)
        if variant == 'original':
            db.execute('UPDATE images SET original_evicted=0,original_used=?,cache_retry_at=0 WHERE id=?',
                       (time.time(), row['id']))
        else:
            db.execute('UPDATE images SET image_evicted=0,image_used=?,image_sha256=? WHERE id=?',
                       (time.time(), digest, row['id']))


def install_original(row, source, before):
    with staged_asset(row, 'original') as temporary:
        digest = hashlib.sha256()
        try:
            stream = source.open('rb')
        except OSError as error:
            raise SourceUnavailable from error
        with stream, temporary.open('wb') as destination:
            while True:
                try:
                    chunk = stream.read(1024 * 1024)
                except OSError as error:
                    raise SourceUnavailable from error
                if not chunk:
                    break
                destination.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != row['sha256']:
            raise SourceUnavailable('Original SHA-256 mismatch')
        publish(row, 'original', before, temporary=temporary)


def recover_original(row, before):
    from .worker import download_media
    with storage.connect() as db:
        sources = list(locations(db, row))
        urls = list(post_urls(db, row))
    for _, source in sources:
        try:
            install_original(row, source, before)
            return
        except SourceUnavailable:
            continue
    last_error = 'No matching source file'
    for url in urls:
        with tempfile.TemporaryDirectory(dir=storage.DATA / 'downloads', prefix=f'cache-fetch-{row["id"] % 256}-') as attempt:
            try:
                directory = download_media(None, {'url': url}, Path(attempt), restore_id=row['id'])
            except ValueError as error:
                last_error = str(error)
                continue
            for source in directory.rglob('*'):
                if source.resolve().is_relative_to(directory.resolve()) and matches_original(source, row['sha256']):
                    try:
                        install_original(row, source, before)
                        return
                    except SourceUnavailable:
                        continue
    raise SourceUnavailable(last_error)


def stripe_lock(stripe):
    locks = storage.DATA / 'cache-locks'
    locks.mkdir(exist_ok=True)
    return (locks / str(stripe)).open('a')


def cleanup_fetches():
    for folder, prefix in [('downloads', 'cache-fetch-'), *[(folder, '.cache-stage-') for folder in FOLDERS.values()]]:
        for path in (storage.DATA / folder).glob(prefix + '*'):
            match = re.fullmatch(re.escape(prefix) + r'(\d{1,3})-.+', path.name)
            if not match or path.is_symlink():
                continue
            with stripe_lock(int(match[1])) as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                if folder == 'downloads' and path.is_dir():
                    shutil.rmtree(path)
                elif folder != 'downloads':
                    path.unlink(missing_ok=True)


def restore_asset(row, variant):
    from .importer import encode_display
    target = asset_path(row, variant)
    before = stamp(target)
    known_hash = row['image_sha256' if variant == 'image' else 'sha256']
    if before and storage.file_hash(target) == known_hash:
        publish(row, variant, before, digest=known_hash)
        return
    if row['cache_retry_at'] > time.time():
        raise Unavailable('Media recovery is in backoff')
    original = asset_path(row, 'original')
    if original is None:
        raise SourceUnavailable('Missing original filename')
    original_stamp = before if variant == 'original' else stamp(original)
    if variant == 'image' and original_stamp and storage.file_hash(original) == row['sha256']:
        publish(row, 'original', original_stamp)
    else:
        recover_original(row, original_stamp)
        if variant == 'original':
            return
        original_stamp = stamp(original)
    with storage.connect() as db:
        latest = active(db, row['id'])
    if not latest['image_evicted'] or any(latest[key] != row[key] for key in ('sha256', 'filename', 'original_filename', 'image_sha256')):
        raise StaleRecovery
    with staged_asset(latest, 'image') as temporary:
        with Image.open(original) as image:
            encode_display(ImageOps.exif_transpose(image), temporary)
        publish(latest, 'image', before, temporary=temporary, digest=storage.file_hash(temporary), original_stamp=original_stamp)


def recover(identifier, variant):
    with stripe_lock(identifier % 256) as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with storage.connect() as db:
            row = active(db, identifier)
        target = asset_path(row, variant)
        if target is None or not row[variant + '_evicted']:
            if target and target.is_file():
                return
            raise FileNotFoundError(identifier)
        try:
            try:
                restore_asset(row, variant)
            except (SourceUnavailable, ValueError, OSError) as error:
                retry = time.time() + 60
                with storage.connect(True) as db:
                    check_snapshot(db, row)
                    db.execute('UPDATE images SET cache_retry_at=? WHERE id=?', (retry, identifier))
                raise Unavailable('Media recovery failed') from error
        except StaleRecovery:
            return


def request_recovery(identifier, variant, timeout):
    key = (storage.DATA, identifier, variant)
    with pending_lock:
        future = pending.get(key)
        if future is None:
            if len(pending) >= 64:
                raise Unavailable('Media recovery queue is full')
            future = pending[key] = pool.submit(recover, identifier, variant)
            owner = True
        else:
            owner = False
    if owner:
        def finished(done):
            with pending_lock:
                if pending.get(key) is done:
                    pending.pop(key)
        future.add_done_callback(finished)
    try:
        future.result(timeout=timeout)
    except TimeoutError:
        raise Unavailable('Media recovery is still running') from None
    except FileNotFoundError:
        raise
    except (OSError, sqlite3.Error) as error:
        logger.warning('Storage unavailable during media recovery for %s: %s', identifier, error)
        raise Unavailable('Media recovery storage unavailable') from error


@contextmanager
def asset(row, variant, *, timeout=None, descriptor=False):
    identifier = row['id']
    until = None if timeout is None else time.monotonic() + timeout
    while True:
        with storage.connect() as db:
            row = active(db, identifier)
        path = asset_path(row, variant)
        if path is None:
            raise FileNotFoundError(identifier)
        if row[variant + '_evicted']:
            request_recovery(identifier, variant, None if until is None else max(0, until - time.monotonic()))
            continue
        try:
            handle = path.open('rb')
        except FileNotFoundError:
            with storage.connect() as db:
                if active(db, identifier)[variant + '_evicted']:
                    continue
            raise
        with handle:
            fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                unchanged = os.path.samestat(os.fstat(handle.fileno()), path.stat())
            except FileNotFoundError:
                unchanged = False
            if not unchanged:
                continue
            now = time.time()
            if now - (row[variant + '_used'] or 0) >= 1:
                try:
                    with storage.connect(wait=False) as db:
                        db.execute(f'UPDATE images SET {variant}_used=max(coalesce({variant}_used,0),?) WHERE id=? AND hidden=0', (now, identifier))
                except sqlite3.Error as error:
                    if getattr(error, 'sqlite_errorcode', 0) & 255 not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        logger.warning('Cannot record media access for %s: %s', identifier, error)
            yield Path('/dev/fd') / str(handle.fileno()) if descriptor else path
            return


def device(path):
    return path.stat().st_dev


def free_bytes(path):
    return shutil.disk_usage(path).free


def cold_score(variant, used, published, now):
    idle = (now - used) / DAY
    published_days = max(0, (now - published) / DAY)
    return idle * (4 if variant == 'image' else 0.25 + 0.75 * min(published_days / 30, 1))


def candidates(variants, now):
    with storage.connect() as db:
        rows = db.execute('''SELECT i.*, coalesce((SELECT max(unixepoch(p.published_at)) FROM sources s
            JOIN posts p ON p.id=s.post_id WHERE s.image_id=i.id), unixepoch(i.created_at), ?) AS published
            FROM images i WHERE hidden=0''', (now,)).fetchall()
    result = []
    for row in rows:
        for variant in variants:
            path = asset_path(row, variant)
            if not path or not re.fullmatch('[a-f0-9]{64}', row['sha256']) or path.stem != row['sha256']:
                continue
            try:
                used = row[variant + '_used'] or path.stat().st_mtime
            except FileNotFoundError:
                continue
            except PermissionError as error:
                logger.warning('Skipping inaccessible cache file %s: %s', path, error)
                continue
            if used <= now - DAY and path.is_file():
                result.append((cold_score(variant, used, row['published'], now), row['id'], variant))
    return sorted(result, reverse=True)


@dataclass(frozen=True)
class EvictionSource:
    url: str | None = None
    path: Path | None = None
    signature: tuple | None = None
    relative: str | None = None

    def unchanged(self):
        from .importer import IMPORT
        if self.relative is not None and (IMPORT / self.relative).resolve() != self.path:
            return False
        return self.path is None or stamp(self.path) == self.signature

    def registered(self, db, row):
        if self.url:
            return self.url in post_urls(db, row)
        return self.relative is None or db.execute('SELECT 1 FROM import_locations WHERE image_id=? AND path=?',
                                                   (row['id'], self.relative)).fetchone() is not None


def eviction_proof(db, row, variant, path):
    url = next(post_urls(db, row), None)
    if url:
        return EvictionSource(url=url)
    sources = locations(db, row)
    if variant == 'image':
        sources = chain([(None, asset_path(row, 'original'))], sources)
    for relative, source in sources:
        before = stamp(source)
        if before and matches_original(source, row['sha256'], excluding=path):
            return EvictionSource(path=source, signature=before, relative=relative)


def evict(identifier, variant, volume, now):
    with stripe_lock(identifier % 256) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with storage.connect() as db:
            row = active(db, identifier)
            path = asset_path(row, variant)
            if not path or not asset_path(row, 'original'):
                return
            if path.is_symlink() or device(path.parent) != volume or device(path) != volume:
                return
            before = stamp(path)
            proof = eviction_proof(db, row, variant, path)
        if not proof or not proof.unchanged():
            return
        with path.open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            info = os.fstat(handle.fileno())
            def eligible(db):
                latest = active(db, identifier)
                return (asset_path(latest, variant) == path and latest['original_filename'] == row['original_filename']
                        and latest['sha256'] == row['sha256'] and latest['image_sha256'] == row['image_sha256']
                        and (latest[variant + '_used'] or info.st_mtime) <= now - DAY
                        and not path.is_symlink() and stamp(path) == before and os.path.samestat(path.stat(), info)
                        and device(path.parent) == volume and proof.registered(db, latest))
            with storage.connect(True) as db:
                if not eligible(db):
                    return
                db.execute(f'UPDATE images SET {variant}_evicted=1 WHERE id=?', (identifier,))
            if not proof.unchanged():
                return
            with storage.connect(True) as db:
                if not active(db, identifier)[variant + '_evicted'] or not eligible(db):
                    return
                path.unlink()
                return (now - (row[variant + '_used'] or info.st_mtime)) / DAY


def clean(low, target):
    volumes = {}
    for variant, folder in [*FOLDERS.items(), (None, '.')]:
        path = storage.DATA / folder
        try:
            volume = device(path)
        except OSError as error:
            logger.warning('Cannot inspect cache filesystem %s: %s', path, error)
            continue
        root, variants = volumes.setdefault(volume, (path, []))
        if variant:
            variants.append(variant)
    for volume, (root, variants) in volumes.items():
        report = None
        try:
            before = free_bytes(root)
            if before >= low:
                continue
            now = time.time()
            report = Cleanup(finished_at=now, before_bytes=before, after_bytes=None, target_bytes=target, outcome='error',
                             removals={FOLDERS[key]: Evictions(count=0, min_idle_days=None, min_score=None) for key in variants})
            for score, identifier, variant in candidates(variants, now) if variants else ():
                if device(root) != volume:
                    raise OSError('Cache mount changed')
                if free_bytes(root) >= target:
                    break
                try:
                    days = evict(identifier, variant, volume, now)
                except FileNotFoundError:
                    continue
                except PermissionError as error:
                    logger.warning('Skipping inaccessible %s for image %s: %s', variant, identifier, error)
                    continue
                if days is not None:
                    item = report['removals'][FOLDERS[variant]]
                    item['count'] += 1
                    for key, value in [('min_idle_days', days), ('min_score', score)]:
                        item[key] = value if item[key] is None else min(item[key], value)
            if device(root) != volume:
                raise OSError('Cache mount changed')
            remaining = free_bytes(root)
            report.update(after_bytes=remaining, outcome='target' if remaining >= target else 'exhausted')
            if remaining < target:
                logger.warning('Cache filesystem %s has %d bytes free (target %d); no more eligible files', root, remaining, target)
        except (OSError, sqlite3.Error) as error:
            logger.warning('Stopped cache cleanup on %s: %s', root, error)
        if report is not None:
            report['finished_at'] = time.time()
            try:
                record(f'volume:{volume}', report)
            except (OSError, sqlite3.Error) as error:
                logger.warning('Could not save cache cleanup report: %s', error)
