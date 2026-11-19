from app import db
from test_workflows import client


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
