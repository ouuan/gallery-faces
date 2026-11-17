import hashlib
import shutil
from datetime import datetime, timezone
from urllib.parse import urlparse
from PIL import Image, ImageOps
from .db import DATA, IMPORT, connect, settings
from .vision import phash, similarity

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def validate_url(value):
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or port:
        return False
    host = (parsed.hostname or "").lower()
    return host in (
        "instagram.com",
        "www.instagram.com",
        "x.com",
        "www.x.com",
        "twitter.com",
        "www.twitter.com",
    ) and bool(parsed.path.strip("/"))


def metadata(raw, filename):
    platform = raw.get("category", raw.get("platform", ""))
    platform = "x" if platform in ("twitter", "x") else platform
    if platform not in ("instagram", "x"):
        raise ValueError("无法识别 metadata 平台")
    user = raw.get("author") or raw.get("owner") or raw.get("user") or {}
    author = (
        (
            (user.get("username") or user.get("name"))
            if platform == "instagram"
            else user.get("screen_name") or user.get("name")
        )
        if isinstance(user, dict)
        else user
    )
    author = (author or raw.get("username")) if raw.get("author") or raw.get("owner") else (raw.get("username") or author)
    author_name = raw.get("author_name")
    if isinstance(user, dict):
        author_name = author_name or (
            user.get("full_name") or user.get("fullname")
            if platform == "instagram"
            else user.get("nick") or (user.get("name") if user.get("screen_name") else None)
        )
    if platform == "instagram":
        author_name = author_name or raw.get("fullname") or raw.get("full_name")
    author_name = author_name.strip() if isinstance(author_name, str) else None
    key = str(
        raw.get("tweet_id")
        or raw.get("post_id")
        or raw.get("post_shortcode")
        or raw.get("shortcode")
        or raw.get("id")
        or ""
    )
    date = raw.get("date") or raw.get("published_at") or raw.get("timestamp")
    if isinstance(date, (float, int)):
        date = datetime.fromtimestamp(date, timezone.utc)
    elif date:
        date = datetime.fromisoformat(str(date).replace("Z", "+00:00"))
    if date:
        date = (
            date.replace(tzinfo=date.tzinfo or timezone.utc)
            .astimezone(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
    url = raw.get("post_url") or raw.get("url")
    if not url or not validate_url(url):
        url = (
            f"https://x.com/{author}/status/{key}"
            if platform == "x" and author and key
            else f"https://www.instagram.com/p/{raw.get('post_shortcode') or raw.get('shortcode')}/"
            if raw.get("post_shortcode") or raw.get("shortcode")
            else None
        )
    text_fields = [raw.get("post_text"), raw.get("content") if platform == "x" else raw.get("description")]
    if platform == "x":
        details = raw.get("details") or {}
        text_fields.extend([
            details.get("full_text") if isinstance(details, dict) else None,
            raw.get("full_text"), raw.get("text"),
        ])
    text = next((value for value in text_fields if isinstance(value, str) and value.strip()), None)
    return dict(
        platform=platform,
        key=key or "incomplete:" + filename,
        author=author,
        author_name=author_name or None,
        date=date,
        url=url,
        text=text if isinstance(text, str) else None,
        media=str(raw.get("num") or raw.get("media_id") or filename),
        collected=raw.get("collected_account")
        or (
            (raw.get("user") or {}).get("name")
            if isinstance(raw.get("user"), dict)
            else None
        ),
    )


def import_file(path, raw, start=None, end=None):
    meta = metadata(raw, path.name)
    if (start or end) and not meta["date"]:
        return None
    if meta["date"] and (
        (start and meta["date"] < start) or (end and meta["date"] >= end)
    ):
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with connect(True) as db:
        original = DATA / "originals" / (digest + path.suffix.lower())
        if not original.exists():
            shutil.copyfile(path, original)
        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)
            width, height = im.size
            filename = digest + ".jpg"
            target = DATA / "images" / filename
            if not target.exists():
                im.convert("RGB").save(target, quality=97)
                im.thumbnail((640, 640))
                im.convert("RGB").save(DATA / "thumbs" / filename, quality=85)
        hash_value = phash(target)
        image = db.execute("SELECT id FROM images WHERE sha256=?", (digest,)).fetchone()
        if image:
            image_id = image[0]
        else:
            group = db.execute("INSERT INTO duplicate_groups DEFAULT VALUES").lastrowid
            image_id = db.execute(
                "INSERT INTO images(sha256,filename,width,height,phash,group_id) VALUES(?,?,?,?,?,?)",
                (digest, filename, width, height, hash_value, group),
            ).lastrowid
            from .db import schedule_detection
            schedule_detection(db, image_id)
        db.execute(
            "INSERT INTO posts(platform,post_key,author,author_name,published_at,url,post_text,collected_account) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(platform,post_key) DO UPDATE SET author=COALESCE(excluded.author,posts.author), author_name=CASE WHEN lower(excluded.author)<>lower(posts.author) THEN excluded.author_name ELSE COALESCE(excluded.author_name,posts.author_name) END, published_at=COALESCE(excluded.published_at,posts.published_at),url=COALESCE(excluded.url,posts.url),post_text=COALESCE(NULLIF(excluded.post_text,''),posts.post_text)",
            (
                meta["platform"],
                meta["key"],
                meta["author"],
                meta["author_name"],
                meta["date"],
                meta["url"],
                meta["text"],
                meta["collected"],
            ),
        )
        post_id = db.execute(
            "SELECT id FROM posts WHERE platform=? AND post_key=?",
            (meta["platform"], meta["key"]),
        ).fetchone()[0]
        db.execute(
            "INSERT OR IGNORE INTO sources(image_id,post_id,media_key) VALUES(?,?,?)",
            (image_id, post_id, meta["media"]),
        )
    deduplicate(image_id)
    return image_id


def deduplicate(image_id):
    with connect() as db:
        current = dict(
            db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        )
        others = [
            dict(r) for r in db.execute("SELECT * FROM images WHERE id<>?", (image_id,))
        ]
        config = settings(db)
    for other in others:
        distance = (int(current["phash"], 16) ^ int(other["phash"], 16)).bit_count()
        if distance > 10:
            continue
        ratio = abs(
            (current["width"] / current["height"]) / (other["width"] / other["height"])
            - 1
        )
        score = similarity(
            DATA / "images" / current["filename"], DATA / "images" / other["filename"]
        )
        with connect(True) as db:
            a, b = sorted((image_id, other["id"]))
            if db.execute(
                "SELECT 1 FROM duplicate_decisions WHERE a=? AND b=?", (a, b)
            ).fetchone():
                continue
            auto = (
                distance <= int(config["phash_distance"])
                and ratio <= float(config["aspect_tolerance"])
                and score >= float(config["ssim_threshold"])
            )
            groups = [
                db.execute("SELECT group_id FROM images WHERE id=?", (i,)).fetchone()[0]
                for i in (a, b)
            ]
            # Every cross-group pair must pass, preventing transitive chains.
            members = [
                [
                    dict(r)
                    for r in db.execute("SELECT * FROM images WHERE group_id=?", (g,))
                ]
                for g in groups
            ]
            if auto and groups[0] != groups[1]:
                for left in members[0]:
                    for right in members[1]:
                        denied = db.execute(
                            "SELECT 1 FROM duplicate_decisions WHERE a=? AND b=? AND decision='separate'",
                            tuple(sorted((left["id"], right["id"]))),
                        ).fetchone()
                        if (
                            denied
                            or (
                                int(left["phash"], 16) ^ int(right["phash"], 16)
                            ).bit_count()
                            > int(config["phash_distance"])
                            or abs(
                                (left["width"] / left["height"])
                                / (right["width"] / right["height"])
                                - 1
                            )
                            > float(config["aspect_tolerance"])
                            or similarity(
                                DATA / "images" / left["filename"],
                                DATA / "images" / right["filename"],
                            )
                            < float(config["ssim_threshold"])
                        ):
                            auto = False
                if auto:
                    db.execute(
                        "UPDATE images SET group_id=? WHERE group_id=?",
                        (groups[0], groups[1]),
                    )
            db.execute(
                "INSERT OR IGNORE INTO duplicate_decisions VALUES(?,?,?,?)",
                (a, b, "auto" if auto else "pending", score),
            )


def safe_directory(relative):
    path = (IMPORT / relative).resolve()
    if not path.is_relative_to(IMPORT) or not path.is_dir():
        raise ValueError("只能选择挂载的导入目录")
    return path
