import base64
import hashlib
import io
import json
import re
import stat
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

from . import db as storage, trash
from .importer import atomic_asset
from .representatives import require_representative
from .review_format import (
    AddFace,
    AddReference,
    CreatePerson,
    ExternalReference,
    Identifier,
    LibraryReference,
    Match,
    Operation,
    Remove,
    Result,
    fits,
)
from .review_packages import PREFIX
from .vision import MODEL_VERSION, Vision, validate_embedding

MAX_BYTES = 20 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
ATTACHMENT_NAME = re.compile(r'attachments/[A-Za-z0-9_-]{1,100}\.(?:jpg|jpeg|png|webp)\Z')


def fail(detail, status=400):
    raise HTTPException(status, detail)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unpack(file):
    name = (file.filename or '').lower()
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        fail('结果文件超过 20 MiB', 413)
    attachments = {}
    if name.endswith('.zip'):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                if len(entries) > 130 or sum(entry.file_size for entry in entries) > MAX_BYTES:
                    fail('解压后文件过多或过大', 413)
                names = set()
                for entry in entries:
                    path = entry.orig_filename
                    kind = stat.S_IFMT(entry.external_attr >> 16)
                    if (
                        path in names
                        or entry.flag_bits & 1
                        or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    ):
                        fail('结果包包含重复、加密或不支持的文件')
                    names.add(path)
                    if path == 'attachments/' and kind in (0, stat.S_IFDIR) and not entry.file_size:
                        continue
                    if kind not in (0, stat.S_IFREG) or not (
                        ATTACHMENT_NAME.fullmatch(path) or path == 'review-result.json'
                    ):
                        fail('结果包路径或文件类型无效')
                    if path == 'review-result.json' and entry.file_size > MAX_JSON:
                        fail('结果 JSON 过大', 413)
                    attachments[path] = archive.read(entry)
                if 'review-result.json' not in attachments:
                    fail('缺少 review-result.json')
                raw = attachments.pop('review-result.json')
        except (OSError, ValueError, zipfile.BadZipFile, EOFError, RuntimeError, zlib.error) as error:
            raise HTTPException(400, '无法读取结果 ZIP') from error
    elif not name.endswith('.json'):
        fail('请选择 JSON 或 ZIP 文件')
    if len(raw) > MAX_JSON:
        fail('结果 JSON 过大', 413)
    try:
        result = Result.model_validate_json(raw, strict=True)
    except ValidationError as error:
        first = error.errors(include_input=False, include_url=False)[0]
        fail(f"结果格式无效：{'.'.join(map(str, first['loc']))} {first['msg']}")
    expected = {
        op.source.attachment
        for op in result.suggestions
        if isinstance(op, AddReference) and isinstance(op.source, ExternalReference)
    }
    if expected != set(attachments):
        fail('结果包附件与建议引用不一致')
    return result, attachments


def attachment_pixels(name, raw):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            suffix = name.rsplit('.', 1)[1]
            if source.format != {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}[suffix] or getattr(
                source, 'is_animated', False
            ):
                fail('附件格式与扩展名不符或不是静态图片')
            if source.width * source.height > 24_000_000:
                fail('附件图片像素过多', 413)
            return source.width * source.height
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(400, '无法读取附件图片') from error


def prepare_attachment(raw, threshold):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            oriented = ImageOps.exif_transpose(source).convert('RGB')
            output = io.BytesIO()
            oriented.save(output, 'JPEG', quality=94)
    except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError) as error:
        raise HTTPException(400, '无法读取附件图片') from error
    jpeg = output.getvalue()
    with tempfile.TemporaryDirectory(dir=storage.DATA) as temp:
        path = Path(temp) / 'source.jpg'
        path.write_bytes(jpeg)
        try:
            detected = Vision().detect(path, mode='highres', threshold=threshold)
        except ValueError as error:
            fail(str(error))
    faces = []
    for box, embedding in detected:
        try:
            validate_embedding(embedding)
        except ValueError:
            continue
        faces.append(dict(box=box, embedding=base64.b64encode(embedding).decode()))
    return jpeg, oriented.width, oriented.height, encode(faces), MODEL_VERSION


def face_identifier(op):
    if isinstance(op, (Match, Remove)):
        return op.face_id
    if isinstance(op, AddReference) and isinstance(op.source, LibraryReference):
        return op.source.face_id
    return None


def validate_scope(db, batch, op):
    row = db.execute(
        'SELECT snapshot FROM review_snapshots WHERE batch=? AND image_id=?', (batch, op.image_id)
    ).fetchone()
    if not row:
        fail('图片不在本批导出范围内')
    image = json.loads(row[0])
    face_id = face_identifier(op)
    if face_id and not any(face['id'] == face_id for face in image['faces']):
        fail('人脸不在该图片的导出快照中')
    if isinstance(op, AddFace) and not fits(op.box, image['width'], image['height']):
        fail('人脸框超出展示图范围')
    person = getattr(op, 'person_id', None)
    if (
        isinstance(person, int)
        and not db.execute('SELECT 1 FROM review_roster WHERE batch=? AND exported_id=?', (batch, person)).fetchone()
    ):
        fail('目标人物不在本批名册中')


class ImportCount(BaseModel):
    added: int
    duplicates: int


def import_file(file):
    result, attachments = unpack(file)
    batch = result.batch
    hashes = {path: digest(data) for path, data in attachments.items()}
    with storage.connect() as db:
        job = db.execute('SELECT status FROM review_batches WHERE id=?', (batch,)).fetchone()
        if not job or job['status'] not in ('ready', 'expired', 'downloaded'):
            fail('无效或未完成的导出批次')
        for op in result.suggestions:
            validate_scope(db, batch, op)
        threshold = float(storage.settings(db)['detection_threshold'])
    added = 0
    if sum(attachment_pixels(path, raw) for path, raw in attachments.items()) > 96_000_000:
        fail('附件总像素过多，请分次导入', 413)
    with tempfile.TemporaryDirectory(dir=storage.DATA) as temp:
        prepared = {}
        for path, raw in attachments.items():
            key = hashes[path]
            with storage.connect() as db:
                if key in prepared or db.execute('SELECT 1 FROM review_attachments WHERE digest=?', (key,)).fetchone():
                    continue
            jpeg, *metadata = prepare_attachment(raw, threshold)
            staging = Path(temp) / key
            staging.write_bytes(jpeg)
            prepared[key] = staging, metadata
        with storage.connect(True) as db:
            for key, (staging, metadata) in prepared.items():
                db.execute(
                    'INSERT OR IGNORE INTO review_attachments VALUES(?,?,?,?,?,?)',
                    (key, staging.read_bytes(), *metadata),
                )
            for op in result.suggestions:
                payload = op.model_dump(mode='json')
                if op.confidence is None:
                    payload.pop('confidence')
                key = None
                identity = {k: v for k, v in payload.items() if k not in ('id', 'reason', 'confidence')}
                if isinstance(op, AddReference) and isinstance(op.source, ExternalReference):
                    key = hashes[op.source.attachment]
                    width, height = db.execute(
                        'SELECT width,height FROM review_attachments WHERE digest=?', (key,)
                    ).fetchone()
                    if op.source.box and not fits(op.source.box, width, height):
                        fail('目标人脸框超出附件范围')
                    identity['source'] = dict(attachment=key, box=op.source.box)
                content = digest(encode([payload, key]).encode())
                previous = db.execute(
                    'SELECT content FROM review_result_keys WHERE batch=? AND key=?', (batch, op.id)
                ).fetchone()
                if previous:
                    if previous[0] != content:
                        fail(f'建议 {op.id} 的内容与已导入记录不同', 409)
                    continue
                fingerprint = digest(encode(identity).encode())
                duplicate = db.execute(
                    'SELECT id FROM review_suggestions WHERE batch=? AND fingerprint=?', (batch, fingerprint)
                ).fetchone()
                if duplicate:
                    identifier = duplicate[0]
                else:
                    if isinstance(op, CreatePerson) and temporary_person(db, batch, op.person_id):
                        fail('临时人物编号已被使用', 409)
                    identifier = db.execute(
                        '''INSERT INTO review_suggestions(batch,key,image_id,payload,fingerprint,attachment)
                        VALUES(?,?,?,?,?,?)''',
                        (batch, op.id, op.image_id, encode(payload), fingerprint, key),
                    ).lastrowid
                    added += 1
                db.execute('INSERT INTO review_result_keys VALUES(?,?,?,?)', (batch, op.id, content, identifier))
    return ImportCount(added=added, duplicates=len(result.suggestions) - added)


def temporary_person(db, batch, key):
    return db.execute(
        "SELECT created_person,status,json_extract(payload,'$.name') name FROM review_suggestions WHERE batch=? AND json_extract(payload,'$.kind')='create_person' AND json_extract(payload,'$.person_id')=?",
        (batch, key),
    ).fetchone()


def resolve_person(db, batch, key):
    if key is None:
        return None
    if isinstance(key, str):
        row = temporary_person(db, batch, key)
        if not row or row['status'] != 'accepted' or not row['created_person']:
            fail('请先单独接受新建人物建议，或检查人物是否已删除', 409)
        return row['created_person']
    row = db.execute('SELECT person_id FROM review_roster WHERE batch=? AND exported_id=?', (batch, key)).fetchone()
    if not row or not row[0]:
        fail('目标人物已不存在', 409)
    return row[0]


def suggested_index(detections, box):
    if box is None:
        return 0 if len(detections) == 1 else None
    left, top, width, height = box
    matches = []
    for index, face in enumerate(detections):
        other_left, other_top, other_width, other_height = face['box']
        overlap = max(0, min(left + width, other_left + other_width) - max(left, other_left)) * max(
            0, min(top + height, other_top + other_height) - max(top, other_top)
        )
        if overlap / (width * height + other_width * other_height - overlap) >= 0.4:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


class AttachmentPreview(BaseModel):
    width: int
    height: int
    boxes: list[list[float]]
    suggested_index: int | None


class QueueItem(BaseModel):
    id: int
    batch: str
    status: str
    image_id: int
    width: int
    height: int
    proposal: Operation
    current: str
    proposed: str
    box: list[float] | None
    reference_ids: list[int]
    attachment: AttachmentPreview | None
    member_ids: list[int]
    scope_token: str | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    total: int
    page: int
    page_size: int


def name(db, key):
    if key is None:
        return '未知人物'
    row = db.execute('SELECT name FROM people WHERE id=?', (key,)).fetchone()
    return f'{row[0]} (#{key})' if row else f'已删除人物 #{key}'


def queue_item(db, row):
    payload = json.loads(row['payload'])
    image = json.loads(row['snapshot'])
    person = payload.get('person_id')
    batch = row['batch']
    if isinstance(person, str):
        temporary = temporary_person(db, batch, person)
        target = f"{temporary['name']} ({person})" if temporary else person
        person = temporary['created_person'] if temporary else None
    else:
        target = name(db, person)
    refs = [
        ref[0]
        for ref in db.execute(
            f'SELECT id FROM reference_images WHERE person_id=? AND {storage.ACTIVE_REFERENCE} ORDER BY id LIMIT 3',
            (person,),
        )
    ]
    source = payload.get('source', {})
    face_id = payload.get('face_id') or source.get('face_id')
    face = db.execute('SELECT * FROM faces WHERE id=? AND image_id=?', (face_id, row['image_id'])).fetchone()
    old = next((item for item in image['faces'] if item['id'] == face_id), {})
    box = json.loads(face['box']) if face else payload.get('box') or old.get('box')
    attachment = None
    if row['attachment']:
        data = db.execute(
            'SELECT width,height,detections FROM review_attachments WHERE digest=?', (row['attachment'],)
        ).fetchone()
        detections = json.loads(data['detections'])
        index = row['chosen_face'] if row['chosen_face'] is not None else suggested_index(detections, source.get('box'))
        attachment = AttachmentPreview(
            width=data['width'],
            height=data['height'],
            boxes=[item['box'] for item in detections],
            suggested_index=index,
        )
    token = None
    members = image['member_ids']
    kind = payload['kind']
    if kind in ('match', 'remove_face'):
        current = (
            (
                '已移除'
                if face['ignored']
                else name(db, face['person_id']) + (' · 已确认' if face['locked'] else ' · 未确认')
            )
            if face
            else '人脸不存在'
        )
        proposed = target + ' · 已确认' if kind == 'match' else '移除误检'
    elif kind == 'add_reference':
        count = db.execute(
            f'SELECT count(*) FROM reference_images WHERE person_id=? AND {storage.ACTIVE_REFERENCE}', (person,)
        ).fetchone()[0]
        current, proposed = f'{target} · {count} 张参考图', f'添加至 {target} 的参考图'
    elif kind == 'create_person':
        current, proposed = ('已创建' if person else '未创建'), payload['name']
    elif kind == 'add_face':
        current, proposed = '未标注此框', f'补画人脸 · {target}'
    else:
        scope = trash.preview(db, [row['image_id']])
        members, token = scope['ids'], scope['scope_token']
        current, proposed = f"在库 {scope['total']-scope['already_trashed']} 张", f'整组 {len(members)} 张移入回收站'
    return QueueItem(
        id=row['id'],
        batch=batch,
        status=row['status'],
        image_id=row['image_id'],
        width=image['width'],
        height=image['height'],
        proposal=payload,
        current=current,
        proposed=proposed,
        box=box,
        reference_ids=refs,
        attachment=attachment,
        member_ids=members,
        scope_token=token,
    )


class Choice(BaseModel):
    id: Identifier
    face_index: int | None = Field(None, ge=0)
    scope_token: str | None = None


class Decision(BaseModel):
    decision: Literal['accept', 'reject']
    items: list[Choice] = Field(min_length=1, max_length=100)


class Failure(BaseModel):
    id: int
    detail: str


class Decisions(BaseModel):
    applied: list[int]
    failures: list[Failure]


def apply(db, row, choice, created_files):
    from .main import FaceEdit, write_face_edit

    image_id = row['image_id']
    batch = row['batch']
    image = require_representative(db, image_id)
    snap = json.loads(row['snapshot'])
    if image['group_id'] != snap['group_id'] or image['sha256'] != snap['sha256']:
        fail('代表图已变化', 409)
    payload = json.loads(row['payload'])
    kind = payload['kind']
    source = payload.get('source', {})
    face_id = payload.get('face_id') or source.get('face_id')
    if face_id:
        face = db.execute(
            'SELECT f.*,identity.token FROM faces f JOIN review_face_identity identity ON identity.face_id=f.id WHERE f.id=? AND f.image_id=?',
            (face_id, image_id),
        ).fetchone()
        old = next(item for item in snap['faces'] if item['id'] == face_id)
        if not face or face['token'] != old['token'] or json.loads(face['box']) != old['box']:
            fail('目标人脸已变化', 409)
        if face['revision'] != old['revision']:
            accepted = (
                kind == 'add_reference'
                and db.execute(
                    '''SELECT 1 FROM review_match_versions m JOIN review_suggestions s ON s.id=m.suggestion
                WHERE s.batch=? AND s.status='accepted' AND m.face_id=? AND m.revision=?''',
                    (batch, face_id, face['revision']),
                ).fetchone()
            )
            if not accepted:
                fail('人脸版本已变化，请重新导出', 409)
    if kind == 'create_person':
        person = db.execute('INSERT INTO people(name) VALUES(?)', (payload['name'].strip(),)).lastrowid
        db.execute('UPDATE review_suggestions SET created_person=? WHERE id=?', (person, choice.id))
        return
    person = resolve_person(db, batch, payload.get('person_id'))
    if kind in ('match', 'remove_face'):
        write_face_edit(
            db, face_id, FaceEdit(person_id=person, ignored=kind == 'remove_face', revision=face['revision'])
        )
        if kind == 'match':
            db.execute('INSERT INTO review_match_versions VALUES(?,?,?)', (choice.id, face_id, face['revision'] + 1))
    elif kind == 'add_face':
        box = payload['box']
        if not fits(box, image['width'], image['height']):
            fail('人脸框超出当前图片范围', 409)
        existing = [
            dict(box=json.loads(item[0]))
            for item in db.execute('SELECT box FROM faces WHERE image_id=? AND ignored=0', (image_id,))
        ]
        if any(suggested_index([item], box) == 0 for item in existing):
            fail('相同位置已有人脸框', 409)
        db.execute(
            'INSERT INTO faces(image_id,box,person_id,locked) VALUES(?,?,?,?)',
            (image_id, encode(box), person, person is not None),
        )
        db.execute("UPDATE images SET detection='done',error=NULL WHERE id=?", (image_id,))
    elif kind == 'recycle':
        rows, actual = trash.scope(db, [image_id])
        if choice.scope_token != actual or actual != snap['scope_token']:
            fail('请重新确认整组回收范围；组成员变化后须重新导出', 409)
        trash.recycle_rows(db, rows)
    elif face_id:
        if not face['locked'] or face['ignored'] or face['person_id'] != person or not face['embedding']:
            fail('库内参考须为该人物已确认且有有效特征的人脸', 409)
        validate_embedding(face['embedding'], face['model_version'])
        if not db.execute(
            'SELECT 1 FROM reference_images WHERE face_id=? AND person_id=?', (face_id, person)
        ).fetchone():
            db.execute(
                'INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(?,?,?,?,?)',
                (person, image_id, face_id, face['embedding'], face['model_version']),
            )
            storage.schedule_rematch(db)
    else:
        data = db.execute('SELECT * FROM review_attachments WHERE digest=?', (row['attachment'],)).fetchone()
        faces = json.loads(data['detections'])
        index = choice.face_index if choice.face_index is not None else suggested_index(faces, source.get('box'))
        if index is None or index >= len(faces):
            fail('请从附件中选择有效的目标人脸', 409)
        embedding = base64.b64decode(faces[index]['embedding'])
        validate_embedding(embedding, data['model'])
        filename = f"review-{row['attachment']}.jpg"
        path = storage.DATA / 'references' / filename
        if not path.exists():
            with atomic_asset(path) as temp:
                temp.write_bytes(data['jpeg'])
            created_files.append(path)
        db.execute(
            'INSERT INTO reference_images(person_id,filename,box,embedding,model_version) VALUES(?,?,?,?,?)',
            (person, filename, encode(faces[index]['box']), embedding, data['model']),
        )
        db.execute('UPDATE review_suggestions SET chosen_face=? WHERE id=?', (index, choice.id))
        storage.schedule_rematch(db)


JOIN_SNAPSHOT = (
    '''FROM review_suggestions s JOIN review_snapshots snap ON snap.batch=s.batch AND snap.image_id=s.image_id'''
)


def install(app, admin):
    router = APIRouter(prefix=PREFIX, dependencies=[Depends(admin)])

    @router.post('/imports', response_model=ImportCount)
    def import_review(file: UploadFile = File(...)):
        return import_file(file)

    @router.get('/suggestions', response_model=QueuePage)
    def review_queue(
        status: Literal['pending', 'accepted', 'rejected'] = 'pending',
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ):
        with storage.connect() as db:
            db.execute('BEGIN')
            total = db.execute('SELECT count(*) FROM review_suggestions WHERE status=?', (status,)).fetchone()[0]
            page = min(page, max(1, (total + page_size - 1) // page_size))
            rows = db.execute(
                'SELECT s.*,snap.snapshot '
                + JOIN_SNAPSHOT
                + ' WHERE status=? ORDER BY s.image_id,s.id LIMIT ? OFFSET ?',
                (status, page_size, (page - 1) * page_size),
            )
            return QueuePage(items=[queue_item(db, row) for row in rows], total=total, page=page, page_size=page_size)

    @router.get(
        '/suggestions/{identifier}/attachment',
        responses={200: {'content': {'image/jpeg': {}}}},
        response_class=Response,
    )
    def review_attachment(identifier: Identifier):
        with storage.connect() as db:
            row = db.execute(
                'SELECT jpeg FROM review_attachments a JOIN review_suggestions s ON s.attachment=a.digest WHERE s.id=?',
                (identifier,),
            ).fetchone()
            if not row:
                fail('附件不存在', 404)
            return Response(row[0], media_type='image/jpeg')

    @router.post('/decisions', response_model=Decisions)
    def decide(body: Decision):
        if len({item.id for item in body.items}) != len(body.items):
            fail('所选建议不能重复')
        applied, failures = [], []
        recycle = False
        choices = body.items
        if body.decision == 'accept':
            with storage.connect() as db:
                kinds = dict(
                    db.execute(
                        "SELECT id,json_extract(payload,'$.kind') FROM review_suggestions WHERE id IN (SELECT value FROM json_each(?))",
                        (encode([item.id for item in choices]),),
                    )
                )
            order = {'create_person': 0, 'match': 1, 'add_reference': 2, 'recycle': 3}
            choices = sorted(choices, key=lambda item: order.get(kinds.get(item.id), 1))
        for choice in choices:
            created_files = []
            try:
                with storage.connect(True) as db:
                    row = db.execute(
                        'SELECT s.*,snap.snapshot ' + JOIN_SNAPSHOT + ' WHERE s.id=?', (choice.id,)
                    ).fetchone()
                    if not row or row['status'] != 'pending':
                        fail('建议不存在或已处理', 409)
                    if body.decision == 'accept':
                        apply(db, row, choice, created_files)
                    status = 'accepted' if body.decision == 'accept' else 'rejected'
                    db.execute('UPDATE review_suggestions SET status=? WHERE id=?', (status, choice.id))
                applied.append(choice.id)
                recycle |= status == 'accepted' and json.loads(row['payload'])['kind'] == 'recycle'
            except (HTTPException, ValueError) as error:
                failures.append(
                    Failure(id=choice.id, detail=error.detail if isinstance(error, HTTPException) else str(error))
                )
            finally:
                if created_files and choice.id not in applied:
                    with storage.connect(True) as db:
                        for path in created_files:
                            if not db.execute(
                                'SELECT 1 FROM reference_images WHERE filename=?', (path.name,)
                            ).fetchone():
                                path.unlink(missing_ok=True)
        if recycle:
            storage.cleanup_deleted_files()
        return Decisions(applied=applied, failures=failures)

    app.include_router(router)
