import json
import logging
import secrets
import shutil
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from anyio import CancelScope, to_thread
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db as storage, trash
from .review_format import Identifier, Result

PREFIX = '/api/v1/admin/review-packages'
logger = logging.getLogger(__name__)
lock = threading.Lock()
transfers = set()
executor = None


def directory():
    return storage.DATA / 'review-exports'


def cleanup(startup=False):
    with lock, storage.connect(True) as db:
        if startup:
            db.execute("UPDATE review_batches SET status='failed',error='生成中断，请重新导出' WHERE status='building'")
            for path in directory().glob('*.part'):
                path.unlink(missing_ok=True)
            for path in directory().glob('*.zip'):
                if not db.execute(
                    "SELECT 1 FROM review_batches WHERE id=? AND status='ready'", (path.stem,)
                ).fetchone():
                    path.unlink(missing_ok=True)
            for row in db.execute("SELECT id FROM review_batches WHERE status='ready'"):
                if not (directory() / (row['id'] + '.zip')).is_file():
                    db.execute("UPDATE review_batches SET status='expired' WHERE id=?", (row['id'],))
        for row in db.execute("SELECT id FROM review_batches WHERE status='ready' AND expires<=?", (time.time(),)):
            if row['id'] not in transfers:
                (directory() / (row['id'] + '.zip')).unlink(missing_ok=True)
                db.execute("UPDATE review_batches SET status='expired' WHERE id=?", (row['id'],))


@contextmanager
def service():
    global executor
    directory().mkdir(exist_ok=True)
    cleanup(startup=True)
    stop = threading.Event()

    def sweep():
        while not stop.wait(30):
            try:
                cleanup()
            except Exception:
                logger.exception('Review package cleanup failed')

    with ThreadPoolExecutor(max_workers=1) as pool:
        executor = pool
        thread = threading.Thread(target=sweep, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()
            executor = None


class ExportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: str = 'review'
    image_id: Identifier | None = None
    ids: list[Identifier] = Field(default_factory=list, max_length=500)
    people: str = ''
    publishers: str = ''
    match: Literal['any', 'all', 'exact', 'subset'] = 'any'
    start: str = ''
    end: str = ''


class Job(BaseModel):
    id: str
    status: Literal['building', 'ready', 'downloaded', 'expired', 'failed']
    total: int
    done: int = 0
    expires: float | None = None
    error: str | None = None


def snapshot(db, image_id):
    image = db.execute('SELECT id,group_id,width,height,sha256 FROM images WHERE id=?', (image_id,)).fetchone()
    faces = []
    db.execute('INSERT OR IGNORE INTO review_face_identity(face_id) SELECT id FROM faces WHERE image_id=?', (image_id,))
    for row in db.execute(
        'SELECT id,token,box,revision,person_id,locked,ignored,candidates,length(embedding)>0 AS has_feature FROM faces JOIN review_face_identity ON face_id=id WHERE image_id=? ORDER BY id',
        (image_id,),
    ):
        faces.append(dict(row, box=json.loads(row['box']), candidates=json.loads(row['candidates'])))
    group = trash.preview(db, [image_id])
    return dict(image, faces=faces, member_ids=group['ids'], scope_token=group['scope_token'])


def start(body):
    from .main import review_selection

    grouped, base, where, params = review_selection(
        body.state, body.image_id, body.start, body.end, body.people, body.match, body.publishers
    )
    if not grouped:
        raise HTTPException(400, '回收站图片不能导出')
    if body.ids:
        where += ' AND g.representative IN (SELECT value FROM json_each(?))'
        params.append(json.dumps(body.ids))
    batch = secrets.token_hex(16)
    with storage.connect(True) as db:
        ids = [row[0] for row in db.execute(f'SELECT g.representative FROM {base}{where} ORDER BY g.group_id', params)]
        if not ids or (body.ids and set(ids) != set(body.ids)):
            raise HTTPException(409, '导出范围已变化或为空，请刷新后重试')
        instructions = storage.settings(db)['agent_review_rules']
        db.execute(
            "INSERT INTO review_batches(id,status,instructions,total) VALUES(?,'building',?,?)",
            (batch, instructions, len(ids)),
        )
        db.executemany(
            'INSERT INTO review_snapshots VALUES(?,?,?)',
            ((batch, identifier, json.dumps(snapshot(db, identifier))) for identifier in ids),
        )
        db.execute('INSERT INTO review_roster SELECT ?,id,id FROM people', (batch,))
        db.execute('INSERT INTO review_group_roster SELECT ?,id,id,name,name_ja FROM groups', (batch,))
    executor.submit(build, batch, instructions)
    return Job(id=batch, status='building', total=len(ids))


def write_json(archive, name, value):
    archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2), compress_type=zipfile.ZIP_DEFLATED)


def snapshot_rows(db, batch):
    after = 0
    while rows := db.execute('''SELECT image_id,snapshot FROM review_snapshots
        WHERE batch=? AND image_id>? ORDER BY image_id LIMIT 32''', (batch, after)).fetchall():
        yield from rows
        after = rows[-1]['image_id']


def build(batch, instructions):
    from .main import MediaRead, people, reference_crop, cropped_image

    partial = directory() / (batch + '.part')
    try:
        with zipfile.ZipFile(partial, 'w') as archive, storage.connect() as db:
            roster = []
            allowed = {row[0] for row in db.execute('SELECT person_id FROM review_roster WHERE batch=?', (batch,))}
            for person in people():
                if person['id'] not in allowed:
                    continue
                refs = []
                for row in db.execute(
                    f'SELECT id FROM reference_images WHERE person_id=? AND {storage.ACTIVE_REFERENCE} ORDER BY id',
                    (person['id'],),
                ).fetchall():
                    try:
                        with MediaRead() as reads:
                            data = reference_crop(row['id'], reads).body
                    except (HTTPException, OSError, ValueError):
                        continue
                    name = f"references/{person['id']}/{row['id']}.jpg"
                    archive.writestr(name, data)
                    refs.append(name)
                    if len(refs) == 3:
                        break
                roster.append(dict(person, references=refs, missing_references=not refs))
            write_json(archive, 'people.json', roster)
            groups = db.execute('SELECT exported_id AS id,name,name_ja FROM review_group_roster WHERE batch=? ORDER BY exported_id', (batch,))
            write_json(archive, 'groups.json', [dict(row) for row in groups])
            images = []
            for identifier, raw in snapshot_rows(db, batch):
                item = json.loads(raw)
                item.pop('scope_token')
                item.pop('sha256')
                with MediaRead() as reads:
                    path = reads.pin({'id': identifier}, 'image')
                    item['display'] = f'images/{identifier}/display.jpg'
                    with path.open('rb') as source, archive.open(item['display'], 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target)
                    for face in item['faces']:
                        face.pop('token')
                        face['crop'] = f"images/{identifier}/face-{face['id']}.jpg"
                        archive.writestr(face['crop'], cropped_image(path, face['box']).body)
                item['sources'] = [
                    dict(row, coauthors=json.loads(row['coauthors'] or '[]'))
                    for row in db.execute(
                        '''SELECT s.image_id,p.id,p.author,p.author_name,p.platform,p.coauthors,p.post_text,p.url,p.published_at
                    FROM sources s JOIN posts p ON p.id=s.post_id JOIN images i ON i.id=s.image_id
                    WHERE i.hidden=0 AND i.id IN (SELECT value FROM json_each(?)) ORDER BY s.image_id,p.id''',
                        (json.dumps(item['member_ids']),),
                    )
                ]
                name = f'images/{identifier}/metadata.json'
                write_json(archive, name, item)
                images.append(name)
                if len(images) == 1 or len(images) % 10 == 0:
                    with storage.connect(True) as progress:
                        progress.execute('UPDATE review_batches SET done=? WHERE id=?', (len(images), batch))
            write_json(
                archive,
                'manifest.json',
                dict(version=1, batch=batch, instructions=instructions, images=images, people='people.json', groups='groups.json'),
            )
            archive.write(Path(__file__).with_name('review-kit') / 'SKILL.md', 'SKILL.md')
            write_json(archive, 'review-result.schema.json', Result.model_json_schema())
            write_json(archive, 'review-result.example.json', dict(version=1, batch=batch, suggestions=[]))
        partial.replace(partial.with_suffix('.zip'))
        with storage.connect(True) as db:
            db.execute(
                "UPDATE review_batches SET done=total,status='ready',expires=? WHERE id=?", (time.time() + 3600, batch)
            )
    except Exception:
        logger.exception('Review package generation failed: %s', batch)
        partial.unlink(missing_ok=True)
        with storage.connect(True) as db:
            db.execute(
                "UPDATE review_batches SET status='failed',error='生成失败，请检查图片是否可用并重新导出' WHERE id=?",
                (batch,),
            )


class Download(FileResponse):
    def finish(self, complete):
        batch = self.path.stem
        with lock:
            transfers.discard(batch)
            if complete:
                self.path.unlink(missing_ok=True)
                with storage.connect(True) as db:
                    db.execute("UPDATE review_batches SET status='downloaded' WHERE id=?", (batch,))

    async def __call__(self, scope, receive, send):
        complete = False

        async def forward(message):
            nonlocal complete
            await send(message)
            if message['type'] == 'http.response.body' and not message.get('more_body'):
                complete = True

        try:
            await super().__call__(
                {
                    **scope,
                    'extensions': {},
                    'headers': [(key, value) for key, value in scope['headers'] if key != b'range'],
                },
                receive,
                forward,
            )
        finally:
            with CancelScope(shield=True):
                await to_thread.run_sync(self.finish, complete)


def install(app, admin):
    router = APIRouter(prefix=PREFIX, dependencies=[Depends(admin)])

    @router.post('/exports', response_model=Job, status_code=202)
    def export_review(body: ExportInput):
        return start(body)

    @router.get('/exports/{batch}', response_model=Job)
    def export_status(batch: str):
        with storage.connect() as db:
            row = db.execute('SELECT * FROM review_batches WHERE id=?', (batch,)).fetchone()
            if not row:
                raise HTTPException(404, '导出任务不存在')
            return dict(row)

    @router.get(
        '/exports/{batch}/download', response_class=FileResponse, responses={200: {'content': {'application/zip': {}}}}
    )
    def download_review(batch: str):
        with lock:
            job = export_status(batch)
            if job['status'] != 'ready' or job['expires'] <= time.time():
                raise HTTPException(410, '审核包尚未就绪、已下载或已过期')
            if batch in transfers:
                raise HTTPException(409, '该审核包正在下载')
            transfers.add(batch)
        return Download(directory() / (batch + '.zip'), filename=f'review-{batch}.zip', media_type='application/zip')

    app.include_router(router)
