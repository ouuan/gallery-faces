import shutil
from PIL import Image, ImageOps
from .db import DATA, IMPORT, connect, settings, file_hash
from .vision import phash, similarity
from .metadata import metadata, validate_url, source_image, save_source, in_date_range

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


def write_assets(path, digest, *, refresh=False):
    """Caller holds the database write transaction, shared with file cleanup."""
    original = DATA / "originals" / (digest + path.suffix.lower())
    with Image.open(path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)
        width, height = im.size
        filename = digest + ".jpg"
        target = DATA / "images" / filename
        if refresh or not target.exists():
            im.convert("RGB").save(target, quality=97)
        if refresh or not (DATA / "thumbs" / filename).exists():
            im.thumbnail((640, 640))
            im.convert("RGB").save(DATA / "thumbs" / filename, quality=85)
    if not original.exists() or (refresh and path.resolve() != original.resolve()):
        shutil.copyfile(path, original)
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
        db.execute(
            "UPDATE images SET image_sha256=?,thumbnail_sha256=?,original_filename=?,file_size=? WHERE id=?",
            (file_hash(target), file_hash(DATA / "thumbs" / filename), original_name, path.stat().st_size, image_id),
        )
        save_source(db, image_id, meta)
        record_location(db, image_id, path)
        if counts is not None:
            counts["skipped_existing" if image else "imported"] += 1
    if not image:
        deduplicate(image_id)
    return image_id


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
