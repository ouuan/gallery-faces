"""Lightweight metadata shared by extraction and import."""
from datetime import datetime, timezone
import json
from urllib.parse import urlparse


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
    explicit_author = raw.get("author") or raw.get("owner")
    collector = raw.get("user") or {}
    user = explicit_author or collector
    if isinstance(user, dict):
        author = (
            (user.get("username") or user.get("name"))
            if platform == "instagram"
            else user.get("screen_name") or user.get("name")
        )
    else:
        author = user
    if not explicit_author:
        if platform == "instagram":
            # gallery-dl's username/fullname are the post owner. `user` is
            # the monitored account and may be an Instagram coauthor.
            author = raw.get("username") or author
        else:
            author = raw.get("username") or author
    author_name = raw.get("author_name")
    if isinstance(user, dict) and explicit_author:
        author_name = author_name or (
            user.get("full_name") or user.get("fullname")
            if platform == "instagram"
            else user.get("nick") or (user.get("name") if user.get("screen_name") else None)
        )
    if platform == "instagram":
        author_name = author_name or raw.get("fullname") or raw.get("full_name")
    author_name = author_name.strip() if isinstance(author_name, str) else None
    coauthors = None
    if platform == "instagram" and "coauthors" in raw:
        coauthors = []
        seen = set()
        for coauthor in raw.get("coauthors") or []:
            if not isinstance(coauthor, dict):
                continue
            username = str(coauthor.get("username") or "").strip()
            key_username = username.casefold()
            if not username or key_username in seen:
                continue
            seen.add(key_username)
            full_name = coauthor.get("full_name") or coauthor.get("fullname")
            coauthors.append({
                "username": username,
                "full_name": full_name.strip() if isinstance(full_name, str) and full_name.strip() else None,
            })
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
        coauthors=coauthors,
    )


def source_image(db, meta):
    return db.execute(
        "SELECT i.* FROM sources s JOIN posts p ON p.id=s.post_id JOIN images i ON i.id=s.image_id WHERE p.platform=? AND p.post_key=? AND s.media_key=?",
        (meta["platform"], meta["key"], meta["media"]),
    ).fetchone()


def save_source(db, image_id, meta):
    coauthors = (
        json.dumps(meta["coauthors"], ensure_ascii=False, separators=(",", ":"))
        if meta.get("coauthors") is not None
        else None
    )
    db.execute(
        "INSERT INTO posts(platform,post_key,author,author_name,published_at,url,post_text,collected_account,coauthors) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(platform,post_key) DO UPDATE SET author=COALESCE(excluded.author,posts.author), author_name=CASE WHEN lower(excluded.author)<>lower(posts.author) THEN excluded.author_name ELSE COALESCE(excluded.author_name,posts.author_name) END, published_at=COALESCE(excluded.published_at,posts.published_at),url=COALESCE(excluded.url,posts.url),post_text=COALESCE(NULLIF(excluded.post_text,''),posts.post_text),coauthors=COALESCE(excluded.coauthors,posts.coauthors)",
        tuple(meta[k] for k in ("platform", "key", "author", "author_name", "date", "url", "text", "collected")) + (coauthors,),
    )
    post_id = db.execute("SELECT id FROM posts WHERE platform=? AND post_key=?", (meta["platform"], meta["key"])).fetchone()[0]
    db.execute("INSERT OR IGNORE INTO sources(image_id,post_id,media_key) VALUES(?,?,?)", (image_id, post_id, meta["media"]))


def in_date_range(meta, start=None, end=None):
    return not ((start or end) and not meta["date"]) and not (
        meta["date"] and ((start and meta["date"] < start) or (end and meta["date"] >= end))
    )
