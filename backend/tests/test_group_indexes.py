import pytest

from app import db, group_index, list_queries
from test_workflows import client, image


def contents(conn):
    return {table: [tuple(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1,2')]
            for scope in group_index.SCOPES for table in
            (f'{scope}_groups', f'{scope}_group_people', f'{scope}_group_posts')}


def assert_matches_rebuild():
    with db.connect(True) as conn:
        before = contents(conn)
        conn.execute('INSERT INTO dirty_groups SELECT id FROM duplicate_groups')
        group_index.refresh(conn)
        assert contents(conn) == before
        assert not conn.execute('SELECT 1 FROM dirty_groups').fetchone()


def test_incremental_indexes_follow_members_sources_faces_and_feedback(client):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn)
        third = image(conn, group=first)
        conn.execute("INSERT INTO people VALUES(1,'one',NULL)")
        conn.execute('UPDATE faces SET person_id=1,locked=1')
        conn.execute('UPDATE images SET file_size=100 WHERE id=?', (third,))
        conn.execute('UPDATE posts SET url=NULL WHERE id=?', (third,))
        conn.execute("INSERT INTO feedback(image_id,content) VALUES(?,'check')", (first,))
    assert_matches_rebuild()
    with db.connect() as conn:
        assert tuple(conn.execute('SELECT representative,first_post FROM public_groups WHERE group_id=?', (first,)).fetchone()) == (first, first)
        assert tuple(conn.execute('SELECT representative,incomplete,feedback FROM review_groups WHERE group_id=?', (first,)).fetchone()) == (third, 1, 1)
    for sql, args in (
        ('UPDATE images SET group_id=? WHERE id=?', (second, third)),
        ('UPDATE sources SET image_id=? WHERE post_id=?', (third, first)),
        ('UPDATE faces SET image_id=?,ignored=1 WHERE image_id=?', (first, third)),
        ("UPDATE feedback SET image_id=?,status='resolved'", (second,)),
        ("UPDATE posts SET url='https://x.com/a/status/1',published_at='2000-01-01' WHERE id=?", (third,)),
        ('DELETE FROM people WHERE id=1', ()),
        ('UPDATE images SET group_id=? WHERE id=?', (first, third)),
        ('UPDATE images SET hidden=1', ()),
        ('UPDATE images SET hidden=0', ()),
        ('DELETE FROM sources WHERE image_id=?', (third,)),
    ):
        with db.connect(True) as conn:
            conn.execute(sql, args)
        assert_matches_rebuild()


def test_people_photo_counts_match_public_gallery_groups(client):
    with db.connect(True) as conn:
        conn.execute("INSERT INTO people(id,name) VALUES(1,'one'),(2,'two')")
        first = image(conn)
        image(conn, group=first)
        image(conn)
        image(conn, author=None)
        conn.execute('UPDATE faces SET person_id=1')
        conn.execute("INSERT INTO faces(image_id,box,person_id) VALUES(?,'[]',1)", (first,))
    people = client.get('/api/v1/people').json()
    for person, expected in zip(people, [2, 0], strict=True):
        gallery = client.get('/api/v1/gallery', params={'people': person['id']}).json()
        assert person['photo_group_count'] == gallery['total'] == expected


def test_refresh_is_atomic_for_readers_and_savepoints(client, monkeypatch):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn)
    with db.connect() as reader:
        reader.execute('BEGIN')
        assert len(contents(reader)['public_groups']) == 2
        with db.connect(True) as writer:
            writer.execute('SAVEPOINT edit')
            writer.execute('UPDATE images SET hidden=1 WHERE id=?', (second,))
            writer.execute('ROLLBACK TO edit')
            writer.execute('UPDATE images SET hidden=1 WHERE id=?', (first,))
            assert [row[0] for row in writer.execute('SELECT * FROM dirty_groups')] == [first]
        assert len(contents(reader)['public_groups']) == 2
    with db.connect() as conn:
        assert [row[0] for row in conn.execute('SELECT group_id FROM public_groups')] == [second]

    def fail_after_refresh(conn):
        refresh(conn)
        raise RuntimeError('failure before commit')

    refresh = group_index.refresh
    with monkeypatch.context() as patch:
        patch.setattr(group_index, 'refresh', fail_after_refresh)
        with pytest.raises(RuntimeError, match='before commit'), db.connect(True) as conn:
            conn.execute('UPDATE images SET hidden=0 WHERE id=?', (first,))
    with db.connect() as conn:
        assert conn.execute('SELECT hidden FROM images WHERE id=?', (first,)).fetchone()[0] == 1
    assert_matches_rebuild()


def test_v14_migration_rolls_back_and_restarts_once(client, monkeypatch):
    with db.connect(True) as conn:
        image(conn)
    with db.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for name, in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name GLOB 'dirty_*'").fetchall():
            conn.execute(f'DROP TRIGGER {name}')
        for table in contents(conn):
            conn.execute(f'DROP TABLE {table}')
        conn.execute('DROP TABLE dirty_groups')
        conn.execute('UPDATE schema_version SET version=13')

    def interrupt(conn):
        assert conn.execute('SELECT count(*) FROM dirty_groups').fetchone()[0] == 1
        raise RuntimeError('interrupted migration')

    with monkeypatch.context() as patch:
        patch.setattr(group_index, 'refresh', interrupt)
        with pytest.raises(RuntimeError, match='interrupted migration'):
            db.init()
    with db.connect() as conn:
        assert conn.execute('SELECT version FROM schema_version').fetchone()[0] == 13
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='dirty_groups'").fetchone()
    db.init()
    monkeypatch.setattr(group_index, 'install', lambda _: pytest.fail('unnecessary rebuild'))
    db.init()
    assert client.get('/api/v1/gallery').json()['total'] == 1


def test_post_candidate_boundary_with_aliases_and_cursors(client, monkeypatch):
    with db.connect(True) as conn:
        conn.execute("INSERT INTO people(name) VALUES('one')")
        for _ in range(512):
            image(conn)
        conn.execute('UPDATE faces SET person_id=1')
        conn.execute("UPDATE posts SET url=(SELECT url FROM posts WHERE id=1) WHERE id=512")
    for size in (512, 513):
        if size == 513:
            with db.connect(True) as conn:
                last = image(conn)
                conn.execute('UPDATE faces SET person_id=1 WHERE image_id=?', (last,))
        for filters in ({'people': '1', 'match': 'exact'}, {'publishers': 'x:ALICE'}):
            params = dict(**filters, limit=40, sort='newest')
            for _ in range(2):
                actual = client.get('/api/v1/posts', params=params).json()
                with monkeypatch.context() as patch:
                    patch.setattr(list_queries, 'SPARSE_LIMIT', 0 if size == 512 else 513)
                    assert client.get('/api/v1/posts', params=params).json() == actual
                assert 512 not in [item['id'] for item in actual['items']]
                params['cursor'] = actual['next_cursor']


def test_bulk_rematch_preserves_running_and_queued_work(client):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn, group=first)
        finished = image(conn)
        hidden = image(conn)
        locked = image(conn)
        ignored = image(conn)
        empty = image(conn)
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (hidden,))
        conn.execute('UPDATE faces SET locked=1 WHERE image_id=?', (locked,))
        conn.execute('UPDATE faces SET ignored=1 WHERE image_id=?', (ignored,))
        conn.execute("UPDATE faces SET embedding=x'' WHERE image_id=?", (empty,))
        conn.execute("INSERT INTO faces(image_id,box,embedding) VALUES(?,'[]',x'01')", (first,))
        for target, status in [(first, 'running'), (second, 'queued'), (finished, 'done')]:
            conn.execute("INSERT INTO tasks(kind,image_id,status,queue_rank_at,done,processed_version) VALUES('rematch',?,?,42,3,10)", (target, status))
        columns = 'id,image_id,status,queue_rank_at,done,processed_version'
        existing = [tuple(row) for row in conn.execute(f'SELECT {columns} FROM tasks ORDER BY id')]
        db.schedule_rematch(conn)
        db.schedule_rematch(conn)
        assert [tuple(row) for row in conn.execute(f'SELECT {columns} FROM tasks ORDER BY id LIMIT 3')] == existing
        active = list(conn.execute("SELECT image_id,target_version FROM tasks WHERE status IN ('running','queued') ORDER BY image_id"))
        assert [tuple(row) for row in active] == [(first, 2), (second, 2), (finished, 2)]
