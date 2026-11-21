"""Resume a gallery-dl HTTP transfer only for a verified representation."""
import hashlib
import json
import re
import uuid
from contextlib import contextmanager

from . import db as storage


def validator(response, total):
    tag = response.headers.get('ETag', '')
    if (not re.fullmatch(r'"[^"\s]*"', tag) or not total.isdecimal()
            or response.headers.get('Content-Encoding', 'identity').lower() != 'identity'):
        return None
    return hashlib.sha256(json.dumps([response.url, tag, total]).encode()).hexdigest()


@contextmanager
def verified_part(active, session, pathfmt, meta):
    media = json.dumps(active.identity(meta))
    with storage.connect(True) as db:
        active.owner(db)
        row = db.execute('SELECT * FROM download_parts WHERE task_id=? AND media=?', (active.task_id, media)).fetchone()
        if not row:
            filename = f'partial-{active.task_id}-{uuid.uuid4().hex}'
            db.execute('INSERT OR REPLACE INTO download_parts(task_id,media,filename) VALUES(?,?,?)', (active.task_id, media, filename))
        else:
            filename = row['filename']
    saved = row['validator'] if row else None
    path = storage.DATA / 'downloads' / filename
    pathfmt.part_enable()
    pathfmt.temppath = str(path)
    request = session.request

    def fetch(method, url, **kwargs):
        nonlocal saved
        headers = kwargs['headers']
        headers['Accept-Encoding'] = 'identity'
        if not saved:
            headers.pop('Range', None)
        response = request(method, url, **kwargs)
        if response.status_code == 206:
            bounds = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if (bounds and saved and headers.get('Range') == f'bytes={bounds[1]}-'
                    and int(bounds[1]) < int(bounds[3]) == int(bounds[2]) + 1
                    and validator(response, bounds[3]) == saved):
                with storage.connect(True) as db:
                    active.owner(db)
                    db.execute('UPDATE download_parts SET resume_offset=? WHERE task_id=? AND filename=?',
                               (int(bounds[1]), active.task_id, filename))
                return response
        if response.status_code in (206, 416):
            response.close()
            headers.pop('Range', None)
            response = request(method, url, **kwargs)
            if response.status_code in (206, 416):
                response.close()
                raise ValueError('无法验证分段下载内容')
        if response.status_code == 200:
            saved = validator(response, response.headers.get('Content-Length', ''))
            with storage.connect(True) as db:
                active.owner(db)
                path.unlink(missing_ok=True)
                db.execute('UPDATE download_parts SET validator=?,resume_offset=0 WHERE task_id=? AND filename=?',
                           (saved, active.task_id, filename))
        return response

    session.request = fetch
    try:
        yield
    finally:
        session.request = request


def install(active):
    from gallery_dl.downloader.http import HttpDownloader
    from .metadata import metadata
    original = HttpDownloader.download
    def download(downloader, url, pathfmt):
        with verified_part(active, downloader.session, pathfmt, metadata(pathfmt.kwdict, '')):
            return original(downloader, url, pathfmt)
    HttpDownloader.download = download
