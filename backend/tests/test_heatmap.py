from app import db
from test_workflows import client, image


def test_heatmap_matches_gallery_and_posts(client):
    with db.connect(True) as conn:
        first = image(conn, date='2025-12-31T15:59:59Z')
        repost = image(conn, group=first, author='bob', date='2026-01-01T16:00:00Z')
        second = image(conn, date='2025-12-31T16:00:00Z')
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,?)', (second, repost, 'extra'))
        alias = image(conn, group=first, date='2025-12-31T15:59:59Z')
        conn.execute("UPDATE posts SET url='https://twitter.com/alias/status/1/photo/1' WHERE id=?", (alias,))
        image(conn, faces=False)
        conn.execute("INSERT INTO people(id,name) VALUES(1,'A'),(2,'B')")
        conn.execute('UPDATE faces SET person_id=1')
        conn.execute('UPDATE faces SET person_id=2 WHERE image_id=?', (second,))

    def days(**filters):
        response = client.get('/api/v1/gallery/heatmap', params={'timezone': 'Asia/Shanghai', **filters})
        assert response.status_code == 200
        result = response.json()
        assert sum(row['new_photos'] for row in result) == client.get('/api/v1/gallery', params=filters).json()['total']
        assert sum(row['posts'] for row in result) == len(client.get('/api/v1/posts', params=filters).json()['items'])
        return [(row['date'], row['new_photos'], row['posts']) for row in result]

    assert days() == [('2025-12-31', 1, 1), ('2026-01-01', 1, 1), ('2026-01-02', 0, 1)]
    assert days(publishers='x:bob') == [('2026-01-02', 2, 1)]
    assert days(people='1', match='exact') == [('2025-12-31', 1, 1), ('2026-01-02', 0, 1)]
    assert days(people='1-2', match='all') == []
    assert days(include_no_faces=True)[1] == ('2026-01-01', 2, 2)
    assert days(start='2025-12-31T16:00:00Z', end='2026-01-01T16:00:00Z') == [('2026-01-01', 1, 1)]


def test_heatmap_dst_and_validation(client):
    with db.connect(True) as conn:
        for instant in ['2026-03-08T04:59:59Z', '2026-03-08T05:00:00Z', '2026-03-09T03:59:59Z', '2026-03-09T04:00:00Z']:
            image(conn, date=instant)
    path = '/api/v1/gallery/heatmap'
    days = client.get(path, params={'timezone': 'America/New_York'}).json()
    assert [(day['date'], day['posts']) for day in days] == [('2026-03-07', 1), ('2026-03-08', 2), ('2026-03-09', 1)]
    assert client.get(path, params={'timezone': 'not/a-zone'}).status_code == 400
    assert client.get(path, params={'timezone': 'UTC', 'start': '2020-01-01'}).status_code == 400
