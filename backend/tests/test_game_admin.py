from datetime import datetime, timezone

from app import db, game_rooms
from test_game_rooms import match
from test_workflows import client


def test_admin_lists_matches_without_advancing_or_touching(client, match):
    _, _, act, now = match
    created = datetime.fromtimestamp(now[0], timezone.utc)
    first = act('start')
    now[0] += 5
    ended = act('finish')
    finished = datetime.fromtimestamp(now[0], timezone.utc)
    now[0] += 5
    second = act('restart', stage=ended['stage'])
    restarted = datetime.fromtimestamp(now[0], timezone.utc)
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
    active = client.get(path, params={'phase': 'active', 'limit': 1}).json()
    assert active['total'] == 1 and active['items'][0]['id'] == second['match_id']
    assert client.get(path, params={'mode': 'solo'}).json()['total'] == 0
    detail = client.get(path + '/' + second['match_id']).json()
    previous = client.get(path + '/' + first['match_id']).json()
    assert datetime.fromisoformat(previous['created_at']) == created
    assert datetime.fromisoformat(previous['activity']) == finished
    assert datetime.fromisoformat(detail['created_at']) == restarted
    assert detail['phase'] == 'answer' and detail['round'] == 1 and len(detail['players']) == 2
    assert all('token' not in player for player in detail['players']) and 'question' not in detail
    assert snapshot() == before
    now[0] += game_rooms.RETENTION
    assert client.get(path).json()['total'] == 0
    client.cookies.clear()
    assert client.get(path).status_code == client.get(path + '/' + second['match_id']).status_code == 401
