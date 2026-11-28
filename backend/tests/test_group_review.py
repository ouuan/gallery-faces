"""Review records belong to physical images; presentation follows representatives."""
import json
import pytest
from PIL import Image
from app import db, importer
from test_workflows import client, image, recycle
from test_trash import photo, run_restore


def seed():
    with db.connect(True) as conn:
        small = image(conn)
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (small,)).fetchone()[0]
        large = image(conn, group=group)
        conn.execute('UPDATE images SET file_size=100 WHERE id=?', (small,))
        conn.execute('UPDATE images SET file_size=200 WHERE id=?', (large,))
        alice = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
        bob = conn.execute("INSERT INTO people(name) VALUES('Bob')").lastrowid
        conn.execute('UPDATE faces SET person_id=? WHERE image_id=?', (alice, small))
        conn.execute('UPDATE faces SET person_id=? WHERE image_id=?', (bob, large))
    return small, large, group, alice, bob


def listing(client, state='review', **params):
    result = client.get('/api/v1/admin/images', params={'state': state, **params})
    assert result.status_code == 200, result.text
    return result.json()


def test_review_sort_before_pagination(client):
    member, rep, _, person, other = seed()
    with db.connect(True) as conn:
        missing = image(conn, date=None)
        later = image(conn, date='2026-02-01T00:00:00Z')
        tied = image(conn, date='2026-02-01T00:00:00Z')
        conn.execute("UPDATE posts SET published_at='2026-03-01T00:00:00Z' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (rep,))
        for image_id, score in [(member, 0.1), (rep, 0.9), (later, 0.7), (tied, 0.7)]:
            conn.execute('UPDATE faces SET person_id=?,candidates=? WHERE image_id=?',
                         (person, json.dumps([{'person_id': person, 'score': score}]), image_id))
        conn.execute('UPDATE faces SET candidates=? WHERE image_id=?',
                     (json.dumps([{'person_id': other, 'score': 0.95}, {'person_id': person, 'score': 0.7}]), later))
        conn.execute('UPDATE faces SET person_id=?,candidates=? WHERE image_id=?',
                     (person, json.dumps([{'person_id': other, 'score': 0.1}]), missing))
        for image_id, score, locked, ignored, identity in [
            (rep, 0.8, 0, 0, person), (tied, 0.6, 0, 0, person), (rep, 0.1, 1, 0, person),
            (rep, 0.2, 0, 1, person), (rep, 0.3, 0, 0, None),
        ]:
            conn.execute("INSERT INTO faces(image_id,box,person_id,candidates,locked,ignored) VALUES(?,'[0,0,10,10]',?,?,?,?)",
                         (image_id, identity, json.dumps([{'person_id': person, 'score': score}]), locked, ignored))
    for sort, expected in [('default', [rep, missing, later, tied]), ('newest', [later, tied, rep, missing]),
                           ('oldest', [rep, later, tied, missing]), ('confidence', [tied, later, rep, missing])]:
        pages = [listing(client, 'all', sort=sort, page=number, page_size=2) for number in (1, 2)]
        assert [item['id'] for page in pages for item in page['items']] == expected


def test_confirm_only_representative_and_resolve_member_links(client):
    small, large, group, alice, bob = seed()
    rows = listing(client)
    assert len(rows) == 1
    assert (rows[0]['id'], rows[0]['group_id'], rows[0]['member_count']) == (large, group, 2)
    assert rows[0]['member_ids'] == [small, large]
    assert listing(client, 'all', image_id=small)[0]['id'] == large
    assert {face['image_id'] for face in rows[0]['faces']} == {large}
    face = rows[0]['faces'][0]
    assert client.put(f"/api/v1/admin/faces/{face['id']}", json={'revision': 0, 'person_id': bob}).status_code == 200
    assert listing(client) == []
    with db.connect() as conn:
        assert conn.execute('SELECT person_id,locked,revision FROM faces WHERE image_id=?', (small,)).fetchone()[:] == (alice, 0, 0)
        assert conn.execute('SELECT count(*) FROM review_history').fetchone()[0] == 1
    assert client.post(f"/api/v1/admin/faces/{face['id']}/undo").status_code == 200
    assert listing(client)[0]['id'] == large


@pytest.mark.parametrize('state', ['unknown', 'no_faces', 'pending', 'failed'])
def test_member_face_problems_do_not_change_representative(client, state):
    small, large, _, _, _ = seed()
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=1 WHERE image_id=?', (large,))
        if state == 'unknown':
            conn.execute('UPDATE faces SET person_id=NULL WHERE image_id=?', (small,))
        elif state == 'no_faces':
            conn.execute('DELETE FROM faces WHERE image_id=?', (small,))
        else:
            conn.execute('UPDATE images SET detection=? WHERE id=?', (state, small))
    assert listing(client, state) == []
    assert listing(client) == []


def test_sources_feedback_grouped_without_changing_ownership(client):
    small, large, group, _, _ = seed()
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=1')
        hidden = image(conn, group=group)
        conn.execute('UPDATE images SET hidden=1,file_size=999 WHERE id=?', (hidden,))
        post = conn.execute('SELECT post_id FROM sources WHERE image_id=?', (small,)).fetchone()[0]
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,?)', (large, post, 'shared'))
        conn.execute('UPDATE posts SET author=NULL WHERE id=?', (post,))
        feedback = [conn.execute("INSERT INTO feedback(image_id,content) VALUES(?,?)", (i, str(i))).lastrowid for i in [small, large, hidden]]
    item = listing(client)[0]
    assert item['id'] == large and item['member_count'] == 2
    assert item['incomplete_image_ids'] == [small]
    assert item['pending_feedback_count'] == 2
    assert next(s for s in item['sources'] if s['id'] == post)['image_ids'] == [small, large]
    assert len(item['sources']) == 2
    assert listing(client, 'incomplete')[0]['id'] == large
    assert listing(client, 'feedback')[0]['id'] == large
    endpoint = f'/api/v1/admin/images/{large}/feedback'
    assert [f['id'] for f in client.get(endpoint).json()['items']] == [feedback[1]]
    first = client.get(endpoint, params={'scope': 'group', 'limit': 1}).json()
    second = client.get(endpoint, params={'scope': 'group', 'before_id': first['next_cursor'], 'limit': 1}).json()
    assert [first['items'][0]['image_id'], second['items'][0]['image_id']] == [large, small]
    assert second['next_cursor'] is None
    for identifier in feedback[:2]:
        assert client.put(f'/api/v1/admin/feedback/{identifier}', json={'status': 'resolved'}).status_code == 200
    assert listing(client, 'feedback') == []
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET author='alice' WHERE id=?", (post,))
    assert listing(client) == []
    assert listing(client, 'hidden')[0]['id'] == hidden


def test_public_labels_filters_and_no_faces_use_same_representative(client):
    small, large, group, alice, bob = seed()
    def gallery(**params):
        return client.get('/api/v1/gallery', params=params).json()['items']
    assert client.get(f'/api/v1/gallery/{group}').json()['people'] == [{'id': bob, 'name': 'Bob'}]
    assert gallery(people=str(alice)) == []
    assert gallery(people=str(bob))[0]['image_id'] == large
    assert gallery(people=f'{alice},{bob}', match='all') == []
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET author='bob' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (large,))
    assert gallery(publishers='x:alice')[0]['image_id'] == large
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1 WHERE image_id=?', (large,))
    assert gallery() == []
    assert gallery(include_no_faces='true')[0]['people'] == []
    assert listing(client, 'no_faces')[0]['id'] == large


@pytest.mark.parametrize('unready', ['pending', 'failed', 'incomplete'])
def test_public_falls_back_until_largest_is_eligible(client, unready):
    small, large, group, alice, bob = seed()
    with db.connect(True) as conn:
        if unready == 'incomplete':
            conn.execute('UPDATE posts SET author=NULL WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)', (large,))
        else:
            conn.execute('UPDATE images SET detection=? WHERE id=?', (unready, large))
    assert listing(client)[0]['id'] == large
    assert listing(client, unready)[0]['id'] == large
    detail = client.get(f'/api/v1/gallery/{group}').json()
    assert detail['image_id'] == small and detail['people'][0]['id'] == alice
    assert client.get('/api/v1/gallery', params={'people': bob}).json()['items'] == []
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (large,))
        conn.execute("UPDATE posts SET author='alice' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (large,))
    assert client.get(f'/api/v1/gallery/{group}').json()['image_id'] == large


@pytest.mark.parametrize('split_largest', [False, True])
def test_merge_split_and_size_ties_keep_physical_results(client, split_largest):
    small, large, group, alice, bob = seed()
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=1')
        conn.execute('UPDATE images SET file_size=200 WHERE id=?', (small,))
    assert listing(client, 'all')[0]['id'] == small
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET file_size=300 WHERE id=?', (large,))
        before = [tuple(row) for row in conn.execute('SELECT * FROM faces ORDER BY id')]
    assert listing(client, 'all')[0]['id'] == large
    a, b = (small, large) if split_largest else (large, small)
    assert client.post('/api/v1/admin/duplicates', json={'a': a, 'b': b, 'action': 'separate'}).status_code == 200
    assert {row['id'] for row in listing(client, 'all')} == {small, large}
    assert client.get(f'/api/v1/gallery/{group}').json()['people'][0]['id'] == (alice if split_largest else bob)
    assert client.post('/api/v1/admin/duplicates', json={'a': a, 'b': b, 'action': 'merge'}).status_code == 200
    assert listing(client) == []
    assert listing(client, 'all')[0]['faces'][0]['person_id'] == bob
    with db.connect() as conn:
        assert [tuple(row) for row in conn.execute('SELECT * FROM faces ORDER BY id')] == before


def test_replacement_rejects_stale_mutations_and_batch_preserves_failures(client):
    small, large, _, _, bob = seed()
    with db.connect() as conn:
        faces = {row['image_id']: row['id'] for row in conn.execute('SELECT id,image_id FROM faces')}
    stale = faces[small]
    edits = [
        ('put', f'/api/v1/admin/faces/{stale}', {'revision': 0, 'person_id': bob}),
        ('post', f'/api/v1/admin/faces/{stale}/undo', {}),
        ('post', f'/api/v1/admin/faces/{stale}/person', {'name': 'New', 'revision': 0, 'add_reference': False}),
        ('post', f'/api/v1/admin/images/{small}/faces', {'box': [1, 1, 5, 5]}),
        ('post', '/api/v1/admin/images/actions', {'action': 'redetect', 'ids': [large, small]}),
    ]
    for method, url, body in edits:
        response = getattr(client, method)(url, json=body)
        assert response.status_code == 409, response.text
        assert '代表图' in response.json()['detail']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM people').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM review_history').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    response = client.put('/api/v1/admin/faces', json={'faces': [
        {'id': faces[i], 'revision': 0, 'person_id': bob} for i in [small, large]
    ]}).json()
    assert response['saved'] == [faces[large]]
    assert response['failures'][0]['id'] == stale and response['failures'][0]['status'] == 409


def test_large_group_not_truncated_before_group_limit(client):
    _, large, group, _, _ = seed()
    with db.connect(True) as conn:
        for _ in range(505):
            image(conn, group=group)
        for _ in range(500):
            image(conn)
        conn.execute('UPDATE faces SET locked=1 WHERE image_id=?', (large,))
    rows = listing(client, 'all')
    assert len(rows) == 500
    assert rows[0]['member_count'] == 507
    assert len(rows[0]['sources']) == len(rows[0]['member_ids']) == 507
    assert rows[0]['id'] == large
    assert len(listing(client)) == 500
    last = listing(client, 'all', page=11)
    assert (last['total'], last['page'], last['page_size']) == (501, 11, 50)
    assert len(last['items']) == 1 and last['items'][0]['group_id'] > rows[-1]['group_id']
    assert listing(client, page=11)['page'] == 10
    assert listing(client, 'failed', page=2) == {'items': [], 'total': 0, 'page': 1, 'page_size': 50}


def test_import_new_copy_and_selective_restore(client, tmp_path, monkeypatch):
    monkeypatch.setattr(importer, 'IMPORT', tmp_path)
    deduplicate = importer.deduplicate
    first, _, _ = photo(tmp_path, monkeypatch, '1', 'red')
    with db.connect(True) as conn:
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (first,)).fetchone()[0]
        conn.execute("INSERT INTO faces(image_id,box,locked) VALUES(?,'[0,0,10,10]',1)", (first,))
    assert listing(client) == []
    monkeypatch.setattr(importer, 'deduplicate', deduplicate)
    monkeypatch.setattr(importer, 'phash', lambda _: '0')
    monkeypatch.setattr(importer, 'similarity', lambda *_: 1)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET phash='0' WHERE id=?", (first,))
    path = tmp_path / 'larger.png'
    Image.new('RGB', (128, 96), 'red').save(path)
    second = importer.import_file(path, {'category': 'twitter', 'tweet_id': '2', 'num': 1,
        'author': {'name': 'alice'}, 'date': '2026-01-01T00:00:00Z'})
    with db.connect() as conn:
        assert conn.execute('SELECT group_id FROM images WHERE id=?', (second,)).fetchone()[0] == group
    assert listing(client)[0]['id'] == second
    assert recycle(client, [first]).json()['deleted'] == 2
    assert listing(client, 'all') == []
    assert run_restore(client, first)['status'] == 'done'
    assert listing(client) == []
    assert listing(client, 'all')[0]['id'] == first
    assert run_restore(client, second)['status'] == 'done'
    with db.connect() as conn:
        expected = conn.execute('SELECT id FROM images WHERE hidden=0 ORDER BY file_size DESC,id LIMIT 1').fetchone()[0]
        assert conn.execute('SELECT locked FROM faces WHERE image_id=?', (first,)).fetchone()[0] == 1
    assert expected == second
    assert listing(client, 'all')[0]['id'] == second


def test_review_dates_match_active_member_sources_and_same_post(client):
    small, large, group, _, _ = seed()
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='Asia/Shanghai' WHERE key='timezone'")
        conn.execute("UPDATE posts SET published_at='2026-01-01T16:00:00Z' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (small,))
        hidden = image(conn, date="2026-02-01T00:00:00Z", group=group)
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (hidden,))
        missing = image(conn, date=None)
    assert [row['id'] for row in listing(client, start='2026-01-02T00:00:00+08:00', end='2026-01-03T00:00:00+08:00')] == [large]
    assert listing(client, image_id=small, start='2026-01-02T00:00:00+08:00')[0]['id'] == large
    assert listing(client, start='2026-02-01T00:00:00+08:00') == []
    assert listing(client, end='2026-01-01T00:00:00+08:00') == []
    assert listing(client, start='2026-01-03T00:00:00+08:00', end='2026-02-01T00:00:00+08:00') == []
    assert missing in [row['id'] for row in listing(client)]
    # Both bounds must match a single source, not different sources in the group.
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET published_at='2026-01-03T16:00:00Z' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (small,))
    assert listing(client, start='2026-01-02T00:00:00+08:00', end='2026-01-04T00:00:00+08:00') == []


def test_review_dates_use_exclusive_end_and_validate_range(client):
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='Asia/Shanghai' WHERE key='timezone'")
        before = image(conn, date='2026-01-01T15:59:59Z')
        first = image(conn, date='2026-01-01T16:00:00Z')
        last = image(conn, date='2026-01-02T15:59:59Z')
        after = image(conn, date='2026-01-02T16:00:00Z')
    assert {row['id'] for row in listing(client, start='2026-01-02T00:00:00+08:00', end='2026-01-03T00:00:00+08:00')} == {first, last}
    assert {row['id'] for row in listing(client, end='2026-01-03T00:00:00+08:00')} == {before, first, last}
    assert {row['id'] for row in listing(client, start='2026-01-02T00:00:00+08:00')} == {first, last, after}
    for params in [{'start': '2026-02-30'}, {'end': 'bad'}, {'start': '2026-01-03', 'end': '2026-01-02'}]:
        assert client.get('/api/v1/admin/images', params=params).status_code == 400


def test_repeated_person_counts_only_visible_faces_on_the_representative(client):
    small, large, _, alice, bob = seed()
    with db.connect(True) as conn:
        conn.executemany("INSERT INTO faces(image_id,box,person_id) VALUES(?,'[]',?)",
                         [(small, bob), (small, bob), (large, alice), (large, None), (large, None)])
        extra = conn.execute("INSERT INTO faces(image_id,box,person_id,ignored) VALUES(?,'[]',?,1)",
                             (large, bob)).lastrowid
        conn.execute('UPDATE faces SET locked=1')
    assert listing(client, 'repeated_person') == []
    assert listing(client) == []
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=0,locked=0 WHERE id=?', (extra,))
    assert [row['id'] for row in listing(client, 'repeated_person')] == [large]
    assert [row['id'] for row in listing(client)] == [large]
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=1 WHERE id=?', (extra,))
    assert listing(client, 'repeated_person') == []
    assert listing(client) == []
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=0 WHERE image_id=? AND person_id=?', (large, alice))
    assert listing(client, 'repeated_person') == []
    assert [row['id'] for row in listing(client)] == [large]


def test_game_ineligible_filters_labeled_faces_without_marking_for_review(client):
    small, large, _, alice, bob = seed()
    def scores(person, score):
        return json.dumps([{'person_id': person, 'score': score}])

    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET locked=1')
        conn.execute('UPDATE faces SET candidates=? WHERE image_id=?', (scores(bob, .3), large))
        conn.executemany("INSERT INTO faces(image_id,box,person_id,locked,ignored) VALUES(?,'[]',?,1,?)",
                         [(large, None, 0), (large, alice, 1)])
    assert listing(client, 'game_ineligible') == []
    with db.connect(True) as conn:
        face = conn.execute("INSERT INTO faces(image_id,box,person_id,locked,candidates) VALUES(?,'[]',?,1,?)",
                            (large, alice, scores(alice, .9))).lastrowid
    for feature, candidates in [(None, scores(alice, .9)), (b'x', scores(bob, .9)), (b'x', scores(alice, .299))]:
        with db.connect(True) as conn:
            conn.execute('UPDATE faces SET embedding=?,candidates=? WHERE id=?', (feature, candidates, face))
        result = listing(client, 'game_ineligible', page=1, page_size=1, image_id=small)
        assert result['total'] == 1 and result['items'][0]['id'] == large
        assert [item['id'] for item in result['items'][0]['faces']] == [face]
        assert [item['ignored'] for item in result['items'][0]['deleted_faces']] == [1]
        assert listing(client) == []
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0.299' WHERE key='face_game_threshold'")
    assert listing(client, 'game_ineligible') == []
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0' WHERE key='face_game_threshold'")
        conn.execute("UPDATE faces SET candidates='[]' WHERE id=?", (face,))
    assert [row['id'] for row in listing(client, 'game_ineligible')] == [large]


def test_review_people_use_representative_and_ignore_ignored_faces(client):
    small, large, _, alice, bob = seed()
    assert listing(client, people=str(alice)) == []
    assert listing(client, people=str(bob))[0]['id'] == large
    assert listing(client, people=f'{alice},{bob}', match='any')[0]['id'] == large
    assert listing(client, people=f'{alice},{bob}', match='all') == []
    with db.connect(True) as conn:
        conn.execute("INSERT INTO faces(image_id,box,person_id) VALUES(?, '[0,0,10,10]', ?)", (large, alice))
    assert listing(client, people=f'{alice},{bob}', match='all')[0]['id'] == large
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1 WHERE image_id=? AND person_id=?', (large, alice))
    assert listing(client, people=f'{alice},{bob}', match='all') == []


def test_review_publisher_and_date_match_same_source(client):
    small, large, _, alice, bob = seed()
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='UTC' WHERE key='timezone'")
        conn.execute("UPDATE posts SET author='bob', published_at='2026-02-01T00:00:00Z' WHERE id IN (SELECT post_id FROM sources WHERE image_id=?)", (small,))
        conn.execute("INSERT INTO accounts(person_id,platform,username) VALUES(?,'x','BOB')", (bob,))
    assert listing(client, publishers='x:Bob')[0]['id'] == large
    assert listing(client, publishers=f'person:{bob}', people=str(bob), start='2026-02-01T00:00:00+08:00')[0]['id'] == large
    assert listing(client, publishers='x:alice', start='2026-02-01T00:00:00+08:00') == []
    assert listing(client, publishers=f'person:{alice}') == []
    assert listing(client, publishers='instagram:bob') == []
    for params in [{'people':'bad'}, {'people':'-1'}, {'publishers':'person:bad'}, {'publishers':'invalid:alice'}, {'match':'bad'}]:
        assert client.get('/api/v1/admin/images', params=params).status_code in (400, 422)
