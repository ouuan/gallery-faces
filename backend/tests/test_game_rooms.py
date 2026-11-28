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
    member = client.post(BASE, json={'nickname': '甲', 'settings': {'grid': False}, 'filters': {'people': '1,2'}}).json()
    path = f"{BASE}/{member['code']}"
    credentials = [member['token']]
    match_id = client.get(path, headers={'X-Room-Token': member['token']}).json()['match_id']

    def join(name):
        response = client.post(path + '/join', json={'nickname': name})
        assert response.status_code == 201
        credentials.append(response.json()['token'])

    def preload(view):
        if view.get('phase') == 'loading' and not view['grid']:
            for player in view['players']:
                if player['online'] and player['playing']:
                    view = client.post(path + '/actions', headers={'X-Room-Token': credentials[player['id'] - 1]},
                                       json={'action': 'image_loaded', 'stage': view['stage'], 'match_id': view['match_id']}).json()
        return view

    def state(who=0):
        view = client.get(path, headers={'X-Room-Token': credentials[who]}).json()
        if view.get('phase') == 'loading' and not view['grid']:
            preload(view)
            return client.get(path, headers={'X-Room-Token': credentials[who]}).json()
        return view

    def act(action, who=0, status=200, stage=None, **fields):
        nonlocal match_id
        if 'settings' in fields:
            fields['settings'].setdefault('grid', False)
        if stage is None:
            stage = state(who)['stage']
        response = client.post(path + '/actions', headers={'X-Room-Token': credentials[who]},
                               json={'action': action, 'stage': stage, 'match_id': match_id, **fields})
        assert response.status_code == status, response.text
        view = response.json()
        if action == 'restart' and status == 200:
            match_id = view['match_id']
        if view.get('phase') == 'loading' and not view['grid']:
            preload(view)
            return state(who)
        return view

    join('乙')
    return join, state, act, now


def test_filter_changes_are_validated_before_start(match):
    _, state, act, _ = match
    original = state()
    act('settings', 1, status=403, filters={})
    act('settings', status=400, settings={'cropped': False}, filters={'start': 'invalid'})
    assert state()['filters'] == original['filters'] and state()['settings'] == original['settings']
    act('settings', filters={'publishers': 'x:absent'})
    assert state(1)['filters']['publishers'] == 'x:absent'
    assert act('start')['phase'] == 'waiting'
    act('settings', status=409, filters={})


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
    act('finish', match_id=first['match_id'], status=409)
    act('answer', 1, stage=first['stage'], choice=1, status=409)
    act('answer', 1, choice=1)


@pytest.mark.parametrize('automatic', [False, True])
def test_round_limit_finishes_after_last_reveal(match, automatic):
    _, state, act, now = match
    act('settings', status=422, settings={'round_limit': -1})
    act('settings', settings={'round_limit': 2, 'continue_seconds': 5 if automatic else 0})
    assert act('start')['round'] == 1
    for number in (1, 2):
        act('answer', choice=1)
        assert act('answer', 1, choice=2)['phase'] == 'reveal'
        if number == 2:
            act('draft'); act('submit', suggested_person_id=2)
            assert act('vote', 1, support=True)['accepted']
        if automatic:
            now[0] += 5
            after = state()
        else:
            act('ready'); after = act('ready', 1)
        assert after['phase'] == ('answer' if number == 1 else 'finished')
        assert after['round'] == 2
    new = act('restart')
    assert new['round'] == 1 and new['settings']['round_limit'] == 2


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
    assert question['settings'] == game_rooms.RoomSettings(grid=False).model_dump()
    assert question['photo'] == state(1)['photo']
    assert set(question['photo']) == {'box', 'width', 'height', 'choices', 'image_url'}
    assert question['answer_name'] is question['correct_choice'] is question['source_photo'] is None
    act('answer', choice=1)
    pending = state(1)
    assert pending['players'][0]['correct'] == 0 and pending['tallies'] is None
    act('answer', status=409, choice=2)
    result = act('answer', 1, choice=2)
    join('丙')
    act('answer', 2, status=403, choice=1)
    result = state()
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
    now[0] += game_rooms.RETENTION + 1
    assert state()['detail'] == '房间不存在或已失效'


def test_tallies_exclude_unanswered_but_include_none(match):
    join, state, act, now = match
    join('丙'); join('丁')
    act('start'); act('answer', choice=None); act('answer', 1, choice=None); act('answer', 2, choice=2)
    assert state(3)['tallies'] is None
    now[0] += 15
    counts = {item['choice']: (item['count'], item['nickname']) for item in state(3)['tallies']}
    assert counts == {2: (1, '丙'), None: (2, None)}


def test_late_join_can_answer_without_extending_deadline(match):
    join, state, act, now = match
    act('start'); now[0] += 4
    join('丙')
    assert state(2)['remaining'] == 11
    assert act('answer', 2, choice=1)['choice'] == 1


def load_grid(act, count=2):
    for who in range(count):
        view = act('image_loaded', who)
    assert view['phase'] == 'answer'
    return view


def test_grid_waits_for_online_players_or_five_seconds(match):
    join, state, act, now = match
    act('settings', settings={'grid': True})
    pending = act('start')
    assert pending['phase'] == 'loading' and pending['remaining'] == 5
    assert all(pending[key] is None for key in ('answer_name', 'source_photo', 'correct_choice', 'tallies'))
    act('image_loaded'); act('image_loaded')
    now[0] += 4.75
    join('丙')
    assert act('image_loaded', 1)['phase'] == 'loading'
    act('answer', status=409, choice=1)
    assert state(2)['grid']['elapsed'] == 0
    now[0] += 0.75
    assert state()['grid']['elapsed'] == 0.5
    assert act('image_loaded', 2, stage=pending['stage'])['phase'] == 'answer'
    assert act('answer', 2, choice=1)['grid']['correct_cells'] == 2


def test_grid_wait_ends_when_unready_player_leaves(match):
    _, state, act, now = match
    act('settings', settings={'grid': True}); act('start'); act('image_loaded')
    now[0] += 2
    act('leave', 1)
    assert state()['phase'] == 'answer' and state()['grid']['elapsed'] == 0


def test_preview_exposes_only_public_room_details_without_joining(client, match):
    _, state, act, _ = match
    act('settings', settings={'answer_seconds': 33, 'allow_late_join': False})
    started = act('start')
    path = f"{BASE}/{started['code']}/preview"
    assert client.get(path).json() == dict(phase='answer', members=2, settings=started['settings'], filters=started['filters'])
    assert state()['version'] == started['version']
    assert client.get(path.replace('face-game', 'history-quiz')).status_code == 404


def test_closed_room_allows_lobby_join_and_member_reconnect(client, match):
    join, state, act, _ = match
    act('settings', settings={'grid': True, 'allow_late_join': False})
    join('丙'); act('start')
    response = client.post(f"{BASE}/{state()['code']}/join", json={'nickname': '丁'})
    assert response.status_code == 409 and '不允许中途加入' in response.json()['detail']
    act('leave', 2)
    assert state(2)['players'][2]['online']


def test_grid_round_privacy_timing_and_rescore(match):
    join, state, act, now = match
    act('settings', settings={'grid': True, 'grid_size': 5, 'grid_seconds': 0.5, 'continue_seconds': 0})
    act('start'); first = load_grid(act)
    assert not first['settings']['single_life'] and first['remaining'] == 27.5
    assert sorted(first['grid']['order']) == list(range(25))
    assert first['grid']['correct_cells'] is None
    now[0] += 0.499
    for choice in (None, 1):
        assert act('answer', status=409, choice=choice)['detail'] == '首格揭示后才能作答'
    assert state()['players'] == first['players'] and not state()['grid']['wrong_choices']
    now[0] += 0.001
    wrong = act('answer', choice=None)
    assert wrong['grid']['wrong_choices'] == [None] and wrong['players'][0]['wrong'] == 1
    assert state()['grid'] == wrong['grid']
    other = state(1)
    assert other['version'] == first['version'] and other['players'] == first['players']
    assert not other['grid']['wrong_choices'] and other['tallies'] is None
    act('answer', status=409, choice=None)
    now[0] += 0.5
    join('丙'); assert state(2)['grid']['order'] == first['grid']['order']
    act('answer', 2, choice=2); act('answer', 1, choice=2)
    now[0] += 20
    assert state()['phase'] == 'answer'
    result = act('answer', choice=1)
    def scores(view):
        return [(player['correct'], player['wrong'], player['correct_cells']) for player in view['players']]
    assert scores(result) == [(1, 1, 25), (0, 1, 0), (0, 1, 0)]
    assert result['grid']['correct_cells'] == 25
    assert {item['choice']: (item['count'], item['nickname']) for item in result['tallies']} == {
        None: (1, '甲'), 2: (2, None), 1: (1, '甲')}
    act('answer', 1, stage=first['stage'], status=409, choice=1)
    act('draft'); act('submit', suggested_person_id=2); act('vote', 1, support=True)
    corrected = act('vote', 2, support=True)
    assert corrected['tallies'] == result['tallies'] and not corrected['void']
    assert scores(corrected) == [(0, 1, 0), (0, 0, 0), (1, 0, 2)]
    assert corrected['grid']['correct_cells'] == 2
    act('ready'); act('ready', 1); act('ready', 2)
    load_grid(act, 3)
    now[0] += 0.5
    act('answer', choice=None)
    assert scores(act('finish')) == scores(corrected)
    assert scores(act('restart')) == [(0, 0, 0)] * 3


@pytest.mark.parametrize('proposal', [{'suggested_person_id': 2}, {'not_face': True}])
def test_grid_void_round_restores_all_previous_statistics(match, proposal):
    _, _, act, now = match
    act('settings', settings={'grid': True, 'continue_seconds': 0})
    act('start'); load_grid(act); now[0] += 0.5
    act('answer', 1, choice=2); previous = act('answer', choice=1)
    act('ready'); act('ready', 1)
    load_grid(act)
    now[0] += 0.5
    act('answer', choice=None); original = act('answer', 1, choice=1)
    act('draft'); act('submit', **proposal); corrected = act('vote', 1, support=True)
    assert corrected['void'] and corrected['tallies'] == original['tallies']
    assert corrected['grid']['correct_cells'] is None
    for before, after in zip(previous['players'], corrected['players'], strict=True):
        assert all(before[key] == after[key] for key in ('correct', 'wrong', 'correct_cells'))


def test_grid_give_up_waits_for_full_grid_and_all_players(match):
    _, state, act, now = match
    act('settings', settings={'grid': True, 'grid_size': 2, 'grid_seconds': 0.5, 'continue_seconds': 0})
    act('start'); load_grid(act); now[0] += 1.999
    act('give_up', status=409)
    act('answer', choice=2)
    now[0] += 0.001
    pending = act('give_up')
    assert pending['phase'] == 'answer' and pending['grid']['gave_up']
    assert state()['grid']['gave_up'] and not state(1)['grid']['gave_up']
    act('give_up', status=409); act('answer', choice=1, status=409)
    result = act('give_up', 1)
    assert result['phase'] == 'reveal' and result['correct_choice'] == 1 and not result['void']
    assert result['grid']['correct_cells'] is None
    assert [(player['correct'], player['wrong']) for player in result['players']] == [(0, 1), (0, 0)]
    act('ready'); following = act('ready', 1)
    assert following['round'] == 2 and not following['grid']['gave_up']


@pytest.mark.parametrize('last_action', ['answer', 'leave'])
def test_grid_give_up_does_not_block_other_players(match, last_action):
    _, _, act, now = match
    act('settings', settings={'grid': True, 'grid_size': 2})
    act('start'); load_grid(act); now[0] += 2
    act('give_up')
    result = act(last_action, 1, **({'choice': 1} if last_action == 'answer' else {}))
    assert result['phase'] == 'reveal' and not result['void']
    assert result['grid']['correct_cells'] == (4 if last_action == 'answer' else None)


def test_grid_competing_correct_answers_score_once(match):
    _, _, act, now = match
    act('settings', settings={'grid': True})
    act('start'); start = load_grid(act)
    now[0] += 0.25
    def submit(who):
        try:
            return act('answer', who, stage=start['stage'], choice=1)['phase']
        except AssertionError as error:
            assert '已抢先答对' in str(error)
            return 'stale'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(submit, (0, 1))) == ['reveal', 'stale']
    players = act('finish')['players']
    assert sum(player['correct'] for player in players) == 1
    assert all(player['correct_cells'] == player['correct'] for player in players)


def test_grid_life_only_eliminates_attempted_wrong_answer(match):
    join, state, act, now = match
    join('丙')
    act('settings', settings={'grid': True, 'single_life': True, 'grid_size': 2, 'grid_seconds': 0.5, 'answer_seconds': 3})
    start = act('start'); load_grid(act, 3)
    now[0] += 2
    act('answer', choice=2); act('give_up', 1)
    game_rooms.rooms.clear()
    assert state()['remaining'] == 3
    now[0] += 3
    players = state()['players']
    assert [player['eliminated'] for player in players] == [True, False, False]
    act('finish'); again = act('restart')
    assert again['match_id'] != start['match_id']
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM game_matches WHERE code=?', (start['code'],)).fetchone()[0] == 2


def test_correction_can_restore_room_life_but_never_public_streak(match):
    _, state, act, _ = match
    act('settings', settings={'single_life': True, 'continue_seconds': 0})
    act('start'); act('answer', choice=1); act('answer', 1, choice=1)
    act('ready'); act('ready', 1)
    act('answer', choice=2); act('answer', 1, choice=2)
    act('draft'); act('submit', suggested_person_id=2); act('vote', 1, support=True)
    act('ready'); act('ready', 1)
    game_rooms.rooms.clear()
    act('answer', choice=1); act('answer', 1, choice=2)
    act('ready'); final = act('ready', 1)
    assert final['phase'] == 'finished'
    assert [(player['correct'], player['public_correct'], player['eligible']) for player in state()['players']] == [(3, 1, True), (2, 1, True)]


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
