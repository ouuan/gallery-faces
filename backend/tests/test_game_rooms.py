from concurrent.futures import ThreadPoolExecutor

import pytest

from app import db, game_rooms
from test_face_game import seed
from test_workflows import client


BASE = '/api/v1/face-game/rooms'


@pytest.fixture
def match(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(game_rooms, 'clock', lambda: now[0])
    monkeypatch.setattr('app.photo_draw.random.random', lambda: 1)
    with db.connect(True) as conn:
        seed(conn)
    member = client.post(BASE, json={'nickname': '甲', 'filters': {'people': '1,2'}}).json()
    path = f"{BASE}/{member['code']}"
    credentials = [member['token']]

    def join(name):
        response = client.post(path + '/join', json={'nickname': name})
        assert response.status_code == 201
        credentials.append(response.json()['token'])

    def state(who=0):
        return client.get(path, headers={'X-Room-Token': credentials[who]}).json()

    def act(action, who=0, status=200, stage=None, **fields):
        if stage is None:
            stage = state(who)['stage']
        response = client.post(path + '/actions', headers={'X-Room-Token': credentials[who]},
                               json={'action': action, 'stage': stage, **fields})
        assert response.status_code == status, response.text
        return response.json()

    join('乙')
    return join, state, act, now


@pytest.mark.parametrize('single_life', [True, False])
def test_host_restarts_finished_room(match, single_life):
    _, state, act, _ = match
    act('settings', settings={'single_life': single_life, 'cropped': True, 'continue_seconds': 17})
    first = act('start')
    act('restart', status=409)
    act('answer', choice=1); act('answer', 1, choice=2)
    act('draft'); act('submit', suggested_person_id=2); act('vote', 1, support=True)
    if single_life:
        act('ready'); finished = act('ready', 1)
    else:
        finished = act('finish')
    assert finished['phase'] == 'finished'
    act('restart', 1, status=403)
    new = act('restart')
    assert new['phase'] == 'answer' and new['round'] == 1 and new['stage'] > finished['stage']
    assert new['settings'] == first['settings'] and new['filters'] == first['filters'] and new['code'] == first['code']
    assert new['proposal'] is new['tallies'] is new['accepted'] is None and not new['ending']
    assert state(1)['me'] == 2
    for player in new['players']:
        assert player['playing'] and not any(player[key] for key in ('correct', 'wrong', 'unanswered', 'eliminated', 'ready', 'answered'))
    act('restart', stage=finished['stage'], status=409)
    act('answer', 1, stage=first['stage'], choice=1, status=409)
    act('answer', 1, choice=1)


def test_restart_alone_reopens_lobby(match):
    join, state, act, _ = match
    act('start'); act('finish'); act('leave', 1)
    new = act('restart')
    assert new['phase'] == 'lobby' and new['round'] == 0 and new['photo'] is None
    assert [player['name'] for player in new['players']] == ['甲']
    join('乙'); assert act('start')['round'] == 1


def test_shared_round_feedback_and_reconnect(match):
    join, state, act, now = match
    act('start', 1, status=403)
    question = act('start')
    assert question['settings'] == {'answer_seconds': 15, 'continue_seconds': 10, 'cropped': True, 'single_life': False}
    assert question['photo'] == state(1)['photo']
    assert set(question['photo']) == {'box', 'width', 'height', 'choices', 'image_url'}
    assert question['answer_name'] is question['correct_choice'] is question['source_photo'] is None
    join('丙')
    act('answer', 2, status=403, choice=1)
    act('answer', choice=1)
    pending = state(1)
    assert pending['players'][0]['correct'] == 0 and pending['tallies'] is None
    act('answer', status=409, choice=2)
    result = act('answer', 1, choice=2)
    assert result['phase'] == 'reveal' and result['correct_choice'] == 1
    assert result['source_photo'] == {'group_id': 1, 'image_id': 1}
    assert [player['correct'] for player in result['players']] == [1, 0, 0]
    assert [player['wrong'] for player in result['players']] == [0, 1, 0]
    assert not any(player['unanswered'] for player in result['players'])
    act('ready', 1)
    now[0] += 4
    assert act('draft')['remaining'] == 90
    now[0] += 20
    act('ready', 1, status=409)
    assert act('cancel')['remaining'] == 10
    draft = act('draft', 1)
    vote = act('submit', 1, suggested_person_id=2, content='看脸型')
    assert vote['phase'] == 'vote' and vote['proposal']['content'] == '看脸型'
    act('submit', 1, stage=draft['stage'], status=409, suggested_person_id=2)
    act('vote', 2, status=403, support=True)
    final = act('vote', support=True)
    assert final['accepted'] and final['correct_choice'] == 2
    assert final['tallies'] == result['tallies']
    assert [player['correct'] for player in state(1)['players']] == [0, 1, 0]
    assert [player['wrong'] for player in state(1)['players']] == [1, 0, 0]
    assert final['remaining'] == 10 and not any(player['ready'] for player in final['players'])
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback').fetchone()[0] == 1
        assert conn.execute('SELECT person_id FROM faces').fetchone()[0] == 1
    act('ready')
    assert act('ready', 1)['phase'] == 'answer'
    assert state(2)['players'][2]['playing']
    assert act('finish')['phase'] == 'finished'


@pytest.mark.parametrize(('proposal', 'choice', 'void'), [({'suggested_person_id': 7}, None, False), ({'not_face': True}, None, True), ({}, None, True)])
def test_vote_effect_and_pending_finish(match, proposal, choice, void):
    _, _, act, _ = match
    act('start'); act('answer', choice=1); act('answer', 1, choice=None)
    act('draft'); act('submit', **proposal)
    assert act('finish')['phase'] == 'vote'
    final = act('vote', 1, support=True)
    assert final['phase'] == 'finished' and final['void'] == void and final['correct_choice'] == choice
    assert [player['correct'] for player in final['players']] == [0, int(not void)]
    assert [player['wrong'] for player in final['players']] == [int(not void), 0]


@pytest.mark.parametrize('reject', [True, False])
def test_deadlines_and_host_transfer(match, reject):
    _, state, act, now = match
    act('start'); act('answer', choice=1)
    now[0] += 15
    assert state()['phase'] == 'reveal'
    act('draft'); now[0] += 90
    assert state(1)['remaining'] == 10
    assert state(1)['host'] == 2
    state()
    act('draft'); act('submit', not_face=True)
    if reject:
        result = act('vote', 1, support=False)
    else:
        now[0] += 30
        result = state(1)
    assert result['accepted'] is False and result['players'][0]['correct'] == 1
    assert result['players'][1]['unanswered'] == 1 and result['players'][1]['wrong'] == 0
    state(); now[0] += 10
    assert state(1)['round'] == 2


@pytest.mark.parametrize('seconds', [0, 17])
@pytest.mark.parametrize('ending', ['cancel', 'draft_timeout', 'vote', 'vote_timeout'])
def test_feedback_ends_with_full_room_countdown(match, seconds, ending):
    _, state, act, now = match
    act('settings', settings={'continue_seconds': seconds})
    act('start'); act('answer', choice=1); act('answer', 1, choice=2)
    now[0] += 7
    act('draft')
    if ending == 'cancel':
        result = act('cancel')
    elif ending == 'draft_timeout':
        now[0] += 90
        result = state()
    else:
        act('submit', not_face=True)
        if ending == 'vote':
            result = act('vote', 1, support=True)
        else:
            now[0] += 30
            result = state()
    assert result['phase'] == 'reveal' and result['remaining'] == (seconds or None)
    assert state(1)['remaining'] == (seconds or None)
    now[0] += seconds - 1 if seconds else 20
    assert state()['round'] == 1
    now[0] += 1
    assert state()['round'] == (2 if seconds else 1)


def test_capacity_visibility_and_expiry(client, match):
    join, state, act, now = match
    view = state()
    path = f"{BASE}/{view['code']}"
    assert client.get(path, headers={'X-Room-Token': 'not-a-member'}).status_code == 403
    assert client.post(path + '/join', json={'nickname': '甲'}).status_code == 409
    for index in range(10):
        join(str(index))
    assert client.post(path + '/join', json={'nickname': '满'}).status_code == 409
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET ignored=1')
    assert act('start')['phase'] == 'waiting'
    now[0] += 901
    assert state()['detail'] == '房间不存在或已失效'


def test_tallies_exclude_unanswered_but_include_none(match):
    join, state, act, now = match
    join('丙'); join('丁')
    act('start'); act('answer', choice=None); act('answer', 1, choice=None); act('answer', 2, choice=2)
    assert state(3)['tallies'] is None
    now[0] += 15
    counts = {item['choice']: (item['count'], item['nickname']) for item in state(3)['tallies']}
    assert counts == {2: (1, '丙'), None: (2, None)}


def test_single_life_spectators_and_locked_roster(client, match):
    join, state, act, now = match
    join('丙'); join('丁')
    act('settings', settings={'single_life': True})
    started = act('start')
    assert client.post(f"{BASE}/{started['code']}/join", json={'nickname': '迟到'}).status_code == 409
    act('answer', choice=1); act('answer', 1, choice=1); act('answer', 2, choice=2)
    now[0] += 15
    original = state()['players']
    assert [(player['correct'], player['wrong'], player['unanswered']) for player in original] == [(1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
    now[0] += 10
    players = state(2)['players']
    assert [player['playing'] for player in players] == [True, True, False, False]
    act('answer', 2, status=403, choice=1)
    act('answer', choice=1); act('answer', 1, choice=2)
    assert state(3)['players'][3]['unanswered'] == 1
    now[0] += 10
    final = state()
    assert final['phase'] == 'finished' and final['round'] == 2
    assert [player['correct'] for player in final['players']] == [2, 1, 0, 0]


@pytest.mark.parametrize('surviving', [0, 1])
def test_single_life_final_feedback_can_restore_players(match, surviving):
    _, state, act, now = match
    act('settings', settings={'single_life': True, 'continue_seconds': 0})
    act('start'); act('answer', choice=1 if surviving else 2); act('answer', 1, choice=2)
    result = state(1)
    assert result['phase'] == 'reveal' and result['remaining'] == 10
    assert sum(not player['eliminated'] for player in result['players']) == surviving
    act('draft', 1); act('submit', 1, not_face=True); corrected = act('vote', support=True)
    assert corrected['remaining'] is None and not any(player['eliminated'] for player in corrected['players'])
    act('ready'); assert act('ready', 1)['round'] == 2
    now[0] += 15
    assert state()['phase'] == 'reveal'
    now[0] += 10
    final = state(1)
    assert final['phase'] == 'finished' and final['round'] == 2
    assert all(player['eliminated'] and player['unanswered'] == 1 and not player['correct'] for player in final['players'])


def test_stale_feedback_and_concurrent_commands(match):
    _, state, act, _ = match
    act('start'); act('answer', choice=1); act('answer', 1, choice=2)
    stage = act('draft')['stage']
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET revision=revision+1')
    act('submit', status=409, not_face=True)
    assert state()['phase'] == 'draft'
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET revision=revision-1')
    def submit():
        try:
            return act('submit', stage=stage, not_face=True)['phase']
        except AssertionError as error:
            assert '房间状态已更新' in str(error)
            return 'stale'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: submit(), range(2))) == ['stale', 'vote']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM feedback').fetchone()[0] == 1
