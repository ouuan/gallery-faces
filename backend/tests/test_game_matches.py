from app import db, game_rooms
from test_face_game import seed
from test_workflows import client


def test_solo_restores_original_question_and_deadline(client, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(game_rooms, 'clock', lambda: now[0])
    with db.connect(True) as conn:
        seed(conn)
    base = '/api/v1/face-game/rooms'
    member = client.post(base, json={'solo': True, 'nickname': '我', 'settings': {'single_life': True}}).json()
    path = f"{base}/{member['code']}"
    headers = {'X-Room-Token': member['token']}
    def read():
        return client.get(path, headers=headers).json()
    start = read()
    missing_id = client.post(path + '/actions', headers=headers, json={'stage': start['stage'], 'action': 'finish'})
    assert missing_id.status_code == 422
    assert start['phase'] == 'loading' and start['source_photo'] is None
    assert start['settings']['grid_seconds'] == 0.2 and len(start['grid']['order']) == 100
    now[0] += 8
    game_rooms.rooms.clear()
    restored = read()
    assert restored['photo'] == start['photo'] and restored['remaining'] == 32
    now[0] += 32
    game_rooms.rooms.clear()
    revealed = read()
    assert revealed['phase'] == 'reveal' and revealed['players'][0]['unanswered'] == 1
    assert read()['players'] == revealed['players']
