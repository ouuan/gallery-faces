import json
import random
from datetime import date, datetime

from fastapi import HTTPException

from . import face_draw
from .db import connect
from .list_queries import gallery_matches


def local_day():
    return date.today().isoformat()


def saved_pick(db, key):
    row = db.execute('SELECT day,group_id FROM daily_picks WHERE filter_key=?', (key,)).fetchone()
    return tuple(row) if row else None


def candidates(db, filters, *, group_id=None, last=None, first=False, first_source=False):
    matches, args = gallery_matches(*filters, group_id=group_id, first_source=first_source)
    sql = f'SELECT g.group_id,g.representative FROM ({matches}) hit JOIN public_groups g ON g.group_id=hit.group_id'
    if group_id is None:
        sql += ' ORDER BY g.group_id IS ?,random()'
        args.append(last)
    if first:
        sql += ' LIMIT 1'
    return [tuple(row) for row in db.execute(sql, args)]


def draw(filters, last, *, first_source=False):
    with connect() as db:
        first = candidates(db, filters, last=last, first=True, first_source=first_source)
    if first:
        yield first[0]
        with connect() as db:
            others = candidates(db, filters, last=last, first_source=first_source)
        yield from (candidate for candidate in others if candidate != first[0])


def game_choices(db, face, selected):
    people = dict(db.execute('SELECT id,name FROM people'))
    answer = face['person_id']
    scope = (set(selected or people) & people.keys()) - {answer}
    ranked = [item['person_id'] for item in sorted(json.loads(face['candidates']),
              key=lambda item: item['score'], reverse=True) if item['person_id'] in scope]
    count = min(4, len(scope) + 1)
    choices = [answer] if len(scope) < 4 or random.random() >= 0.1 else []
    ranked_slots = max(0, count - 1 - len(choices))
    choices.extend(list(dict.fromkeys(ranked))[:ranked_slots])
    remaining = sorted(scope.difference(choices))
    choices.extend(random.sample(remaining, count - len(choices)))
    return [dict(id=person, name=people[person]) for person in sorted(choices)]


def game_question(filters, last_group, last_face, pin):
    selected = filters[0]
    missing = set()
    for person, group, representative in face_draw.candidates(filters, last_group, last_face):
        if representative in missing:
            continue
        try:
            asset = pin(representative)
        except HTTPException as error:
            if error.status_code == 404:
                missing.add(representative)
                continue
            raise
        with connect() as db:
            db.execute('BEGIN')
            groups, args = face_draw.group_query(filters, group)
            face = db.execute(f'''SELECT f.id,f.box,f.revision,f.locked,f.person_id,f.candidates,p.name AS answer_name
                FROM ({groups}) hit JOIN public_groups g USING(group_id) JOIN faces f ON f.image_id=g.representative
                JOIN people p ON p.id=f.person_id WHERE g.representative=? AND {face_draw.ELIGIBLE_FACE} AND f.person_id=?
                ORDER BY f.id IS ?,random() LIMIT 1''', [*args, representative, person, last_face]).fetchone()
            if face:
                return group, asset, dict(id=face['id'], box=json.loads(face['box']), revision=face['revision'],
                                          locked=bool(face['locked']), person_id=face['person_id'],
                                          answer_name=face['answer_name']), game_choices(db, face, selected)
    raise HTTPException(404, '当前筛选下没有可出题的人脸')


def history_question(filters, last, pin):
    matches, args = gallery_matches(*filters, first_source=True)
    for group, representative in draw(filters, last, first_source=True):
        try:
            asset = pin(representative)
        except HTTPException as error:
            if error.status_code == 404:
                continue
            raise
        with connect() as db:
            db.execute('BEGIN')
            if candidates(db, filters, group_id=group, first_source=True) != [(group, representative)]:
                continue
            stamp = db.execute('SELECT stamp FROM public_groups WHERE group_id=?', (group,)).fetchone()[0]
            bounds = db.execute(f'SELECT MIN(stamp), MAX(stamp) FROM ({matches})', args).fetchone()
            earliest, latest, answer = (datetime.fromisoformat(value).astimezone().date() for value in (*bounds, stamp))
            return group, asset, earliest, latest, answer
    raise HTTPException(404, '当前筛选下没有可用于史官测验的照片')


def resolve(key, filters, pin):
    for _ in range(5):
        with connect() as db:
            db.execute('BEGIN')
            day = local_day()
            saved = saved_pick(db, key) if key is not None else None
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

            with connect(key is not None) as db:
                if key is not None and (local_day() != day or saved_pick(db, key) != saved):
                    break
                if candidates(db, filters, group_id=group) != [(group, representative)]:
                    continue
                if key is not None:
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
