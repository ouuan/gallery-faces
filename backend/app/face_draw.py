"""Person-first sampling over the public representatives used by the face game."""

from collections import defaultdict
import random

from .db import connect
from .group_index import GAME_FACE_SCORE, GAME_THRESHOLD
from .list_queries import matching_groups

ELIGIBLE_FACE = f'f.ignored=0 AND {GAME_FACE_SCORE} >= {GAME_THRESHOLD}'


def group_query(filters, group_id=None):
    selected, match, source, source_args, _ = filters
    if selected:
        groups, args = matching_groups('public', selected, match, group_id=group_id)
    elif group_id is not None:
        groups, args = 'SELECT group_id FROM public_groups WHERE group_id=?', [group_id]
    else:
        groups, args = 'SELECT group_id FROM public_groups', []
    if source:
        links = 'public_group_posts link'
        if selected or group_id is not None:
            links = f'({groups}) hit JOIN {links} ON link.group_id=hit.group_id'
        groups = f'SELECT DISTINCT link.group_id FROM {links} JOIN posts p ON p.id=link.post_id WHERE {source}'
        args.extend(source_args)
    return groups, args


def pair_query(filters, last_group):
    groups, args = group_query(filters)
    selected, match = filters[:2]
    sql = f'''WITH hits AS MATERIALIZED ({groups}) SELECT who.person_id,hit.group_id
        FROM hits hit CROSS JOIN public_group_people who ON who.group_id=hit.group_id
        WHERE hit.group_id IS NOT ? AND who.game_score >= {GAME_THRESHOLD}'''
    args.append(last_group)
    if selected and match in ('any', 'all'):
        # Probe the group index once per hit, not once per selected person per hit.
        sql += ' AND +who.person_id IN (' + ','.join('?' for _ in selected) + ')'
        args.extend(selected)
    return sql, args


def first_candidate(db, filters, last_group):
    selected, match, source = filters[:3]
    if not source and (not selected or match == 'any'):
        scope = 'id IN (' + ','.join('?' for _ in selected) + ') AND ' if selected else ''
        chosen = db.execute(f'''WITH eligible AS MATERIALIZED (SELECT id FROM people WHERE {scope}
            (SELECT 1 FROM public_group_people who WHERE who.person_id=people.id AND who.group_id IS NOT ?
             AND who.game_score >= {GAME_THRESHOLD} LIMIT 1))
            SELECT id FROM eligible ORDER BY random() LIMIT 1''', [*selected, last_group]).fetchone()
        if not chosen:
            return None
        person = chosen[0]
        groups, args = f'SELECT group_id FROM public_group_people WHERE person_id=? AND game_score >= {GAME_THRESHOLD}', [person]
    else:
        pairs, args = pair_query(filters, last_group)
        return db.execute(f'''WITH pool AS MATERIALIZED ({pairs}), chosen AS MATERIALIZED (
            SELECT DISTINCT person_id FROM pool ORDER BY random() LIMIT 1), picked AS (
            SELECT person_id,group_id FROM chosen CROSS JOIN pool USING(person_id) ORDER BY random() LIMIT 1)
            SELECT person_id,group_id,representative FROM picked JOIN public_groups USING(group_id)''', args).fetchone()
    return db.execute(f'''SELECT ?,group_id,representative FROM (SELECT group_id FROM ({groups})
        WHERE group_id IS NOT ? ORDER BY random() LIMIT 1) picked JOIN public_groups USING(group_id)''',
        [person, *args, last_group]).fetchone()


def remaining_candidates(db, filters, last_group, first):
    pairs, args = pair_query(filters, last_group)
    by_person = defaultdict(list)
    for person, group, rep in db.execute(f'SELECT person_id,group_id,representative FROM ({pairs}) JOIN public_groups USING(group_id)', args):
        if (person, group, rep) != first:
            by_person[person].append((person, group, rep))
    ordered = by_person.pop(first[0], [])
    random.shuffle(ordered)
    remaining = list(by_person.values())
    random.shuffle(remaining)
    for photos in remaining:
        random.shuffle(photos)
        ordered.extend(photos)
    return ordered


def candidates(filters, last_group, last_face):
    with connect() as db:
        db.execute('BEGIN')
        if last_group is None and last_face is not None:
            row = db.execute('SELECT i.group_id FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=?', (last_face,)).fetchone()
            last_group = row[0] if row else None
        first = first_candidate(db, filters, last_group)
    if first:
        first = tuple(first)
        yield first
        with connect() as db:
            others = remaining_candidates(db, filters, last_group, first)
        yield from others
    if last_group is not None:
        groups, args = group_query(filters, last_group)
        selected = filters[0]
        scope = ' AND f.person_id IN (' + ','.join('?' for _ in selected) + ')' if selected else ''
        with connect() as db:
            previous = db.execute(f'''SELECT f.person_id,g.group_id,g.representative FROM ({groups}) hit
                JOIN public_groups g USING(group_id) JOIN faces f ON f.image_id=g.representative
                WHERE {ELIGIBLE_FACE} AND f.person_id IS NOT NULL{scope} GROUP BY f.person_id
                ORDER BY min(f.id IS ?),random()''', [*args, *selected, last_face]).fetchall()
        yield from previous
