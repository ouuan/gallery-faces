"""Compare face-game selection SQL against the former group-first draw on synthetic metadata."""

import argparse
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from app import db, face_draw, game_rooms, main
from app.list_queries import gallery_matches
from library_queries import seed


def cases(size):
    many = f'1-{min(4096, max(1, size * 9 // 1000))}'
    start = '2024-02-01T00:00:00Z'
    end = '2024-02-02T00:00:00Z'
    publisher = 'x:u314'
    yield from [('default', {}), ('include faceless', dict(include_no_faces=True)), ('rare person', dict(people='3')),
                ('large any', dict(people=many)), ('large subset', dict(people=many, match='subset')),
                ('large all', dict(people=many, match='all')), ('publisher', dict(publishers=publisher)),
                ('mixed publishers', dict(publishers='person:3,x:u20')), ('empty', dict(publishers='x:absent')),
                ('wide date', dict(start=start)), ('narrow date', dict(start=start, end=end)), ('end only', dict(end=end)),
                ('publisher + date', dict(publishers=publisher, start=start)), ('rare + date', dict(people='3', start=start))]
    for mode in ('any', 'all', 'subset', 'exact'):
        yield mode, dict(people='1,3', match=mode)
        yield f'{mode} + publisher + date', dict(people='2,316', match=mode, publishers=publisher, start=start)


def measure(conn, scope, repeats):
    matches, args = gallery_matches(*scope)
    groups = {row[0] for row in conn.execute(matches, args)}
    selected = set(scope[0])
    expected = {(person, group) for person, group in conn.execute('SELECT person_id,group_id FROM public_group_people')
                if group in groups and (not selected or person in selected)}
    pairs, params = face_draw.pair_query(scope, None)
    assert {tuple(row) for row in conn.execute(pairs, params)} == expected
    last = min((group for _, group in expected), default=None) if len({group for _, group in expected}) > 1 else None
    baseline = f'SELECT g.group_id,g.representative FROM ({matches}) hit JOIN public_groups g ON g.group_id=hit.group_id'
    if not selected:
        baseline += ' WHERE EXISTS(SELECT 1 FROM public_group_people who WHERE who.group_id=g.group_id)'
    baseline += ' ORDER BY g.group_id IS ?,random() LIMIT 1'
    old, new = [], []
    for trial in range(repeats + 1):
        before = perf_counter()
        group = conn.execute(baseline, [*args, last]).fetchone()
        middle = perf_counter()
        picked = face_draw.first_candidate(conn, scope, last)
        after = perf_counter()
        assert bool(group) == bool(picked) == bool(expected)
        assert not picked or (tuple(picked)[:2] in expected and picked[1] != last)
        if trial:
            old.append((middle - before) * 1000)
            new.append((after - middle) * 1000)
    return median(old), median(new)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=50_000)
    parser.add_argument('--repeats', type=int, default=9)
    args = parser.parse_args()
    if args.size < 300 or args.repeats < 1:
        parser.error('use at least 300 images and one repeat')
    with TemporaryDirectory(prefix='gallery-face-draw-') as directory, patch.object(db, 'DATA', Path(directory)):
        db.init()
        seed(args.size)
        with db.connect(True) as conn:
            conn.executemany("INSERT INTO accounts(person_id,platform,username) VALUES(3,'x',?)", [('u314',), ('u350',)])
            conn.execute('DELETE FROM faces WHERE image_id%211=0')
            conn.execute('UPDATE faces SET person_id=NULL WHERE image_id%223=0')
            conn.execute('UPDATE faces SET ignored=1 WHERE image_id%433=0')
        with db.connect() as conn:
            conn.execute('ANALYZE')
            print(f'{args.size} images; {args.repeats}-run median SQL milliseconds\n{"filter":26} {"before":>8} {"after":>8}')
            for name, options in cases(args.size):
                old, new = measure(conn, main.game_scope(game_rooms.GameFilters(**options)), args.repeats)
                print(f'{name:26} {old:8.2f} {new:8.2f}', flush=True)
