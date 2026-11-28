import json
import random
from collections import Counter

import pytest
from fastapi import HTTPException

from app import db, face_draw, game_rooms, main, photo_draw
from test_photo_draw import photo
from test_workflows import client


def draw(last_group=None, last_face=None, **filters):
    with main.MediaRead() as reads:
        return main.draw_game_question(reads, main.game_scope(game_rooms.GameFilters(**filters)), last_group, last_face)


def seed(conn):
    conn.executemany('INSERT INTO people(id,name) VALUES(?,?)', [(index, f'人{index}') for index in range(1, 9)])
    identifier = photo(conn)
    ranked = [{'person_id': person, 'score': score} for person, score in [(5, .8), (8, .9), (3, .7), (4, .6), (6, .5)]]
    conn.execute('UPDATE faces SET person_id=1,locked=1,candidates=? WHERE image_id=?', (json.dumps(ranked), identifier))
    return identifier


@pytest.mark.parametrize(('scope', 'expected'), [('', {1, 8, 5, 2}), ('1,2,3,4', {1, 2, 3, 4}),
                                                ('1,2,3', {1, 2, 3}), ('1,2', {1, 2}), ('1', {1})])
def test_choices(client, monkeypatch, scope, expected):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: .1)
    monkeypatch.setattr('app.photo_draw.random.sample', lambda population, count: population[:count])
    with db.connect(True) as conn:
        target = seed(conn)
    question = draw(people=scope)
    assert question['image_id'] == target and question['face']['locked']
    assert [item['id'] for item in question['choices']] == sorted(expected)
    assert all(set(item) == {'id', 'name'} for item in question['choices'])


@pytest.mark.parametrize(('scope', 'expected'), [('', {8, 5, 3, 2}),
                                                ('1,2,3,4,6', {2, 3, 4, 6})])
def test_omit_recognition_with_four_alternatives(client, monkeypatch, scope, expected):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: .0999)
    monkeypatch.setattr('app.photo_draw.random.sample', lambda population, count: population[:count])
    with db.connect(True) as conn:
        seed(conn)
    question = draw(people=scope)
    assert question['face']['person_id'] == 1
    assert [choice['id'] for choice in question['choices']] == sorted(expected)


def test_keep_recognition_without_four_distinct_alternatives(client, monkeypatch):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: 0)
    with db.connect(True) as conn:
        seed(conn)
        ranked = [{'person_id': person, 'score': .8} for person in [1, 2, 2, 3, 4]]
        conn.execute('UPDATE faces SET candidates=?', (json.dumps(ranked),))
    choices = draw(people='1,2,3,4')['choices']
    assert {choice['id'] for choice in choices} == {1, 2, 3, 4}


def test_filters_rotation_and_empty(client):
    with db.connect(True) as conn:
        target = seed(conn)
        other = photo(conn, author='bob')
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id=?', (other,))
        conn.execute("INSERT INTO faces(image_id,box,person_id) VALUES(?,'[20,20,5,5]',2)", (target,))
        photo(conn, faces=False)
        photo(conn)
    for match in ('any', 'all'):
        question = draw(people='1', match=match)
        assert question['image_id'] == target and question['face']['person_id'] == 1
    for match in ('subset', 'exact'):
        with pytest.raises(HTTPException) as empty:
            draw(people='1', match=match)
        assert empty.value.status_code == 404
    first = draw(publishers='x:alice')
    assert draw(last_group=target)['image_id'] == other
    second = draw(last_face=first['face']['id'], publishers='x:alice')
    assert second['image_id'] == target and first['face']['id'] != second['face']['id']
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1 WHERE person_id IS NOT NULL')
    with pytest.raises(HTTPException) as empty:
        draw(include_no_faces=True)
    assert empty.value.status_code == 404


def test_skips_unavailable_and_nonrepresentative(client):
    with db.connect(True) as conn:
        target = seed(conn)
        photo(conn, group=target)
        other = photo(conn)
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id!=?', (target,))
    assert draw(people='2')['image_id'] == other
    (db.DATA / 'images' / f'{other}.jpg').unlink()
    assert draw(last_group=target)['image_id'] == target
    with db.connect(True) as conn:
        conn.execute("UPDATE faces SET candidates='[]'")
    assert draw(people='1')['choices'] == [{'id': 1, 'name': '人1'}]


@pytest.mark.parametrize('filters', [{}, {'publishers': 'x:alice'}, {'people': '1,2', 'match': 'subset'}])
def test_person_then_group_are_uniform(client, filters):
    with db.connect(True) as conn:
        common = [seed(conn)] + [photo(conn) for _ in range(9)]
        conn.execute('UPDATE faces SET person_id=1')
        for group in common[:2]:
            for _ in range(5 if group == common[0] else 1):
                conn.execute("INSERT INTO faces(image_id,person_id,box) VALUES(?,2,'[]')", (group,))
    scope = main.game_scope(game_rooms.GameFilters(**filters))
    with db.connect() as conn:
        rng = random.Random(426)
        conn.create_function('random', 0, lambda: rng.getrandbits(63))
        draws = Counter(tuple(face_draw.first_candidate(conn, scope, None))[:2] for _ in range(2000))
    assert set(draws) == {(1, group) for group in common} | {(2, group) for group in common[:2]}
    for (person, _), count in draws.items():
        expected = 100 if person == 1 else 500
        assert abs(count - expected) < expected * .35


@pytest.mark.parametrize('mode', ['any', 'all', 'subset', 'exact'])
def test_filtered_person_group_pairs(client, mode):
    with db.connect(True) as conn:
        first = seed(conn)
        conn.execute("INSERT INTO accounts(person_id,platform,username) VALUES(1,'x','ALICE')")
        second = photo(conn)
        solo = photo(conn)
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id=?', (solo,))
        for person in [2, 3]:
            conn.execute("INSERT INTO faces(image_id,person_id,box) VALUES(?,?,'[]')", (first, person))
        for person in [1, 2, 3, 4]:
            conn.execute("INSERT INTO faces(image_id,person_id,box) VALUES(?,?,'[]')", (second, person))
        extra = photo(conn, author='alice', date='2025-01-01T00:00:00Z')
        photo(conn, group=extra, author='bob', date='2026-01-01T00:00:00Z')
        conn.execute('UPDATE faces SET person_id=3 WHERE image_id=?', (extra,))
    scope = main.game_scope(game_rooms.GameFilters(people='1-3', match=mode, publishers='person:1,x:absent',
                            start='2026-01-01T00:00:00Z', end='2026-01-02T00:00:00Z', include_no_faces=True))
    expected = {(person, first) for person in (1, 2, 3)}
    if mode in ('any', 'subset'):
        expected.add((2, solo))
    if mode in ('any', 'all'):
        expected.update((person, second) for person in (1, 2, 3))
    candidates = {(person, group) for person, group, _ in face_draw.candidates(scope, None, None)}
    assert candidates == expected


def test_retry_same_person_before_others_and_previous_group(client, monkeypatch):
    with db.connect(True) as conn:
        previous = seed(conn)
        missing, same, other = [photo(conn) for _ in range(3)]
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id IN (?,?)', (missing, same))
        conn.execute('UPDATE faces SET person_id=3 WHERE image_id=?', (other,))
        conn.execute("INSERT INTO faces(image_id,person_id,box) VALUES(?,3,'[]')", (missing,))
    monkeypatch.setattr(face_draw, 'first_candidate', lambda *_: (2, missing, missing))
    scope = main.game_scope(game_rooms.GameFilters())
    attempts = []

    def pin(rep):
        attempts.append(rep)
        if rep in unavailable:
            raise HTTPException(404)
        return rep

    for unavailable, expected, person in [({missing}, same, 2), ({missing, same}, other, 3),
                                          ({missing, same, other}, previous, 1)]:
        attempts.clear()
        group, _, face, _ = photo_draw.game_question(scope, previous, None, pin)
        assert attempts[:2] == [missing, same] and attempts[-1] == group == expected
        assert len(attempts) == len(set(attempts)) and face['person_id'] == person


@pytest.mark.parametrize('change', ['person', 'source'])
def test_rechecks_after_pin(client, monkeypatch, change):
    with db.connect(True) as conn:
        changed = seed(conn)
        other = photo(conn)
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id=?', (other,))
    monkeypatch.setattr(face_draw, 'first_candidate', lambda *_: (1, changed, changed))
    scope = main.game_scope(game_rooms.GameFilters(publishers='x:alice'))
    def pin(rep):
        if rep == changed:
            with db.connect(True) as conn:
                if change == 'source':
                    conn.execute("UPDATE posts SET author='bob' WHERE id=?", (changed,))
                else:
                    conn.execute('UPDATE faces SET person_id=NULL WHERE image_id=?', (changed,))
        return rep
    group, _, face, _ = photo_draw.game_question(scope, None, None, pin)
    assert (group, face['person_id']) == (other, 2)


def test_only_previous_group_prefers_another_face_of_same_person(client):
    with db.connect(True) as conn:
        group = seed(conn)
        previous = conn.execute('SELECT id FROM faces WHERE image_id=?', (group,)).fetchone()[0]
        alternate = conn.execute("INSERT INTO faces(image_id,person_id,box) VALUES(?,1,'[1,2,3,4]')", (group,)).lastrowid
    assert draw(group, previous)['face']['id'] == alternate
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1 WHERE id=?', (alternate,))
    assert draw(group, previous)['face']['id'] == previous


@pytest.mark.parametrize('not_face', [True, False])
def test_feedback_apply_and_undo(client, not_face):
    with db.connect(True) as conn:
        target = seed(conn)
    face = draw()['face']
    base = {'face_id': face['id'], 'face_revision': face['revision']}
    path = f'/api/v1/images/{target}/feedback'
    assert client.post(path, json={**base, 'suggested_person_id': 2, 'not_face': True}).status_code == 422
    assert client.post(path, json={'content': '误检', 'not_face': True}).status_code == 422
    assert client.post(path, json={**base, 'face_revision': 8}).status_code == 409
    doubt = client.post(path, json=base).json()
    assert client.post(f"/api/v1/admin/feedback/{doubt['id']}/apply").status_code == 409
    item = client.post(path, json={**base, **({'not_face': True} if not_face else {'suggested_person_id': 2})}).json()
    assert item['original_name'] == '人1' and item['not_face'] is not_face
    apply = f"/api/v1/admin/feedback/{item['id']}/apply"
    assert client.post(apply).status_code == 200
    assert client.post(apply).status_code == 409
    with db.connect() as conn:
        assert tuple(conn.execute('SELECT ignored,person_id,locked FROM faces').fetchone()) == (not_face, None if not_face else 2, 1)
        assert conn.execute('SELECT status FROM feedback WHERE id=?', (item['id'],)).fetchone()[0] == 'resolved'
    assert client.post(f"/api/v1/admin/faces/{face['id']}/undo").status_code == 200
    assert draw()['face']['person_id'] == 1


def test_feedback_cannot_retarget(client):
    with db.connect(True) as conn:
        target = seed(conn)
        other = photo(conn)
    face = draw()['face']
    suggestion = {'face_id': face['id'], 'face_revision': face['revision'], 'suggested_person_id': 2}
    assert client.post(f'/api/v1/images/{other}/feedback', json=suggestion).status_code == 404
    item = client.post(f'/api/v1/images/{target}/feedback', json=suggestion).json()
    apply = f"/api/v1/admin/feedback/{item['id']}/apply"
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET revision=revision+1 WHERE id=?', (face['id'],))
    assert client.post(apply).status_code == 409
    client.delete('/api/v1/admin/people/2')
    assert client.post(apply).status_code == 409
    saved = client.get(f'/api/v1/admin/images/{target}/feedback').json()['items'][0]
    assert saved['suggested_person_id'] is None and saved['suggested_name'] == '人2' and saved['status'] == 'pending'
