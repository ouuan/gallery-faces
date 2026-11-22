import asyncio
import io
import json
import threading
import time
import zipfile
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app import db, review_packages as packages, review_results as results, worker
from test_workflows import client, image

BASE = '/api/v1/admin/review-packages'


def seed(count=1):
    Image.new('RGB', (100, 100)).save(db.DATA / 'images' / 'fixture.jpg')
    with db.connect(True) as conn:
        return [image(conn) for _ in range(count)]


def export(client, *, expected_status='ready', **params):
    response = client.post(BASE + '/exports', json=dict(state='all', **params))
    assert response.status_code == 202, response.text
    batch = response.json()['id']
    for _ in range(200):
        status = client.get(BASE + '/exports/' + batch).json()
        if status['status'] != 'building':
            assert status['status'] == expected_status, status
            break
        time.sleep(0.02)
    else:
        pytest.fail('Package generation did not finish')
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
    response = client.post(BASE + '/imports', files={'file': (name, raw)})
    assert response.status_code == 202, response.text
    for _ in range(200):
        job = client.get(BASE + '/imports/' + response.json()['id']).json()
        if job['status'] not in ('queued', 'running'):
            assert job['status'] in ('done', 'failed')
            assert job['error'] != '导入失败，请检查文件后重试', job
            return job
        time.sleep(0.02)
    pytest.fail('Result import did not finish')


def suggestion(kind, identifier, image_id, **params):
    return dict(kind=kind, id=identifier, image_id=image_id, reason='人工复核测试', **params)


def queue(client, status=None):
    response = client.get(BASE + '/suggestions', params={'status': status} if status else {})
    assert response.status_code == 200, response.text
    return response.json()['items']


def decide(client, item, action='accept', **params):
    return client.post(BASE + '/decisions', json=dict(decision=action, items=[dict(id=item['id'], **params)])).json()


@pytest.mark.parametrize(('counts', 'pages'), [
    ([], []),
    ([8, 12, 1], [([1, 2], 20), ([3], 1)]),
    ([11, 12, 13], [([1], 11), ([2], 12), ([3], 13)]),
    ([2, 21, 1, 4], [([1], 2), ([2], 21), ([3, 4], 5)]),
])
def test_queue_pages_budget_records_without_splitting_images(counts, pages):
    assert list(results.queue_pages(enumerate(counts, 1), 20)) == pages


def test_queue_paginates_filtered_images_across_batches(client):
    first, second = seed(2)
    batch = export(client, ids=[first, second])
    notes = [suggestion('review_outcome', f'note-{image_id}', image_id, outcome='needs_human')
             for image_id in (second, first)]
    assert upload(client, batch, notes)['recorded'] == 2
    batch = export(client, ids=[first])
    assert upload(client, batch, [suggestion('recycle', 'remove', first)])['added'] == 1

    def get_page(number, status='review'):
        response = client.get(BASE + '/suggestions', params=dict(page_size=1, page=number, status=status))
        assert response.status_code == 200, response.text
        return response.json()

    page = get_page(1)
    assert (page['total_images'], page['total'], page['page_count']) == (2, 3, 2)
    assert [(item['image_id'], item['status']) for item in page['items']] == [(first, 'recorded'), (first, 'pending')]
    last = get_page(99)
    assert last['page'] == 2 and [item['image_id'] for item in last['items']] == [second]
    pending = get_page(2, 'pending')
    assert (pending['page'], pending['page_count'], pending['total_images'], pending['total']) == (1, 1, 1, 1)
    assert pending['items'] == page['items'][1:]


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
    assert upload(client, batch, [match])['added'] == 1
    assert upload(client, batch, [match])['duplicates'] == 1
    assert upload(client, batch, [{**match, 'id': 'alias'}])['duplicates'] == 1
    assert upload(client, batch, [{**match, 'reason': '不同理由'}])['error'].endswith('的内容与已导入记录不同')
    assert upload(client, batch, [{**match, 'image_id': excluded}])['status'] == 'failed'
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


def test_export_waits_for_references_and_concurrent_display_recovery(client, monkeypatch, tmp_path):
    monkeypatch.setenv('MEDIA_CACHE_WAIT_SECONDS', '0')
    first, second, reference = seed(3)
    sources = {}
    with db.connect(True) as conn:
        for identifier in (first, second, reference):
            source = sources[identifier] = tmp_path / f'input-{identifier}.png'
            Image.new('RGB', (100, 100), (identifier, 0, 0)).save(source)
            conn.execute('''UPDATE images SET filename=?, original_filename=?, sha256=?, image_evicted=1,
                original_evicted=1 WHERE id=?''', (f'{identifier}.jpg', source.name, db.file_hash(source), identifier))
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
        conn.execute('''INSERT INTO reference_images(person_id,face_id,image_id,embedding,model_version)
            SELECT ?,id,image_id,embedding,model_version FROM faces WHERE image_id=?''', (person, reference))

    concurrent_downloads = threading.Barrier(2)

    def download(task, payload, attempt, restore_id):
        if restore_id != reference:
            concurrent_downloads.wait(timeout=3)
        (attempt / 'photo.png').write_bytes(sources[restore_id].read_bytes())
        return attempt

    monkeypatch.setattr(worker, 'download_media', download)
    batch = export(client, ids=[first, second])
    with zipfile.ZipFile(packages.directory() / (batch + '.zip')) as archive:
        for identifier in (first, second):
            item = json.loads(archive.read(f'images/{identifier}/metadata.json'))
            assert Image.open(io.BytesIO(archive.read(item['display']))).size == (100, 100)
            assert item['faces'][0]['crop'] in archive.namelist()
        person, = json.loads(archive.read('people.json'))
        assert not person['missing_references'] and person['references'][0] in archive.namelist()


def test_export_fails_if_required_display_cannot_be_recovered(client):
    identifier, = seed()
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET filename='missing.jpg', image_evicted=1, original_lost=1 WHERE id=?", (identifier,))
    batch = export(client, expected_status='failed')
    assert not list(packages.directory().glob(batch + '.*'))


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
    assert upload(client, stale, [])['status'] == 'done'


def test_optional_agent_confidence(client):
    (identifier,) = seed()
    batch = export(client)
    original = suggestion('recycle', 'recycle', identifier, confidence='low')
    for invalid in (0, 0.85, 1, 'unknown', True):
        assert upload(client, batch, [{**original, 'confidence': invalid}])['status'] == 'failed'
    assert upload(client, batch, [original])['added'] == 1
    assert queue(client)[0]['proposal']['confidence'] == 'low'
    assert upload(client, batch, [{**original, 'confidence': 'medium'}])['error'].endswith('的内容与已导入记录不同')
    assert upload(client, batch, [{**original, 'id': 'alias', 'confidence': 'high'}])['duplicates'] == 1
    assert len(queue(client)) == 1


def test_create_person_with_groups(client):
    (identifier,) = seed()
    with db.connect(True) as conn:
        group = conn.execute("INSERT INTO groups(name) VALUES('Speakers')").lastrowid
    batch = export(client)
    with zipfile.ZipFile(packages.directory() / (batch + '.zip')) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert json.loads(archive.read(manifest['groups'])) == [{'id': group, 'name': 'Speakers', 'name_ja': None}]
    op = suggestion('create_person', 'alice', identifier, person_id='new:a', name='Alice',
                    group_ids=[group], new_groups=[' Guests ', 'Speakers', 'Guests'])
    for invalid in ({'group_ids': [group + 1]}, {'new_groups': ['   ']}, {'new_groups': ['a' * 101]}):
        assert upload(client, batch, [{**op, **invalid}])['status'] == 'failed'
    assert upload(client, batch, [op])['added'] == 1
    assert upload(client, batch, [{**op, 'new_groups': ['Speakers', 'Guests']}])['duplicates'] == 1
    item, = queue(client)
    assert f'Speakers (#{group})' in item['proposed'] and 'Guests' in item['proposed']
    assert client.get('/api/v1/people').json() == [] and len(client.get('/api/v1/groups').json()) == 1
    assert decide(client, item)['applied'] == [item['id']]
    person, = client.get('/api/v1/people').json()
    assert {entry['name'] for entry in person['groups']} == {'Guests', 'Speakers'}
    assert [entry['members'] for entry in client.get('/api/v1/groups').json()] == [1, 1]
    assert upload(client, batch, [op])['duplicates'] == 1


def test_create_person_does_not_use_replacement_group(client):
    (identifier,) = seed()
    with db.connect(True) as conn:
        group = conn.execute("INSERT INTO groups(name) VALUES('Original')").lastrowid
    batch = export(client)
    op = suggestion('create_person', 'person', identifier, person_id='new:p', name='Person',
                    group_ids=[group], new_groups=['Guests'])
    assert upload(client, batch, [op])['added'] == 1
    with db.connect(True) as conn:
        conn.execute('DELETE FROM groups WHERE id=?', (group,))
        assert conn.execute("INSERT INTO groups(name) VALUES('Replacement')").lastrowid == group
    item, = queue(client)
    assert 'Original（已删除）' in item['proposed'] and 'Replacement' not in item['proposed']
    assert decide(client, item)['failures']
    assert decide(client, item, 'reject')['applied'] == [item['id']]
    assert client.get('/api/v1/people').json() == []
    assert [entry['name'] for entry in client.get('/api/v1/groups').json()] == ['Replacement']


def test_export_includes_group_review_evidence(client):
    (identifier,) = seed()
    Image.new('RGB', (32, 20)).save(db.DATA / 'thumbs' / 'fixture.jpg')
    with db.connect(True) as conn:
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (identifier,)).fetchone()[0]
        member = image(conn, author=None, group=group)
        missing = image(conn, group=group)
        conn.execute("UPDATE images SET filename='missing.jpg' WHERE id=?", (missing,))
        conn.execute("UPDATE images SET detection='failed',error='无法解码' WHERE id=?", (identifier,))
        conn.execute("INSERT INTO feedback(image_id,content) VALUES(?, '请检查发布账号')", (member,))
        conn.execute("INSERT INTO feedback(image_id,content,status) VALUES(?, '旧反馈','resolved')", (member,))
    batch = export(client)
    with zipfile.ZipFile(packages.directory() / (batch + '.zip')) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['selected_state'] == 'all'
        item = json.loads(archive.read(manifest['images'][0]))
        assert {'feedback', 'incomplete', 'failed'} <= set(item['review_reasons'])
        assert (item['detection'], item['error']) == ('failed', '无法解码')
        assert item['incomplete_image_ids'] == [member]
        feedback, = item['pending_feedback']
        assert (feedback['image_id'], feedback['content']) == (member, '请检查发布账号')
        representative, other, absent = item['members']
        assert representative['preview'] == item['display']
        assert other['id'] == member and Image.open(io.BytesIO(archive.read(other['preview']))).size == (32, 20)
        assert absent['id'] == missing and absent['preview'] is None


def test_localized_person_and_additive_edits(client):
    (identifier,) = seed()
    person = client.post('/api/v1/admin/people', json={'name': '甲', 'new_groups': ['原组'],
                         'accounts': [{'platform': 'x', 'username': 'original'}]}).json()['id']
    with db.connect(True) as conn:
        group = conn.execute("INSERT INTO groups(name) VALUES('嘉宾')").lastrowid
    batch = export(client)
    account = {'platform': 'instagram', 'username': 'alice'}
    create = suggestion('create_person', 'create', identifier, person_id='new:b', name='乙', name_ja='オツ',
                        new_groups=[{'name': '新组', 'name_ja': '新組'}], accounts=[account])
    operations = [create, suggestion('add_person_group', 'membership', identifier, person_id=person, group_id=group),
                  suggestion('add_person_account', 'account', identifier, person_id=person, account=account),
                  suggestion('set_group_name_ja', 'group', identifier, group_id=group, name_ja='ゲスト'),
                  suggestion('set_person_name_ja', 'person', identifier, person_id=person, name_ja='コウ')]
    assert upload(client, batch, [{**operations[1], 'group_id': group + 100}])['status'] == 'failed'
    assert upload(client, batch, [{**create, 'accounts': [{'platform': 'x', 'username': '@bad'}]}])['status'] == 'failed'
    assert upload(client, batch, operations)['added'] == 5
    items = queue(client)
    assert all(label in items[0]['proposed'] for label in ('新組', 'オツ', '@alice'))
    assert len(client.get('/api/v1/people').json()) == 1
    assert all(decide(client, item)['applied'] for item in items)
    original, new = sorted(client.get('/api/v1/people').json(), key=lambda item: item['id'])
    assert original['name_ja'] == 'コウ' and {entry['username'] for entry in original['accounts']} == {'original', 'alice'}
    assert {entry['name']: entry['name_ja'] for entry in original['groups']} == {'原组': None, '嘉宾': 'ゲスト'}
    assert (new['name_ja'], new['groups'][0]['name_ja'], new['accounts'][0]['username']) == ('オツ', '新組', 'alice')
    conflict = {**operations[-1], 'id': 'conflict', 'name_ja': '別名'}
    assert upload(client, batch, [conflict])['added'] == 1
    assert decide(client, queue(client)[0])['failures']
    assert upload(client, batch, operations)['duplicates'] == 5


def test_source_correction_and_image_outcomes(client):
    identifier, other = seed(2)
    with db.connect() as conn:
        post, unrelated = [row[0] for row in conn.execute('SELECT post_id FROM sources ORDER BY image_id')]
    batch = export(client, ids=[identifier])
    correct = suggestion('correct_source', 'author', identifier, post_id=post, field='author', value='corrected')
    outcome = suggestion('review_outcome', 'inspection', identifier, outcome='needs_human')
    for invalid in ({**correct, 'post_id': unrelated}, {**correct, 'field': 'url', 'value': 'not a URL'},
                    {**correct, 'field': 'url', 'value': 'https://instagram.com/p/123/'}, {**correct, 'value': None},
                    {**correct, 'field': 'published_at', 'value': '2026-01-01'}, {**outcome, 'image_id': other}):
        assert upload(client, batch, [invalid])['status'] == 'failed'
    edits = [correct, {**correct, 'id': 'text', 'field': 'post_text', 'value': '修正正文'}, outcome]
    job = upload(client, batch, edits)
    assert (job['added'], job['recorded'], job['duplicates']) == (2, 1, 0)
    with db.connect(True) as conn:
        conn.execute("UPDATE posts SET author='manual' WHERE id=?", (post,))
    conflict, text, note = queue(client)
    assert note['status'] == 'recorded' and queue(client, 'pending') == [conflict, text]
    assert 'manual' in conflict['current'] and decide(client, conflict)['failures']
    assert decide(client, text)['applied'] and decide(client, note)['failures']
    assert decide(client, note, 'reject')['failures']
    assert decide(client, conflict, 'acknowledge')['failures']
    assert decide(client, note, 'acknowledge') == {'applied': [note['id']], 'failures': []}
    assert decide(client, note, 'acknowledge')['failures']
    assert [item['id'] for item in queue(client)] == [conflict['id']]
    assert [item['id'] for item in queue(client, 'acknowledged')] == [note['id']]
    with db.connect() as conn:
        assert tuple(conn.execute('SELECT author,post_text FROM posts WHERE id=?', (post,)).fetchone()) == ('manual', '修正正文')
        assert conn.execute('SELECT locked FROM faces WHERE image_id=?', (identifier,)).fetchone()[0] == 0
    assert upload(client, batch, [{**outcome, 'id': 'alias'}])['duplicates'] == 1
    assert [item['id'] for item in queue(client)] == [conflict['id']]
    assert upload(client, batch, [{**outcome, 'id': 'other', 'outcome': 'no_faces'}])['status'] == 'failed'


def test_import_returns_before_processing_and_resumes_after_restart(client, monkeypatch):
    (identifier,) = seed()
    batch = export(client)
    note = suggestion('review_outcome', 'note', identifier, outcome='no_change')
    raw = json.dumps(dict(version=1, batch=batch, suggestions=[note])).encode()
    with monkeypatch.context() as patch:
        patch.setattr(packages.executor, 'submit', lambda *_: None)
        response = client.post(BASE + '/imports', files={'file': ('result.json', raw)})
    assert response.status_code == 202 and response.json()['status'] == 'queued'
    job_id = response.json()['id']
    assert client.get(BASE + '/imports/' + job_id).json()['status'] == 'queued'
    assert not queue(client)
    with db.connect(True) as conn:
        conn.execute("UPDATE review_imports SET status='running' WHERE id=?", (job_id,))
    with packages.service():
        pass
    job = client.get(BASE + '/imports/' + job_id).json()
    assert job['status'] == 'done' and job['recorded'] == 1
    with db.connect(True) as conn:
        assert conn.execute('SELECT upload FROM review_imports WHERE id=?', (job_id,)).fetchone()[0] is None
        conn.execute("UPDATE review_suggestions SET status='pending' WHERE batch=?", (batch,))
    db.init()
    note, = queue(client)
    assert note['status'] == 'recorded' and not queue(client, 'pending')


def test_legacy_snapshot_and_result_keys(client):
    (identifier,) = seed()
    batch = export(client)
    original = suggestion('create_person', 'legacy', identifier, person_id='new:legacy', name='Legacy', new_groups=['Guests'])
    with db.connect(True) as conn:
        conn.execute("UPDATE review_snapshots SET snapshot=json_remove(snapshot,'$.sources','$.members') WHERE batch=?", (batch,))
        identifier_key = conn.execute('''INSERT INTO review_suggestions(batch,key,image_id,payload,fingerprint)
            VALUES(?,?,?,?,?)''', (batch, original['id'], identifier, results.encode(original), 'legacy')).lastrowid
        conn.execute('INSERT INTO review_result_keys VALUES(?,?,?,?)', (batch, original['id'],
                     results.digest(results.encode([original, None]).encode()), identifier_key))
    assert upload(client, batch, [original])['duplicates'] == 1
    assert decide(client, queue(client)[0])['applied']
    assert upload(client, batch, [suggestion('correct_source', 'post', identifier, post_id=1,
                                             field='post_text', value=None)])['status'] == 'failed'


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
    assert upload(client, batch, [ref], files)['added'] == 1
    assert upload(client, batch, [new])['added'] == 1
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
    assert upload(client, batch, [ref], files)['duplicates'] == 1
    with db.connect() as conn:
        row = conn.execute('SELECT r.*,p.name FROM reference_images r JOIN people p ON p.id=r.person_id').fetchone()
        assert row['name'] == 'Alice' and json.loads(row['box']) == [65, 10, 15, 20]
        assert row['embedding'] == vector and (db.DATA / 'references' / row['filename']).is_file()
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='rematch'").fetchone()[0] == 1
    response = client.get(f"{BASE}/suggestions/{ref_item['id']}/attachment")
    assert response.status_code == 200 and Image.open(io.BytesIO(response.content)).size == (100, 60)
    client.cookies.clear()
    assert client.get(f"{BASE}/suggestions/{ref_item['id']}/attachment").status_code == 401


@pytest.mark.parametrize('kind', ['match', 'remove_face'])
def test_rematch_does_not_invalidate_face_suggestion(client, kind):
    (identifier,) = seed()
    with db.connect(True) as conn:
        auto = conn.execute("INSERT INTO people(name) VALUES('Auto')").lastrowid
        face = conn.execute('SELECT * FROM faces WHERE image_id=?', (identifier,)).fetchone()
    batch = export(client)
    params = {'person_id': None} if kind == 'match' else {}
    assert upload(client, batch, [suggestion(kind, 'edit', identifier, face_id=face['id'], **params)])['added'] == 1
    with db.connect(True) as conn:
        conn.execute('INSERT INTO reference_images(person_id,embedding,model_version) VALUES(?,?,?)',
                     (auto, face['embedding'], face['model_version']))
        db.schedule_rematch(conn)
    worker.step()
    with db.connect() as conn:
        current = conn.execute('SELECT person_id,locked,revision FROM faces WHERE id=?', (face['id'],)).fetchone()
        assert tuple(current) == (auto, 0, face['revision'] + 1)
    assert decide(client, queue(client)[0])['applied']
    with db.connect() as conn:
        assert tuple(conn.execute('SELECT person_id,locked,ignored FROM faces WHERE id=?', (face['id'],)).fetchone()) == (
            None, 1, kind == 'remove_face')


def test_manual_confirmation_satisfies_match_and_library_reference(client):
    (identifier,) = seed()
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
        face = conn.execute('SELECT id,revision FROM faces WHERE image_id=?', (identifier,)).fetchone()
    batch = export(client)
    ops = [suggestion('add_reference', 'ref', identifier, person_id=person, source={'face_id': face['id']}),
           suggestion('match', 'match', identifier, person_id=person, face_id=face['id'])]
    assert upload(client, batch, ops)['added'] == 2
    ref, match = queue(client)
    assert client.put(f"/api/v1/admin/faces/{face['id']}", json=dict(person_id=person, revision=face['revision'])).is_success
    assert decide(client, ref)['applied']
    assert decide(client, match)['applied']
    with db.connect() as conn:
        assert conn.execute('SELECT revision FROM faces WHERE id=?', (face['id'],)).fetchone()[0] == face['revision'] + 1
        assert conn.execute('SELECT count(*) FROM review_history WHERE face_id=?', (face['id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('change', ['candidates', 'confirmed_person', 'box'])
def test_removal_rechecks_exported_human_decision_and_box(client, change):
    (identifier,) = seed()
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
        other = conn.execute("INSERT INTO people(name) VALUES('Bob')").lastrowid
        face_id = conn.execute('SELECT id FROM faces WHERE image_id=?', (identifier,)).fetchone()[0]
        conn.execute('UPDATE faces SET locked=1,person_id=? WHERE id=?', (person, face_id))
    batch = export(client)
    assert upload(client, batch, [suggestion('remove_face', 'remove', identifier, face_id=face_id)])['added'] == 1
    with db.connect(True) as conn:
        if change == 'candidates':
            conn.execute('UPDATE faces SET candidates=?,revision=revision+1 WHERE id=?',
                         (json.dumps([dict(person_id=other, score=0.8)]), face_id))
        elif change == 'confirmed_person':
            conn.execute('UPDATE faces SET person_id=?,revision=revision+1 WHERE id=?', (other, face_id))
        else:
            conn.execute("UPDATE faces SET box='[1,1,20,20]' WHERE id=?", (face_id,))
    item, = queue(client)
    decision = decide(client, item)
    if change == 'candidates':
        assert decision['applied'] == [item['id']]
    else:
        assert decision['failures'] and queue(client)[0]['id'] == item['id']
        with db.connect() as conn:
            assert conn.execute('SELECT ignored FROM faces WHERE id=?', (face_id,)).fetchone()[0] == 0


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
    assert upload(client, batch, operations)['added'] == len(operations)
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
    with db.connect(True) as conn:
        assert conn.execute('SELECT sum(hidden) FROM images').fetchone()[0] == 2
        conn.execute('UPDATE images SET hidden=0 WHERE id=?', (identifier,))
        image(conn, group=group)
    history = next(item for item in queue(client, 'accepted') if item['id'] == recycle['id'])
    assert history['member_ids'] == [identifier, member] and history['scope_token'] is None


def test_reject_unsafe_archives_and_unknown_faces(client, monkeypatch):
    (identifier,) = seed()
    batch = export(client)
    for path in ['../bad.jpg', '/outside', 'attachments/sub/image.jpg', 'attachments\\bad.jpg', 'unknown.txt']:
        assert upload(client, batch, [], {path: b'x'})['status'] == 'failed'
    source = 'attachments/ref.jpg'
    ref = suggestion('add_reference', 'empty', identifier, person_id='new:unused', source={'attachment': source})
    assert upload(client, batch, [ref], {source: b'invalid'})['status'] == 'failed'
    data = io.BytesIO()
    Image.new('RGB', (30, 50)).save(data, 'JPEG')
    monkeypatch.setattr(results, 'Vision', lambda: SimpleNamespace(detect=lambda *args, **kwargs: []))
    new = suggestion('create_person', 'unused', identifier, name='Unused', person_id='new:unused')
    assert upload(client, batch, [new, ref], {source: data.getvalue()})['status'] == 'done'
    person, reference = queue(client)
    assert decide(client, person)['applied']
    assert not reference['attachment']['boxes'] and decide(client, reference, face_index=0)['failures']
    assert decide(client, reference, 'reject')['applied']
    assert not list((db.DATA / 'references').iterdir())


def test_reused_face_and_changed_recycle_scope_remain_pending(client):
    (identifier,) = seed()
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
    batch = export(client)
    with db.connect(True) as conn:
        old = conn.execute('SELECT * FROM faces WHERE image_id=?', (identifier,)).fetchone()
        token = conn.execute('SELECT token FROM review_face_identity WHERE face_id=?', (old['id'],)).fetchone()[0]
        conn.execute('DELETE FROM people WHERE id=?', (person,))
        assert conn.execute("INSERT INTO people(name) VALUES('Replacement')").lastrowid == person
        conn.execute("INSERT INTO reference_images(person_id,filename,embedding,model_version) VALUES(?,'replacement.jpg',?,?)",
                     (person, old['embedding'], old['model_version']))
        conn.execute('DELETE FROM faces WHERE id=?', (old['id'],))
        conn.execute("INSERT INTO faces(id,image_id,box) VALUES(?,?,'[20,20,2,2]')", (old['id'], identifier))
        conn.execute('INSERT INTO review_face_identity(face_id) VALUES(?)', (old['id'],))
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (identifier,)).fetchone()[0]
        image(conn, group=group)
    ops = [
        suggestion('remove_face', 'remove', identifier, face_id=old['id']),
        suggestion('recycle', 'trash', identifier),
        suggestion('add_reference', 'ref', identifier, person_id=person, source={'face_id': old['id']}),
    ]
    assert upload(client, batch, ops)['added'] == 3
    remove, recycle, ref = queue(client)
    assert remove['box'] == json.loads(old['box']) and remove['current'] == '人脸不存在'
    assert ref['face_token'] is None and not ref['reference_ids'] and '已删除人物' in ref['proposed']
    assert '原人脸不存在' in ref['current']
    assert client.get(f"/api/v1/admin/faces/{old['id']}/crop?token={token}").status_code == 404
    assert decide(client, ref, 'reject')['applied']
    assert queue(client, 'rejected')[0]['reference_ids'] == []
    assert decide(client, remove)['failures']
    assert decide(client, recycle, scope_token=recycle['scope_token'])['failures']
    assert len(queue(client)) == 2
    with db.connect() as conn:
        assert conn.execute('SELECT sum(hidden) FROM images').fetchone()[0] == 0
        assert conn.execute('SELECT sum(ignored) FROM faces').fetchone()[0] == 0


def test_attachment_versions_survive_migration_and_reimport(client, monkeypatch):
    (identifier,) = seed()
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('Alice')").lastrowid
    photo = io.BytesIO()
    Image.new('RGB', (20, 20)).save(photo, 'PNG')
    files = {'attachments/photo.png': photo.getvalue()}
    ref = suggestion('add_reference', 'ref', identifier, person_id=person, source={'attachment': next(iter(files))})
    calls = []
    vector = np.ones(512, dtype='float32').tobytes()

    def detect(path, *, mode, threshold):
        calls.append((results.MODEL_VERSION, threshold))
        return [] if threshold >= 0.5 else [([1, 2, 3, 4], vector)]

    monkeypatch.setattr(results, 'Vision', lambda: SimpleNamespace(detect=detect))
    original_model = results.MODEL_VERSION
    first = export(client)
    assert upload(client, first, [ref], files)['added'] == 1
    with db.connect(True) as conn:
        conn.execute('ALTER TABLE review_attachments ADD COLUMN detections TEXT NOT NULL DEFAULT \'[]\'')
        conn.execute('ALTER TABLE review_attachments ADD COLUMN model TEXT NOT NULL DEFAULT \'legacy\'')
        conn.execute('ALTER TABLE review_suggestions DROP COLUMN detection_id')
        conn.execute('DROP TABLE review_detections')
    db.init()
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0.3' WHERE key='detection_threshold'")
    second = export(client)
    assert upload(client, second, [ref], files)['added'] == 1
    assert upload(client, second, [ref], files)['duplicates'] == 1
    old, new = queue(client)
    assert old['attachment']['boxes'] == [] and new['attachment']['boxes'] == [[1, 2, 3, 4]]
    assert decide(client, old, face_index=0)['failures'] and decide(client, new)['applied']
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0.5' WHERE key='detection_threshold'")
    assert upload(client, export(client), [ref], files)['added'] == 1
    monkeypatch.setattr(results, 'MODEL_VERSION', 'new-model')
    assert upload(client, export(client), [ref], files)['added'] == 1
    assert calls == [(original_model, 0.5), (original_model, 0.3), (original_model, 0.5), ('new-model', 0.5)]
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM review_attachments').fetchone()[0] == 1
        assert conn.execute('SELECT count(DISTINCT detection_id) FROM review_suggestions').fetchone()[0] == 4


def test_subpixel_crop_exports_and_releases_read_snapshot(client, monkeypatch):
    (identifier,) = seed()
    box = [5, 5, 0.25, 1]
    assert client.post(f'/api/v1/admin/images/{identifier}/faces', json={'box': box}).status_code == 200
    from app import main
    crop = main.cropped_image

    def crop_after_checkpoint(path, face_box):
        with db.connect(True) as conn:
            conn.execute("UPDATE review_batches SET done=1 WHERE status='building'")
        with db.connect() as conn:
            _, pages, checkpointed = conn.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
            assert checkpointed == pages
        return crop(path, face_box)

    monkeypatch.setattr(main, 'cropped_image', crop_after_checkpoint)
    batch = export(client)
    with zipfile.ZipFile(packages.directory() / (batch + '.zip')) as archive:
        item = json.loads(archive.read(f'images/{identifier}/metadata.json'))
        face = next(face for face in item['faces'] if face['box'] == box)
        assert Image.open(io.BytesIO(archive.read(face['crop']))).size == (1, 1)


def test_download_finalization_does_not_block_event_loop(client, monkeypatch):
    seed()
    batch = export(client)
    path = packages.directory() / (batch + '.zip')
    entered = threading.Event()
    finish = packages.Download.finish

    def observed_finish(response, complete):
        entered.set()
        return finish(response, complete)

    async def send(message):
        pass

    async def run():
        with db.connect(True):
            scope = dict(type='http', method='GET', headers=[], asgi={'spec_version': '2.4'})
            download = asyncio.create_task(packages.Download(path)(scope, None, send))
            assert await asyncio.to_thread(entered.wait, 2)
            assert not download.done()
        await download

    monkeypatch.setattr(packages.Download, 'finish', observed_finish)
    asyncio.run(run())
    assert client.get(f'{BASE}/exports/{batch}').json()['status'] == 'downloaded'
