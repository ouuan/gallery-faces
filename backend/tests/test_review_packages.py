import asyncio
import io
import json
import time
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app import db, review_packages as packages, review_results as results
from test_workflows import client, image

BASE = '/api/v1/admin/review-packages'


def seed(count=1):
    Image.new('RGB', (100, 100)).save(db.DATA / 'images' / 'fixture.jpg')
    with db.connect(True) as conn:
        return [image(conn) for _ in range(count)]


def export(client, **params):
    response = client.post(BASE + '/exports', json=dict(state='all', **params))
    assert response.status_code == 202, response.text
    batch = response.json()['id']
    for _ in range(200):
        status = client.get(BASE + '/exports/' + batch).json()
        if status['status'] != 'building':
            assert status['status'] == 'ready', status
            break
        time.sleep(0.02)
    else:
        pytest.fail('Package never became ready')
    return batch


def upload(client, batch, ops, files=None):
    raw = json.dumps(dict(version=1, batch=batch, suggestions=ops)).encode()
    name = 'review-result.json'
    if files is not None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for path, data in files.items():
                archive.writestr(path, data)
            archive.writestr(name, raw)
        name, raw = 'result.zip', stream.getvalue()
    return client.post(BASE + '/imports', files={'file': (name, raw)})


def suggestion(kind, identifier, image_id, **params):
    return dict(kind=kind, id=identifier, image_id=image_id, reason='人工复核测试', **params)


def queue(client, status='pending'):
    response = client.get(BASE + '/suggestions', params={'status': status})
    assert response.status_code == 200, response.text
    return response.json()['items']


def decide(client, item, action='accept', **params):
    return client.post(BASE + '/decisions', json=dict(decision=action, items=[dict(id=item['id'], **params)])).json()


def test_scope_rules_and_download_once(client):
    ids = seed(52)
    with db.connect(True) as conn:
        excluded = image(conn, author='different')
    endpoint = '/api/v1/admin/settings'
    config = client.get(endpoint).json()
    assert client.put(endpoint, json={**config, 'agent_review_rules': '仅确认有视觉证据的人物'}).status_code == 200
    batch = export(client, publishers='x:alice')
    assert client.put(endpoint, json={**config, 'agent_review_rules': '新规则'}).status_code == 200
    url = f'{BASE}/exports/{batch}/download'
    response = client.get(url)
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['instructions'] == '仅确认有视觉证据的人物'
        items = [json.loads(archive.read(path)) for path in manifest['images']]
        assert [item['id'] for item in items] == ids
        assert 'embedding' not in json.dumps(items) and str(db.DATA) not in json.dumps(items)
        assert all(item['sources'][0]['post_text'] and item['faces'][0]['crop'] in archive.namelist() for item in items)
        assert {'SKILL.md', 'review-result.schema.json', 'review-result.example.json', 'people.json'} <= set(
            archive.namelist()
        )
    assert client.get(url).status_code == 410
    assert not (packages.directory() / (batch + '.zip')).exists()
    match = suggestion('match', 'first', ids[0], face_id=items[0]['faces'][0]['id'], person_id=None)
    assert upload(client, batch, [match]).json() == {'added': 1, 'duplicates': 0}
    assert upload(client, batch, [match]).json() == {'added': 0, 'duplicates': 1}
    assert upload(client, batch, [{**match, 'id': 'alias'}]).json() == {'added': 0, 'duplicates': 1}
    assert upload(client, batch, [{**match, 'reason': '不同理由'}]).status_code == 409
    assert upload(client, batch, [{**match, 'image_id': excluded}]).status_code == 400
    assert len(queue(client)) == 1
    for params, expected in [({'ids': ids[-2:]}, ids[-2:]), ({'image_id': excluded}, [excluded])]:
        batch = export(client, **params)
        with db.connect() as conn:
            assert [
                row[0]
                for row in conn.execute(
                    'SELECT image_id FROM review_snapshots WHERE batch=? ORDER BY image_id', (batch,)
                )
            ] == expected


def test_transfer_interruption_expiry_and_restart_cleanup(client):
    seed()
    batch = export(client)
    path = packages.directory() / (batch + '.zip')
    with db.connect() as conn:
        remaining = conn.execute('SELECT expires FROM review_batches WHERE id=?', (batch,)).fetchone()[0] - time.time()
        assert 3590 < remaining <= 3600
    scope = dict(type='http', method='GET', headers=[], asgi={'spec_version': '2.4'})

    async def broken_send(message):
        if message['type'] == 'http.response.body':
            raise OSError('connection dropped')

    with pytest.raises(OSError):
        asyncio.run(packages.Download(path)(scope, None, broken_send))

    async def interrupted_stream():
        writing = asyncio.Event()

        async def receive():
            await writing.wait()
            return {'type': 'http.disconnect'}

        async def blocked_send(message):
            if message['type'] == 'http.response.body':
                writing.set()
                await asyncio.Future()

        await packages.Download(path)({**scope, 'asgi': {'spec_version': '2.3'}}, receive, blocked_send)

    asyncio.run(interrupted_stream())
    assert path.exists() and client.get(f'{BASE}/exports/{batch}/download').status_code == 200
    stale = export(client)
    path = packages.directory() / (stale + '.zip')
    with db.connect(True) as conn:
        conn.execute('UPDATE review_batches SET expires=? WHERE id=?', (time.time() - 1, stale))
    packages.transfers.add(stale)
    try:
        packages.cleanup()
        assert path.exists()
    finally:
        packages.transfers.discard(stale)
    partial = path.with_suffix('.part')
    partial.touch()
    packages.cleanup(startup=True)
    assert not partial.exists() and not path.exists()
    assert client.get(f'{BASE}/exports/{stale}').json()['status'] == 'expired'
    assert upload(client, stale, []).status_code == 200


def test_optional_agent_confidence(client):
    (identifier,) = seed()
    batch = export(client)
    original = suggestion('recycle', 'recycle', identifier, confidence='low')
    for invalid in (0, 0.85, 1, 'unknown', True):
        assert upload(client, batch, [{**original, 'confidence': invalid}]).status_code == 400
    assert upload(client, batch, [original]).json()['added'] == 1
    assert queue(client)[0]['proposal']['confidence'] == 'low'
    assert upload(client, batch, [{**original, 'confidence': 'medium'}]).status_code == 409
    assert upload(client, batch, [{**original, 'id': 'alias', 'confidence': 'high'}]).json()['duplicates'] == 1
    assert len(queue(client)) == 1


def test_external_first_reference_and_dependencies(client, monkeypatch):
    (identifier,) = seed()
    batch = export(client)
    binary = io.BytesIO()
    Image.new('RGB', (100, 60)).save(binary, 'PNG')
    vector = np.ones(512, dtype='float32').tobytes()
    monkeypatch.setattr(
        results,
        'Vision',
        lambda: SimpleNamespace(detect=lambda *args, **kw: [([5, 0, 10, 20], vector), ([65, 10, 15, 20], vector)]),
    )
    ref = suggestion(
        'add_reference',
        'ref',
        identifier,
        person_id='new:a',
        source={'attachment': 'attachments/ref.png', 'source_url': 'https://example.org/photo'},
    )
    new = suggestion('create_person', 'person', identifier, name='Alice', person_id='new:a')
    files = {'attachments/ref.png': binary.getvalue()}
    assert upload(client, batch, [ref], files).json()['added'] == 1
    assert upload(client, batch, [new]).json()['added'] == 1
    pending = queue(client)
    ref_item, new_item = pending
    assert ref_item['attachment']['suggested_index'] is None
    assert decide(client, ref_item, face_index=0)['failures']
    assert decide(client, new_item)['applied'] == [new_item['id']]
    assert decide(client, ref_item)['failures']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 0
    assert not list((db.DATA / 'references').iterdir())
    assert decide(client, ref_item, face_index=1)['applied'] == [ref_item['id']]
    reviewed = next(item for item in queue(client, 'accepted') if item['id'] == ref_item['id'])
    assert reviewed['attachment']['suggested_index'] == 1
    assert upload(client, batch, [ref], files).json()['duplicates'] == 1
    with db.connect() as conn:
        row = conn.execute('SELECT r.*,p.name FROM reference_images r JOIN people p ON p.id=r.person_id').fetchone()
        assert row['name'] == 'Alice' and json.loads(row['box']) == [65, 10, 15, 20]
        assert row['embedding'] == vector and (db.DATA / 'references' / row['filename']).is_file()
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='rematch'").fetchone()[0] == 1
    response = client.get(f"{BASE}/suggestions/{ref_item['id']}/attachment")
    assert response.status_code == 200 and Image.open(io.BytesIO(response.content)).size == (100, 60)
    client.cookies.clear()
    assert client.get(f"{BASE}/suggestions/{ref_item['id']}/attachment").status_code == 401


def test_library_reference_conflicts_and_recycle(client):
    (identifier,) = seed()
    with db.connect(True) as conn:
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (identifier,)).fetchone()[0]
        member = image(conn, group=group)
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
        face_id = conn.execute('SELECT id FROM faces WHERE image_id=?', (identifier,)).fetchone()[0]
    batch = export(client)
    operations = [
        suggestion('match', 'lock', identifier, face_id=face_id, person_id=person),
        suggestion('add_reference', 'ref', identifier, person_id=person, source={'face_id': face_id}),
        suggestion('remove_face', 'remove', identifier, face_id=face_id),
        suggestion('add_face', 'draw', identifier, box=[40, 40, 20, 20]),
        suggestion('recycle', 'trash', identifier),
    ]
    assert upload(client, batch, operations).json()['added'] == len(operations)
    lock, ref, remove, draw, recycle = queue(client)
    assert decide(client, ref)['failures']
    assert decide(client, lock)['applied']
    assert decide(client, ref)['applied']
    assert decide(client, remove)['failures']
    assert decide(client, remove, 'reject')['applied']
    assert decide(client, draw)['applied']
    assert decide(client, recycle)['failures']
    assert recycle['member_ids'] == [identifier, member]
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM reference_images WHERE face_id=?', (face_id,)).fetchone()[0] == 1
        assert conn.execute('SELECT ignored FROM faces WHERE id=?', (face_id,)).fetchone()[0] == 0
    assert decide(client, recycle, scope_token=recycle['scope_token'])['applied']
    with db.connect() as conn:
        assert conn.execute('SELECT sum(hidden) FROM images').fetchone()[0] == 2


def test_reject_unsafe_archives_and_unknown_faces(client, monkeypatch):
    (identifier,) = seed()
    batch = export(client)
    for path in ['../bad.jpg', '/outside', 'attachments/sub/image.jpg', 'attachments\\bad.jpg', 'unknown.txt']:
        assert upload(client, batch, [], {path: b'x'}).status_code == 400
    source = 'attachments/ref.jpg'
    ref = suggestion('add_reference', 'empty', identifier, person_id='new:unused', source={'attachment': source})
    assert upload(client, batch, [ref], {source: b'invalid'}).status_code == 400
    data = io.BytesIO()
    Image.new('RGB', (30, 50)).save(data, 'JPEG')
    monkeypatch.setattr(results, 'Vision', lambda: SimpleNamespace(detect=lambda *args, **kwargs: []))
    new = suggestion('create_person', 'unused', identifier, name='Unused', person_id='new:unused')
    assert upload(client, batch, [new, ref], {source: data.getvalue()}).status_code == 200
    person, reference = queue(client)
    assert decide(client, person)['applied']
    assert not reference['attachment']['boxes'] and decide(client, reference, face_index=0)['failures']
    assert decide(client, reference, 'reject')['applied']
    assert not list((db.DATA / 'references').iterdir())


def test_reused_face_and_changed_recycle_scope_remain_pending(client):
    (identifier,) = seed()
    batch = export(client)
    with db.connect(True) as conn:
        old = conn.execute('SELECT * FROM faces WHERE image_id=?', (identifier,)).fetchone()
        conn.execute('DELETE FROM faces WHERE id=?', (old['id'],))
        conn.execute('INSERT INTO faces(id,image_id,box) VALUES(?,?,?)', (old['id'], identifier, old['box']))
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (identifier,)).fetchone()[0]
        image(conn, group=group)
    ops = [
        suggestion('remove_face', 'remove', identifier, face_id=old['id']),
        suggestion('recycle', 'trash', identifier),
    ]
    assert upload(client, batch, ops).json()['added'] == 2
    remove, recycle = queue(client)
    assert decide(client, remove)['failures']
    assert decide(client, recycle, scope_token=recycle['scope_token'])['failures']
    assert len(queue(client)) == 2
    with db.connect() as conn:
        assert conn.execute('SELECT sum(hidden) FROM images').fetchone()[0] == 0
        assert conn.execute('SELECT sum(ignored) FROM faces').fetchone()[0] == 0
