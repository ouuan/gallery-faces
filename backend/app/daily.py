import json
from datetime import date

from fastapi import HTTPException

from .db import connect
from .list_queries import gallery_matches


def local_day():
    return date.today().isoformat()


def saved_pick(db, key):
    row = db.execute('SELECT day,group_id FROM daily_picks WHERE filter_key=?', (key,)).fetchone()
    return tuple(row) if row else None


def candidates(db, filters, *, group_id=None, last=None, first=False):
    matches, args = gallery_matches(*filters, group_id=group_id)
    sql = f'SELECT g.group_id,g.representative FROM ({matches}) hit JOIN public_groups g ON g.group_id=hit.group_id'
    if group_id is None:
        sql += ' ORDER BY g.group_id IS ?,random()'
        args.append(last)
    if first:
        sql += ' LIMIT 1'
    return [tuple(row) for row in db.execute(sql, args)]


def draw(filters, last):
    with connect() as db:
        first = candidates(db, filters, last=last, first=True)
    if first:
        yield first[0]
        with connect() as db:
            others = candidates(db, filters, last=last)
        yield from (candidate for candidate in others if candidate != first[0])


def resolve(key, filters, pin):
    for _ in range(5):
        with connect() as db:
            db.execute('BEGIN')
            day = local_day()
            saved = saved_pick(db, key)
            last = saved[1] if saved else None
            current = candidates(db, filters, group_id=last) if saved and saved[0] == day else []
        if current:
            group, representative = current[0]
            try:
                asset = pin(representative)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
            else:
                with connect() as db:
                    db.execute('BEGIN')
                    if (day == local_day() and saved_pick(db, key) == saved and
                            candidates(db, filters, group_id=group) == current):
                        return day, group, asset
                continue

        for group, representative in draw(filters, last):
            if current and (group, representative) == current[0]:
                continue
            try:
                asset = pin(representative)
            except HTTPException as error:
                if error.status_code == 404:
                    continue
                raise

            with connect(True) as db:
                if local_day() != day or saved_pick(db, key) != saved:
                    break
                if candidates(db, filters, group_id=group) != [(group, representative)]:
                    continue
                db.execute('INSERT INTO daily_picks VALUES(?,?,?) ON CONFLICT(filter_key) DO UPDATE SET '
                           'day=excluded.day,group_id=excluded.group_id', (key, day, group))
                return day, group, asset
        else:
            raise HTTPException(404, '当前筛选下没有可展示的照片')
    raise HTTPException(503, '图库正在更新，请稍后重试', headers={'Retry-After': '1'})


def filter_key(people, match, accounts, bounds, include_no_faces):
    if not people:
        match = 'any'
    elif len(people) == 1:
        match = {'all': 'any', 'exact': 'subset'}.get(match, match)
    publishers = sorted({(platform, str(int(author)) if platform == 'person' else
                          author.translate(_ASCII_LOWER)) for platform, author in accounts})
    return json.dumps([people, match, publishers, bounds, include_no_faces and not people], separators=(',', ':'))


_ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
