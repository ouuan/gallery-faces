import json

import pytest

from app import db, importer, review_packages, worker
from app.download_round import DownloadRound
from app.metadata import metadata, publisher_blocked
from test_restart_recovery import RAW, source
from test_workflows import client, image

ROOT = '/api/v1/admin/publishers'
ALICE = ROOT + '/x/ALICE'


def preview(client):
    response = client.get(ALICE + '/purge-preview')
    assert response.status_code == 200, response.text
    return response.json()


def purge(client, token, blocked):
    return client.post(ALICE + '/purge', json={'scope_token': token, 'blocked': blocked})


def test_list_rules_and_later_link(client):
    with db.connect(True) as conn:
        image(conn, author='alice')
        image(conn, author='ALICE')
        image(conn, author='other')
        conn.execute("UPDATE posts SET author_name='昵称' WHERE id=1")
        conn.execute("INSERT INTO posts(platform,post_key,author) VALUES('instagram','1','alice')")
    listing = client.get(ROOT, params={'platform': 'x', 'search': '昵称'}).json()
    assert listing['items'] == [{'username': 'alice', 'label': '昵称', 'posts': 2, 'linked': False, 'blocked': []}]
    assert (listing['posts_count'], listing['rules_count']) == (1, 0)
    for invalid in (['tagged'], ['quoted', 'all'], ['quoted', 'quoted']):
        assert client.put(ALICE + '/rule', json={'blocked': invalid}).status_code == 422
    assert client.put(ALICE + '/rule', json={'blocked': ['quoted']}).status_code == 200
    token = preview(client)['scope_token']
    client.post('/api/v1/admin/people', json={'name': '人物', 'accounts': [{'platform': 'x', 'username': 'Alice'}]})
    assert purge(client, token, ['all']).status_code == 409
    assert client.get(ROOT, params={'platform': 'x', 'search': '@alice'}).json()['items'][0]['linked']
    assert client.put(ALICE + '/rule', json={'blocked': []}).status_code == 200
    assert not client.get(ROOT, params={'platform': 'x', 'search': 'alice'}).json()['items']
    assert client.get(ROOT, params={'platform': 'instagram'}).json()['posts_count'] == 1
    client.post('/api/v1/logout')
    assert client.get(ROOT, params={'platform': 'x'}).status_code == 401


def test_purge_preserves_shared_images_and_other_group_members(client, tmp_path):
    path = source(tmp_path)
    exclusive = importer.import_file(path, RAW)
    with db.connect(True) as conn:
        group, digest, filename = conn.execute('SELECT group_id,sha256,filename FROM images WHERE id=?', (exclusive,)).fetchone()
        shared = image(conn, author='Other', group=group)
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,?)', (shared, 'shared'))
        conn.execute("INSERT INTO people(id,name) VALUES(1,'共享图参考')")
        conn.execute('INSERT INTO reference_images(person_id,image_id,embedding,model_version) VALUES(1,?,?,?)', (shared, b'feature', worker.MODEL_VERSION))
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (exclusive,))
        conn.execute("INSERT INTO duplicate_decisions VALUES(?,?, 'different',0.1)", (exclusive, shared))
    for folder in ('images', 'thumbs'):
        assert (tmp_path / folder / filename).exists()
    before = preview(client)
    assert (before['posts'], before['exclusive'], before['shared'], before['references']) == (1, 1, 1, [])
    result = purge(client, before['scope_token'], ['retweets', 'quoted'])
    assert result.status_code == 200, result.text
    with db.connect() as conn:
        assert [row[0] for row in conn.execute('SELECT id FROM images')] == [shared]
        assert [row[0] for row in conn.execute('SELECT author FROM posts')] == ['Other']
        assert conn.execute('SELECT representative FROM review_groups').fetchone()[0] == shared
        assert conn.execute('SELECT image_id FROM reference_images').fetchone()[0] == shared
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    assert path.exists() and not list((tmp_path / 'originals').glob(digest + '.*'))
    assert all(not (tmp_path / folder / filename).exists() for folder in ('images', 'thumbs'))
    listing = client.get(ROOT, params={'platform': 'x', 'view': 'rules'}).json()
    assert (listing['posts_count'], listing['rules_count']) == (1, 1)
    assert listing['items'][0]['posts'] == 0
    client.put(ALICE + '/rule', json={'blocked': []})
    assert client.get(ROOT, params={'platform': 'x', 'view': 'rules'}).json()['rules_count'] == 0


def test_purge_scrubs_shared_review_snapshot_and_invalidates_package(client, tmp_path):
    with db.connect(True) as conn:
        kept = image(conn, author='other')
        group = conn.execute('SELECT group_id FROM images WHERE id=?', (kept,)).fetchone()[0]
        removed = image(conn, group=group)
    with db.connect(True) as conn:
        snap = review_packages.snapshot(conn, kept)
        conn.execute("INSERT INTO review_batches(id,status,instructions,total,expires) VALUES('batch','ready','',1,9999999999)")
        conn.execute("INSERT INTO review_snapshots VALUES('batch',?,?)", (kept, json.dumps(snap)))
    assert purge(client, preview(client)['scope_token'], []).status_code == 200
    assert client.get('/api/v1/admin/review-packages/exports/batch/download').status_code == 410
    with db.connect() as conn:
        retained = json.loads(conn.execute('SELECT snapshot FROM review_snapshots').fetchone()[0])
        assert [post['author'] for post in retained['sources']] == ['other']
        assert retained['member_ids'] == [kept]
    assert importer.import_file(source(tmp_path), RAW) > removed


def test_reference_scope_and_task_conflict_roll_back_rule(client):
    with db.connect(True) as conn:
        identifier = image(conn)
        conn.execute("INSERT INTO people(id,name) VALUES(1,'参考人物')")
    original = preview(client)
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (identifier,))
        conn.execute('INSERT INTO reference_images(person_id,image_id,face_id,embedding,model_version) VALUES(1,?,1,?,?)', (identifier, b'feature', worker.MODEL_VERSION))
    occupied = preview(client)
    assert occupied['references'] == [{'image_id': identifier, 'person': '参考人物', 'reference_id': 1}]
    for token in (original['scope_token'], occupied['scope_token']):
        assert purge(client, token, ['all']).status_code == 409
    with db.connect(True) as conn:
        conn.execute('DELETE FROM reference_images')
        conn.execute("INSERT INTO tasks(kind,status) VALUES('monitor','running')")
    assert purge(client, preview(client)['scope_token'], ['all']).status_code == 409
    assert preview(client)['blocked'] == []
    with db.connect(True) as conn:
        image(conn)
    assert purge(client, original['scope_token'], ['all']).status_code == 409


def test_batch_rule_rolls_back_all_updates(client):
    with db.connect(True) as conn:
        image(conn, author='alice')
        image(conn, author='bob')
    endpoint = ROOT + '/x/batch-rule'
    body = {'usernames': ['alice', 'bob'], 'blocked': ['quoted']}
    assert client.put(endpoint, json=body).status_code == 200
    assert client.put(endpoint, json=body | {'usernames': ['alice', 'missing'], 'blocked': []}).status_code == 404
    items = client.get(ROOT, params={'platform': 'x'}).json()['items']
    assert [item['blocked'] for item in items] == [['quoted'], ['quoted']]


def test_batch_purge_checks_combined_scope_and_preserves_individual_rules(client):
    with db.connect(True) as conn:
        first = image(conn, author='alice')
        image(conn, author='bob')
        shared = image(conn, author='carol')
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,2,?)', (first, 'also-bob'))
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,?)', (shared, 'outside'))
        conn.execute("INSERT INTO people(id,name) VALUES(1,'参考人物')")
        conn.execute('INSERT INTO reference_images(person_id,image_id,embedding,model_version) VALUES(1,?,?,?)', (first, b'feature', worker.MODEL_VERSION))
    assert not preview(client)['references']
    body = {'usernames': ['bob', 'Alice']}
    endpoint = ROOT + '/x/batch-purge'
    before = client.post(endpoint + '-preview', json=body).json()
    assert (before['posts'], before['exclusive'], before['shared']) == (2, 2, 1)
    assert before['references'][0]['image_id'] == first
    assert client.post(endpoint, json=body | {'scope_token': before['scope_token']}).status_code == 409
    with db.connect(True) as conn:
        conn.execute('DELETE FROM reference_images')
    token = client.post(endpoint + '-preview', json=body).json()['scope_token']
    client.put(ALICE + '/rule', json={'blocked': ['quoted']})
    assert client.post(endpoint, json=body | {'scope_token': token}).status_code == 409
    token = client.post(endpoint + '-preview', json=body).json()['scope_token']
    assert client.post(endpoint, json=body | {'scope_token': token}).status_code == 200
    with db.connect() as conn:
        assert [row['id'] for row in conn.execute('SELECT id FROM images')] == [shared]
        assert [row['author'] for row in conn.execute('SELECT author FROM posts')] == ['carol']
        assert [tuple(row) for row in conn.execute('SELECT username,blocked FROM publisher_rules')] == [('alice', '["quoted"]')]


@pytest.mark.parametrize(('platform', 'blocked', 'hit', 'allowed'), [
    ('x', 'retweets', {'retweet_id': 12}, {'quote_id': 12}),
    ('x', 'quoted', {'quote_id': 12}, {'quoted_id': 12}),
    ('instagram', 'reposts', {'subcategory': 'reposts'}, {'subcategory': 'posts'}),
    ('instagram', 'tagged', {'subcategory': 'tagged'}, {'coauthors': [{'username': 'alice'}]}),
])
def test_directory_obeys_actual_discovery(client, tmp_path, platform, blocked, hit, allowed):
    path = source(tmp_path)
    raw = {'platform': platform, 'author': 'ALICE', 'collected_account': 'elsewhere', 'post_id': '123'}
    with db.connect(True) as conn:
        conn.execute('INSERT INTO publisher_rules VALUES(?,?,?,?)', (platform, 'alice', 'Alice', json.dumps([blocked])))
    assert importer.import_file(path, raw | hit) is None
    assert importer.import_file(path, raw | allowed) is not None
    client.put(ROOT + '/' + platform + '/alice/rule', json={'blocked': ['all']})
    assert importer.import_file(path, raw) is None
    assert importer.import_file(path, raw | {'author': None, 'media_id': 'extra'}) is None
    with db.connect() as conn:
        assert not publisher_blocked(conn, metadata(raw | {'author': 'other', 'collected_account': 'alice'} | hit, ''))


def test_round_rechecks_staging_without_poisoning_an_allowed_path(client, tmp_path):
    task_id = client.post('/api/v1/admin/import', json={'urls': ['https://x.com/other']}).json()[0]['task_id']
    active = DownloadRound(task_id, worker.claim(('download',))['rounds'])
    quoted = metadata(RAW | {'quote_id': 12345}, '')
    assert not active.skip(quoted)
    active.stage(source(tmp_path), quoted, tmp_path)
    with db.connect(True) as conn:
        conn.execute("INSERT INTO publisher_rules VALUES('x','ALICE','Alice','[\"quoted\"]')")
    active.resume()
    assert active.skip(quoted)
    direct = metadata(RAW, '')
    assert not active.skip(direct)
    active.stage(source(tmp_path), direct, tmp_path)
    active.import_ready()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 1
        assert conn.execute('SELECT done FROM tasks WHERE id=?', (task_id,)).fetchone()[0] == 1
        assert not conn.execute('SELECT 1 FROM download_ready UNION ALL SELECT 1 FROM download_item_errors').fetchone()
