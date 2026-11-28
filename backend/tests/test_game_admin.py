from app import db, game_rooms
from test_game_rooms import match
from test_workflows import client


def test_admin_lists_matches_without_advancing_or_touching(client, match):
    _, _, act, now = match
    first = act('start'); act('finish'); second = act('restart')
    path = '/api/v1/admin/game-matches'
    now[0] += 100
    def snapshot():
        with db.connect() as conn:
            return [tuple(row) for row in conn.execute('SELECT * FROM game_matches ORDER BY id')]
    before = snapshot()
    listed = client.get(path, params={'game': 'face-game', 'mode': 'multi', 'limit': 1}).json()
    assert listed['total'] == 2 and listed['items'][0]['id'] == second['match_id']
    assert client.get(path, params={'page': 2, 'limit': 1}).json()['items'][0]['id'] == first['match_id']
    assert client.get(path, params={'phase': 'finished'}).json()['total'] == 1
    assert client.get(path, params={'mode': 'solo'}).json()['total'] == 0
    detail = client.get(path + '/' + second['match_id']).json()
    assert detail['phase'] == 'answer' and detail['round'] == 1 and len(detail['players']) == 2
    assert all('token' not in player for player in detail['players']) and 'question' not in detail
    assert snapshot() == before
    now[0] += game_rooms.RETENTION
    assert client.get(path).json()['total'] == 0
    client.cookies.clear()
    assert client.get(path).status_code == client.get(path + '/' + second['match_id']).status_code == 401
