import base64
import ipaddress
import math
import mimetypes
import hashlib
import hmac
import json
import os
import secrets
import re
import resource
import threading
import time
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Request,
    Response,
    UploadFile,
    File,
    Query,
)
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator, model_validator
from .open_graph import render_open_graph
from . import game_boards, game_rooms, list_queries, photo_draw, publisher_avatars, publishers, review_packages, social
from .review_format import fits
from .group_index import REVIEW_FLAGS
from .db import DATA, IMPORT, connect, init, settings, schedule_rematch, cleanup_deleted_files, startup_phase
from .security import download_url, cookie_bytes, save_cookie
from .feed_scope import ImportScope, effective_scope
from .importer import validate_url, safe_directory
from .vision import MODEL_VERSION, Vision, candidates, models_ready, validate_embedding
from .db import schedule_detection, ACTIVE_REFERENCE
from .task_queue import NEXT_RANK, Subtype, Tier
from .trash import require_active, require_active_face
from . import duplicate_review
from .representatives import complete_source_sql, representative_sql, require_representative, require_representative_face
from .archives import stream_zip
from . import media_cache
from . import cache_status
from .hashtags import Hashtags


@asynccontextmanager
async def lifespan(app):
    media_wait_seconds()
    init()
    with startup_phase('pending file deletions'):
        cleanup_deleted_files()
    feedback_limits()
    with review_packages.service():
        async with game_rooms.service():
            yield


app = FastAPI(title="Gallery Faces", version="1.0.0", lifespan=lifespan)
from .request_guard import RequestGuard
app.add_middleware(RequestGuard)


@app.exception_handler(Exception)
async def uncaught_error(request: Request, error: Exception):
    return PlainTextResponse("Internal Server Error", status_code=500, headers={
        "Cache-Control": "no-store", "Cloudflare-CDN-Cache-Control": "no-store",
    })


def fail(message, code=400):
    raise HTTPException(code, message)


def media_wait_seconds():
    value = os.getenv('MEDIA_CACHE_WAIT_SECONDS') or '10'
    if not value.isascii() or not value.isdecimal() or int(value) > threading.TIMEOUT_MAX // 3:
        raise ValueError('MEDIA_CACHE_WAIT_SECONDS must be a non-negative integer within the supported timeout range')
    return int(value)


class MediaRead(ExitStack):
    def __init__(self, *, background=False):
        super().__init__()
        self.wait_seconds = media_wait_seconds()
        self.deadline = None if background else time.monotonic() + self.wait_seconds

    def pin(self, row, variant, *, recover_missing=True, recovery=None):
        try:
            timeout = None if self.deadline is None else max(0, self.deadline - time.monotonic())
            return self.enter_context(media_cache.asset(row, variant, timeout=timeout,
                                                       descriptor=True, recover_missing=recover_missing, recovery=recovery))
        except FileNotFoundError:
            fail('图片不存在', 404)
        except media_cache.Unavailable as error:
            raise HTTPException(503, '图片暂不可用，请稍后重试', headers={'Retry-After': str(error.retry_after)}) from None


def media_read():
    with MediaRead() as reads:
        yield reads


MediaReads = Annotated[MediaRead, Depends(media_read, scope='request')]


def admin(request: Request):
    token = request.cookies.get("session", "")
    with connect() as db:
        session = db.execute(
            "SELECT 1 FROM sessions WHERE token_hash=? AND expires>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
    if not session:
        fail("请先登录管理员", 401)
    if (
        request.method not in ("GET", "HEAD")
        and request.headers.get("x-gallery-request") != "1"
    ):
        fail("缺少请求校验", 403)


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from starlette.datastructures import MutableHeaders
        async def forward(message):
            if message['type'] == 'http.response.start':
                headers = MutableHeaders(scope=message)
                headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'})
                path = scope['path']
                if message['status'] >= 400:
                    headers.update({'Cache-Control': 'no-store', 'Cloudflare-CDN-Cache-Control': 'no-store'})
                elif path.startswith('/assets/'):
                    headers['Cache-Control'] = IMMUTABLE
                elif path.startswith(('/api/v1/media/by-hash/', '/api/v1/publisher-avatars/by-hash/')):
                    headers.setdefault('Cache-Control', 'no-store')
                elif path.startswith('/api/'):
                    headers['Cache-Control'] = 'no-store'
            await send(message)
        await self.app(scope, receive, forward)


app.add_middleware(SecurityHeaders)


class Login(BaseModel):
    password: str = Field(max_length=1024)


attempts = {}
login_lock = threading.Lock()


@app.post("/api/v1/login")
def login(body: Login, request: Request, response: Response):
    with login_lock:
        return login_locked(body, request, response)


def login_locked(body, request, response):
    from .request_guard import client_key
    key = client_key(request.client.host)
    now = time.time()
    for old in list(attempts):
        if not attempts[old] or attempts[old][-1] <= now - 300:
            del attempts[old]
    if key not in attempts and len(attempts) >= 10000:
        fail("尝试过于频繁", 429)
    attempts[key] = [t for t in attempts.get(key, []) if t > now - 300]
    if len(attempts[key]) >= 10:
        fail("尝试过于频繁，请五分钟后重试", 429)
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        fail("尚未配置 ADMIN_PASSWORD", 503)
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        attempts[key].append(now)
        fail("密码错误", 401)
    token = secrets.token_urlsafe(32)
    with connect(True) as db:
        db.execute("DELETE FROM sessions WHERE expires<?", (now,))
        db.execute(
            "INSERT INTO sessions VALUES(?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), now + 86400),
        )
    response.set_cookie(
        "session",
        token,
        httponly=True,
        samesite="strict",
        secure=os.getenv("COOKIE_SECURE", "true") == "true",
        max_age=86400,
    )
    return {"ok": True}


@app.get("/api/v1/session")
def session(_: None = Depends(admin)):
    return {"admin": True}


@app.post("/api/v1/logout")
def logout(request: Request, response: Response, _: None = Depends(admin)):
    with connect(True) as db:
        db.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (hashlib.sha256(request.cookies.get("session", "").encode()).hexdigest(),),
        )
    response.delete_cookie("session")
    return {"ok": True}


class Account(BaseModel):
    platform: Literal["instagram", "x"]
    username: str = Field(min_length=1, max_length=100, pattern=r"^[\w.]+$")


class UploadedReference(BaseModel):
    token: str = Field(pattern="^[a-f0-9]{32}$")
    index: int = Field(ge=0)


class GroupName(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    name_ja: str | None = Field(default=None, max_length=100)


class PersonInput(BaseModel):
    name_ja: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    group_ids: list[int] = []
    new_groups: list[str | GroupName] = []
    accounts: list[Account] = []
    removed_reference_ids: list[int] = []
    uploaded_references: list[UploadedReference] = []


def write_person(db, body, person_id=None):
    name = body.name.strip()
    if not name:
        fail("姓名不能为空")
    if person_id:
        if not db.execute(
            "SELECT 1 FROM people WHERE id=?", (person_id,)
        ).fetchone():
            fail("人物不存在", 404)
        db.execute("UPDATE people SET name=? WHERE id=?", (name, person_id))
    else:
        person_id = db.execute(
            "INSERT INTO people(name) VALUES(?)", (name,)
        ).lastrowid
    if 'name_ja' in body.model_fields_set:
        db.execute('UPDATE people SET name_ja=? WHERE id=?', ((body.name_ja or '').strip() or None, person_id))
    ids = set(body.group_ids)
    for group in body.new_groups:
        value = (group if isinstance(group, str) else group.name).strip()
        name_ja = None if isinstance(group, str) else (group.name_ja or '').strip() or None
        if not value or len(value) > 100:
            fail("分组名称不能为空且不能超过 100 字")
        db.execute("INSERT OR IGNORE INTO groups(name,name_ja) VALUES(?,?)", (value, name_ja))
        ids.add(
            db.execute("SELECT id FROM groups WHERE name=?", (value,)).fetchone()[0]
        )
    if any(
        not db.execute("SELECT 1 FROM groups WHERE id=?", (g,)).fetchone()
        for g in ids
    ):
        fail("分组不存在")
    db.execute("DELETE FROM person_groups WHERE person_id=?", (person_id,))
    db.executemany(
        "INSERT INTO person_groups VALUES(?,?)", [(person_id, g) for g in ids]
    )
    db.execute("DELETE FROM accounts WHERE person_id=?", (person_id,))
    db.executemany(
        "INSERT OR IGNORE INTO accounts(person_id,platform,username) VALUES(?,?,?)",
        [(person_id, a.platform, a.username) for a in body.accounts],
    )
    reference_changed = False
    for reference_id in set(body.removed_reference_ids):
        reference = db.execute(
            "SELECT person_id FROM reference_images WHERE id=?", (reference_id,)
        ).fetchone()
        if reference and reference["person_id"] != person_id:
            fail("参考图不属于该人物", 409)
        if reference:
            was_active = db.execute(
                f"SELECT 1 FROM reference_images WHERE id=? AND {ACTIVE_REFERENCE}",
                (reference_id,),
            ).fetchone()
            db.execute("DELETE FROM reference_images WHERE id=?", (reference_id,))
            reference_changed = reference_changed or bool(was_active)
    for uploaded in body.uploaded_references:
        write_uploaded_reference(db, person_id, uploaded)
        reference_changed = True
    if reference_changed:
        schedule_rematch(db)
    return person_id


def save_person(body, person_id=None):
    with connect(True) as db:
        person_id = write_person(db, body, person_id)
    for uploaded in body.uploaded_references:
        (DATA / "references" / f"{uploaded.token}.json").unlink(missing_ok=True)
    return {"id": person_id}


@app.post("/api/v1/admin/people")
def create_person(body: PersonInput, _: None = Depends(admin)):
    return save_person(body)


@app.put("/api/v1/admin/people/{person_id}")
def update_person(person_id: int, body: PersonInput, _: None = Depends(admin)):
    return save_person(body, person_id)


@app.delete("/api/v1/admin/people/{person_id}")
def delete_person(person_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        if not db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
            fail("人物不存在", 404)
        # A deleted identity must not survive in candidates or undo snapshots,
        # even if SQLite later reuses its numeric ID for another person.
        db.execute(
            "DELETE FROM review_history WHERE face_id IN (SELECT id FROM faces WHERE person_id=?) OR json_extract(before_json,'$.person_id')=?",
            (person_id, person_id),
        )
        db.execute(
            "UPDATE faces SET person_id=NULL,locked=0,ignored=0,revision=revision+1 WHERE person_id=?",
            (person_id,),
        )
        for face in db.execute("SELECT id,candidates FROM faces").fetchall():
            candidates = json.loads(face["candidates"])
            remaining = [c for c in candidates if c["person_id"] != person_id]
            if remaining != candidates:
                db.execute(
                    "UPDATE faces SET candidates=? WHERE id=?",
                    (json.dumps(remaining), face["id"]),
                )
        db.execute("DELETE FROM people WHERE id=?", (person_id,))
        schedule_rematch(db)
    return {"ok": True}


@app.get("/api/v1/people")
def people():
    with connect() as db:
        db.execute('BEGIN')
        result = {row['id']: dict(row, groups=[], accounts=[], reference_count=0, avatar_reference_id=None)
                  for row in db.execute('''SELECT p.*, (SELECT count(*) FROM public_group_people WHERE person_id=p.id) AS photo_group_count
                                           FROM people p ORDER BY p.id''')}
        for row in db.execute('SELECT pg.person_id,g.* FROM person_groups pg JOIN groups g ON g.id=pg.group_id ORDER BY pg.person_id,g.id'):
            group = dict(row)
            result[group.pop('person_id')]['groups'].append(group)
        for person_id, platform, username in db.execute('SELECT person_id,platform,username FROM accounts ORDER BY person_id,platform,username'):
            result[person_id]['accounts'].append(dict(platform=platform, username=username))
        for person_id, count, avatar in db.execute(f'SELECT person_id,count(*),min(id) FROM reference_images WHERE {ACTIVE_REFERENCE} GROUP BY person_id'):
            result[person_id].update(reference_count=count, avatar_reference_id=avatar)
        return list(result.values())


class PublisherCandidate(BaseModel):
    platform: Literal["x", "instagram"]
    username: str
    label: str


@app.get("/api/v1/publisher-candidates", response_model=list[PublisherCandidate])
def publisher_candidates() -> list[PublisherCandidate]:
    """Return account names found in posts that are not linked to a person."""
    with connect() as db:
        rows = db.execute(
            """
            WITH candidates AS (
                SELECT COUNT(*) AS post_count,
                       COALESCE(MAX(p.id) FILTER (WHERE TRIM(p.author_name) <> ''), MAX(p.id)) AS post_id
                FROM posts p
                WHERE p.platform IN ('x', 'instagram')
                  AND p.author IS NOT NULL
                  AND TRIM(p.author) <> ''
                GROUP BY p.platform, lower(p.author)
            )
            SELECT p.platform, p.author AS username, COALESCE(NULLIF(TRIM(p.author_name), ''), p.author) AS label
            FROM candidates JOIN posts p ON p.id=candidates.post_id
            WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.platform=p.platform AND lower(a.username)=lower(p.author))
            ORDER BY candidates.post_count DESC, lower(label), lower(username), p.platform
            """
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/v1/groups")
def groups():
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT g.*,coalesce(pg.members,0) AS members FROM groups g LEFT JOIN "
                "(SELECT group_id,count(*) AS members FROM person_groups GROUP BY group_id) pg ON pg.group_id=g.id ORDER BY g.id"
            )
        ]


class GroupInput(GroupName):
    person_ids: list[int] = []


@app.put("/api/v1/admin/groups/{group_id}")
def group_update(group_id: int, body: GroupInput, _: None = Depends(admin)):
    with connect(True) as db:
        name = body.name.strip()
        if not name:
            fail("名称不能为空")
        if db.execute(
            "SELECT 1 FROM groups WHERE name=? AND id<>?", (name, group_id)
        ).fetchone():
            fail("分组名称已存在")
        if not db.execute("SELECT 1 FROM groups WHERE id=?", (group_id,)).fetchone():
            fail("分组不存在", 404)
        if any(
            not db.execute("SELECT 1 FROM people WHERE id=?", (p,)).fetchone()
            for p in body.person_ids
        ):
            fail("人物不存在")
        db.execute("UPDATE groups SET name=? WHERE id=?", (name, group_id))
        if 'name_ja' in body.model_fields_set:
            db.execute('UPDATE groups SET name_ja=? WHERE id=?', ((body.name_ja or '').strip() or None, group_id))
        db.execute("DELETE FROM person_groups WHERE group_id=?", (group_id,))
        db.executemany(
            "INSERT INTO person_groups VALUES(?,?)",
            [(p, group_id) for p in set(body.person_ids)],
        )
    return {"ok": True}


@app.delete("/api/v1/admin/groups/{group_id}")
def group_delete(group_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        db.execute("DELETE FROM groups WHERE id=?", (group_id,))
    return {"ok": True}


class ReferenceInput(BaseModel):
    face_id: int


@app.post("/api/v1/admin/people/{person_id}/references")
def reference_add(person_id: int, body: ReferenceInput, _: None = Depends(admin)):
    with connect(True) as db:
        require_active_face(db, body.face_id)
        face = db.execute(
            "SELECT * FROM faces WHERE id=? AND ignored=0", (body.face_id,)
        ).fetchone()
        if not face or not face["embedding"]:
            fail("该人脸没有有效特征")
        if not db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
            fail("人物不存在", 404)
        require_embedding(face["embedding"], face["model_version"])
        if db.execute(
            "SELECT 1 FROM reference_images WHERE person_id=? AND face_id=?",
            (person_id, body.face_id),
        ).fetchone():
            return {"ok": True}
        db.execute(
            "INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(?,?,?,?,?)",
            (
                person_id,
                face["image_id"],
                face["id"],
                face["embedding"],
                face["model_version"],
            ),
        )
        schedule_rematch(db)
    return {"ok": True}


@app.post("/api/v1/admin/reference-upload")
def reference_upload(file: UploadFile = File(...), _: None = Depends(admin)):
    content = file.file.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        fail("图片不能超过 20MB")
    from PIL import Image, ImageOps
    import io

    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content)))
        image.load()
    except Exception:
        fail("无法读取图片")
    token = secrets.token_hex(16)
    path = DATA / "references" / f"{token}.jpg"
    image.convert("RGB").save(path)
    try:
        with connect() as db:
            detection_threshold = float(settings(db)["detection_threshold"])
        detected = Vision().detect(path, mode="highres", threshold=detection_threshold)
    except ValueError as error:
        path.unlink()
        fail(str(error))
    if not detected:
        path.unlink()
        fail("未检测到人脸，请换一张参考图")
    # Staged uploads have no effect until an explicitly selected face is saved.
    (DATA / "references" / f"{token}.json").write_text(
        json.dumps(
            {"model_version": MODEL_VERSION, "faces": [{"box": b, "embedding": base64.b64encode(e).decode()} for b, e in detected]}
        )
    )
    return {
        "token": token,
        "width": image.width,
        "height": image.height,
        "faces": [{"index": i, "box": b} for i, (b, e) in enumerate(detected)],
    }


def write_uploaded_reference(db, person_id, body):
    path = DATA / "references" / f"{body.token}.json"
    if not path.exists():
        fail("上传已失效，请重新上传", 404)
    staged = json.loads(path.read_text())
    if not isinstance(staged, dict) or staged.get('model_version') != MODEL_VERSION:
        fail("上传的特征版本不兼容，请重新上传")
    faces = staged['faces']
    if body.index < 0 or body.index >= len(faces):
        fail("请选择有效人脸")
    require_embedding(base64.b64decode(faces[body.index]['embedding']), staged['model_version'])
    db.execute(
        "INSERT INTO reference_images(person_id,filename,box,embedding,model_version) VALUES(?,?,?,?,?)",
        (person_id, body.token + ".jpg", json.dumps(faces[body.index]["box"]),
         base64.b64decode(faces[body.index]["embedding"]), MODEL_VERSION),
    )


@app.post("/api/v1/admin/people/{person_id}/uploaded-reference")
def reference_commit(person_id: int, body: UploadedReference, _: None = Depends(admin)):
    with connect(True) as db:
        if not db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
            fail("人物不存在", 404)
        write_uploaded_reference(db, person_id, body)
        schedule_rematch(db)
    (DATA / "references" / f"{body.token}.json").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/v1/admin/people/{person_id}/references")
def references(person_id: int, _: None = Depends(admin)):
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                f"SELECT id,face_id,image_id,filename FROM reference_images WHERE person_id=? AND {ACTIVE_REFERENCE}",
                (person_id,),
            )
        ]


@app.get("/api/v1/admin/faces/{face_id}/crop")
def face_crop(face_id: int, reads: MediaReads, _: None = Depends(admin), token: str | None = None):
    with connect() as db:
        face = db.execute(
            '''SELECT f.box,i.id FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=? AND i.hidden=0
               AND (? IS NULL OR EXISTS (SELECT 1 FROM review_face_identity WHERE face_id=f.id AND token=?))''',
            (face_id, token, token),
        ).fetchone()
    if not face:
        fail("人脸不存在", 404)
    return cropped_image(reads.pin(face, 'image'), json.loads(face["box"]))


def cropped_image(path, box):
    from PIL import Image
    import io

    if not path.is_file():
        fail("图片不存在", 404)
    x, y, w, h = box
    with Image.open(path) as image:
        left = max(0, min(image.width - 1, math.floor(x)))
        top = max(0, min(image.height - 1, math.floor(y)))
        right = max(left + 1, min(image.width, math.ceil(x + w)))
        bottom = max(top + 1, min(image.height, math.ceil(y + h)))
        crop = image.crop((left, top, right, bottom)).convert("RGB")
        crop.thumbnail((240, 240))
        output = io.BytesIO()
        crop.save(output, format="JPEG")
    return Response(output.getvalue(), media_type="image/jpeg")


@app.get("/api/v1/admin/references/{reference_id}/crop")
def reference_crop(reference_id: int, reads: MediaReads, _: None = Depends(admin)):
    with connect() as db:
        reference = db.execute(f"SELECT * FROM reference_images WHERE id=? AND {ACTIVE_REFERENCE}", (reference_id,)).fetchone()
    if not reference:
        fail("参考图不存在", 404)
    if reference["face_id"]:
        return face_crop(reference["face_id"], reads)
    if not reference["filename"]:
        fail("参考图不存在", 404)
    path = DATA / "references" / reference["filename"]
    if reference["box"]:
        box = json.loads(reference["box"])
    else:
        # Old uploads discarded the chosen box. Recover it using the saved
        # embedding, never by choosing the first face in a multi-person image.
        if reference["model_version"] != MODEL_VERSION or not path.is_file():
            fail("无法恢复参考人脸，请重新上传参考图", 404)
        try:
            with connect() as db:
                detection_threshold = float(settings(db)["detection_threshold"])
            faces = Vision().detect(path, mode="highres", threshold=detection_threshold)
            matches = candidates(reference["embedding"], [
                {"person_id": index, "embedding": embedding}
                for index, (_, embedding) in enumerate(faces)
            ])
        except ValueError:
            fail("无法恢复参考人脸，请检查模型或重新上传参考图", 404)
        if not matches or matches[0]["score"] < 0.99:
            fail("无法恢复参考人脸，请重新上传参考图", 404)
        box = faces[matches[0]["person_id"]][0]
        with connect(True) as db:
            db.execute("UPDATE reference_images SET box=? WHERE id=? AND box IS NULL", (json.dumps(box), reference_id))
    return cropped_image(path, box)


@app.get("/api/v1/admin/reference-media/{filename}")
def reference_media(filename: str, _: None = Depends(admin)):
    if Path(filename).name != filename or not filename.endswith(".jpg"):
        fail("无效文件", 404)
    path = DATA / "references" / filename
    if not path.is_file():
        fail("图片不存在", 404)
    return FileResponse(path)


@app.delete("/api/v1/admin/references/{reference_id}")
def reference_delete(reference_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        was_active = db.execute(
            f"SELECT 1 FROM reference_images WHERE id=? AND {ACTIVE_REFERENCE}",
            (reference_id,),
        ).fetchone()
        if db.execute(
            "DELETE FROM reference_images WHERE id=?", (reference_id,)
        ).rowcount and was_active:
            schedule_rematch(db)
    return {"ok": True}


def date_bounds(start, end):
    from .monitors import instant
    lower, upper = instant(start) if start else None, instant(end) if end else None
    if lower and upper and lower >= upper:
        fail("结束时间必须晚于开始时间")
    return lower, upper


def publisher_condition(publishers, post='p'):
    if len(publishers) == 1 and publishers[0][0] != 'person':
        return f'({post}.platform=? AND lower({post}.author)=lower(?))', publishers[0]
    rows, args = [], []
    accounts = [(platform, author) for platform, author in publishers if platform != 'person']
    if accounts:
        rows.append('VALUES ' + ','.join('(?,lower(?))' for _ in accounts))
        args.extend(value for account in accounts for value in account)
    person_ids = [int(author) for platform, author in publishers if platform == 'person']
    if person_ids:
        marks = ','.join('?' for _ in person_ids)
        rows.append(f'SELECT platform,lower(username) FROM accounts WHERE person_id IN ({marks})')
        args.extend(person_ids)
    return f'({post}.platform,lower({post}.author)) IN (' + ' UNION ALL '.join(rows) + ')', args


PeopleMatch = Literal["any", "all", "exact", "subset"]


def people_condition(image_id, people_ids, match: PeopleMatch):
    marks = ",".join("?" for _ in people_ids)
    faces = f"FROM faces f WHERE f.image_id={image_id} AND f.ignored=0"
    selected = f"f.person_id IN ({marks})"
    if match in ("all", "exact"):
        clause = f"(SELECT count(DISTINCT f.person_id) {faces} AND {selected})=?"
        args = [*people_ids, len(people_ids)]
    else:
        clause = f"EXISTS(SELECT 1 {faces} AND {selected})"
        args = list(people_ids)
    if match in ("subset", "exact"):
        clause += f" AND NOT EXISTS(SELECT 1 {faces} AND f.person_id NOT IN ({marks}))"
        args.extend(people_ids)
    return clause, args


def source_filter(publishers, start, end, post='p'):
    conditions, args = [], []
    if start:
        conditions.append(f'{post}.published_at>=?')
        args.append(start)
    if end:
        conditions.append(f'{post}.published_at<?')
        args.append(end)
    if publishers:
        clause, values = publisher_condition(publishers, post)
        conditions.append(clause)
        args.extend(values)
    return ' AND '.join(conditions), args


def list_edge(cursor, *, gallery=False):
    if not cursor:
        return ()
    try:
        if len(cursor) > 1024:
            raise ValueError()
        stamp, identifier = json.loads(base64.urlsafe_b64decode(cursor))
        if gallery:
            identifier = int(identifier)
        if not isinstance(stamp, str) or not isinstance(identifier, int) or not 0 < identifier <= 9223372036854775807:
            raise ValueError()
        return stamp, identifier
    except (TypeError, ValueError, OverflowError):
        fail("分页游标无效")


def visible_members(db, group_id):
    return db.execute(
        "SELECT i.* FROM images i WHERE group_id=? AND hidden=0 AND detection='done' AND EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=i.id AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL) ORDER BY file_size DESC,id",
        (group_id,),
    ).fetchall()


def gallery_labels(db, ids):
    marks = ','.join('?' for _ in ids)
    labels = {identifier: {} for identifier in ids}
    for face in db.execute(
        "SELECT f.image_id,p.id,p.name FROM people p JOIN faces f ON f.person_id=p.id "
        f"WHERE f.ignored=0 AND f.image_id IN ({marks}) "
        "ORDER BY f.image_id,json_extract(f.box,'$[0]') + json_extract(f.box,'$[2]') / 2.0,f.id", ids,
    ):
        labels[face['image_id']][face['id']] = dict(id=face['id'], name=face['name'])
    return {identifier: list(people.values()) for identifier, people in labels.items()}


def summary(row, image, labels, count):
    return dict(
        id=row["group_id"],
        image_id=image["id"],
        **media_urls(image),
        width=image["width"],
        height=image["height"],
        people=labels,
        source_count=count,
        matched_source={k: v for k, v in row.items() if k != "group_id"},
    )


def gallery_summaries(db, page):
    if not page:
        return []
    groups = [row['group_id'] for row in page]
    marks = ','.join('?' for _ in groups)
    images = {row['group_id']: row for row in db.execute(
        f"SELECT i.* FROM public_groups g CROSS JOIN images i ON i.id=g.representative "
        f"WHERE g.group_id IN ({marks})", groups,
    )}
    labels = gallery_labels(db, [image['id'] for image in images.values()])
    counts = dict(db.execute(
        f"SELECT i.group_id,count(DISTINCT s.post_id) FROM images i JOIN sources s ON s.image_id=i.id "
        f"WHERE i.group_id IN ({marks}) AND i.hidden=0 AND i.detection='done' AND {complete_source_sql('i')} "
        "GROUP BY i.group_id", groups,
    ))
    items = []
    for row in page:
        image = images[row['group_id']]
        items.append(summary(row, image, labels[image['id']], counts[row['group_id']]))
    return items


class GalleryPhoto(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    image_id: int
    width: int
    height: int
    image_url: str
    thumbnail_url: str
    download_url: str
    people: list[dict]
    source_count: int
    matched_source: dict


class GalleryPage(BaseModel):
    items: list[GalleryPhoto]
    next_cursor: str | None
    total: int | None


def source_record(row):
    source = dict(row)
    source['key'] = social.post_key(row)
    source.pop('embed_id')
    try:
        coauthors = json.loads(source.get("coauthors") or "[]")
    except (TypeError, ValueError):
        coauthors = []
    source["coauthors"] = coauthors if isinstance(coauthors, list) else []
    return source


FILTER_ID_LIMIT = 4096


def id_range(token, remaining):
    match = re.fullmatch(r'([0-9]{1,19})(?:-([0-9]{1,19}))?', token)
    if not match:
        raise ValueError()
    first = int(match[1])
    last = int(match[2] or match[1])
    if not 0 < first <= last <= 9223372036854775807 or last - first + 1 > remaining:
        raise ValueError()
    return range(first, last + 1)


def parse_people_publishers(people, publishers):
    try:
        ids = []
        for token in filter(None, people.split(',')):
            ids.extend(id_range(token, FILTER_ID_LIMIT - len(ids)))
    except ValueError:
        fail("人物编号无效，请重新选择人物")
    try:
        accounts = []
        person_count = 0
        for token in filter(None, publishers.split(',')):
            platform, author = token.split(':', 1)
            if platform == 'person':
                selected = id_range(author, FILTER_ID_LIMIT - person_count)
                person_count += len(selected)
                accounts.extend((platform, str(identifier)) for identifier in selected)
            elif platform in ('x', 'instagram') and author:
                accounts.append((platform, author))
            else:
                raise ValueError()
    except ValueError:
        fail("发布者格式无效，请重新选择发布者")
    return sorted(set(ids)), accounts


class PublicPost(BaseModel):
    id: int
    key: str
    platform: str
    url: str
    embed_id: str | None
    author: str
    author_name: str | None
    published_at: str


class PostPage(BaseModel):
    items: list[PublicPost]
    next_cursor: str | None


class PostPicture(BaseModel):
    id: int
    width: int
    height: int
    people: list[dict]
    image_url: str | None
    thumbnail_url: str


class PostDetail(BaseModel):
    key: str
    platform: str
    author: str
    author_name: str | None
    published_at: str
    url: str
    post_text: str | None
    coauthors: list[dict]
    images: list[PostPicture]


@app.get('/api/v1/publisher-avatars/by-hash/{digest}', response_class=Response,
         responses={200: {'content': {'image/jpeg': {}}}})
def publisher_avatar_image(digest: str):
    return Response(publisher_avatars.image_bytes(digest), media_type='image/jpeg', headers={'Cache-Control': IMMUTABLE})


class PublisherAvatar(BaseModel):
    image_url: str | None
    pending: bool


@app.get('/api/v1/publisher-avatars/{platform}/{username}', response_model=PublisherAvatar)
def publisher_avatar(platform: Literal['x', 'instagram'], username: str):
    return publisher_avatars.status(platform, username)


@app.get('/api/v1/posts/{key}', response_model=PostDetail)
def post_detail(key: str):
    with connect() as db:
        db.execute('BEGIN')
        row = social.find_post(db, key)
        if not row:
            fail('帖子不存在或已不可见', 404)
        return social.hydrate(db, [row['id']], media_urls, gallery_labels, thumbs=DATA / 'thumbs')[0]


@app.get('/api/v1/posts/{key}/thumbnails/{group_id}', response_class=FileResponse,
         responses={200: {'content': {'image/jpeg': {}}}})
def post_thumbnail(key: str, group_id: int):
    thumbs = DATA / 'thumbs'
    with connect() as db:
        db.execute('BEGIN')
        post = social.find_post(db, key)
        if post:
            rows = social.picture_rows(db, json.dumps([post['id']]), ['member.group_id=?'], [group_id], thumbs=thumbs)
            for row in rows:
                if row['hidden']:
                    return FileResponse(thumbs / row['filename'], media_type='image/jpeg', headers={'Cache-Control': 'no-store'})
    fail('图片不存在', 404)


class RSSResponse(Response):
    media_type = 'application/rss+xml'


@app.get(social.RSS_PATH, response_class=RSSResponse)
def gallery_feed(request: Request, people: str = '', match: PeopleMatch = 'any', publishers: str = '',
                 start: str = '', end: str = '', include_no_faces: bool = False):
    ids, accounts = parse_people_publishers(people, publishers)
    source, args = source_filter(accounts, *date_bounds(start, end), post='{post}')
    with connect() as db:
        db.execute('BEGIN')
        rows = list_queries.post_rows(db, ids, match, source, args, include_no_faces, 'newest', (), 20)
        entries = social.hydrate(db, [row['id'] for row in rows][:20], media_urls, gallery_labels,
                                 ids, match, source.format(post='p'), args, include_no_faces)
        title = settings(db)['site_title']
    return RSSResponse(social.render_feed(title, str(request.base_url).rstrip('/'), request.query_params, entries))


@app.get('/api/v1/posts', response_model=PostPage)
def posts(people: str = '', match: PeopleMatch = 'any', publishers: str = '',
          start: str = '', end: str = '', include_no_faces: bool = False,
          sort: Literal['newest', 'oldest'] = 'newest', cursor: str = '',
          limit: int = Query(default=20, ge=1, le=100)):
    ids, accounts = parse_people_publishers(people, publishers)
    source, args = source_filter(accounts, *date_bounds(start, end), post='{post}')
    edge = list_edge(cursor)
    with connect() as db:
        db.execute('BEGIN')
        rows = [dict(row) for row in list_queries.post_rows(
            db, ids, match, source, args, include_no_faces, sort, edge, limit)]
        page = rows[:limit]
        next_cursor = base64.urlsafe_b64encode(json.dumps([page[-1]['published_at'],page[-1]['id']]).encode()).decode() if len(rows) > limit else None
        return {'items': page, 'next_cursor': next_cursor}


@app.get("/api/v1/gallery", response_model=GalleryPage)
def gallery(
    people: str = "",
    match: PeopleMatch = "any",
    publishers: str = "",
    start: str = "",
    end: str = "",
    include_no_faces: bool = False,
    sort: Literal["newest", "oldest"] = "newest",
    cursor: str = "",
    limit: int = Query(default=40, ge=1, le=100),
    include_total: bool = Query(default=True, description='Return the exact matching group count; false skips counting and returns null.'),
):
    ids, accounts = parse_people_publishers(people, publishers)
    edge = list_edge(cursor, gallery=True)
    source, args = source_filter(accounts, *date_bounds(start, end))
    with connect() as db:
        db.execute('BEGIN')
        rows, total = list_queries.gallery_rows(db, ids, match, source, args, include_no_faces,
                                              sort, edge, limit, include_total)
        page = rows[:limit]
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps([page[-1]["published_at"], page[-1]["group_id"]]).encode()
            ).decode()
            if len(rows) > limit
            else None
        )
        return {"items": gallery_summaries(db, page), "next_cursor": next_cursor, "total": total}


class HeatmapDay(BaseModel):
    date: str
    new_photos: int
    posts: int


@app.get('/api/v1/gallery/heatmap', response_model=list[HeatmapDay])
def gallery_heatmap(timezone: str = Query(max_length=128), people: str = '', match: PeopleMatch = 'any',
                    publishers: str = '', start: str = '', end: str = '', include_no_faces: bool = False):
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        fail('时区无效')
    ids, accounts = parse_people_publishers(people, publishers)
    source, args = source_filter(accounts, *date_bounds(start, end), post='{post}')
    with connect() as db:
        db.execute('BEGIN')
        return list_queries.heatmap_days(db, ids, match, source, args, include_no_faces, zone)


class GalleryDownloadInput(BaseModel):
    group_ids: list[Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]] = Field(min_length=1, max_length=200)


class GalleryDownloadLink(BaseModel):
    download_url: str
    display_count: int
    thumbnail_count: int


class ArchiveBudget:
    def __init__(self):
        self.used = 0
        self.lock = threading.Lock()

    def reserve(self, reads, count):
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        limit = 512 if soft == resource.RLIM_INFINITY else min(512, soft // 4)
        with self.lock:
            if self.used + count > limit:
                raise HTTPException(503, '下载繁忙，请稍后重试', headers={'Retry-After': '10'})
            self.used += count
        reads.callback(self.release, count)

    def release(self, count):
        with self.lock:
            self.used -= count


archive_budget = ArchiveBudget()


def gallery_download_files(group_ids, reads, *, preflight=False):
    files = []
    variants = []
    selected = []
    with connect() as db:
        db.execute("BEGIN")
        for group_id in dict.fromkeys(group_ids):
            row = db.execute(
                f"SELECT * FROM images WHERE id={representative_sql('?', public=True)}",
                (group_id,),
            ).fetchone()
            if not row:
                fail("部分照片已不可用，请刷新后重新选择", 404)
            published_at = db.execute(
                "SELECT p.published_at FROM images i JOIN sources s ON s.image_id=i.id "
                "JOIN posts p ON p.id=s.post_id WHERE i.group_id=? "
                "AND i.hidden=0 AND i.detection='done' AND p.author IS NOT NULL "
                "AND p.published_at IS NOT NULL AND p.url IS NOT NULL "
                "ORDER BY p.published_at,p.id LIMIT 1",
                (group_id,),
            ).fetchone()[0]
            selected.append((group_id, row, published_at))
    archive_budget.reserve(reads, 1 if preflight else len(selected) + 1)
    entries = []
    for group_id, row, published_at in selected:
        variant = download_variant(row)
        entries.append((group_id, row, published_at, variant, media_cache.prefetch(row, variant)))
    if preflight:
        missing = sum(recovery is not None for *_, recovery in entries)
        rounds = min(3, math.ceil(missing / media_cache.RECOVERY_WORKERS))
        reads.deadline += (rounds - 1) * reads.wait_seconds
        entries.sort(key=lambda entry: entry[-1] is not None)
    for group_id, row, published_at, variant, recovery in entries:
        if preflight:
            with MediaRead() as probe:
                probe.deadline = reads.deadline
                actual, _, _ = pin_public(probe, row, variant, recovery=recovery)
                variants.append(actual)
            continue
        actual, path, current = pin_public(reads, row, variant, recovery=recovery)
        files.append((f"{group_id}-{media_name(current, actual)}", path, datetime.fromisoformat(published_at)))
    with connect() as db:
        db.execute('BEGIN')
        for group_id, row, _ in selected:
            if db.execute(f"SELECT {representative_sql('?', public=True)}", (group_id,)).fetchone()[0] != row['id']:
                fail('部分照片已不可用，请刷新后重新选择', 404)
    return files, variants


@app.post("/api/v1/gallery/downloads", response_model=GalleryDownloadLink)
def prepare_gallery_download(body: GalleryDownloadInput, reads: MediaReads):
    ids = sorted(set(body.group_ids))
    _, variants = gallery_download_files(ids, reads, preflight=True)
    # Validate before handing the request to the browser's download manager.
    # This stores no archive or job; GET rechecks visibility and availability.
    ranges = []
    first = last = ids[0]
    for identifier in ids[1:]:
        if identifier != last + 1:
            ranges.append(str(first) if first == last else f'{first}-{last}')
            first = identifier
        last = identifier
    ranges.append(str(first) if first == last else f'{first}-{last}')
    return {"download_url": "/api/v1/gallery/download.zip?prepared=true&groups=" + ",".join(ranges),
            "display_count": variants.count('image'), "thumbnail_count": variants.count('thumbnail')}


@app.get(
    "/api/v1/gallery/download.zip", response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}},
)
def download_gallery(reads: MediaReads, groups: str = Query(min_length=1, max_length=4000), prepared: bool = False):
    ids = []
    try:
        for token in groups.split(','):
            ids.extend(id_range(token, 200 - len(ids)))
    except ValueError:
        fail("请选择 1–200 张照片")
    if prepared:
        reads.deadline = time.monotonic()
    files, _ = gallery_download_files(ids, reads)
    filename = datetime.now(timezone.utc).strftime("gallery-%Y%m%d-%H%M%S.zip")
    return StreamingResponse(stream_zip(files), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-store",
        "Cloudflare-CDN-Cache-Control": "no-store",
    })


class PhotoDraw(BaseModel):
    date: str
    group_id: int
    image_url: str


def register_photo_draw(mode):
    def selection(reads: MediaReads, people: str = '', match: PeopleMatch = 'any', publishers: str = '',
                  start: str = '', end: str = '', include_no_faces: bool = False):
        ids, accounts = parse_people_publishers(people, publishers)
        bounds = date_bounds(start, end)
        source, args = source_filter(accounts, *bounds)
        key = photo_draw.filter_key(ids, match, accounts, bounds, include_no_faces) if mode == 'daily' else None

        def pin(identifier):
            reads.close()
            return pin_public(reads, public_row(identifier), 'image')
        return photo_draw.resolve(key, (ids, match, source, args, include_no_faces), pin)

    @app.get(f'/api/v1/gallery/{mode}', name=f'{mode}_photo', response_model=PhotoDraw)
    def photo(picked=Depends(selection)):
        day, group, (variant, _, row) = picked
        return PhotoDraw(date=day, group_id=group, image_url=variant_url(row, variant))

    @app.get(f'/api/v1/gallery/{mode}/image', name=f'{mode}_image', response_class=FileResponse, responses={
        200: {'content': {'image/*': {'schema': {'type': 'string', 'format': 'binary'}}}},
        404: {'description': 'No matching public photo is available'},
        503: {'description': 'Media temporarily unavailable; retry later'},
    })
    def image(picked=Depends(selection)):
        _, _, (variant, path, row) = picked
        return FileResponse(path, media_type=mimetypes.guess_type(media_name(row, variant))[0])


register_photo_draw('daily')
register_photo_draw('random')


class PublicFace(BaseModel):
    id: int
    box: list[float]
    revision: int
    person_id: int | None
    locked: bool


class GameChoice(BaseModel):
    id: int
    name: str


class GameQuestion(BaseModel):
    group_id: int
    image_id: int
    width: int
    height: int
    image_url: str
    face: PublicFace
    choices: list[GameChoice]


@app.get('/api/v1/gallery/face-game', response_model=GameQuestion)
def face_game(reads: MediaReads, people: str = '', match: PeopleMatch = 'any', publishers: str = '',
              start: str = '', end: str = '', include_no_faces: bool = False,
              last_group: int | None = Query(None, gt=0, le=9223372036854775807),
              last_face: int | None = Query(None, gt=0, le=9223372036854775807)):
    filters = game_rooms.GameFilters(people=people, match=match, publishers=publishers, start=start, end=end,
                                     include_no_faces=include_no_faces)
    return draw_game_question(reads, game_scope(filters), last_group, last_face)


def game_scope(filters):
    ids, accounts = parse_people_publishers(filters.people, filters.publishers)
    source, args = source_filter(accounts, *date_bounds(filters.start, filters.end))
    return ids, filters.match, source, args, filters.include_no_faces


def draw_game_question(reads, scope, last_group, last_face):

    def pin(identifier):
        reads.close()
        return pin_public(reads, public_row(identifier), 'image')

    group, (variant, _, row), face, choices = photo_draw.game_question(scope, last_group, last_face, pin)
    return dict(group_id=group, image_id=row['id'], width=row['width'], height=row['height'],
                image_url=variant_url(row, variant), face=face, choices=choices)


def draw_history_question(reads, scope, last_group):
    def pin(identifier):
        reads.close()
        return pin_public(reads, public_row(identifier), 'image')

    group, (variant, _, row), first, last, answer = photo_draw.history_question(scope, last_group, pin)
    return dict(group_id=group, image_id=row['id'], width=row['width'], height=row['height'],
                image_url=variant_url(row, variant), first_date=first, last_date=last, correct_date=answer)


@app.get('/api/v1/gallery/history-quiz', response_model=game_rooms.HistoryQuestion)
def history_quiz(reads: MediaReads, filters: Annotated[game_rooms.GameFilters, Depends()],
                 last_group: int | None = Query(None, gt=0, le=9223372036854775807)):
    return draw_history_question(reads, game_scope(filters), last_group)


class GalleryDetail(GalleryPhoto):
    faces: list[PublicFace]


@app.get("/api/v1/gallery/{group_id}", response_model=GalleryDetail)
def detail(group_id: int, matched_post: int | None = None):
    with connect() as db:
        db.execute("BEGIN")
        members = visible_members(db, group_id)
        if not members:
            fail("图片不存在", 404)
        sources = [
            source_record(r)
            for r in db.execute(
                "SELECT DISTINCT p.* FROM images i JOIN sources s ON s.image_id=i.id JOIN posts p ON p.id=s.post_id "
                "WHERE i.group_id=? AND i.hidden=0 AND i.detection='done' AND p.author IS NOT NULL "
                "AND p.published_at IS NOT NULL AND p.url IS NOT NULL ORDER BY p.published_at,p.id", (group_id,),
            )
        ]
        by_post = {source['id']: source for source in sources}
        for source in sources:
            source['images'] = []
        post_ids = set()
        for link in db.execute(
            "SELECT DISTINCT s.post_id,i.id AS image_id,i.width,i.height FROM images i JOIN sources s ON s.image_id=i.id "
            f"WHERE i.group_id=? AND i.hidden=0 AND i.detection='done' AND {complete_source_sql('i')} ORDER BY i.id", (group_id,),
        ):
            post_ids.add(link['post_id'])
            if source := by_post.get(link['post_id']):
                source['images'].append({key: link[key] for key in ('image_id', 'width', 'height')})
        matched = next((s for s in sources if s["id"] == matched_post), sources[0])
        faces, labels = [], {}
        for face in db.execute('SELECT f.id,f.box,f.revision,f.person_id,f.locked,p.name FROM faces f '
                               'LEFT JOIN people p ON p.id=f.person_id WHERE f.image_id=? AND f.ignored=0 '
                               "ORDER BY json_extract(f.box,'$[0]') + json_extract(f.box,'$[2]') / 2.0,f.id", (members[0]['id'],)):
            item = dict(face, box=json.loads(face['box']))
            name = item.pop('name')
            if name is not None:
                labels[item['person_id']] = dict(id=item['person_id'], name=name)
            faces.append(item)
        result = summary(
            dict(
                group_id=group_id,
                post_id=matched["id"],
                platform=matched["platform"],
                author=matched["author"],
                published_at=matched["published_at"],
                url=matched["url"],
            ),
            members[0], list(labels.values()), len(post_ids),
        )
        result.update(
            faces=faces,
            sources=sources,
            earliest_source=sources[0],
            matched_source=matched,
            members=[{**{key: member[key] for key in member.keys() if key not in media_cache.PRIVATE_FIELDS}, **media_urls(member)} for member in members],
            pending_feedback_count=db.execute(
                "SELECT count(*) FROM images i JOIN feedback f ON f.image_id=i.id WHERE i.group_id=? AND i.hidden=0 "
                f"AND i.detection='done' AND {complete_source_sql('i')} AND f.status='pending'", (group_id,),
            ).fetchone()[0],
        )
        return result


IMMUTABLE = "public, max-age=31536000, immutable"
PUBLIC_IMAGE = "hidden=0 AND detection='done' AND EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=images.id AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL)"


def download_variant(row):
    original = media_cache.asset_path(row, 'original')
    return 'original' if original and (row['original_evicted'] or original.is_file()) else 'image'


HASH_COLUMNS = {'original': 'sha256', 'image': 'image_sha256', 'thumbnail': 'thumbnail_sha256'}


def media_name(row, variant):
    return row['original_filename' if variant == 'original' else 'filename']


def variant_url(row, variant, download=False):
    digest = row[HASH_COLUMNS[variant]]
    if digest:
        url = f'/api/v1/media/by-hash/{variant}/{digest}'
    else:
        url = f'/api/v1/media/{row["id"]}' + ('?thumbnail=true' if variant == 'thumbnail' else '')
    return url + (('&' if '?' in url else '?') + 'download=true' if download and variant != 'original' else '')


def media_urls(row):
    legacy = f"/api/v1/media/{row['id']}"
    def url(variant, column, folder, fallback):
        if row[column] and ((variant == 'image' and row['image_evicted']) or (DATA / folder / row["filename"]).is_file()):
            return f"/api/v1/media/by-hash/{variant}/{row[column]}"
        return fallback
    image_url = url("image", "image_sha256", "images", legacy)
    thumbnail_url = url("thumbnail", "thumbnail_sha256", "thumbs", legacy + "?thumbnail=true")
    if row['original_lost']:
        if not (DATA / 'images' / row['filename']).is_file():
            return dict(image_url=thumbnail_url, thumbnail_url=thumbnail_url, download_url=variant_url(row, 'thumbnail', True))
        return dict(image_url=image_url, thumbnail_url=thumbnail_url, download_url=variant_url(row, 'image', True))
    download_url = (
        f"/api/v1/media/by-hash/original/{row['sha256']}"
        if download_variant(row) == 'original'
        else image_url + "?download=true"
    )
    return dict(image_url=image_url, thumbnail_url=thumbnail_url, download_url=download_url)


def public_row(identifier):
    with connect() as db:
        row = db.execute(f'SELECT * FROM images WHERE id=? AND {PUBLIC_IMAGE}', (identifier,)).fetchone()
    if not row:
        fail('图片不存在', 404)
    return row


def fallback_asset(reads, row, variant, error):
    latest = public_row(row['id'])
    if latest[HASH_COLUMNS[variant]] != row[HASH_COLUMNS[variant]]:
        fail('图片不存在', 404)
    if variant == 'thumbnail' or not (latest['original_lost'] or (variant == 'original' and error.status_code == 503)):
        raise error
    candidates = ['image'] if variant == 'original' else []
    if latest['original_lost']:
        candidates.append('thumbnail')
    for actual in candidates:
        try:
            path = reads.pin(latest, actual, recover_missing=False)
        except HTTPException as missing:
            if missing.status_code == 404:
                continue
            raise
        current = public_row(row['id'])
        if (current[HASH_COLUMNS[variant]] != row[HASH_COLUMNS[variant]] or current[HASH_COLUMNS[actual]] != latest[HASH_COLUMNS[actual]]
                or media_name(current, actual) != media_name(latest, actual)):
            fail('图片不存在', 404)
        return actual, path, current
    if latest['original_lost']:
        fail('图片不存在', 404)
    raise error


def pin_public(reads, row, variant, *, recovery=None):
    try:
        path = reads.pin(row, variant, recovery=recovery)
    except HTTPException as error:
        return fallback_asset(reads, row, variant, error)
    return variant, path, public_row(row['id'])


def conditional_file(request, path, *, headers, filename=None, media_type=None):
    response = FileResponse(path, filename=filename, headers=headers, stat_result=path.stat(), media_type=media_type)
    # If-None-Match takes precedence, including when it does not match.
    if "if-none-match" in request.headers:
        tags = request.headers["if-none-match"].split(",")
        unchanged = any(tag.strip() == "*" or tag.strip().removeprefix("W/") == response.headers["etag"] for tag in tags)
    else:
        unchanged = StaticFiles().is_not_modified(response.headers, request.headers)
    if unchanged:
        return Response(status_code=304, headers={key: value for key, value in response.headers.items() if key in ("etag", "last-modified", "cache-control", "cloudflare-cdn-cache-control", "content-disposition")})
    return response


@app.head("/api/v1/media/by-hash/{variant}/{digest}", response_class=FileResponse)
@app.get(
    "/api/v1/media/by-hash/{variant}/{digest}", response_class=FileResponse,
    responses={
        200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
        206: {"description": "Partial file content"},
        304: {"description": "Not modified; visibility and file availability checked"},
        307: {"description": "Temporary redirect to an available lower-resolution variant"},
        404: {"description": "No public, available file for this hash"},
    },
)
def hash_media(request: Request, reads: MediaReads, variant: Literal["image", "thumbnail", "original"], digest: str, download: bool = False):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("图片不存在", 404)
    column = HASH_COLUMNS[variant]
    with connect() as db:
        order = 'id' if variant == 'thumbnail' else f'{variant}_evicted,id'
        rows = db.execute(f"SELECT * FROM images WHERE {column}=? AND {PUBLIC_IMAGE} ORDER BY {order}", (digest,)).fetchall()
    unavailable = None
    fallbacks = []
    for row in rows:
        name = media_name(row, variant)
        if not name:
            continue
        try:
            path = reads.pin(row, variant)
        except HTTPException as error:
            if error.status_code not in (404, 503):
                raise
            if error.status_code == 503 or row['original_lost']:
                fallbacks.append((row, error))
            continue
        with connect() as db:
            if not db.execute(f'SELECT 1 FROM images WHERE id=? AND {column}=? AND {PUBLIC_IMAGE}', (row['id'], digest)).fetchone():
                continue
        return conditional_file(request, path, headers={"Cache-Control": IMMUTABLE, "ETag": f'"{digest}"'}, filename=name if download or variant == "original" else None, media_type=mimetypes.guess_type(name)[0])
    for row, error in fallbacks:
        try:
            actual, _, current = fallback_asset(reads, row, variant, error)
        except HTTPException as failure:
            if failure.status_code == 404:
                continue
            if failure.status_code == 503:
                unavailable = failure
                continue
            raise
        return RedirectResponse(variant_url(current, actual, download or variant == 'original'), status_code=307,
                                headers={'Cache-Control': 'no-store', 'Cloudflare-CDN-Cache-Control': 'no-store'})
    if unavailable is not None:
        raise unavailable
    fail("图片不存在", 404)


@app.get("/api/v1/media/{image_id}")
@app.head("/api/v1/media/{image_id}", include_in_schema=False)
def media(image_id: int, reads: MediaReads, thumbnail: bool = False, download: bool = False):
    row = public_row(image_id)
    variant = 'thumbnail' if thumbnail else download_variant(row) if download else 'image'
    if download and not thumbnail and not row['original_filename'] and not row['original_lost']:
        original = next((DATA / 'originals').glob(row['sha256'] + '.*'), None)
        if original:
            return FileResponse(original, filename=original.name)
    actual, path, current = pin_public(reads, row, variant)
    name = media_name(current, actual)
    return FileResponse(path, filename=name if download else None, media_type=mimetypes.guess_type(name)[0])


class FeedbackInput(BaseModel):
    content: str = Field(default='', max_length=1000)
    face_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    face_revision: int | None = Field(default=None, ge=0)
    suggested_person_id: int | None = Field(default=None, gt=0, le=9223372036854775807)
    not_face: bool = False

    @model_validator(mode='after')
    def valid_target(self):
        if (self.face_id is None) != (self.face_revision is None):
            raise ValueError('请选择有效的人脸')
        if self.not_face and (self.suggested_person_id is not None or self.face_id is None):
            raise ValueError('“不是人脸”需要选定人脸框，不能同时建议人物')
        if self.face_id is None and (not self.content or self.suggested_person_id is not None):
            raise ValueError('请填写反馈内容或选择人脸')
        return self

    @field_validator("content", mode="before")
    @classmethod
    def trim_content(cls, value):
        return value.strip() if isinstance(value, str) else value


class FeedbackStatus(BaseModel):
    status: Literal["pending", "resolved"]


class FeedbackOutput(BaseModel):
    id: int
    image_id: int
    content: str
    status: Literal["pending", "resolved"]
    created_at: str
    resolved_at: str | None
    face_id: int | None
    face_revision: int | None
    original_name: str | None
    suggested_person_id: int | None
    suggested_name: str | None
    not_face: bool


class ReviewFeedback(FeedbackOutput):
    face_number: int | None = None


class FeedbackPage(BaseModel):
    items: list[ReviewFeedback]
    next_cursor: int | None


def feedback_limits():
    limits = [int(os.environ.get(name, default)) for name, default in (
        ("FEEDBACK_RATE_LIMIT_PER_MINUTE", "5"), ("FEEDBACK_RATE_LIMIT_PER_DAY", "50")
    )]
    if any(limit < 1 for limit in limits):
        raise ValueError("Feedback rate limits must be positive integers")
    return limits


def feedback_page(db, ids, before_id, limit):
    marks = ",".join("?" for _ in ids)
    rows = db.execute(
        f"SELECT * FROM feedback WHERE image_id IN ({marks})"
        + (" AND id<?" if before_id else "") + " ORDER BY id DESC LIMIT ?",
        [*ids, *([before_id] if before_id else []), limit + 1],
    ).fetchall()
    items = [dict(row) for row in rows[:limit]]
    image_ids = sorted({item['image_id'] for item in items if item['face_id'] is not None})
    if image_ids:
        numbers = dict(db.execute(f'''SELECT id,row_number() OVER (PARTITION BY image_id ORDER BY
            json_extract(box,'$[0]') + json_extract(box,'$[2]') / 2.0,id) FROM faces
            WHERE ignored=0 AND image_id IN ({placeholders(image_ids)})''', image_ids))
        for item in items:
            if item['face_id'] is not None:
                item['face_number'] = numbers.get(item['face_id'])
    return {"items": items,
            "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}


@app.post("/api/v1/images/{image_id}/feedback", response_model=FeedbackOutput, status_code=201)
def feedback_create(image_id: int, body: FeedbackInput, request: Request):
    if request.headers.get("x-gallery-request") != "1":
        fail("缺少请求校验", 403)
    host = request.client.host if request.client else "unknown"
    try:
        address = ipaddress.ip_address(host)
        host = str(address.ipv4_mapped or address) if isinstance(address, ipaddress.IPv6Address) else str(address)
    except ValueError:
        pass
    with connect(True) as db:
        now = time.time()
        row = db.execute("SELECT group_id FROM images WHERE id=?", (image_id,)).fetchone()
        if not row or image_id not in [m["id"] for m in visible_members(db, row["group_id"])]:
            fail("图片不存在", 404)
        secret = db.execute("SELECT value FROM private_config WHERE key='feedback_secret'").fetchone()[0]
        key = hmac.new(secret.encode(), host.encode(), hashlib.sha256).hexdigest()
        db.execute("DELETE FROM feedback_submissions WHERE submitted_at<=?", (now - 86400,))
        timestamps = [r[0] for r in db.execute(
            "SELECT submitted_at FROM feedback_submissions WHERE ip_hash=? ORDER BY submitted_at", (key,)
        )]
        retry = 0
        for window, limit in zip((60, 86400), feedback_limits()):
            recent = [t for t in timestamps if t > now - window]
            if len(recent) >= limit:
                retry = max(retry, math.ceil(recent[-limit] + window - now))
        if retry:
            raise HTTPException(429, f"反馈提交过于频繁，请在 {retry} 秒后重试", headers={"Retry-After": str(retry)})
        original_name = suggested_name = None
        if body.face_id is not None:
            face = db.execute('SELECT f.revision,p.name FROM faces f LEFT JOIN people p ON p.id=f.person_id '
                              'WHERE f.id=? AND f.image_id=? AND f.ignored=0', (body.face_id, image_id)).fetchone()
            if not face or not db.execute('SELECT 1 FROM public_groups WHERE representative=?', (image_id,)).fetchone():
                fail('目标人脸已不可用，请刷新后再试', 404)
            if face['revision'] != body.face_revision:
                fail('人脸已更新，请刷新后再试', 409)
            original_name = face['name']
            if body.suggested_person_id is not None:
                suggested = db.execute('SELECT name FROM people WHERE id=?', (body.suggested_person_id,)).fetchone()
                if not suggested:
                    fail('建议人物已不存在', 409)
                suggested_name = suggested['name']
        feedback_id = db.execute('INSERT INTO feedback(image_id,content,face_id,face_revision,original_name,'
                                 'suggested_person_id,suggested_name,not_face) VALUES(?,?,?,?,?,?,?,?)',
                                 (image_id, body.content, body.face_id, body.face_revision, original_name,
                                  body.suggested_person_id, suggested_name, body.not_face)).lastrowid
        db.execute("INSERT INTO feedback_submissions VALUES(?,?)", (key, now))
        return dict(db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())


def draw_room_question(filters, previous):
    with MediaRead() as reads:
        question = draw_game_question(reads, game_scope(filters), previous and previous['group_id'],
                                      previous and previous['face']['id'])
    return question


def save_room_feedback(question, proposal, request):
    face = question['face']
    if proposal.not_face and proposal.suggested_person_id is not None:
        fail('不能同时标记误检和建议人物', 422)
    body = FeedbackInput(face_id=face['id'], face_revision=face['revision'], content=proposal.content,
                         suggested_person_id=proposal.suggested_person_id, not_face=proposal.not_face)
    return feedback_create(question['image_id'], body, request)


app.include_router(game_rooms.router(draw_room_question, game_scope, save_room_feedback))
app.include_router(game_boards.router(parse_people_publishers, date_bounds))


def draw_history_room_question(filters, previous):
    with MediaRead() as reads:
        return draw_history_question(reads, game_scope(filters), previous and previous['group_id'])


app.include_router(game_rooms.router(draw_history_room_question, game_scope, room_type=game_rooms.HistoryRoom))


@app.get("/api/v1/admin/images/{image_id}/feedback", response_model=FeedbackPage, response_model_exclude_unset=True)
def feedback_admin(image_id: int, before_id: int | None = Query(None, ge=1), limit: int = Query(20, ge=1, le=100), scope: Literal["image", "group"] = "image", _: None = Depends(admin)):
    with connect() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT group_id FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            fail("图片不存在", 404)
        ids = [image_id]
        if scope == "group":
            require_active(db, image_id)
            ids = [r[0] for r in db.execute("SELECT id FROM images WHERE group_id=? AND hidden=0", (row["group_id"],))]
        return feedback_page(db, ids, before_id, limit)


@app.put("/api/v1/admin/feedback/{feedback_id}", response_model=FeedbackOutput)
def feedback_update(feedback_id: int, body: FeedbackStatus, _: None = Depends(admin)):
    with connect(True) as db:
        row = db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
        if not row:
            fail("反馈不存在", 404)
        if row["status"] != body.status:
            db.execute("UPDATE feedback SET status=?, resolved_at=CASE WHEN ?='resolved' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE NULL END WHERE id=?", (body.status, body.status, feedback_id))
        return dict(db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())


@app.delete("/api/v1/admin/feedback/{feedback_id}")
def feedback_delete(feedback_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        if not db.execute("DELETE FROM feedback WHERE id=?", (feedback_id,)).rowcount:
            fail("反馈不存在", 404)
    return {"ok": True}


@app.post('/api/v1/admin/feedback/{feedback_id}/apply')
def feedback_apply(feedback_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        row = db.execute('SELECT * FROM feedback WHERE id=?', (feedback_id,)).fetchone()
        if not row:
            fail('反馈不存在', 404)
        if row['status'] != 'pending' or row['face_id'] is None or (row['suggested_person_id'] is None and not row['not_face']):
            fail('此反馈没有可应用的建议', 409)
        if not db.execute('SELECT 1 FROM public_groups WHERE representative=?', (row['image_id'],)).fetchone():
            fail('代表图已变化，请重新审核', 409)
        write_face_edit(db, row['face_id'], FaceEdit(person_id=row['suggested_person_id'], ignored=bool(row['not_face']), revision=row['face_revision']))
        db.execute("UPDATE feedback SET status='resolved',resolved_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (feedback_id,))
    return {'ok': True}


@app.get("/api/v1/admin/media/{image_id}")
def admin_media(image_id: int, reads: MediaReads, thumbnail: bool = False, _: None = Depends(admin)):
    with connect() as db:
        row = db.execute(
            "SELECT id,filename,hidden FROM images WHERE id=?", (image_id,)
        ).fetchone()
    if not row:
        fail("图片不存在", 404)
    path = DATA / 'thumbs' / row['filename'] if thumbnail else reads.pin(row, 'image')
    if (row["hidden"] and not thumbnail) or not path.is_file():
        fail("原图已移入回收站或文件不存在", 404)
    return FileResponse(path, media_type='image/jpeg')


def placeholders(values):
    return ','.join('?' for _ in values)


def review_images(db, rows, *, grouped=False):
    items = {row['id']: dict(row, faces=[], sources=[], pending_feedback_count=0) for row in rows}
    if not items:
        return []
    for row in db.execute(f'''SELECT id,image_id,box,person_id,locked,ignored,candidates,revision,
            (embedding IS NOT NULL AND length(embedding)>0) AS has_embedding FROM faces
            WHERE image_id IN ({placeholders(items)}) ORDER BY image_id,json_extract(box,'$[0]') + json_extract(box,'$[2]') / 2.0,id''', list(items)):
        items[row['image_id']]['faces'].append(dict(row, box=json.loads(row['box']), candidates=json.loads(row['candidates'])))

    by_owner = {item['group_id']: item for item in items.values()} if grouped else items
    owner = 'i.group_id' if grouped else 'i.id'
    scope = f'{owner} IN ({placeholders(by_owner)})' + (' AND i.hidden=0' if grouped else '')
    owners = list(by_owner)
    if grouped:
        prefix, decisions = duplicate_review.scope_sql(owners)
        for item in items.values():
            item.update(member_ids=[], member_count=0, incomplete_image_ids=[], pending_duplicate_count=0)
        for first, second in db.execute(prefix + f'SELECT first_id,second_id FROM ({duplicate_review.pending_sql(decisions)})',
                                        [*owners, float(settings(db)['review_ssim_threshold'])]):
            for group in (first, second):
                if group in by_owner:
                    by_owner[group]['pending_duplicate_count'] += 1
    incomplete = f'NOT {complete_source_sql("i")}' if grouped else '0'
    for owner_id, image_id, missing, pending in db.execute(f'''SELECT {owner},i.id,{incomplete},
            (SELECT count(*) FROM feedback WHERE image_id=i.id AND status='pending')
            FROM images i WHERE {scope} ORDER BY {owner},i.id''', owners):
        item = by_owner[owner_id]
        item['pending_feedback_count'] += pending
        if grouped:
            item['member_ids'].append(image_id)
            item['member_count'] += 1
            if missing:
                item['incomplete_image_ids'].append(image_id)

    for row in db.execute(f'''SELECT {'DISTINCT' if grouped else ''} {owner} AS owner,i.id AS image_id,p.* FROM images i
            CROSS JOIN sources s ON s.image_id=i.id CROSS JOIN posts p ON p.id=s.post_id WHERE {scope}
            ORDER BY {owner},p.id,i.id''', owners):
        post = dict(row)
        sources = by_owner[post.pop('owner')]['sources']
        image_id = post.pop('image_id')
        del post['embed_id']
        if grouped:
            if not sources or sources[-1]['id'] != post['id']:
                sources.append(dict(post, image_ids=[]))
            sources[-1]['image_ids'].append(image_id)
        else:
            sources.append(post)
    return list(items.values())


class ReviewSource(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    image_ids: list[int] = Field(default_factory=list, description="Active group members associated with this post; empty for legacy single-image reads.")


class ReviewImage(BaseModel):
    model_config = {"extra": "allow"}
    pending_duplicate_count: int = Field(default=0, description="Distinct pending duplicate group pairs involving this active group.")
    id: int = Field(description="Current review representative image ID; original image ID for hidden entries.")
    group_id: int
    member_count: int = Field(default=1, description="Number of active images in this duplicate group.")
    member_ids: list[int] = Field(default_factory=list, description="All active member IDs, without the list's 500-group limit.")
    incomplete_image_ids: list[int] = Field(default_factory=list, description="Active members without any complete source.")
    faces: list[dict]
    sources: list[ReviewSource]
    pending_feedback_count: int = Field(description="Pending feedback across active group members; single-image count for hidden entries.")


class ReviewPage(BaseModel):
    items: list[ReviewImage]
    total: int
    page: int
    page_size: int


@app.get("/api/v1/admin/images", response_model=list[ReviewImage] | ReviewPage)
def admin_images(
    state: str = "review", image_id: int | None = None,
    start: str = "", end: str = "", people: str = "",
    match: PeopleMatch = "any", publishers: str = "",
    sort: Literal['default', 'newest', 'oldest', 'confidence'] = 'default',
    page: int | None = Query(None, ge=1, description="Request a page instead of the legacy list."),
    page_size: int = Query(50, ge=1, le=100), _: None = Depends(admin)
):
    with connect() as db:
        db.execute("BEGIN")
        grouped, base, where, params = review_selection(state, image_id, start, end, people, match, publishers)
        owner = 'g.group_id' if grouped else 'i.id'
        representative = 'g.representative' if grouped else 'i.id'
        key, order = owner, 'sort_key'
        if sort in ('newest', 'oldest'):
            links, scope = ('review_group_posts', 'link.group_id=g.group_id') if grouped else ('sources', 'link.image_id=i.id')
            key = f'(SELECT min(p.published_at) FROM {links} link JOIN posts p ON p.id=link.post_id WHERE {scope})'
            order = ('sort_key DESC' if sort == 'newest' else 'sort_key ASC') + ' NULLS LAST,owner_id'
        elif sort == 'confidence':
            key = f'''(SELECT min(json_extract(candidate.value,'$.score'))
                FROM faces f CROSS JOIN json_each(f.candidates) candidate WHERE f.image_id={representative}
                AND f.ignored=0 AND f.locked=0 AND f.person_id=json_extract(candidate.value,'$.person_id'))'''
            order = 'sort_key ASC NULLS LAST,owner_id'
        limit, offset = 500, 0
        if page is not None:
            total = db.execute(f'SELECT count(*) FROM {base}' + where, params).fetchone()[0]
            page = min(page, max(1, (total + page_size - 1) // page_size))
            limit, offset = page_size, (page - 1) * page_size
        sql = f'''WITH page AS MATERIALIZED (SELECT {owner} AS owner_id,{representative} AS image_id,{key} AS sort_key
            FROM {base}{where} ORDER BY {order} LIMIT ? OFFSET ?)
            SELECT i.* FROM page CROSS JOIN images i ON i.id=page.image_id ORDER BY {order}'''
        rows = db.execute(sql, [*params, limit, offset])
        items = review_images(db, rows, grouped=grouped)
        if page is None:
            return items
        return ReviewPage(items=items, total=total, page=page, page_size=page_size)


def review_selection(state, image_id, start, end, people, match, publishers):
    ids, accounts = parse_people_publishers(people, publishers)
    if state not in (*REVIEW_FLAGS, 'hidden', 'all'):
        fail("状态无效")
    grouped = state != "hidden"
    conditions = [f'g.{state}=1' if state in REVIEW_FLAGS else ('1' if grouped else 'i.hidden=1')]
    params = []
    if image_id is not None:
        conditions.append('g.group_id=(SELECT group_id FROM images WHERE id=? AND hidden=0)' if grouped else 'i.id=?')
        params.append(image_id)
    source, args = source_filter(accounts, *date_bounds(start, end))
    if source:
        if grouped:
            conditions.append(f'g.group_id IN (SELECT link.group_id FROM posts p CROSS JOIN review_group_posts link ON link.post_id=p.id WHERE {source})')
        else:
            conditions.append(f'EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=i.id AND {source})')
        params.extend(args)
    if ids:
        if grouped:
            chosen, people_args = list_queries.matching_groups('review', ids, match)
            clause = f'g.group_id IN ({chosen})'
        else:
            clause, people_args = people_condition('i.id', ids, match)
        conditions.append(clause)
        params.extend(people_args)
    base = 'review_groups g' if grouped else 'images i'
    where = ' WHERE ' + ' AND '.join(conditions)
    return grouped, base, where, params


@app.get("/api/v1/admin/trash")
def trash_list(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), _: None = Depends(admin)):
    with connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT count(*) FROM images WHERE hidden=1").fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = db.execute("SELECT * FROM images WHERE hidden=1 ORDER BY trashed_at DESC,id DESC LIMIT ? OFFSET ?", (page_size, (page - 1) * page_size)).fetchall()
        items = review_images(db, rows)
        if items:
            ids = [item['id'] for item in items]
            marks = placeholders(ids)
            tasks = {row['image_id']: {key: row[key] for key in ('id','status','error','stage')} for row in db.execute(
                f"""SELECT i.id AS image_id,t.id,t.status,t.error,t.stage FROM images i JOIN tasks t ON t.id=(
                    SELECT id FROM tasks WHERE kind='restore' AND image_id=i.id ORDER BY status IN ('queued','running') DESC,id DESC LIMIT 1)
                    WHERE i.id IN ({marks})""", ids)}
            references = {row[0] for row in db.execute(f'SELECT DISTINCT image_id FROM reference_images WHERE image_id IN ({marks})', ids)}
            pending = {row[0] for row in db.execute(f'SELECT DISTINCT sha256 FROM pending_file_deletions WHERE sha256 IN ({marks})', [item['sha256'] for item in items])}
            for item in items:
                item.update(restore_task=tasks.get(item['id']), has_references=item['id'] in references, cleanup_pending=item['sha256'] in pending)
        return {"items": items, "total": total, "page": page, "page_size": page_size}


class FaceEdit(BaseModel):
    person_id: int | None = None
    ignored: bool = False
    locked: bool = True
    revision: int


class PersonFromFaceInput(PersonInput):
    revision: int
    add_reference: bool = True


@app.post("/api/v1/admin/faces/{face_id}/person")
def person_from_face(
    face_id: int, body: PersonFromFaceInput, _: None = Depends(admin)
):
    name = body.name.strip()
    if not name:
        fail("姓名不能为空")
    with connect(True) as db:
        require_representative_face(db, face_id)
        face = db.execute("SELECT * FROM faces WHERE id=?", (face_id,)).fetchone()
        if not face:
            fail("人脸不存在", 404)
        if face["revision"] != body.revision:
            fail("人脸已更新，请刷新后再操作", 409)
        if body.add_reference and not face["embedding"]:
            fail("该人脸没有有效特征，请取消添加参考图后重试")
        person_id = write_person(db, body)
        before = {key: face[key] for key in ("id", "person_id", "ignored", "locked", "revision")}
        db.execute(
            "INSERT INTO review_history(face_id,before_json,after_revision) VALUES(?,?,?)",
            (face_id, json.dumps(before), body.revision + 1),
        )
        db.execute(
            "UPDATE faces SET person_id=?,ignored=0,locked=1,revision=revision+1 WHERE id=?",
            (person_id, face_id),
        )
        if body.add_reference:
            require_embedding(face["embedding"], face["model_version"])
            db.execute(
                "INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(?,?,?,?,?)",
                (person_id, face["image_id"], face_id, face["embedding"], face["model_version"]),
            )
            schedule_rematch(db)
    return {"id": person_id}


def write_face_edit(db, face_id: int, body: FaceEdit):
    require_representative_face(db, face_id)
    old = db.execute(
        "SELECT id,person_id,ignored,locked,revision FROM faces WHERE id=?",
        (face_id,),
    ).fetchone()
    if not old:
        fail("人脸不存在", 404)
    if old["revision"] != body.revision:
        fail("人脸已更新，请刷新后再操作", 409)
    if (
        body.person_id is not None
        and not db.execute(
            "SELECT 1 FROM people WHERE id=?", (body.person_id,)
        ).fetchone()
    ):
        fail("人物不存在")
    db.execute(
        "INSERT INTO review_history(face_id,before_json,after_revision) VALUES(?,?,?)",
        (face_id, json.dumps(dict(old)), body.revision + 1),
    )
    db.execute(
        "UPDATE faces SET person_id=?,ignored=?,locked=?,revision=revision+1 WHERE id=?",
        (
            None if body.ignored else body.person_id,
            body.ignored,
            body.locked,
            face_id,
        ),
    )


class BatchFaceEditItem(FaceEdit):
    id: int


class BatchFaceEdit(BaseModel):
    faces: list[BatchFaceEditItem] = Field(min_length=1)


class FaceEditFailure(BaseModel):
    id: int
    detail: str
    status: int


class BatchFaceEditResult(BaseModel):
    saved: list[int]
    failures: list[FaceEditFailure]


@app.put("/api/v1/admin/faces", response_model=BatchFaceEditResult)
def faces_edit(body: BatchFaceEdit, _: None = Depends(admin)):
    if len({face.id for face in body.faces}) != len(body.faces):
        fail("人脸不能重复")
    saved = []
    failures = []
    with connect(True) as db:
        for face in body.faces:
            db.execute("SAVEPOINT face_edit")
            try:
                write_face_edit(db, face.id, face)
            except HTTPException as error:
                db.execute("ROLLBACK TO face_edit")
                failures.append({"id": face.id, "detail": error.detail, "status": error.status_code})
            else:
                saved.append(face.id)
            finally:
                db.execute("RELEASE face_edit")
    return {"saved": saved, "failures": failures}


@app.put("/api/v1/admin/faces/{face_id}")
def face_edit(face_id: int, body: FaceEdit, _: None = Depends(admin)):
    with connect(True) as db:
        write_face_edit(db, face_id, body)
    return {"ok": True}


@app.post("/api/v1/admin/faces/{face_id}/undo")
def undo(face_id: int, _: None = Depends(admin)):
    with connect(True) as db:
        require_representative_face(db, face_id)
        history = db.execute(
            "SELECT * FROM review_history WHERE face_id=? ORDER BY id DESC LIMIT 1",
            (face_id,),
        ).fetchone()
        current = db.execute(
            "SELECT revision FROM faces WHERE id=?", (face_id,)
        ).fetchone()
        if not history or not current or current[0] != history["after_revision"]:
            fail("此修改已不能撤销", 409)
        old = json.loads(history["before_json"])
        db.execute(
            "UPDATE faces SET person_id=?,ignored=?,locked=?,revision=revision+1 WHERE id=?",
            (old["person_id"], old["ignored"], old["locked"], face_id),
        )
        db.execute("DELETE FROM review_history WHERE id=?", (history["id"],))
    return {"ok": True}


class BoxInput(BaseModel):
    box: list[float] = Field(min_length=4, max_length=4)
    person_id: int | None = None


@app.post("/api/v1/admin/images/{image_id}/faces")
def add_face(image_id: int, body: BoxInput, _: None = Depends(admin)):
    with connect() as db:
        row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    if not row:
        fail("图片不存在", 404)
    if not fits(body.box, row['width'], row['height']):
        fail("人脸框超出图片范围")
    with connect(True) as db:
        require_representative(db, image_id)
        if (
            body.person_id is not None
            and not db.execute(
                "SELECT 1 FROM people WHERE id=?", (body.person_id,)
            ).fetchone()
        ):
            fail("人物不存在")
        db.execute(
            "INSERT INTO faces(image_id,box,person_id,locked) VALUES(?,?,?,?)",
            (image_id, json.dumps(body.box), body.person_id, body.person_id is not None),
        )
        db.execute(
            "UPDATE images SET detection='done',error=NULL WHERE id=?", (image_id,)
        )
    return {"ok": True}


class ImageSelection(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class ImageAction(ImageSelection):
    action: Literal["hide", "show", "redetect", "delete", "restore"] = Field(description="delete recycles complete duplicate groups; restore applies only to selected images. Legacy hide/show requests are rejected.")
    scope_token: str | None = Field(default=None, description="Required for delete: token returned by recycle-preview.")
    directory: str | None = Field(default=None, description="Optional mounted import directory to search for exact original files during restore.")


@app.post("/api/v1/admin/images/recycle-preview")
def recycle_preview(body: ImageSelection, _: None = Depends(admin)):
    from .trash import preview
    with connect() as db:
        db.execute("BEGIN")
        return preview(db, body.ids)


@app.post("/api/v1/admin/images/actions")
def image_action(body: ImageAction, _: None = Depends(admin)):
    from .trash import recycle, enqueue_restore
    if body.action in ("hide", "show"):
        fail("隐藏和显示已合并为回收站，请刷新页面后操作", 409)
    if body.action == "delete":
        return recycle(body.ids, body.scope_token)
    if body.action == "restore":
        try:
            return enqueue_restore(body.ids, body.directory)
        except ValueError as error:
            fail(str(error))
    with connect(True) as db:
        ids = set(body.ids)
        for image_id in ids:
            require_representative(db, image_id)
            schedule_detection(db, image_id, 'highres', 'single' if len(ids) == 1 else 'bulk')
    return {"ok": True}


class PostEdit(BaseModel):
    author: str = Field(min_length=1)
    author_name: str | None = None
    published_at: str
    url: str
    post_text: str | None = None


@app.put("/api/v1/admin/posts/{post_id}")
def post_edit(post_id: int, body: PostEdit, _: None = Depends(admin)):
    if not validate_url(body.url):
        fail("请输入受支持的平台链接")
    try:
        date = datetime.fromisoformat(body.published_at.replace("Z", "+00:00"))
        assert date.tzinfo
    except Exception:
        fail("发布时间必须包含时区")
    with connect(True) as db:
        old = db.execute("SELECT author,author_name FROM posts WHERE id=?", (post_id,)).fetchone()
        if not old:
            fail("来源不存在", 404)
        author_name = body.author_name
        if "author_name" not in body.model_fields_set and (old["author"] or "").lower() == body.author.lower():
            author_name = old["author_name"]
        db.execute(
            "UPDATE posts SET author=?,author_name=?,published_at=?,url=?,post_text=? WHERE id=?",
            (
                body.author,
                author_name.strip() or None if author_name else None,
                date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                body.url,
                body.post_text,
                post_id,
            ),
        )
    return {"ok": True}


@app.get("/api/v1/admin/directories")
def directories(_: None = Depends(admin)):
    if not IMPORT.exists():
        return []
    return ["."] + [
        str(p.relative_to(IMPORT))
        for p in IMPORT.rglob("*")
        if p.is_dir() and p.resolve().is_relative_to(IMPORT)
    ][:1000]


class ImportInput(BaseModel):
    scope: ImportScope = Field(default_factory=ImportScope)
    urls: list[str] = []
    hashtags: Hashtags = Field(default_factory=list)
    directory: str | None = None
    start: str = ""
    end: str = ""


@app.post("/api/v1/admin/import")
def import_create(body: ImportInput, _: None = Depends(admin)):
    results = []
    if body.scope.reposts and (body.start or body.end):
        fail('包含 Instagram 转发时，不能按日期筛选')
    with connect(True) as db:
        start, end = date_bounds(body.start, body.end)
        if body.directory is not None:
            try:
                safe_directory(body.directory)
            except ValueError as e:
                fail(str(e))
            task = db.execute(
                "INSERT INTO tasks(kind,payload) VALUES('import',?)",
                (
                    json.dumps(
                        {"directory": body.directory, "start": start, "end": end}
                    ),
                ),
            ).lastrowid
            results.append(
                {"value": body.directory, "status": "queued", "task_id": task}
            )
        targets = []
        for url in body.urls:
            url = url.strip()
            if not url:
                continue
            try:
                targets.append((url, download_url(url)[1]))
            except ValueError:
                targets.append((url, None))
        bulk = body.directory is not None or len({url for _, url in targets if url}) > 1
        seen = set()
        for submitted, url in targets:
            if url is None:
                results.append({'value': submitted, 'status': 'invalid'})
                continue
            if url in seen:
                results.append({"value": url, "status": "duplicate"})
                continue
            seen.add(url)
            scope = effective_scope(url, body.scope.model_dump())
            active = db.execute(
                "SELECT id FROM tasks WHERE kind='download' AND json_extract(payload,'$.url')=? AND json_extract(payload,'$.start') IS ? AND json_extract(payload,'$.end') IS ? AND coalesce(json_extract(payload,'$.hashtags'),'[]')=json(?) AND coalesce(json_extract(payload,'$.scope'),'{}')=json(?) AND status IN ('queued','running')",
                (url, start, end, json.dumps(body.hashtags, ensure_ascii=False), json.dumps(scope)),
            ).fetchone()
            if active:
                results.append(
                    {"value": url, "status": "duplicate", "task_id": active[0]}
                )
                continue
            task = db.execute(
                "INSERT INTO tasks(kind,payload,tier) VALUES('download',?,?)",
                (json.dumps({"url": url, "start": start, "end": end, "hashtags": body.hashtags, "scope": scope}, ensure_ascii=False),
                 'bulk' if bulk else None),
            ).lastrowid
            results.append({"value": url, "status": "queued", "task_id": task})
    return results


@app.get("/api/v1/admin/tasks")
def tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: list[Literal["download", "import", "detect", "rematch", "restore", "monitor", "avatar"]] = Query(default=[]),
    status: list[Literal["queued", "running", "done", "failed", "cancelled"]] = Query(default=[]),
    subtype: list[Subtype] = Query(default=[]),
    tier: list[Tier] = Query(default=[]),
    has_imported: bool | None = None,
    _: None = Depends(admin),
):
    conditions = []
    params = []
    types = []
    for column, values in (("kind", kind), ("subtype", subtype), ("status", status), ("tier", tier)):
        if values:
            clause = f"{column} IN ({','.join('?' for _ in values)})"
            if column in ('kind', 'subtype'):
                types.append(clause)
            else:
                conditions.append(clause)
            params.extend(values)
    if types:
        conditions.insert(0, '(' + ' OR '.join(types) + ')')
    if has_imported is not None:
        conditions.append("(kind IN ('download','monitor','import') AND coalesce(json_extract(result,'$.imported'),0)>0) = ?")
        params.append(has_imported)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT count(*) FROM tasks" + where, params).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        items = [
            dict(r)
            for r in db.execute(
                """SELECT *,runtime_seconds + CASE WHEN status='running' THEN
                    max(0,unixepoch()-unixepoch(coalesce(round_started_at,started_at))) ELSE 0 END AS elapsed_seconds,
                    CASE WHEN status='running' THEN max(0,unixepoch()-unixepoch(round_started_at)) END AS round_seconds
                    FROM tasks""" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            )
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.post("/api/v1/admin/tasks/{task_id}/{action}")
def task_action(
    task_id: int, action: Literal["cancel", "retry"], _: None = Depends(admin)
):
    with connect(True) as db:
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            fail("任务不存在", 404)
        if action == "cancel":
            db.execute(
                "UPDATE tasks SET cancel_requested=1,finished_at=CASE WHEN status='queued' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE finished_at END,stage=CASE WHEN status='queued' THEN '已取消' ELSE stage END,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=? AND status IN ('queued','running')",
                (task_id,),
            )
        elif row["status"] in ("failed", "cancelled"):
            if row['kind'] == 'avatar' and db.execute("SELECT 1 FROM tasks WHERE kind='avatar' AND payload=? AND status IN ('queued','running')", (row['payload'],)).fetchone():
                fail('已有头像更新任务', 409)
            if row["kind"] == "monitor":
                from .monitors import enqueue
                tid = enqueue(db, json.loads(row["payload"])["monitor_id"], retry=row)
                return {"ok": True, "task_id": tid}
            if row["kind"] in ("detect", "rematch"):
                require_active(db, row["image_id"])
            if row["kind"] == "restore" and not db.execute("SELECT 1 FROM images WHERE id=? AND hidden=1", (row["image_id"],)).fetchone():
                fail("图片已恢复，无需重试", 409)
            if (
                row["kind"] in ("rematch", "restore")
                and db.execute(
                    "SELECT 1 FROM tasks WHERE kind=? AND image_id=? AND status IN ('queued','running')",
                    (row["kind"], row["image_id"]),
                ).fetchone()
            ):
                fail("该图片已有同类活动任务", 409)
            db.execute(
                f"UPDATE tasks SET status='queued',started_at=NULL,round_started_at=NULL,runtime_seconds=NULL,finished_at=NULL,stage='等待重试',error=NULL,cancel_requested=0,stalled_rounds=0,done=CASE WHEN kind='download' THEN done ELSE 0 END,total=0,speed=0,queue_rank_at={NEXT_RANK} WHERE id=?",
                (task_id,),
            )
        else:
            fail("只能重试失败或已取消的任务")
    return {"ok": True}


@app.post("/api/v1/admin/cookies/{platform}")
def cookie_upload(
    platform: Literal["instagram", "x"],
    file: UploadFile = File(...),
    _: None = Depends(admin),
):
    content = file.file.read(1024 * 1024 + 1)
    try:
        cookie_bytes(content, platform)
    except ValueError as error:
        fail(str(error))
    save_cookie(DATA / "cookies" / f"{platform}.txt", content)
    return {"ok": True}


@app.delete("/api/v1/admin/cookies/{platform}")
def cookie_delete(platform: Literal["instagram", "x"], _: None = Depends(admin)):
    (DATA / "cookies" / f"{platform}.txt").unlink(missing_ok=True)
    return {"ok": True}


@app.get('/api/v1/admin/media-cache', response_model=cache_status.CacheStatus)
def get_media_cache(_: None = Depends(admin)):
    return cache_status.status()


@app.get("/api/v1/admin/settings")
def get_settings(_: None = Depends(admin)):
    with connect() as db:
        result = settings(db)
    result["cookies"] = {
        p: (DATA / "cookies" / f"{p}.txt").exists() for p in ("instagram", "x")
    }
    result["models_ready"] = models_ready()
    return result


class SettingsInput(BaseModel):
    site_title: str = Field(default="Gallery Faces", min_length=1, max_length=100)
    agent_review_rules: str = Field(default='', max_length=4000)
    og_title: str = Field(default="", max_length=100)
    og_description: str = Field(default="", max_length=500)
    og_image: str = Field(default="", max_length=2048)
    og_url: str = Field(default="", max_length=2048)
    og_title_ja: str = Field(default="", max_length=100)
    og_description_ja: str = Field(default="", max_length=500)
    og_image_ja: str = Field(default="", max_length=2048)
    og_url_ja: str = Field(default="", max_length=2048)
    detection_threshold: float = Field(default=0.5, ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=2)
    phash_distance: int = Field(ge=0, le=64)
    aspect_tolerance: float = Field(ge=0, le=1)
    ssim_threshold: float = Field(ge=0, le=1)
    review_ssim_threshold: float = Field(default=0.5, ge=0, le=1)

    @field_validator("og_title", "og_description", "og_title_ja", "og_description_ja")
    @classmethod
    def trim_open_graph_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("og_image", "og_url", "og_image_ja", "og_url_ja")
    @classmethod
    def validate_open_graph_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.username or url.password or any(char.isspace() for char in value):
            raise ValueError("请填写不含用户名、密码或空白字符的完整 HTTP(S) URL")
        return str(url)


@app.put("/api/v1/admin/settings")
def settings_update(body: SettingsInput, _: None = Depends(admin)):
    values = body.model_dump(exclude_unset=True)
    if "site_title" in values:
        values["site_title"] = body.site_title.strip()
    if "site_title" in values and not values["site_title"]:
        fail("站点标题不能为空")
    with connect(True) as db:
        effective = {**settings(db), **values}
        if float(effective["review_ssim_threshold"]) > float(effective["ssim_threshold"]):
            fail("待审核下限不能高于自动合并下限", 422)
        for key, value in values.items():
            db.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))
    return {"ok": True}


class DuplicatePage(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int
    scope_group_id: int | None = Field(default=None, description="Current group of the image used to filter these results.")


@app.get("/api/v1/admin/duplicates", response_model=list[dict] | DuplicatePage)
def duplicates(
    decision: list[Literal["pending", "auto", "merge", "separate"]] = Query(default=[]),
    image_id: int | None = Query(None, ge=1, description="Limit results to the active image's current group."),
    pair: list[int] = Query(default=[], max_length=2, description="When paging, locate this pair if still present; otherwise use the requested page."),
    page: int | None = Query(None, ge=1), page_size: int = Query(50, ge=1, le=100),
    _: None = Depends(admin),
):
    with connect() as db:
        db.execute('BEGIN')
        group = require_active(db, image_id)['group_id'] if image_id is not None else None
        params = [group] if group is not None else []
        prefix, decisions = duplicate_review.scope_sql(params)
        queries = []
        if not decision or 'pending' in decision:
            queries.append(f'SELECT a,b,decision,score FROM ({duplicate_review.pending_sql(decisions)})')
            params.append(float(settings(db)['review_ssim_threshold']))
        history = [state for state in (decision or ['auto', 'merge', 'separate']) if state != 'pending']
        if history:
            queries.append(f'''SELECT d.* {duplicate_review.joined(decisions)} WHERE l.hidden=0 AND r.hidden=0
                AND decision IN ({placeholders(history)})''')
            params.extend(history)
        matching = ' FROM (' + ' UNION ALL '.join(queries) + ')'
        limit, offset = 500, 0
        ordering = "ORDER BY decision='pending' DESC,a,b"
        if page is not None:
            total = db.execute(prefix + 'SELECT count(*)' + matching, params).fetchone()[0]
            if len(pair) == 2:
                found = db.execute(prefix + f'SELECT pos FROM (SELECT a,b,row_number() OVER ({ordering}) AS pos' + matching + ') WHERE a=? AND b=?', [*params, *pair]).fetchone()
                if found:
                    page = (found[0] - 1) // page_size + 1
            page = min(page, max(1, (total + page_size - 1) // page_size))
            limit, offset = page_size, (page - 1) * page_size
        result = [dict(row) for row in db.execute(prefix + 'SELECT *' + matching + f' {ordering} LIMIT ? OFFSET ?', [*params, limit, offset])]
        ids = sorted({pair[key] for pair in result for key in ('a', 'b')})
        if ids:
            marks = placeholders(ids)
            images = {row['id']: dict(row, people=[], sources=[]) for row in db.execute(f'SELECT * FROM images WHERE id IN ({marks})', ids)}
            for row in db.execute(f'SELECT DISTINCT f.image_id,p.* FROM faces f JOIN people p ON p.id=f.person_id WHERE f.image_id IN ({marks}) AND f.ignored=0 ORDER BY f.image_id,p.id', ids):
                person = dict(row)
                images[person.pop('image_id')]['people'].append(person)
            for row in db.execute(f'SELECT s.image_id,p.* FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id IN ({marks}) ORDER BY s.image_id,s.id', ids):
                post = dict(row)
                del post['embed_id']
                images[post.pop('image_id')]['sources'].append(post)
            for pair in result:
                pair['images'] = [images[pair['a']], images[pair['b']]]
        if page is None:
            return result
        return DuplicatePage(items=result, total=total, page=page, page_size=page_size, scope_group_id=group)


class DuplicateInput(BaseModel):
    a: int
    b: int
    action: Literal["merge", "separate", "delete_a", "delete_b", "delete_both"]


@app.post("/api/v1/admin/duplicates")
def duplicate_action(body: DuplicateInput, _: None = Depends(admin)):
    if body.a == body.b:
        fail("请选择两张不同图片")
    if body.action in ('delete_a', 'delete_b', 'delete_both'):
        from .trash import recycle_pair
        return recycle_pair(body.a, body.b, body.action)
    with connect(True) as db:
        require_active(db, body.a)
        require_active(db, body.b)
        a = db.execute("SELECT group_id FROM images WHERE id=?", (body.a,)).fetchone()
        b = db.execute("SELECT group_id FROM images WHERE id=?", (body.b,)).fetchone()
        if not a or not b:
            fail("图片不存在", 404)
        if body.action == "merge":
            db.execute("UPDATE images SET group_id=? WHERE group_id=?", (a[0], b[0]))
        elif a[0] == b[0]:
            # Remember every separated pair, so future import cannot undo this split.
            for other in db.execute(
                "SELECT id FROM images WHERE group_id=? AND id<>?", (b[0], body.b)
            ).fetchall():
                db.execute(
                    "INSERT INTO duplicate_decisions(a,b,decision) VALUES(?,?,'separate') ON CONFLICT(a,b) DO UPDATE SET decision='separate'",
                    tuple(sorted((other[0], body.b))),
                )
            group = db.execute("INSERT INTO duplicate_groups DEFAULT VALUES").lastrowid
            db.execute("UPDATE images SET group_id=? WHERE id=?", (group, body.b))
        db.execute(
            "INSERT INTO duplicate_decisions(a,b,decision) VALUES(?,?,?) ON CONFLICT(a,b) DO UPDATE SET decision=excluded.decision",
            (*sorted((body.a, body.b)), body.action),
        )
    return {"ok": True}


@app.get("/api/v1/site")
def site():
    with connect() as db:
        config = settings(db)
        return {"site_title": config["site_title"]}


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/site/open-graph", response_class=HTMLResponse)
def site_open_graph(locale: Literal["zh", "ja"] = "zh"):
    with connect() as db:
        return HTMLResponse(render_open_graph(settings(db), locale))


from .monitors import install as install_monitors
install_monitors(app, admin)
from .review_results import install as install_review_results
review_packages.install(app, admin)
publishers.install(app, admin)
install_review_results(app, admin)

static = Path(os.environ.get("FRONTEND_DIR", "../frontend/dist"))


def spa(request: Request, path: str):
    if path.startswith("api/"):
        fail("接口不存在", 404)
    with connect() as db:
        metadata = render_open_graph(settings(db))
    html = (static / "index.html").read_text(encoding="utf-8")
    html = html.replace("<!--open-graph-->", metadata)
    if not path:
        from html import escape
        suffix = social.query(request.query_params) if 'query_string' in request.scope else ''
        html = html.replace('</head>', f'<link id="gallery-rss" rel="alternate" type="application/rss+xml" title="订阅图库 RSS" href="{social.RSS_PATH}{escape(suffix)}"></head>')
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Cloudflare-CDN-Cache-Control": "no-store"})


if static.is_dir():
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")
    app.add_api_route("/{path:path}", spa, methods=["GET", "HEAD"], include_in_schema=False)


def require_embedding(embedding, version):
    try:
        validate_embedding(embedding, version)
    except ValueError as error:
        fail(str(error))
