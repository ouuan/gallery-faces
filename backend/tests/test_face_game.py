import json

import pytest

from app import db
from test_photo_draw import photo
from test_workflows import client


GAME = '/api/v1/gallery/face-game'


def seed(conn):
    conn.executemany('INSERT INTO people(id,name) VALUES(?,?)', [(index, f'人{index}') for index in range(1, 9)])
    identifier = photo(conn)
    ranked = [{'person_id': person, 'score': score} for person, score in [(5, .8), (8, .9), (3, .7), (4, .6), (6, .5)]]
    conn.execute('UPDATE faces SET person_id=1,locked=1,candidates=? WHERE image_id=?', (json.dumps(ranked), identifier))
    return identifier


@pytest.mark.parametrize(('scope', 'expected'), [('', {1, 8, 5, 3}), ('1,2,3,4', {1, 2, 3, 4}),
                                                ('1,2', {1, 2, 8, 5}), ('1', {1, 8, 5, 3})])
def test_choices_and_public_payload(client, monkeypatch, scope, expected):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: .1)
    with db.connect(True) as conn:
        target = seed(conn)
    response = client.get(GAME, params={'people': scope})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    question = response.json()
    assert question['image_id'] == target and question['face']['locked']
    assert len(question['choices']) == 4 and {item['id'] for item in question['choices']} == expected
    assert set(question['face']) == {'id', 'box', 'person_id', 'locked', 'revision'}
    assert all(set(item) == {'id', 'name'} for item in question['choices'])


@pytest.mark.parametrize(('scope', 'expected'), [('', {8, 5, 3, 4}), ('1,2', {2, 8, 5, 3}),
                                                ('1,2,3,4,6', {2, 3, 4, 6})])
def test_omit_recognition_with_four_alternatives(client, monkeypatch, scope, expected):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: .0999)
    with db.connect(True) as conn:
        seed(conn)
    question = client.get(GAME, params={'people': scope}).json()
    assert question['face']['person_id'] == 1
    assert {choice['id'] for choice in question['choices']} == expected


def test_keep_recognition_without_four_distinct_alternatives(client, monkeypatch):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: 0)
    with db.connect(True) as conn:
        seed(conn)
        ranked = [{'person_id': person, 'score': .8} for person in [1, 2, 2, 3, 4]]
        conn.execute('UPDATE faces SET candidates=?', (json.dumps(ranked),))
    choices = client.get(GAME, params={'people': '1,2'}).json()['choices']
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
        question = client.get(GAME, params={'people': '1', 'match': match}).json()
        assert question['image_id'] == target and question['face']['person_id'] == 1
    for match in ('subset', 'exact'):
        assert client.get(GAME, params={'people': '1', 'match': match}).status_code == 404
    first = client.get(GAME, params={'publishers': 'x:alice'}).json()
    assert client.get(GAME, params={'last_group': target}).json()['image_id'] == other
    second = client.get(GAME, params={'last_face': first['face']['id'], 'publishers': 'x:alice'}).json()
    assert second['image_id'] == target and first['face']['id'] != second['face']['id']
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1 WHERE person_id IS NOT NULL')
    assert client.get(GAME, params={'include_no_faces': 'true'}).status_code == 404


def test_skips_unavailable_and_nonrepresentative(client):
    with db.connect(True) as conn:
        target = seed(conn)
        photo(conn, group=target)
        other = photo(conn)
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id!=?', (target,))
    assert client.get(GAME, params={'people': '2'}).json()['image_id'] == other
    (db.DATA / 'images' / f'{other}.jpg').unlink()
    assert client.get(GAME, params={'last_group': target}).json()['image_id'] == target
    with db.connect(True) as conn:
        conn.execute("UPDATE faces SET candidates='[]'")
    assert client.get(GAME, params={'people': '1'}).json()['choices'] == [{'id': 1, 'name': '人1'}]


@pytest.mark.parametrize('not_face', [True, False])
def test_feedback_apply_and_undo(client, not_face):
    with db.connect(True) as conn:
        target = seed(conn)
    face = client.get(GAME).json()['face']
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
    assert client.get(GAME).json()['face']['person_id'] == 1


def test_feedback_cannot_retarget(client):
    with db.connect(True) as conn:
        target = seed(conn)
        other = photo(conn)
    face = client.get(GAME).json()['face']
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
