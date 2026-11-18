"""Select an image without moving its detection or human review records."""
from fastapi import HTTPException
from .trash import require_active, require_active_face


def complete_source_sql(image):
    return (
        "EXISTS(SELECT 1 FROM sources s JOIN posts p ON p.id=s.post_id "
        f"WHERE s.image_id={image}.id AND p.author IS NOT NULL "
        "AND p.published_at IS NOT NULL AND p.url IS NOT NULL)"
    )


def representative_sql(group, *, public=False):
    """Arguments are internal SQL expressions, never request values."""
    eligible = " AND r.detection='done' AND " + complete_source_sql("r") if public else ""
    return (
        f"(SELECT r.id FROM images r WHERE r.group_id={group} AND r.hidden=0{eligible} "
        "ORDER BY r.file_size DESC,r.id ASC LIMIT 1)"
    )


def require_representative(db, image_id):
    row = require_active(db, image_id)
    representative = db.execute(f"SELECT {representative_sql('?')}", (row["group_id"],)).fetchone()[0]
    if representative != image_id:
        raise HTTPException(409, "代表图已变化，请刷新后审核当前代表图")
    return row


def require_representative_face(db, face_id):
    image = require_active_face(db, face_id)
    return require_representative(db, image["id"])
