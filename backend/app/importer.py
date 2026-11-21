import shutil
import os
import tempfile
import logging
from contextlib import contextmanager
from pathlib import Path
from PIL import Image, ImageOps
from .db import DATA, IMPORT, connect, settings, file_hash
from .vision import phash, similarity
from .media_cache import asset, Unavailable
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


def encode_display(image, target):
    image.convert('RGB').save(target, format='JPEG', quality=97)


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
                encode_display(im, temporary)
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
            "UPDATE images SET image_evicted=0,original_evicted=0,cache_retry_at=0,image_used=unixepoch(),original_used=unixepoch(),image_sha256=?,thumbnail_sha256=?,original_filename=?,file_size=? WHERE id=?",
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
    if deduplicate(image_id) is False:
        return
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


def pair_score(first, second):
    try:
        with asset(first, 'image') as left, asset(second, 'image') as right:
            return similarity(left, right)
    except FileNotFoundError:
        return None


def consider_pair(first, second, config):
    pair = tuple(sorted((first, second)))
    query = 'SELECT * FROM images WHERE group_id IN (SELECT group_id FROM images WHERE id IN (?,?)) ORDER BY id'
    decision = 'SELECT 1 FROM duplicate_decisions WHERE a=? AND b=?'

    def membership(rows):
        return [(row['id'], row['group_id'], row['hidden'], row['image_sha256']) for row in rows]

    def similar_shape(left, right):
        distance = (int(left['phash'], 16) ^ int(right['phash'], 16)).bit_count()
        ratio = abs(left['width'] * right['height'] / (left['height'] * right['width']) - 1)
        return distance <= int(config['phash_distance']) and ratio <= float(config['aspect_tolerance'])

    while True:
        with connect() as db:
            if db.execute(decision, pair).fetchone():
                return
            rows = db.execute(query, pair).fetchall()
        images = {row['id']: row for row in rows}
        if any(identifier not in images or images[identifier]['hidden'] for identifier in pair):
            return
        left, right = images[first], images[second]
        score = pair_score(left, right)
        if score is None:
            return
        threshold = float(config['ssim_threshold'])
        auto = score >= threshold and similar_shape(left, right) and all(
            not row['hidden'] and row['phash'] and (row['image_evicted'] or (DATA / 'images' / row['filename']).is_file()) for row in rows
        )
        groups = (left['group_id'], right['group_id'])
        if auto and groups[0] != groups[1]:
            for member in rows:
                if member['group_id'] != groups[0]:
                    continue
                for other in rows:
                    if other['group_id'] != groups[1] or (member['id'], other['id']) == (first, second):
                        continue
                    cross_score = pair_score(member, other) if similar_shape(member, other) else None
                    if cross_score is None or cross_score < threshold:
                        auto = False
                        break
                if not auto:
                    break
        with connect(True) as db:
            if db.execute(decision, pair).fetchone():
                return
            if membership(rows) != membership(db.execute(query, pair)):
                continue
            if auto and groups[0] != groups[1]:
                auto = not db.execute('''SELECT 1 FROM duplicate_decisions d JOIN images l ON l.id=d.a
                    JOIN images r ON r.id=d.b WHERE decision='separate' AND
                    ((l.group_id=? AND r.group_id=?) OR (l.group_id=? AND r.group_id=?)) LIMIT 1''', (*groups, *reversed(groups))).fetchone()
                if auto:
                    db.execute('UPDATE images SET group_id=? WHERE group_id=?', tuple(images[identifier]['group_id'] for identifier in pair))
            db.execute('INSERT INTO duplicate_decisions VALUES(?,?,?,?)', (*pair, 'auto' if auto else 'pending', score))
            return


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
        return True
    complete = True
    for other in others:
        distance = (int(current["phash"], 16) ^ int(other["phash"], 16)).bit_count()
        if distance > 10:
            continue
        try:
            consider_pair(image_id, other['id'], config)
        except Unavailable:
            logging.getLogger(__name__).warning('Deferring unavailable duplicate comparison %s/%s', image_id, other['id'])
            complete = False
    return complete


def safe_directory(relative):
    path = (IMPORT / relative).resolve()
    if not path.is_relative_to(IMPORT) or not path.is_dir():
        raise ValueError("只能选择挂载的导入目录")
    return path
