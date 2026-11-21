from contextlib import contextmanager
import sqlite3

import pytest

from app import db, main
from test_workflows import client, image


def test_gallery_reads_are_batched(client, monkeypatch):
    with db.connect(True) as conn:
        group = image(conn)
        for _ in range(40):
            image(conn)
            image(conn, group=group)

    statements = []

    @contextmanager
    def traced_connect():
        with db.connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(main, 'connect', traced_connect)
    for limit in (1, 40):
        statements.clear()
        page = client.get('/api/v1/gallery', params={'limit': limit}).json()
        assert page['total'] == 41 and len(page['items']) == limit
        assert len([sql for sql in statements if sql.lstrip().startswith(('WITH', 'SELECT'))]) <= 4

    statements.clear()
    detail = client.get(f'/api/v1/gallery/{group}').json()
    assert detail['source_count'] == len(detail['sources']) == 41
    assert len([sql for sql in statements if sql.lstrip().startswith(('WITH', 'SELECT'))]) <= 5


def test_filtered_source_tie_and_empty_cursor_page(client):
    with db.connect(True) as conn:
        group = image(conn, author='other')
        first_match = image(conn, author='selected', group=group)
        image(conn, author='selected', group=group)
        last = image(conn, author='selected')

    params = {'sort': 'oldest', 'publishers': 'x:selected', 'limit': 1}
    page = client.get('/api/v1/gallery', params=params).json()
    assert page['total'] == 2
    assert page['items'][0]['image_id'] == group
    assert page['items'][0]['matched_source']['post_id'] == first_match
    assert page['items'][0]['source_count'] == 3

    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (last,))
    after = client.get('/api/v1/gallery', params={**params, 'cursor': page['next_cursor']}).json()
    assert after == {'items': [], 'total': 1, 'next_cursor': None}


@pytest.mark.parametrize('sort', ['newest', 'oldest'])
def test_gallery_indexed_pages_match_exact_pages(client, sort):
    with db.connect(True) as conn:
        first = image(conn, author='other', date='2025-01-01')
        member = image(conn, group=first)
        image(conn, group=first)
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,?)', (first, member, 'second'))
        image(conn)
        image(conn, date='2024-01-01')
        image(conn, faces=False)
        conn.execute("INSERT INTO people(name) VALUES('Selected')")
        conn.execute('UPDATE faces SET person_id=1')
    for filters in ({}, {'publishers': 'x:alice'}, {'include_no_faces': True},
                    {'people': '1', 'match': 'exact', 'start': '2025-01-01T00:00:00Z'}):
        params = dict(sort=sort, limit=1, **filters)
        seen = set()
        while True:
            exact = client.get('/api/v1/gallery', params=params).json()
            indexed = client.get('/api/v1/gallery', params={**params, 'include_total': False}).json()
            assert indexed == {**exact, 'total': None}
            seen.update(item['id'] for item in indexed['items'])
            if not exact['next_cursor']:
                break
            params['cursor'] = exact['next_cursor']
        assert len(seen) == exact['total']


def test_post_identity_upgrade_and_filtered_aliases(client):
    with db.connect(True) as conn:
        first = image(conn, author='other')
        second = image(conn, author='selected')
        conn.execute("UPDATE posts SET url='https://twitter.com/alias/status/1/photo/1' WHERE id=?", (second,))
        conn.execute('DROP TRIGGER post_embed_insert')
        conn.execute('DROP TRIGGER post_embed_update')
        conn.execute('DROP INDEX post_embed')
        conn.execute('ALTER TABLE posts DROP COLUMN embed_id')
        conn.execute('UPDATE schema_version SET version=10')
    db.init()
    db.init()
    def listing(**params):
        return [(row['id'], row['key']) for row in client.get('/api/v1/posts', params=params).json()['items']]
    assert listing() == [(first, 'x:1')]
    assert listing(publishers='x:selected') == [(second, 'x:1')]
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (first,))
    assert listing() == [(second, 'x:1')]
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=0 WHERE id=?', (first,))
        conn.execute("UPDATE posts SET platform='instagram',url='https://instagram.com/p/1/' WHERE id=?", (second,))
    assert listing() == [(second, 'instagram:1'), (first, 'x:1')]
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET url='https://x.com/profile' WHERE id=?", (second,))
    assert listing(sort='oldest') == [(first, 'x:1'), (second, f'instagram:record:{second}')]
    with sqlite3.connect(db.DATA / 'gallery.sqlite3') as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


@pytest.mark.parametrize('sort', ['newest', 'oldest'])
def test_dense_gallery_date_spans_pages_and_falls_through_to_other_dates(client, sort):
    with db.connect(True) as conn:
        for _ in range(35):
            image(conn)
        image(conn, date='2024-01-01')
        image(conn, date='2027-01-01')
    params = dict(limit=4, sort=sort, publishers='x:alice')
    while True:
        exact = client.get('/api/v1/gallery', params=params).json()
        indexed = client.get('/api/v1/gallery', params={**params, 'include_total': False}).json()
        assert indexed == {**exact, 'total': None}
        if not exact['next_cursor']:
            break
        params['cursor'] = exact['next_cursor']


def test_admin_page_reads_are_bounded(client, monkeypatch):
    with db.connect(True) as conn:
        for number in range(60):
            first = image(conn)
            group = conn.execute('SELECT group_id FROM images WHERE id=?', (first,)).fetchone()[0]
            second = image(conn, group=group)
            conn.execute("INSERT INTO duplicate_decisions VALUES(?,?,'pending',1)", (first, second))
            conn.execute('UPDATE images SET hidden=1 WHERE id=?', (image(conn),))
            conn.execute('INSERT INTO people(name) VALUES(?)', (f'person{number}',))
    statements = []

    @contextmanager
    def traced_connect():
        with db.connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    monkeypatch.setattr(main, 'connect', traced_connect)
    for size in (1, 50):
        for path in ('/admin/images', '/admin/duplicates', '/admin/trash', '/people'):
            statements.clear()
            result = client.get('/api/v1' + path, params={'page': 1, 'page_size': size}).json()
            if isinstance(result, list):
                assert len(result) == 60
            else:
                assert result['total'] == 60 and len(result['items']) == size
            assert sum(sql.lstrip().upper().startswith(('SELECT', 'WITH')) for sql in statements) <= 10
    legacy = client.get('/api/v1/admin/duplicates').json()
    tail = client.get('/api/v1/admin/duplicates?page=99').json()
    assert tail['items'] == legacy[50:] and tail['page'] == 2
