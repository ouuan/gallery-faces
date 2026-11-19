from test_workflows import client, image
from app import db


def test_names(client):
    person = client.post('/api/v1/admin/people', json={'name': '中文', 'name_ja': ' 日本語 ', 'new_groups': ['组']}).json()['id']
    group = client.get('/api/v1/groups').json()[0]['id']
    client.put(f'/api/v1/admin/groups/{group}', json={'name': '组', 'name_ja': ' グループ ', 'person_ids': [person]})
    client.put(f'/api/v1/admin/people/{person}', json={'name': '中文', 'group_ids': [group]})
    data = client.get('/api/v1/people').json()[0]
    assert data['name_ja'] == '日本語'
    assert data['groups'][0]['name_ja'] == 'グループ'
    client.put(f'/api/v1/admin/people/{person}', json={'name': '中文', 'name_ja': ''})
    assert client.get('/api/v1/people').json()[0]['name_ja'] is None
    db.init()
    assert client.get('/api/v1/groups').json()[0]['name_ja'] == 'グループ'


def test_posts_dedup_and_pagination(client):
    with db.connect(True) as conn:
        a, b = image(conn), image(conn)
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,'second')", (b,))
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,2,'shared')", (a,))
        image(conn)
        conn.execute("UPDATE posts SET url='https://twitter.com/alias/status/1/photo/1' WHERE id=3")
    result = client.get('/api/v1/posts?limit=1').json()
    item = result['items'][0]
    assert item['key'] == 'x:2'
    assert set(item) == {'id','key','platform','url','embed_id','author','author_name','published_at'}
    second = client.get('/api/v1/posts', params={'limit':1,'cursor':result['next_cursor']}).json()
    assert second['items'][0]['key'] == 'x:1'
    assert second['next_cursor'] is None
    assert len(client.get('/api/v1/posts').json()['items']) == 2
    assert client.get('/api/v1/posts?cursor=invalid').status_code == 400


def test_same_photo_matching_and_visibility(client):
    with db.connect(True) as conn:
        a, b = image(conn), image(conn)
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,'second')", (b,))
        conn.execute("INSERT INTO people(id,name) VALUES(1,'A'),(2,'B')")
        conn.execute('UPDATE faces SET person_id=1 WHERE image_id=?', (a,))
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id=?', (b,))
    assert client.get('/api/v1/posts?people=1,2&match=all').json()['items'] == []
    assert len(client.get('/api/v1/posts?people=1').json()['items']) == 1
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1')
    assert client.get('/api/v1/posts').json()['items'] == []
