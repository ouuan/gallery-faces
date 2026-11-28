from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app import db, game_boards, game_rooms, main
from test_face_game import seed
from test_workflows import client


def test_equivalent_rules_use_the_same_board():
    def board(people, publishers, start, **settings):
        return game_boards.board_for('face-game', game_boards.BoardRules(settings=settings, filters=dict(
            people=people, publishers=publishers, start=start)), main.parse_people_publishers, main.date_bounds).id
    first = board('2,1', 'x:ABC,person:1-2', '2026-01-01T08:00:00+08:00')
    assert first == board('1-2', 'person:2,person:1,x:abc', '2026-01-01T00:00:00Z', continue_seconds=0, grid_size=8)
    assert first != board('1-2', 'x:abc,person:1-2', '2026-01-01T00:00:00Z', answer_seconds=30)


def test_upload_atomic_best_and_time_survive_cleanup(client, monkeypatch):
    monkeypatch.setattr('app.photo_draw.random.random', lambda: 1)
    with db.connect(True) as conn:
        seed(conn)
    def play(choice):
        base = '/api/v1/face-game/rooms'
        member = client.post(base, json={'solo': True, 'nickname': '我', 'settings': {'round_limit': 1}, 'filters': {'people': '1,2'}}).json()
        headers = {'X-Room-Token': member['token']}
        path = f"{base}/{member['code']}"
        view = client.get(path, headers=headers).json()
        for action in ('image_loaded', 'answer', 'ready'):
            view = client.post(path + '/actions', headers=headers, json={'stage': view['stage'], 'action': action, 'choice': choice}).json()
        assert view['players'][0]['eligible']
        return f"/api/v1/face-game/matches/{view['match_id']}/score", headers
    def upload(match, name='甲'):
        path, headers = match
        return client.post(path, headers=headers, json={'nickname': name})
    low, high, tie = play(2), play(1), play(1)
    original = upload(low).json()
    assert original['correct'] == 0 and upload(low).json() == original
    assert upload(low, '乙').status_code == 409
    with ThreadPoolExecutor(2) as pool:
        winners = list(pool.map(lambda match: upload(match).json(), [high, tie]))
    assert winners[0] == winners[1] and winners[0]['correct'] == 1
    assert datetime.fromisoformat(winners[0]['recorded_at']) > datetime.fromisoformat(original['recorded_at'])
    assert upload(low).json() == winners[0]
    monkeypatch.setattr(game_rooms, 'clock', lambda: 10**12)
    game_rooms.cleanup()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM game_matches').fetchone()[0] == 0
        record = conn.execute('SELECT * FROM game_records').fetchone()
        assert record['correct'] == 1 and datetime.fromisoformat(record['recorded_at']) == datetime.fromisoformat(winners[0]['recorded_at'])
