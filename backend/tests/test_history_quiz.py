import time
from datetime import date

import pytest
from fastapi import HTTPException

from app import db, game_rooms, main, photo_draw
from test_photo_draw import photo
from test_workflows import client


ROOMS = '/api/v1/history-quiz/rooms'


def test_quiz_only_filters_first_public_source(client, monkeypatch):
    def draw(last_group=None, **filters):
        previous = {'group_id': last_group} if last_group is not None else None
        return main.draw_history_room_question(game_rooms.GameFilters(**filters), previous)

    def assert_empty(**filters):
        with pytest.raises(HTTPException) as error:
            draw(**filters)
        assert error.value.status_code == 404

    assert_empty()
    try:
        with monkeypatch.context() as patch:
            patch.setenv('TZ', 'America/New_York')
            time.tzset()
            with db.connect(True) as conn:
                first = photo(conn, date='2026-03-08T04:59:00Z')
                photo(conn, group=first, author='bob', date='2026-03-08T04:59:00Z')
                photo(conn, group=first, author='bob', date='2026-07-01T12:00:00Z')
                other_image = photo(conn, date='2026-03-09T04:00:00Z')
                other = conn.execute('SELECT group_id FROM images WHERE id=?', (other_image,)).fetchone()[0]
                photo(conn, author='carol', faces=False, date='2020-01-01T12:00:00Z')
            for params in ({'publishers': 'x:bob'}, {'start': '2026-07-01T00:00:00Z'}):
                assert client.get('/api/v1/gallery', params=params).json()['total'] == 1
                assert_empty(**params)
            result = draw(publishers='x:alice', last_group=other)
            assert (result['group_id'], result['correct_date'], result['first_date'], result['last_date']) == (
                first, date(2026, 3, 7), date(2026, 3, 7), date(2026, 3, 9))
            only = draw(start='2026-03-09T04:00:00Z')
            assert only['first_date'] == only['last_date'] == only['correct_date'] == date(2026, 3, 9)
            assert_empty(end='2026-03-08T04:59:00Z')
            assert draw(include_no_faces=True)['first_date'] == date(2020, 1, 1)
    finally:
        time.tzset()


def test_history_room_midpoint_timeout_backfill_and_reconnect(client, monkeypatch):
    with db.connect(True) as conn:
        for day in ('01', '08', '10'):
            photo(conn, date=f'2026-01-{day}T12:00:00Z')
    monkeypatch.setattr(photo_draw, 'draw', lambda *args, **kwargs: [(2, 2)])
    now = [100.0]
    monkeypatch.setattr(game_rooms, 'clock', lambda: now[0])
    member = client.post(ROOMS, json={'nickname': '甲', 'settings': {'continue_seconds': 0, 'answer_seconds': 3}}).json()
    path = f"{ROOMS}/{member['code']}"
    def headers(member):
        return {'X-Room-Token': member['token']}
    def join(name):
        return client.post(path + '/join', json={'nickname': name}).json()
    def read(who):
        return client.get(path, headers=headers(who)).json()
    def act(who, action, status=200, view=None, **fields):
        if view is None:
            view = read(who)
        response = client.post(path + '/actions', headers=headers(who), json={'action': action, 'stage': view['stage'], 'match_id': view['match_id'], **fields})
        assert response.status_code == status, response.text
        return response.json()

    def preload(*members):
        view = read(member)
        for participant in members:
            act(participant, 'image_loaded', view=view)

    guest = join('乙')
    act(member, 'start')
    assert client.get(path.replace('history-quiz', 'face-game'), headers=headers(member)).status_code == 404
    for round_number in range(1, 5):
        preload(member, guest)
        if round_number == 4:
            late = join('丙')
            assert read(late)['history']['total_deviations']['3'] == 9
            assert read(late)['history']['scores']['3'] == 0
            act(late, 'answer', guess_date='2026-01-08')
        act(member, 'answer', 422, guess_date='2026-01-11')
        act(member, 'answer', guess_date='2026-01-07')
        game_rooms.rooms.clear()
        act(member, 'answer', 409, guess_date='2026-01-08')
        pending = read(guest)
        assert pending['history']['closest'] is None
        assert pending['source_photo'] is pending['history']['correct_date'] is pending['history']['guesses'] is None
        assert 'correct_date' not in pending['history']['photo'] and pending['history']['my_guess'] is None
        now[0] += 3
        revealed = read(guest)
        assert revealed['history']['settled'] == round_number
        assert revealed['history']['closest'] == ([3] if round_number == 4 else [1])
        assert revealed['history']['guesses'] == ({'1': '2026-01-07', '3': '2026-01-08'} if round_number == 4 else {'1': '2026-01-07'})
        assert revealed['history']['total_deviations']['1'] == round_number
        assert revealed['history']['total_deviations']['2'] == 3 * round_number
        act(guest, 'draft', 409)
        act(member, 'ready'); act(guest, 'ready')
        if round_number == 4:
            act(late, 'ready')
    preload(member, guest, late)
    for _ in range(2):
        view = read(late)
        assert view['round'] == 5 and view['players'][2]['playing']
        assert view['history']['total_deviations']['3'] == 9 and view['players'][2]['unanswered'] == 3
    act(late, 'answer', guess_date='2026-01-05')
    act(member, 'answer', guess_date='2026-01-08')
    result = act(guest, 'answer', guess_date='2026-01-05')
    assert result['history']['total_deviations'] == {'1': 4, '2': 15, '3': 12}
    assert result['players'][2]['unanswered'] == 3
    assert result['history']['scores'] == {'1': 4, '2': 0, '3': 1}
    for who in (member, guest, late):
        act(who, 'ready')
    preload(member, guest, late)
    act(member, 'answer', guess_date='2026-01-07')
    act(guest, 'answer', guess_date='2026-01-09')
    now[0] += 3
    tied = read(late)['history']
    assert tied['closest'] == [1, 2] and tied['scores'] == {'1': 4.5, '2': 0.5, '3': 1}
    for who in (member, guest, late):
        act(who, 'ready')
    preload(member, guest, late)
    now[0] += 3
    empty = read(guest)['history']
    assert empty['closest'] == [] and empty['scores'] == tied['scores']
    act(member, 'finish'); restarted = act(member, 'restart')
    assert restarted['history']['settled'] == 0 and not any(restarted['history']['total_deviations'].values())
    assert restarted['history']['closest'] is None and not any(restarted['history']['scores'].values())
