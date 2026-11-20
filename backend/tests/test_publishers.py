from app import db
from test_workflows import client, image


def test_large_selections_match_linked_and_explicit_publishers(client):
    with db.connect(True) as conn:
        conn.executemany('INSERT INTO people(id,name) VALUES(?,?)', [(identifier, str(identifier)) for identifier in range(1, 101)])
        conn.execute("INSERT INTO accounts(person_id,platform,username) VALUES(100,'x','linked')")
        linked = image(conn, author='LINKED')
        explicit = image(conn, author='manual')
        unrelated = image(conn, author='unrelated')
        conn.execute('UPDATE faces SET person_id=100 WHERE image_id IN (?,?)', (linked, explicit))
        conn.execute('UPDATE faces SET person_id=1 WHERE image_id=?', (unrelated,))
    params = {
        'people': ','.join(str(identifier) for identifier in range(1, 101)),
        'publishers': ','.join([*(f'person:{identifier}' for identifier in range(1, 101)), 'x:MANUAL', 'instagram:unrelated']),
    }
    for path in ('/gallery', '/posts', '/admin/images'):
        response = client.get('/api/v1' + path, params={**params, 'state': 'all'})
        assert response.status_code == 200
        rows = response.json() if path == '/admin/images' else response.json()['items']
        assert {row['id'] for row in rows} == {linked, explicit}


def test_invalid_filter_explains_what_to_reselect(client):
    for params, detail in [({'people': 'bad'}, '人物编号无效，请重新选择人物'),
                           ({'publishers': 'group:1'}, '发布者格式无效，请重新选择发布者')]:
        response = client.get('/api/v1/gallery', params=params)
        assert response.status_code == 400
        assert response.json()['detail'] == detail


def test_all_unlinked_publishers_use_nicknames_and_account_fallback(client):
    person = client.post('/api/v1/admin/people', json={
        'name': '关联人物', 'accounts': [{'platform': 'x', 'username': 'ALICE'}],
    }).json()['id']
    with db.connect(True) as conn:
        rows = [
            ('x', 'alice', '人物的昵称'),
            ('instagram', 'alice', '同名的其他平台账号'),
            ('x', 'unlinked', '旧昵称'),
            ('x', 'UNLINKED', ' 新昵称 '),
            ('x', 'unlinked', None),
            ('x', 'fallback', ' '),
            ('x', None, '缺少用户名'),
            ('x', ' ', '空用户名'),
        ] + [('x', f'account{i}', f'昵称{i}') for i in range(101)]
        conn.executemany(
            'INSERT INTO posts(platform,post_key,author,author_name) VALUES(?,?,?,?)',
            [(platform, str(i), username, label) for i, (platform, username, label) in enumerate(rows)],
        )
    client.post('/api/v1/logout', json={})
    response = client.get('/api/v1/publisher-candidates')
    assert response.status_code == 200
    candidates = {(row['platform'], row['username'].lower()): row['label'] for row in response.json()}
    assert len(response.json()) == len(candidates) == 104
    assert ('x', 'alice') not in candidates
    assert candidates['instagram', 'alice'] == '同名的其他平台账号'
    assert candidates['x', 'unlinked'] == '新昵称'
    assert candidates['x', 'fallback'] == 'fallback'
    with db.connect(True) as conn:
        conn.execute('DELETE FROM people WHERE id=?', (person,))
    assert any(row['username'] == 'alice' and row['platform'] == 'x'
               for row in client.get('/api/v1/publisher-candidates').json())
