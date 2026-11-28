"""Index-backed listing queries. SQL fragments use internal identifiers only."""

import json
from datetime import datetime


SPARSE_LIMIT = 512


def matching_groups(scope, people, match, *, group_id=None):
    table = f'{scope}_group_people'
    marks = ','.join('?' for _ in people)
    args = list(people)
    if group_id is not None:
        chosen = f'SELECT group_id FROM {table} WHERE group_id=? AND person_id IN ({marks}) GROUP BY group_id'
        args.insert(0, group_id)
        if match in ('all', 'exact'):
            chosen += ' HAVING count(*)=?'
            args.append(len(people))
    elif match in ('all', 'exact') and len(people) <= 8:
        chosen = ' INTERSECT '.join(f'SELECT group_id FROM {table} WHERE person_id=?' for _ in people)
    elif match in ('all', 'exact'):
        chosen = f'SELECT group_id FROM {table} WHERE person_id IN ({marks}) GROUP BY group_id HAVING count(*)=?'
        args.append(len(people))
    else:
        chosen = f'SELECT DISTINCT group_id FROM {table} WHERE person_id IN ({marks})'
    if match in ('exact', 'subset'):
        chosen = f'''SELECT hit.group_id FROM ({chosen}) hit WHERE NOT EXISTS(SELECT 1 FROM {table} outsider
            WHERE outsider.group_id=hit.group_id AND outsider.person_id NOT IN ({marks}))'''
        args.extend(people)
    return chosen, args


def gallery_matches(people, match, source, source_args, include_no_faces, group_id=None, *, first_source=False):
    conditions, args = [], []
    if people:
        selected, args = matching_groups('public', people, match)
        conditions.append(f'g.group_id IN ({selected})')
    elif not include_no_faces:
        conditions.append('g.has_face=1')
    if group_id is not None:
        conditions.append('g.group_id=?')
        args.append(group_id)
    if source and first_source:
        conditions.append(source)
        matches = ('SELECT g.group_id,g.first_post,g.stamp FROM public_groups g JOIN posts p ON p.id=g.first_post WHERE '
                   + ' AND '.join(conditions))
        args.extend(source_args)
    elif source:
        conditions.append(source)
        args.extend(source_args)
        links = ('public_groups g JOIN public_group_posts link ON link.group_id=g.group_id JOIN posts p ON p.id=link.post_id'
                 if people or group_id is not None else 'posts p CROSS JOIN public_group_posts link ON link.post_id=p.id CROSS JOIN public_groups g NOT INDEXED ON g.group_id=link.group_id')
        matches = f'''SELECT group_id,first_post,stamp FROM (SELECT g.group_id,p.id first_post,p.published_at stamp,
            row_number() OVER(PARTITION BY g.group_id ORDER BY p.published_at,p.id) AS rank
            FROM {links} WHERE ''' + ' AND '.join(conditions) + ') WHERE rank=1'
    else:
        matches = 'SELECT group_id,first_post,stamp FROM public_groups g'
        if conditions:
            matches += ' WHERE ' + ' AND '.join(conditions)
    return matches, args


def gallery_rows(db, people, match, source, source_args, include_no_faces, order, edge, limit, total):
    matches, args = gallery_matches(people, match, source, source_args, include_no_faces)
    direction, comparison = ('DESC', '<') if order == 'newest' else ('ASC', '>')
    boundary = f'WHERE (stamp,group_id) {comparison} (?,?)' if edge else ''
    materialize = 'MATERIALIZED' if total and (people or source) else 'NOT MATERIALIZED'
    count = '(SELECT count(*) FROM matches)' if total else 'NULL'
    rows = db.execute(f'''WITH matches AS {materialize} ({matches}), page AS MATERIALIZED (
        SELECT * FROM matches {boundary} ORDER BY stamp {direction},group_id {direction} LIMIT ?)
        SELECT t.total,page.group_id,p.id post_id,p.platform,p.author,p.author_name,p.published_at,p.url
        FROM (SELECT {count} AS total) t LEFT JOIN page ON true LEFT JOIN posts p ON p.id=page.first_post
        ORDER BY page.stamp {direction},page.group_id {direction}''', [*args, *edge, limit + 1])
    items, count = [], None
    for row in rows:
        item = dict(row)
        count = item.pop('total')
        if item['group_id'] is not None:
            items.append(item)
    return items, count


def post_matches(db, people, match, source_template, source_args, include_no_faces):
    def probe(sql, args):
        rows = [row[0] for row in db.execute(sql + ' LIMIT ?', [*args, SPARSE_LIMIT + 1])]
        return rows if len(rows) <= SPARSE_LIMIT else None

    source = source_template.format(post='p')
    posts = probe('SELECT p.id FROM posts p WHERE ' + source, source_args) if source else None
    selected, person_args = matching_groups('public', people, match) if people else ('', [])
    groups = probe(selected, person_args) if people and (posts is None or len(posts) > 32) else None
    columns = "id,platform || ':' || coalesce(embed_id,'record:' || id) AS key,platform,url,embed_id,author,author_name,published_at"
    supported = "p.platform IN ('x','instagram')"

    def eligible(alias):
        conditions = [f'link.post_id={alias}.id']
        values = []
        if people:
            marks = ','.join('?' for _ in people)
            member = 'FROM public_group_people who WHERE who.group_id=link.group_id'
            if match in ('all', 'exact'):
                conditions.append(f'(SELECT count(*) {member} AND who.person_id IN ({marks}))=?')
                values.extend([*people, len(people)])
            else:
                conditions.append(f'EXISTS(SELECT 1 {member} AND who.person_id IN ({marks}))')
                values.extend(people)
            if match in ('subset', 'exact'):
                conditions.append(f'NOT EXISTS(SELECT 1 {member} AND who.person_id NOT IN ({marks}))')
                values.extend(people)
        elif not include_no_faces:
            conditions.append('EXISTS(SELECT 1 FROM public_groups g WHERE g.group_id=link.group_id AND g.has_face=1)')
        return 'EXISTS(SELECT 1 FROM public_group_posts link WHERE ' + ' AND '.join(conditions) + ')', values

    if posts is not None and (groups is None or len(posts) <= len(groups)):
        condition, values = eligible('p')
        chosen = f'SELECT p.id FROM json_each(?) seed CROSS JOIN posts p ON p.id=seed.value WHERE {supported} AND {condition}'
        args = [json.dumps(posts), *values]
    elif groups is not None:
        chosen = f'''SELECT DISTINCT p.id FROM json_each(?) seed CROSS JOIN public_group_posts link ON link.group_id=seed.value
            CROSS JOIN posts p ON p.id=link.post_id WHERE {supported}'''
        args = [json.dumps(groups)]
        if source:
            chosen += ' AND ' + source
            args.extend(source_args)
    else:
        condition, values = eligible('p')
        other, other_values = eligible('other')
        where = f'{supported} AND {condition}'
        args = list(values)
        if source:
            where += ' AND ' + source
            args.extend(source_args)
            other += ' AND ' + source_template.format(post='other')
            other_values.extend(source_args)
        sql = f'''SELECT {columns} FROM posts p INDEXED BY post_date WHERE {where} AND (embed_id IS NULL OR NOT EXISTS(
            SELECT 1 FROM posts other WHERE other.platform=p.platform AND other.embed_id=p.embed_id AND other.id<p.id AND {other}))'''
        return sql, [*args, *other_values]
    sql = f'''WITH chosen AS MATERIALIZED ({chosen}), ranked AS (SELECT p.*,
        row_number() OVER(PARTITION BY platform,embed_id,CASE WHEN embed_id IS NULL THEN p.id END ORDER BY p.id) AS rank
        FROM chosen CROSS JOIN posts p ON p.id=chosen.id) SELECT {columns} FROM ranked WHERE rank=1'''
    return sql, args


def post_rows(db, people, match, source_template, source_args, include_no_faces, order, edge, limit):
    sql, args = post_matches(db, people, match, source_template, source_args, include_no_faces)
    direction, comparison = ('DESC', '<') if order == 'newest' else ('ASC', '>')
    boundary = f' AND (published_at,id) {comparison} (?,?)' if edge else ''
    tail = f' ORDER BY published_at {direction},id {direction} LIMIT ?'
    return db.execute(sql + boundary + tail, [*args, *edge, limit + 1])


def heatmap_days(db, people, match, source_template, source_args, include_no_faces, zone):
    photos, photo_args = gallery_matches(people, match, source_template.format(post='p'), source_args, include_no_faces)
    posts, post_args = post_matches(db, people, match, source_template, source_args, include_no_faces)
    db.create_function('local_day', 1, lambda stamp: datetime.fromisoformat(stamp).astimezone(zone).date().isoformat(), deterministic=True)
    return [dict(row) for row in db.execute(f'''WITH activity AS (
        SELECT stamp, 1 AS new_photos, 0 AS posts FROM ({photos})
        UNION ALL SELECT published_at, 0, 1 FROM ({posts})
    ) SELECT local_day(stamp) AS date, sum(new_photos) AS new_photos, sum(posts) AS posts
      FROM activity GROUP BY date ORDER BY date''', [*photo_args, *post_args])]
