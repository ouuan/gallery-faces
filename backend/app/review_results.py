import base64
import hashlib
import io
import json
import logging
import re
import secrets
import stat
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, ValidationError

from . import db as storage, review_packages, trash
from .importer import atomic_asset
from .metadata import post_identity
from .representatives import require_representative
from .review_format import (
    AddFace,
    AddPersonGroup,
    AddReference,
    CorrectSource,
    CreatePerson,
    ExternalReference,
    GroupNameJa,
    Identifier,
    LibraryReference,
    Match,
    Operation,
    Remove,
    Result,
    ReviewOutcome,
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


def unpack(extension, raw):
    attachments = {}
    if extension == '.zip':
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


def prepare_attachment(raw):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            oriented = ImageOps.exif_transpose(source).convert('RGB')
            output = io.BytesIO()
            oriented.save(output, 'JPEG', quality=94)
    except (OSError, ValueError, Image.DecompressionBombError, UnidentifiedImageError) as error:
        raise HTTPException(400, '无法读取附件图片') from error
    return output.getvalue(), oriented.width, oriented.height


def detect_attachment(jpeg, threshold):
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
    return encode(faces)


def face_identifier(op):
    if isinstance(op, (Match, Remove)):
        return op.face_id
    if isinstance(op, AddReference) and isinstance(op.source, LibraryReference):
        return op.source.face_id
    return None


def roster_groups(db, batch, ids):
    return {row['exported_id']: row for row in db.execute('''SELECT r.exported_id,r.name,r.group_id,g.name AS current_name,g.name_ja
        FROM review_group_roster r LEFT JOIN groups g ON g.id=r.group_id
        WHERE batch=? AND exported_id IN (SELECT value FROM json_each(?))''', (batch, encode(ids)))}


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
    group_ids = op.group_ids if isinstance(op, CreatePerson) else [op.group_id] if isinstance(op, (GroupNameJa, AddPersonGroup)) else []
    if group_ids and set(group_ids) != roster_groups(db, batch, group_ids).keys():
        fail('指定分组不在本批分组名册中，请检查编号或重新导出')
    if isinstance(op, CorrectSource):
        post = next((source for source in image.get('sources', []) if source['id'] == op.post_id), None)
        if not post:
            fail('来源不在该图片的导出快照中，请重新导出')
        if op.field == 'url' and not post_identity(post['platform'], op.value):
            fail('更正链接必须是该来源平台的帖子链接')


class ImportJob(BaseModel):
    id: str
    status: Literal['queued', 'running', 'done', 'failed']
    added: int = 0
    recorded: int = 0
    duplicates: int = 0
    error: str | None = None


def run_import(identifier):
    try:
        with storage.connect(True) as db:
            db.execute("UPDATE review_imports SET status='running' WHERE id=?", (identifier,))
            row = db.execute('SELECT extension,upload FROM review_imports WHERE id=?', (identifier,)).fetchone()
        import_file(identifier, *row)
    except Exception as error:
        if isinstance(error, HTTPException):
            detail = error.detail
        else:
            logging.getLogger(__name__).exception('Review result import failed: %s', identifier)
            detail = '导入失败，请检查文件后重试'
        with storage.connect(True) as db:
            db.execute("UPDATE review_imports SET status='failed',error=?,upload=NULL WHERE id=?", (detail, identifier))


def import_file(job_id, extension, raw):
    result, attachments = unpack(extension, raw)
    batch = result.batch
    hashes = {path: digest(data) for path, data in attachments.items()}
    with storage.connect() as db:
        job = db.execute('SELECT status FROM review_batches WHERE id=?', (batch,)).fetchone()
        if not job or job['status'] not in ('ready', 'expired', 'downloaded'):
            fail('无效或未完成的导出批次')
        for op in result.suggestions:
            validate_scope(db, batch, op)
        threshold = float(storage.settings(db)['detection_threshold'])
    added = recorded = 0
    if sum(attachment_pixels(path, raw) for path, raw in attachments.items()) > 96_000_000:
        fail('附件总像素过多，请分次导入', 413)
    with tempfile.TemporaryDirectory(dir=storage.DATA) as temp:
        prepared = {}
        detections = {}
        for path, raw in attachments.items():
            key = hashes[path]
            if key in detections:
                continue
            with storage.connect() as db:
                if db.execute('SELECT 1 FROM review_detections WHERE attachment=? AND model=? AND threshold=?',
                              (key, MODEL_VERSION, threshold)).fetchone():
                    continue
                existing = db.execute('SELECT jpeg FROM review_attachments WHERE digest=?', (key,)).fetchone()
            if existing:
                jpeg = existing[0]
            else:
                jpeg, width, height = prepare_attachment(raw)
                staging = Path(temp) / key
                staging.write_bytes(jpeg)
                prepared[key] = staging, width, height
            detections[key] = detect_attachment(jpeg, threshold)
        with storage.connect(True) as db:
            for key, (staging, width, height) in prepared.items():
                db.execute(
                    'INSERT OR IGNORE INTO review_attachments VALUES(?,?,?,?)',
                    (key, staging.read_bytes(), width, height),
                )
            db.executemany('INSERT OR IGNORE INTO review_detections(attachment,model,threshold,detections) VALUES(?,?,?,?)',
                           ((key, MODEL_VERSION, threshold, faces) for key, faces in detections.items()))
            for op in result.suggestions:
                payload = op.model_dump(mode='json')
                if op.confidence is None:
                    payload.pop('confidence')
                if isinstance(op, CreatePerson):
                    if not op.name_ja:
                        payload.pop('name_ja')
                    groups = {}
                    for group in op.new_groups:
                        label = group if isinstance(group, str) else group.name
                        localized = None if isinstance(group, str) else group.name_ja
                        if localized and groups.get(label) not in (None, localized):
                            fail('同一新分组包含不同的日语名')
                        groups[label] = localized or groups.get(label)
                    payload['new_groups'] = [dict(name=label, name_ja=value) if value else label for label, value in sorted(groups.items())]
                    payload['group_ids'] = sorted(set(op.group_ids))
                    payload['accounts'] = [dict(platform=platform, username=username) for platform, username in
                                           sorted({(account.platform, account.username) for account in op.accounts})]
                    for field in ('group_ids', 'new_groups', 'accounts'):
                        if not payload[field]:
                            del payload[field]
                key = None
                detection_id = None
                identity = {k: v for k, v in payload.items() if k not in ('id', 'reason', 'confidence')}
                if isinstance(op, AddReference) and isinstance(op.source, ExternalReference):
                    key = hashes[op.source.attachment]
                    width, height, detection_id = db.execute(
                        'SELECT width,height,id FROM review_attachments JOIN review_detections ON attachment=digest WHERE digest=? AND model=? AND threshold=?', (key, MODEL_VERSION, threshold)
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
                    note = isinstance(op, ReviewOutcome)
                    if note and db.execute("""SELECT 1 FROM review_suggestions WHERE batch=? AND image_id=?
                        AND status IN ('recorded','acknowledged','accepted') AND json_extract(payload,'$.kind')='review_outcome'""",
                        (batch, op.image_id)).fetchone():
                        fail(f'本批次的图片 #{op.image_id} 已有审核结论', 409)
                    identifier = db.execute(
                        '''INSERT INTO review_suggestions(batch,key,image_id,payload,fingerprint,attachment,detection_id,status)
                        VALUES(?,?,?,?,?,?,?,?)''',
                        (batch, op.id, op.image_id, encode(payload), fingerprint, key, detection_id, 'recorded' if note else 'pending'),
                    ).lastrowid
                    if note:
                        recorded += 1
                    else:
                        added += 1
                db.execute('INSERT INTO review_result_keys VALUES(?,?,?,?)', (batch, op.id, content, identifier))
            db.execute("UPDATE review_imports SET status='done',added=?,recorded=?,duplicates=?,upload=NULL WHERE id=?",
                       (added, recorded, len(result.suggestions) - added - recorded, job_id))


def temporary_person(db, batch, key):
    return db.execute(
        "SELECT created_person,status,json_extract(payload,'$.name') name FROM review_suggestions WHERE batch=? AND json_extract(payload,'$.kind')='create_person' AND json_extract(payload,'$.person_id')=?",
        (batch, key),
    ).fetchone()


def roster_person(db, batch, key):
    row = db.execute('SELECT person_id FROM review_roster WHERE batch=? AND exported_id=?', (batch, key)).fetchone()
    return row[0] if row else None


def resolve_person(db, batch, key):
    if key is None:
        return None
    if isinstance(key, str):
        row = temporary_person(db, batch, key)
        if not row or row['status'] != 'accepted' or not row['created_person']:
            fail('请先单独接受新建人物建议，或检查人物是否已删除', 409)
        return row['created_person']
    person = roster_person(db, batch, key)
    if person is None:
        fail('目标人物已不存在', 409)
    return person


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
    face_token: str | None = None
    reference_ids: list[int]
    attachment: AttachmentPreview | None
    member_ids: list[int]
    scope_token: str | None


class QueuePage(BaseModel):
    items: list[QueueItem]
    total: int
    total_images: int
    page: int
    page_count: int
    page_size: int


def name(db, key):
    if key is None:
        return '未知人物'
    row = db.execute('SELECT name FROM people WHERE id=?', (key,)).fetchone()
    return f'{row[0]} (#{key})' if row else f'已删除人物 #{key}'


def snapshot_face(db, image, face_id):
    old = next((item for item in image['faces'] if item['id'] == face_id), None)
    if not old:
        return None, None
    face = db.execute('''SELECT f.* FROM faces f JOIN review_face_identity ON face_id=f.id
        WHERE f.id=? AND image_id=? AND token=?''', (face_id, image['id'], old['token'])).fetchone()
    return old, face


SOURCE_FIELDS = {'author': '发布账号', 'author_name': '发布者名称', 'published_at': '发布时间', 'url': '链接', 'post_text': '正文'}
OUTCOMES = {'no_change': '无需修改', 'no_faces': '确认无人脸', 'needs_human': '证据不足，请人工复核'}


def source_target(db, image, post_id):
    sources = [source for source in image.get('sources', []) if source['id'] == post_id]
    if not sources:
        return None, None
    old = sources[0]
    current = db.execute('''SELECT p.* FROM posts p WHERE p.id=? AND p.platform=? AND p.post_key=? AND EXISTS(
        SELECT 1 FROM sources s JOIN images i ON i.id=s.image_id WHERE s.post_id=p.id AND i.hidden=0 AND i.group_id=?
        AND i.id IN (SELECT value FROM json_each(?)))''', (post_id, old['platform'], old['post_key'], image['group_id'],
                                                          encode([source['image_id'] for source in sources]))).fetchone()
    return old, current


def account_label(account):
    return f"{account['platform']} @{account['username']}"


def queue_item(db, row):
    payload = json.loads(row['payload'])
    image = json.loads(row['snapshot'])
    person = payload.get('person_id')
    batch = row['batch']
    if isinstance(person, str):
        temporary = temporary_person(db, batch, person)
        target = f"{temporary['name']} ({person})" if temporary else person
        person = temporary['created_person'] if temporary else None
    elif isinstance(person, int):
        exported_id = person
        person = roster_person(db, batch, exported_id)
        target = name(db, person) if person is not None else f'已删除人物 #{exported_id}'
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
    old, face = snapshot_face(db, image, face_id)
    box = json.loads(face['box']) if face else old['box'] if old else payload.get('box')
    attachment = None
    if row['attachment']:
        data = db.execute(
            'SELECT width,height,detections FROM review_detections JOIN review_attachments ON digest=attachment WHERE id=?', (row['detection_id'],)
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
        if face_id and not face:
            current += ' · 原人脸不存在'
    elif kind == 'create_person':
        current, proposed = ('已创建' if person else '未创建'), payload['name']
        if payload.get('name_ja'):
            proposed += ' · 日语名：' + payload['name_ja']
        if payload.get('accounts'):
            proposed += ' · 账号：' + '、'.join(map(account_label, payload['accounts']))
        if ids := payload.get('group_ids'):
            groups = roster_groups(db, batch, ids)
            labels = []
            for identifier in ids:
                group = groups[identifier]
                label = group['name'] if row['status'] != 'pending' else group['current_name'] or f"{group['name']}（已删除）"
                labels.append(f'{label} (#{identifier})')
            proposed += ' · 加入分组：' + '、'.join(labels)
        if payload.get('new_groups'):
            proposed += ' · 新建或复用分组：' + '、'.join(group if isinstance(group, str) else
                f"{group['name']}（日语名：{group['name_ja']}）" for group in payload['new_groups'])
    elif kind in ('set_group_name_ja', 'add_person_group'):
        group_id = payload['group_id']
        group = roster_groups(db, batch, [group_id])[group_id]
        label = f"{group['current_name'] or group['name']} (#{group_id})"
        if kind == 'set_group_name_ja':
            current = f"{label} · {group['name_ja'] or '未填写日语名'}" if group['group_id'] else f'{label} · 已删除'
            proposed = f"{label} · 日语名：{payload['name_ja']}"
        else:
            member = db.execute('SELECT 1 FROM person_groups WHERE person_id=? AND group_id=?', (person, group['group_id'])).fetchone()
            current = f"{target} · {'已加入' if member else '未加入'}{label}" if group['group_id'] else f'{label} · 已删除'
            proposed = f'{target} · 加入分组：{label}'
    elif kind == 'set_person_name_ja':
        entry = db.execute('SELECT name_ja FROM people WHERE id=?', (person,)).fetchone()
        current = f"{target} · {entry[0] or '未填写日语名'}" if entry else target
        proposed = f"{target} · 日语名：{payload['name_ja']}"
    elif kind == 'add_person_account':
        account = payload['account']
        exists = db.execute('SELECT 1 FROM accounts WHERE person_id=? AND platform=? AND username=?',
                            (person, account['platform'], account['username'])).fetchone()
        current = f"{target} · {'已关联' if exists else '未关联'} {account_label(account)}"
        proposed = f'{target} · 关联账号：{account_label(account)}'
    elif kind == 'correct_source':
        field = payload['field']
        _, post = source_target(db, image, payload['post_id'])
        label = f"帖子 #{payload['post_id']} · {SOURCE_FIELDS[field]}"
        current = f"{label}：{post[field] or '未填写'}" if post else '来源已移除'
        proposed = f"{label}：{payload['value'] or '清空'}（所有引用此帖的图片共用）"
    elif kind == 'review_outcome':
        current, proposed = '仅记录本批审核结论，不修改图库', OUTCOMES[payload['outcome']]
    elif kind == 'add_face':
        current, proposed = '未标注此框', f'补画人脸 · {target}'
    elif kind == 'recycle' and row['status'] == 'accepted':
        current, proposed = '已执行整组回收', f'整组 {len(members)} 张移入回收站'
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
        face_token=old['token'] if face else None,
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
    decision: Literal['accept', 'reject', 'acknowledge']
    items: list[Choice] = Field(min_length=1, max_length=100)


class Failure(BaseModel):
    id: int
    detail: str


class Decisions(BaseModel):
    applied: list[int]
    failures: list[Failure]


def apply(db, row, choice, created_files):
    from .main import FaceEdit, PersonInput, write_face_edit, write_person

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
        old, face = snapshot_face(db, snap, face_id)
        if not face or json.loads(face['box']) != old['box']:
            fail('目标人脸已变化', 409)
    if kind == 'create_person':
        ids = payload.get('group_ids', [])
        groups = roster_groups(db, batch, ids) if ids else {}
        if any(identifier not in groups or groups[identifier]['group_id'] is None for identifier in ids):
            fail('指定分组已不存在，请重新导出', 409)
        person = write_person(db, PersonInput(name=payload['name'], name_ja=payload.get('name_ja'), accounts=payload.get('accounts', []),
                                             group_ids=[groups[identifier]['group_id'] for identifier in ids], new_groups=payload.get('new_groups', [])))
        db.execute('UPDATE review_suggestions SET created_person=? WHERE id=?', (person, choice.id))
        return
    person = resolve_person(db, batch, payload.get('person_id'))
    if kind in ('set_group_name_ja', 'add_person_group'):
        group = roster_groups(db, batch, [payload['group_id']])[payload['group_id']]
        if group['group_id'] is None:
            fail('指定分组已不存在，请重新导出', 409)
        if kind == 'add_person_group':
            db.execute('INSERT OR IGNORE INTO person_groups(person_id,group_id) VALUES(?,?)', (person, group['group_id']))
        elif not db.execute('UPDATE groups SET name_ja=? WHERE id=? AND (name_ja IS NULL OR name_ja=?)',
                            (payload['name_ja'], group['group_id'], payload['name_ja'])).rowcount:
            fail('分组已有其他日语名，不会覆盖', 409)
    elif kind == 'set_person_name_ja':
        if not db.execute('UPDATE people SET name_ja=? WHERE id=? AND (name_ja IS NULL OR name_ja=?)',
                          (payload['name_ja'], person, payload['name_ja'])).rowcount:
            fail('人物已有其他日语名，不会覆盖', 409)
    elif kind == 'add_person_account':
        account = payload['account']
        db.execute('INSERT OR IGNORE INTO accounts(person_id,platform,username) VALUES(?,?,?)',
                   (person, account['platform'], account['username']))
    elif kind == 'correct_source':
        old, post = source_target(db, snap, payload['post_id'])
        field = payload['field']
        if not post or field not in SOURCE_FIELDS or post[field] not in (old[field], payload['value']):
            fail('来源已移除或字段已更改，请重新导出', 409)
        db.execute(f'UPDATE posts SET {field}=? WHERE id=?', (payload['value'], post['id']))
    elif kind in ('match', 'remove_face'):
        ignored = kind == 'remove_face'
        if face['locked'] and face['ignored'] == ignored and face['person_id'] == person:
            return
        if (face['locked'] != old['locked'] or face['ignored'] != old['ignored']
                or (old['locked'] and face['person_id'] != resolve_person(db, batch, old['person_id']))):
            fail('人脸的人工审核结果已更改，不会覆盖，请重新导出', 409)
        write_face_edit(db, face_id, FaceEdit(person_id=person, ignored=ignored, revision=face['revision']))
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
        data = db.execute('SELECT jpeg,detections,model FROM review_detections JOIN review_attachments ON digest=attachment WHERE id=?', (row['detection_id'],)).fetchone()
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


def queue_pages(image_counts, page_size):
    images = []
    records = 0
    for image_id, count in image_counts:
        if images and records + count > page_size:
            yield images, records
            images = []
            records = 0
        images.append(image_id)
        records += count
    if images:
        yield images, records


def install(app, admin):
    router = APIRouter(prefix=PREFIX, dependencies=[Depends(admin)])

    @router.post('/imports', response_model=ImportJob, status_code=202)
    def import_review(file: UploadFile = File(...)):
        extension = Path(file.filename or '').suffix.lower()
        if extension not in ('.json', '.zip'):
            fail('请选择 JSON 或 ZIP 文件')
        limit = MAX_JSON if extension == '.json' else MAX_BYTES
        raw = file.file.read(limit + 1)
        if len(raw) > limit:
            fail('结果 JSON 过大' if extension == '.json' else '结果文件超过 20 MiB', 413)
        job = ImportJob(id=secrets.token_hex(16), status='queued')
        with storage.connect(True) as db:
            db.execute('INSERT INTO review_imports(id,status,extension,upload) VALUES(?,?,?,?)',
                       (job.id, job.status, extension, raw))
        review_packages.executor.submit(run_import, job.id)
        return job

    @router.get('/imports/{identifier}', response_model=ImportJob)
    def import_status(identifier: str):
        with storage.connect() as db:
            row = db.execute('SELECT id,status,added,recorded,duplicates,error FROM review_imports WHERE id=?', (identifier,)).fetchone()
            if not row:
                fail('导入任务不存在', 404)
            return dict(row)

    @router.get('/suggestions', response_model=QueuePage)
    def review_queue(
        status: Literal['review', 'pending', 'accepted', 'rejected', 'acknowledged'] = 'review',
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100, description='每页目标记录数；单张图片的记录不拆分'),
    ):
        with storage.connect() as db:
            db.execute('BEGIN')
            condition, params = ("status IN ('pending','recorded')", ()) if status == 'review' else ('status=?', (status,))
            image_counts = db.execute(
                f'SELECT image_id,count(*) FROM review_suggestions WHERE {condition} GROUP BY image_id ORDER BY image_id',
                params,
            )
            total = total_images = 0
            page_count = 1
            selected_images = []
            for page_count, (images, records) in enumerate(queue_pages(image_counts, page_size), 1):
                total += records
                total_images += len(images)
                if page_count <= page:
                    selected_images = images
            rows = db.execute(
                'SELECT s.*,snap.snapshot '
                + JOIN_SNAPSHOT
                + f' WHERE {condition} AND s.image_id IN (SELECT value FROM json_each(?)) ORDER BY s.image_id,s.id',
                (*params, encode(selected_images)),
            )
            return QueuePage(items=[queue_item(db, row) for row in rows], total=total, total_images=total_images,
                             page=min(page, page_count), page_count=page_count, page_size=page_size)

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
                    if body.decision == 'acknowledge':
                        if not row or row['status'] != 'recorded' or json.loads(row['payload'])['kind'] != 'review_outcome':
                            fail('只能确认尚未确认的审核结论', 409)
                        status = 'acknowledged'
                    elif not row or row['status'] != 'pending':
                        fail('建议不存在或已处理', 409)
                    elif body.decision == 'accept':
                        apply(db, row, choice, created_files)
                        status = 'accepted'
                    else:
                        status = 'rejected'
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
