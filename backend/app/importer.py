import shutil
import os
import tempfile
import logging
from contextlib import contextmanager
from pathlib import Path
from PIL import Image, ImageOps
from .db import DATA, IMPORT, connect, settings, file_hash
from .vision import phash, similarity
from .metadata import metadata, validate_url, source_image, save_source, in_date_range

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


@contextmanager
def atomic_asset(target):
    # Same filesystem for atomic replacement. Flush bytes and the directory
    # entry before the caller commits the corresponding database record.
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".asset-")
    temporary = Path(name)
    try:
        os.close(fd)
        yield temporary
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.replace(target)
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def valid_image(path):
    try:
        with Image.open(path) as image:
            image.load()
        return True
    except (OSError, ValueError):
        return False


def write_assets(path, digest, *, refresh=False):
    """Caller holds the database write transaction, shared with file cleanup."""
    original = DATA / "originals" / (digest + path.suffix.lower())
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        width, height = im.size
        filename = digest + ".jpg"
        target = DATA / "images" / filename
        if refresh or not valid_image(target):
            with atomic_asset(target) as temporary:
                im.convert("RGB").save(temporary, format="JPEG", quality=97)
        thumbnail = DATA / "thumbs" / filename
        if refresh or not valid_image(thumbnail):
            im.thumbnail((640, 640))
            with atomic_asset(thumbnail) as temporary:
                im.convert("RGB").save(temporary, format="JPEG", quality=85)
    if not original.exists() or file_hash(original) != digest:
        with atomic_asset(original) as temporary:
            shutil.copyfile(path, temporary)
            if file_hash(temporary) != digest:
                raise ValueError("导入期间原文件发生变化，请重试")
    return filename, width, height, original.name


def record_location(db, image_id, path):
    resolved = path.resolve()
    if resolved.is_relative_to(IMPORT):
        db.execute("INSERT OR IGNORE INTO import_locations VALUES(?,?)", (image_id, str(resolved.relative_to(IMPORT))))


def import_file(path, raw, start=None, end=None, *, counts=None):
    meta = metadata(raw, path.name)
    if not in_date_range(meta, start, end):
        return None
    with connect(True) as db:
        known = source_image(db, meta)
        if known and known["hidden"]:
            save_source(db, known["id"], meta)
            record_location(db, known["id"], path)
            if counts is not None:
                counts["skipped_trashed" if known["hidden"] else "skipped_existing"] += 1
            return known["id"]
        digest = file_hash(path)
        if known and known["sha256"] != digest:
            raise ValueError("该来源的文件已变化，不能覆盖已收录的审核记录")
        image = db.execute("SELECT * FROM images WHERE sha256=?", (digest,)).fetchone()
        if image and image["hidden"]:
            save_source(db, image["id"], meta)
            record_location(db, image["id"], path)
            if counts is not None:
                counts["skipped_trashed"] += 1
            return image["id"]
        filename, width, height, original_name = write_assets(path, digest)
        target = DATA / "images" / filename
        if image:
            image_id = image["id"]
        else:
            group = db.execute("INSERT INTO duplicate_groups DEFAULT VALUES").lastrowid
            image_id = db.execute(
                "INSERT INTO images(sha256,filename,width,height,phash,group_id,file_size) VALUES(?,?,?,?,?,?,?)",
                (digest, filename, width, height, phash(target), group, path.stat().st_size),
            ).lastrowid
            from .db import schedule_detection
            schedule_detection(db, image_id)
            db.execute("INSERT INTO pending_deduplications(image_id) VALUES(?)", (image_id,))
        db.execute(
            "UPDATE images SET image_sha256=?,thumbnail_sha256=?,original_filename=?,file_size=? WHERE id=?",
            (file_hash(target), file_hash(DATA / "thumbs" / filename), original_name, path.stat().st_size, image_id),
        )
        save_source(db, image_id, meta)
        record_location(db, image_id, path)
        if counts is not None:
            counts["skipped_existing" if image else "imported"] += 1
    finish_deduplication(image_id)
    return image_id


def finish_deduplication(image_id):
    with connect() as db:
        if not db.execute("SELECT 1 FROM pending_deduplications WHERE image_id=?", (image_id,)).fetchone():
            return
    deduplicate(image_id)
    with connect(True) as db:
        db.execute("DELETE FROM pending_deduplications WHERE image_id=?", (image_id,))


def recover_deduplications(stop):
    with connect() as db:
        pending = [r[0] for r in db.execute("SELECT image_id FROM pending_deduplications ORDER BY image_id")]
    for image_id in pending:
        if stop.is_set():
            break
        try:
            finish_deduplication(image_id)
        except Exception:
            # Keep the durable entry for a later retry without blocking startup
            # for unrelated images when an existing file is unavailable.
            logging.getLogger(__name__).exception("Could not resume deduplication for image %s", image_id)


def deduplicate(image_id):
    with connect() as db:
        current = dict(
            db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        )
        others = [
            dict(r) for r in db.execute("SELECT * FROM images WHERE hidden=0 AND phash IS NOT NULL AND id<>?", (image_id,))
        ]
        config = settings(db)
    if current["hidden"] or not current["phash"]:
        return
    for other in others:
        distance = (int(current["phash"], 16) ^ int(other["phash"], 16)).bit_count()
        if distance > 10:
            continue
        ratio = abs(
            (current["width"] / current["height"]) / (other["width"] / other["height"])
            - 1
        )
        if not (DATA / "images" / other["filename"]).is_file():
            continue
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
            if any(m["hidden"] or not m["phash"] or not (DATA / "images" / m["filename"]).is_file() for group in members for m in group):
                auto = False
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
