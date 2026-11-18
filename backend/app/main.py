import base64
import ipaddress
import math
import hashlib
import hmac
import json
import os
import secrets
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Literal
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
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from .db import DATA, IMPORT, connect, init, settings, schedule_rematch, unknown_sql, cleanup_deleted_files
from .security import download_url, cookie_bytes, save_cookie
from .importer import validate_url, safe_directory
from .vision import MODEL_VERSION, Vision, candidates, models_ready, validate_embedding
from .db import schedule_detection, ACTIVE_REFERENCE
from .trash import require_active, require_active_face


@asynccontextmanager
async def lifespan(app):
    init()
    cleanup_deleted_files()
    feedback_limits()
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


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if response.status_code >= 400:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
    elif request.url.path.startswith("/assets/"):
        response.headers["Cache-Control"] = IMMUTABLE
    elif request.url.path.startswith("/api/"):
        if not request.url.path.startswith("/api/v1/media/by-hash/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
    return response


class Login(BaseModel):
    password: str = Field(max_length=1024)


attempts = {}
import threading
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


class PersonInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    group_ids: list[int] = []
    new_groups: list[str] = []
    accounts: list[Account] = []
    reference_face_ids: list[int] = []
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
    ids = set(body.group_ids)
    for value in body.new_groups:
        value = value.strip()
        if not value or len(value) > 100:
            fail("分组名称不能为空且不能超过 100 字")
        db.execute("INSERT OR IGNORE INTO groups(name) VALUES(?)", (value,))
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
    added_reference = False
    for reference_id in set(body.removed_reference_ids):
        reference = db.execute(
            "SELECT person_id FROM reference_images WHERE id=?", (reference_id,)
        ).fetchone()
        if reference and reference["person_id"] != person_id:
            fail("参考图不属于该人物", 409)
        if reference:
            db.execute("DELETE FROM reference_images WHERE id=?", (reference_id,))
            added_reference = True
    for uploaded in body.uploaded_references:
        write_uploaded_reference(db, person_id, uploaded)
        added_reference = True
    for face_id in set(body.reference_face_ids):
        face = db.execute(
            "SELECT * FROM faces WHERE id=? AND person_id=? AND locked=1 AND ignored=0",
            (face_id, person_id),
        ).fetchone()
        if not face or not face["embedding"]:
            fail("所选人脸已变更或没有有效特征，请刷新后重新选择", 409)
        require_active_face(db, face_id)
        require_embedding(face["embedding"], face["model_version"])
        if db.execute(
            "SELECT 1 FROM reference_images WHERE person_id=? AND face_id=?",
            (person_id, face_id),
        ).fetchone():
            continue
        db.execute(
            "INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(?,?,?,?,?)",
            (person_id, face["image_id"], face_id, face["embedding"], face["model_version"]),
        )
        added_reference = True
    if added_reference:
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
        result = []
        for row in db.execute("SELECT * FROM people ORDER BY id"):
            person = dict(row)
            person["groups"] = [
                dict(g)
                for g in db.execute(
                    "SELECT g.* FROM groups g JOIN person_groups pg ON pg.group_id=g.id WHERE person_id=? ORDER BY g.id",
                    (row["id"],),
                )
            ]
            person["accounts"] = [
                dict(a)
                for a in db.execute(
                    "SELECT platform,username FROM accounts WHERE person_id=?",
                    (row["id"],),
                )
            ]
            person["reference_count"] = db.execute(
                f"SELECT count(*) FROM reference_images WHERE person_id=? AND {ACTIVE_REFERENCE}", (row["id"],)
            ).fetchone()[0]
            avatar = db.execute(
                f"SELECT id FROM reference_images WHERE person_id=? AND {ACTIVE_REFERENCE} ORDER BY id LIMIT 1",
                (row["id"],),
            ).fetchone()
            person["avatar_reference_id"] = avatar[0] if avatar else None
            result.append(person)
        return result


@app.get("/api/v1/groups")
def groups():
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT g.*, (SELECT count(*) FROM person_groups WHERE group_id=g.id) AS members FROM groups g ORDER BY g.id"
            )
        ]


class GroupInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
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


@app.get("/api/v1/admin/people/{person_id}/confirmed-faces")
def confirmed_faces(person_id: int, _: None = Depends(admin)):
    with connect() as db:
        if not db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
            fail("人物不存在", 404)
        return [
            dict(row)
            for row in db.execute(
                "SELECT f.id,f.image_id, (f.embedding IS NOT NULL AND length(f.embedding)>0) AS has_embedding, EXISTS(SELECT 1 FROM reference_images r WHERE r.person_id=f.person_id AND r.face_id=f.id) AS is_reference FROM faces f WHERE EXISTS(SELECT 1 FROM images i WHERE i.id=f.image_id AND i.hidden=0) AND f.person_id=? AND f.locked=1 AND f.ignored=0 ORDER BY f.id DESC",
                (person_id,),
            )
        ]


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
def face_crop(face_id: int, _: None = Depends(admin)):
    with connect() as db:
        face = db.execute(
            "SELECT f.box,i.filename FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=? AND i.hidden=0",
            (face_id,),
        ).fetchone()
    if not face:
        fail("人脸不存在", 404)
    return cropped_image(DATA / "images" / face["filename"], json.loads(face["box"]))


def cropped_image(path, box):
    from PIL import Image
    import io

    if not path.is_file():
        fail("图片不存在", 404)
    x, y, w, h = box
    with Image.open(path) as image:
        crop = image.crop((x, y, x + w, y + h)).convert("RGB")
        crop.thumbnail((240, 240))
        output = io.BytesIO()
        crop.save(output, format="JPEG")
    return Response(output.getvalue(), media_type="image/jpeg")


@app.get("/api/v1/admin/references/{reference_id}/crop")
def reference_crop(reference_id: int, _: None = Depends(admin)):
    with connect() as db:
        reference = db.execute(f"SELECT * FROM reference_images WHERE id=? AND {ACTIVE_REFERENCE}", (reference_id,)).fetchone()
    if not reference:
        fail("参考图不存在", 404)
    if reference["face_id"]:
        return face_crop(reference["face_id"])
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
        if db.execute(
            "DELETE FROM reference_images WHERE id=?", (reference_id,)
        ).rowcount:
            schedule_rematch(db)
    return {"ok": True}


class DateBoundary(BaseModel):
    utc: str
    offset_seconds: int


class DateBounds(BaseModel):
    timezone: str
    start: DateBoundary | None
    end: DateBoundary | None
    current_offset_seconds: int


def date_range_info(start, end, zone):
    tz = ZoneInfo(zone)
    def boundary(value, exclusive=False):
        if not value:
            return None
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            fail("日期格式应为 YYYY-MM-DD")
        try:
            local = (datetime.fromisoformat(value) + timedelta(days=int(exclusive))).replace(tzinfo=tz)
            utc = local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (ValueError, OverflowError):
            fail("日期无效或超出支持范围")
        return DateBoundary(utc=utc, offset_seconds=int(local.utcoffset().total_seconds()))
    lower, upper = boundary(start), boundary(end, True)
    if lower and upper and lower.utc >= upper.utc:
        fail("结束日期不能早于开始日期")
    return DateBounds(timezone=zone, start=lower, end=upper,
                      current_offset_seconds=int(datetime.now(tz).utcoffset().total_seconds()))


def date_bounds(start, end, zone):
    result = date_range_info(start, end, zone)
    return result.start.utc if result.start else None, result.end.utc if result.end else None


@app.get("/api/v1/date-bounds", response_model=DateBounds)
def date_bounds_preview(start: str = "", end: str = ""):
    with connect() as db:
        return date_range_info(start, end, settings(db)["timezone"])


def gallery_rows(
    db, people_ids, match, publishers, start, end, include_no_faces, sort, cursor, limit
):
    # Use the same source row for publisher and date. Each all-person predicate
    # is applied to a single visible member image, not the union of a group.
    conditions = [
        "i.hidden=0",
        "i.detection='done'",
        "p.author IS NOT NULL",
        "p.published_at IS NOT NULL",
        "p.url IS NOT NULL",
    ]
    args = []
    if start:
        conditions.append("p.published_at>=?")
        args.append(start)
    if end:
        conditions.append("p.published_at<?")
        args.append(end)
    if publishers:
        publisher_conditions = []
        for platform, author in publishers:
            if platform == "person":
                publisher_conditions.append(
                    "EXISTS(SELECT 1 FROM accounts a WHERE a.person_id=? AND a.platform=p.platform AND lower(a.username)=lower(p.author))"
                )
                args.append(int(author))
            else:
                publisher_conditions.append("(p.platform=? AND lower(p.author)=lower(?))")
                args.extend((platform, author))
        conditions.append("(" + " OR ".join(publisher_conditions) + ")")
    eligible = "m.group_id=i.group_id AND m.hidden=0 AND m.detection='done' AND EXISTS(SELECT 1 FROM sources ms JOIN posts mp ON mp.id=ms.post_id WHERE ms.image_id=m.id AND mp.author IS NOT NULL AND mp.published_at IS NOT NULL AND mp.url IS NOT NULL)"
    if people_ids:
        marks = ",".join("?" for _ in people_ids)
        if match == "all":
            conditions.append(
                f"EXISTS(SELECT 1 FROM images m WHERE {eligible} AND (SELECT count(DISTINCT person_id) FROM faces f WHERE f.image_id=m.id AND f.ignored=0 AND f.person_id IN ({marks}))=?)"
            )
            args.extend(people_ids)
            args.append(len(people_ids))
        else:
            conditions.append(
                f"EXISTS(SELECT 1 FROM images m JOIN faces f ON f.image_id=m.id WHERE {eligible} AND f.ignored=0 AND f.person_id IN ({marks}))"
            )
            args.extend(people_ids)
    if not include_no_faces:
        conditions.append(
            f"EXISTS(SELECT 1 FROM images m JOIN faces f ON f.image_id=m.id WHERE {eligible} AND f.ignored=0)"
        )
    ranked = (
        "SELECT i.group_id,p.id AS post_id,p.platform,p.author,p.author_name,p.published_at,p.url,ROW_NUMBER() OVER(PARTITION BY i.group_id ORDER BY p.published_at,p.id) AS rank FROM images i JOIN sources s ON s.image_id=i.id JOIN posts p ON p.id=s.post_id WHERE "
        + " AND ".join(conditions)
    )
    sql = (
        "WITH ranked AS ("
        + ranked
        + ") SELECT group_id,post_id,platform,author,author_name,published_at,url FROM ranked WHERE rank=1"
    )
    if cursor:
        try:
            stamp, identifier = json.loads(base64.urlsafe_b64decode(cursor))
            identifier = int(identifier)
            if not isinstance(stamp, str) or not 0 < identifier <= 9223372036854775807:
                raise ValueError()
        except Exception:
            fail("分页游标无效")
        sql += (
            " AND (published_at,group_id) "
            + ("<" if sort == "newest" else ">")
            + " (?,?)"
        )
        args.extend((stamp, identifier))
    direction = "DESC" if sort == "newest" else "ASC"
    sql += f" ORDER BY published_at {direction},group_id {direction} LIMIT ?"
    args.append(limit + 1)
    return [dict(row) for row in db.execute(sql, args)]


def visible_members(db, group_id):
    return db.execute(
        "SELECT i.* FROM images i WHERE group_id=? AND hidden=0 AND detection='done' AND EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=i.id AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL) ORDER BY file_size DESC,id",
        (group_id,),
    ).fetchall()


def summary(db, row):
    members = visible_members(db, row["group_id"])
    ids = [m["id"] for m in members]
    marks = ",".join("?" for _ in ids)
    image = members[0]
    labels = []
    seen = set()
    for face in db.execute(
        "SELECT p.id,p.name FROM people p JOIN faces f ON f.person_id=p.id "
        "WHERE f.ignored=0 AND f.image_id=? "
        "ORDER BY json_extract(f.box,'$[0]') + json_extract(f.box,'$[2]') / 2.0,f.id",
        (image["id"],),
    ):
        if face["id"] not in seen:
            labels.append(dict(face))
            seen.add(face["id"])
    count = db.execute(
        f"SELECT count(DISTINCT post_id) FROM sources WHERE image_id IN ({marks})", ids
    ).fetchone()[0]
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


@app.get("/api/v1/gallery", response_model=GalleryPage)
def gallery(
    people: str = "",
    match: Literal["any", "all"] = "any",
    publishers: str = "",
    start: str = "",
    end: str = "",
    include_no_faces: bool = False,
    sort: Literal["newest", "oldest"] = "newest",
    cursor: str = "",
    limit: int = Query(default=40, ge=1, le=100),
):
    try:
        if len(people.split(",")) > 50 or len(publishers.split(",")) > 50 or len(cursor) > 1024:
            raise ValueError()
        ids = sorted(set(int(i) for i in people.split(",") if i))
        if any(not 0 < i <= 9223372036854775807 for i in ids):
            raise ValueError()
        accounts = [a.split(":", 1) for a in publishers.split(",") if a]
        if any(len(a) != 2 or a[0] not in ("x", "instagram", "person") or not a[1] for a in accounts):
            raise ValueError()
        if any(platform == "person" and (not author.isascii() or not author.isdigit() or not 0 < int(author) <= 9223372036854775807) for platform, author in accounts):
            raise ValueError()
    except (ValueError, OverflowError):
        fail("筛选条件无效")
    with connect() as db:
        lower, upper = date_bounds(start, end, settings(db)["timezone"])
        rows = gallery_rows(
            db,
            ids,
            match,
            accounts,
            lower,
            upper,
            include_no_faces,
            sort,
            cursor,
            limit,
        )
        page = rows[:limit]
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps([page[-1]["published_at"], page[-1]["group_id"]]).encode()
            ).decode()
            if len(rows) > limit
            else None
        )
        return {"items": [summary(db, r) for r in page], "next_cursor": next_cursor}


@app.get("/api/v1/gallery/{group_id}", response_model=GalleryPhoto)
def detail(group_id: int, matched_post: int | None = None):
    with connect() as db:
        members = visible_members(db, group_id)
        if not members:
            fail("图片不存在", 404)
        ids = [m["id"] for m in members]
        marks = ",".join("?" for _ in ids)
        sources = [
            dict(r)
            for r in db.execute(
                f"SELECT DISTINCT p.* FROM posts p JOIN sources s ON s.post_id=p.id WHERE s.image_id IN ({marks}) AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL ORDER BY published_at,p.id",
                ids,
            )
        ]
        for source in sources:
            source["images"] = [
                dict(row) for row in db.execute(
                    f"SELECT DISTINCT i.id AS image_id,i.width,i.height FROM images i "
                    f"JOIN sources s ON s.image_id=i.id WHERE s.post_id=? AND i.id IN ({marks}) ORDER BY i.id",
                    [source["id"], *ids],
                )
            ]
        matched = next((s for s in sources if s["id"] == matched_post), sources[0])
        result = summary(
            db,
            dict(
                group_id=group_id,
                post_id=matched["id"],
                platform=matched["platform"],
                author=matched["author"],
                published_at=matched["published_at"],
                url=matched["url"],
            ),
        )
        result.update(
            sources=sources,
            earliest_source=sources[0],
            matched_source=matched,
            members=[dict(m, **media_urls(m)) for m in members],
            pending_feedback_count=db.execute(
                f"SELECT count(*) FROM feedback WHERE image_id IN ({marks}) AND status='pending'", ids
            ).fetchone()[0],
        )
        return result


IMMUTABLE = "public, max-age=31536000, immutable"
PUBLIC_IMAGE = "hidden=0 AND detection='done' AND EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=images.id AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL)"


def media_urls(row):
    legacy = f"/api/v1/media/{row['id']}"
    def url(variant, column, folder, fallback):
        if row[column] and (DATA / folder / row["filename"]).is_file():
            return f"/api/v1/media/by-hash/{variant}/{row[column]}"
        return fallback
    image_url = url("image", "image_sha256", "images", legacy)
    thumbnail_url = url("thumbnail", "thumbnail_sha256", "thumbs", legacy + "?thumbnail=true")
    original = row["original_filename"]
    download_url = (
        f"/api/v1/media/by-hash/original/{row['sha256']}"
        if original and (DATA / "originals" / original).is_file()
        else image_url + "?download=true"
    )
    return dict(image_url=image_url, thumbnail_url=thumbnail_url, download_url=download_url)


def conditional_file(request, path, *, headers, filename=None):
    response = FileResponse(path, filename=filename, headers=headers, stat_result=path.stat())
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
        404: {"description": "No public, available file for this hash"},
    },
)
def hash_media(request: Request, variant: Literal["image", "thumbnail", "original"], digest: str, download: bool = False):
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("图片不存在", 404)
    column, folder = {"image": ("image_sha256", "images"), "thumbnail": ("thumbnail_sha256", "thumbs"), "original": ("sha256", "originals")}[variant]
    with connect() as db:
        rows = db.execute(f"SELECT * FROM images WHERE {column}=? AND {PUBLIC_IMAGE} ORDER BY id", (digest,))
        for row in rows:
            name = row["original_filename"] if variant == "original" else row["filename"]
            if not name:
                continue
            path = DATA / folder / name
            if path.is_file():
                return conditional_file(request, path, headers={"Cache-Control": IMMUTABLE, "ETag": f'"{digest}"'}, filename=name if download or variant == "original" else None)
    fail("图片不存在", 404)


@app.get("/api/v1/media/{image_id}")
def media(image_id: int, thumbnail: bool = False, download: bool = False):
    with connect() as db:
        row = db.execute(
            f"SELECT * FROM images WHERE id=? AND {PUBLIC_IMAGE}",
            (image_id,),
        ).fetchone()
        if not row:
            fail("图片不存在", 404)
    if download:
        original = next((DATA / "originals").glob(row["sha256"] + ".*"), None)
        if original:
            return FileResponse(original, filename=original.name)
    path = DATA / ("thumbs" if thumbnail else "images") / row["filename"]
    if not path.is_file():
        fail("图片不存在", 404)
    return FileResponse(
        path,
        filename=row["filename"] if download else None,
    )


class FeedbackInput(BaseModel):
    content: str = Field(min_length=1, max_length=1000)

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


class FeedbackPage(BaseModel):
    items: list[FeedbackOutput]
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
    return {"items": [dict(row) for row in rows[:limit]],
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
        feedback_id = db.execute("INSERT INTO feedback(image_id,content) VALUES(?,?)", (image_id, body.content)).lastrowid
        db.execute("INSERT INTO feedback_submissions VALUES(?,?)", (key, now))
        return dict(db.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone())


@app.get("/api/v1/admin/images/{image_id}/feedback", response_model=FeedbackPage)
def feedback_admin(image_id: int, before_id: int | None = Query(None, ge=1), limit: int = Query(20, ge=1, le=100), _: None = Depends(admin)):
    with connect() as db:
        if not db.execute("SELECT 1 FROM images WHERE id=?", (image_id,)).fetchone():
            fail("图片不存在", 404)
        return feedback_page(db, [image_id], before_id, limit)


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


@app.get("/api/v1/admin/media/{image_id}")
def admin_media(image_id: int, thumbnail: bool = False, _: None = Depends(admin)):
    with connect() as db:
        row = db.execute(
            "SELECT filename,hidden FROM images WHERE id=?", (image_id,)
        ).fetchone()
    if not row:
        fail("图片不存在", 404)
    path = DATA / ("thumbs" if thumbnail else "images") / row["filename"]
    if (row["hidden"] and not thumbnail) or not path.is_file():
        fail("原图已移入回收站或文件不存在", 404)
    return FileResponse(path)


def review_image(db, row):
    item = dict(row)
    item["pending_feedback_count"] = db.execute("SELECT count(*) FROM feedback WHERE image_id=? AND status='pending'", (row["id"],)).fetchone()[0]
    item["faces"] = [
        {
            **dict(f),
            "box": json.loads(f["box"]),
            "candidates": json.loads(f["candidates"]),
        }
        for f in db.execute(
            "SELECT id,image_id,box,person_id,locked,ignored,candidates,revision, (embedding IS NOT NULL AND length(embedding)>0) AS has_embedding FROM faces WHERE image_id=? "
            "ORDER BY json_extract(box,'$[0]') + json_extract(box,'$[2]') / 2.0,id",
            (row["id"],),
        )
    ]
    item["sources"] = [
        dict(s)
        for s in db.execute(
            "SELECT p.* FROM posts p JOIN sources s ON s.post_id=p.id WHERE s.image_id=?",
            (row["id"],),
        )
    ]
    return item


@app.get("/api/v1/admin/images")
def admin_images(
    state: str = "review", image_id: int | None = None, _: None = Depends(admin)
):
    with connect() as db:
        incomplete = "NOT EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id WHERE s.image_id=i.id AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL)"
        condition = {
            "review": f"i.hidden=0 AND (i.detection IN ('pending','failed') OR {incomplete} OR NOT EXISTS(SELECT 1 FROM faces WHERE image_id=i.id) OR EXISTS(SELECT 1 FROM faces WHERE image_id=i.id AND locked=0 AND ignored=0) OR EXISTS(SELECT 1 FROM feedback WHERE image_id=i.id AND status='pending'))",
            "feedback": "EXISTS(SELECT 1 FROM feedback WHERE image_id=i.id AND status='pending')",
            "unknown": f"EXISTS(SELECT 1 FROM faces WHERE image_id=i.id AND {unknown_sql()})",
            "no_faces": "detection='done' AND NOT EXISTS(SELECT 1 FROM faces WHERE image_id=i.id AND ignored=0)",
            "failed": "detection='failed'",
            "pending": "detection='pending'",
            "incomplete": incomplete,
            "hidden": "hidden=1",
            "all": "1",
        }.get(state)
        if not condition:
            fail("状态无效")
        if state != "hidden":
            condition = f"i.hidden=0 AND ({condition})"
        result = []
        params = []
        if image_id is not None:
            condition = f"({condition}) AND i.id=?"
            params.append(image_id)
        for row in db.execute(
            "SELECT i.* FROM images i WHERE " + condition + " ORDER BY id LIMIT 500",
            params,
        ):
            result.append(review_image(db, row))
        return result


@app.get("/api/v1/admin/trash")
def trash_list(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), _: None = Depends(admin)):
    with connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT count(*) FROM images WHERE hidden=1").fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        rows = db.execute("SELECT * FROM images WHERE hidden=1 ORDER BY trashed_at DESC,id DESC LIMIT ? OFFSET ?", (page_size, (page - 1) * page_size)).fetchall()
        items = []
        for row in rows:
            item = review_image(db, row)
            task = db.execute("SELECT id,status,error,stage FROM tasks WHERE image_id=? AND kind='restore' ORDER BY status IN ('queued','running') DESC,id DESC LIMIT 1", (row["id"],)).fetchone()
            item["restore_task"] = dict(task) if task else None
            item["cleanup_pending"] = bool(db.execute("SELECT 1 FROM pending_file_deletions WHERE sha256=?", (row["sha256"],)).fetchone())
            items.append(item)
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
        require_active_face(db, face_id)
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
    require_active_face(db, face_id)
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
        require_active_face(db, face_id)
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
    x, y, w, h = body.box
    if (
        x < 0
        or y < 0
        or w <= 0
        or h <= 0
        or x + w > row["width"]
        or y + h > row["height"]
    ):
        fail("人脸框超出图片范围")
    with connect(True) as db:
        require_active(db, image_id)
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
        for image_id in set(body.ids):
            require_active(db, image_id)
            schedule_detection(db, image_id, "highres")
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
    urls: list[str] = []
    directory: str | None = None
    start: str = ""
    end: str = ""


@app.post("/api/v1/admin/import")
def import_create(body: ImportInput, _: None = Depends(admin)):
    results = []
    with connect(True) as db:
        start, end = date_bounds(body.start, body.end, settings(db)["timezone"])
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
        seen = set()
        for url in body.urls:
            url = url.strip()
            if not url:
                continue
            try:
                _, url = download_url(url)
            except ValueError:
                results.append({"value": url, "status": "invalid"})
                continue
            if url in seen:
                results.append({"value": url, "status": "duplicate"})
                continue
            seen.add(url)
            active = db.execute(
                "SELECT id FROM tasks WHERE kind='download' AND json_extract(payload,'$.url')=? AND json_extract(payload,'$.start') IS ? AND json_extract(payload,'$.end') IS ? AND status IN ('queued','running')",
                (url, start, end),
            ).fetchone()
            if active:
                results.append(
                    {"value": url, "status": "duplicate", "task_id": active[0]}
                )
                continue
            task = db.execute(
                "INSERT INTO tasks(kind,payload) VALUES('download',?)",
                (json.dumps({"url": url, "start": start, "end": end}),),
            ).lastrowid
            results.append({"value": url, "status": "queued", "task_id": task})
    return results


@app.get("/api/v1/admin/tasks")
def tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    kind: list[Literal["download", "import", "detect", "rematch", "restore"]] = Query(default=[]),
    status: list[Literal["queued", "running", "done", "failed", "cancelled"]] = Query(default=[]),
    _: None = Depends(admin),
):
    conditions = []
    params = []
    for column, values in (("kind", kind), ("status", status)):
        if values:
            conditions.append(f"{column} IN ({','.join('?' for _ in values)})")
            params.extend(values)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with connect() as db:
        db.execute("BEGIN")
        total = db.execute("SELECT count(*) FROM tasks" + where, params).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        items = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM tasks" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
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
                "UPDATE tasks SET cancel_requested=1,finished_at=CASE WHEN status='queued' THEN strftime('%Y-%m-%dT%H:%M:%SZ','now') ELSE finished_at END,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE id=? AND status IN ('queued','running')",
                (task_id,),
            )
        elif row["status"] in ("failed", "cancelled"):
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
                "UPDATE tasks SET status='queued',finished_at=NULL,stage='等待重试',error=NULL,cancel_requested=0,done=0,total=0,speed=0 WHERE id=?",
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
    detection_threshold: float = Field(default=0.5, ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    margin: float = Field(ge=0, le=2)
    phash_distance: int = Field(ge=0, le=64)
    aspect_tolerance: float = Field(ge=0, le=1)
    ssim_threshold: float = Field(ge=0, le=1)
    review_ssim_threshold: float = Field(default=0.5, ge=0, le=1)
    timezone: str


@app.put("/api/v1/admin/settings")
def settings_update(body: SettingsInput, _: None = Depends(admin)):
    values = body.model_dump(exclude_unset=True)
    if "site_title" in values:
        values["site_title"] = body.site_title.strip()
    if "site_title" in values and not values["site_title"]:
        fail("站点标题不能为空")
    try:
        ZoneInfo(body.timezone)
    except Exception:
        fail("时区无效")
    with connect(True) as db:
        effective = {**settings(db), **values}
        if float(effective["review_ssim_threshold"]) > float(effective["ssim_threshold"]):
            fail("待审核下限不能高于自动合并下限", 422)
        for key, value in values.items():
            db.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))
    return {"ok": True}


@app.get("/api/v1/admin/duplicates")
def duplicates(
    decision: list[Literal["pending", "auto", "merge", "separate"]] = Query(default=[]),
    _: None = Depends(admin),
):
    with connect() as db:
        conditions = "(decision<>'pending' OR score IS NULL OR score>=?) AND EXISTS(SELECT 1 FROM images WHERE id=a AND hidden=0) AND EXISTS(SELECT 1 FROM images WHERE id=b AND hidden=0)"
        params = [float(settings(db)["review_ssim_threshold"])]
        if decision:
            conditions += f" AND decision IN ({','.join('?' for _ in decision)})"
            params.extend(decision)
        result = []
        for row in db.execute(
            "SELECT * FROM duplicate_decisions WHERE " + conditions
            + " ORDER BY decision='pending' DESC,a,b LIMIT 500", params
        ):
            item = dict(row)
            item["images"] = []
            for i in (row["a"], row["b"]):
                image = dict(
                    db.execute("SELECT * FROM images WHERE id=?", (i,)).fetchone()
                )
                image["people"] = [
                    dict(p)
                    for p in db.execute(
                        "SELECT DISTINCT p.* FROM people p JOIN faces f ON f.person_id=p.id WHERE f.image_id=? AND f.ignored=0",
                        (i,),
                    )
                ]
                image["sources"] = [
                    dict(p)
                    for p in db.execute(
                        "SELECT p.* FROM posts p JOIN sources s ON s.post_id=p.id WHERE s.image_id=?",
                        (i,),
                    )
                ]
                item["images"].append(image)
            result.append(item)
        return result


class DuplicateInput(BaseModel):
    a: int
    b: int
    action: Literal["merge", "separate"]


@app.post("/api/v1/admin/duplicates")
def duplicate_action(body: DuplicateInput, _: None = Depends(admin)):
    if body.a == body.b:
        fail("请选择两张不同图片")
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
        return {"timezone": config["timezone"], "site_title": config["site_title"]}


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


static = Path(os.environ.get("FRONTEND_DIR", "../frontend/dist"))
if static.is_dir():
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.head("/{path:path}", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def spa(request: Request, path: str):
        if path.startswith("api/"):
            fail("接口不存在", 404)
        return conditional_file(request, static / "index.html", headers={"Cache-Control": "no-cache", "Cloudflare-CDN-Cache-Control": "no-store"})


def require_embedding(embedding, version):
    try:
        validate_embedding(embedding, version)
    except ValueError as error:
        fail(str(error))
