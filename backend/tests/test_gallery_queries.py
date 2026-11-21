from contextlib import contextmanager

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
