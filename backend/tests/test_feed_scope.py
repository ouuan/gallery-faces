import json
import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
from gallery_dl.extractor.common import Extractor
from gallery_dl.extractor.instagram import InstagramExtractor, InstagramStoriesExtractor
from gallery_dl.extractor.twitter import TwitterExtractor

from app import db, worker
from app.download_round import DownloadRound
from app.downloader import install_policy
from app.feed_scope import ImportScope, effective_scope, feeds
from app.metadata import metadata
from test_monitors import create, get_task, run
from test_workflows import client, image


@pytest.mark.parametrize('bounds', [('start',), ('end',), ('start', 'end')])
def test_reposts_reject_dates_before_any_task(client, bounds):
    body = {'urls': ['https://x.com/a', 'https://instagram.com/a'], 'directory': '.', 'scope': {'reposts': True},
            **dict.fromkeys(bounds, '2025-01-01T00:00:00Z')}
    response = client.post('/api/v1/admin/import', json=body)
    assert response.status_code == 400 and '转发' in response.json()['detail']
    with db.connect() as conn:
        assert not conn.execute("SELECT 1 FROM tasks WHERE kind IN ('download','import')").fetchone()


@pytest.mark.parametrize('url,options,expected', [
    ('https://x.com/a', {}, ['media', 'tweets']),
    ('https://x.com/a', {'quoted': True}, ['media', 'tweets']),
    ('https://x.com/a', {'retweets': True}, ['media', 'tweets', 'reposts']),
    ('https://x.com/a', {'retweets': True, 'quoted': True}, ['media', 'tweets', 'reposts']),
    ('https://x.com/a/media', {'retweets': True}, [None]),
    ('https://x.com/i/lists/123', {'retweets': True}, [None]),
    ('https://instagram.com/p/abc', {'reposts': True}, [None]),
    ('https://instagram.com/a', {}, ['stories', 'posts']),
    ('https://instagram.com/a', {'stories': False, 'tagged': False, 'reposts': True}, ['posts', 'reposts']),
    ('https://instagram.com/a', {'tagged': True}, ['stories', 'posts', 'tagged']),
    ('https://instagram.com/a', {'stories': False}, ['posts']),
])
def test_feed_selection(url, options, expected):
    assert feeds({'url': url, 'scope': effective_scope(url, ImportScope(**options).model_dump())}) == expected
    assert feeds({'url': url}) == [None]


def test_effective_scope_dedup_and_checkpoint(client):
    def submit(**options):
        return client.post('/api/v1/admin/import', json={'urls': ['https://instagram.com/a'], 'scope': options}).json()[0]
    identifier = submit(reposts=True)['task_id']
    assert submit(reposts=True, quoted=True)['status'] == 'duplicate'
    assert submit()['status'] == 'queued'
    task = worker.claim(('download',))
    assert task['id'] == identifier
    def load():
        return DownloadRound(identifier, task['rounds'])
    active = load()
    assert active.feeds == ['stories', 'posts', 'reposts']
    assert active.next_feed()
    active = load()
    assert active.feed_index == 1 and active.cursor is None
    active.checkpoint('post-page-2')
    assert load().cursor == 'post-page-2'
    assert load().next_feed()
    active = load()
    assert active.feed_index == 2 and active.cursor is None
    active.checkpoint('expired')
    load().checkpoint(None)
    assert load().feed_index == 2 and load().cursor is None


@pytest.mark.parametrize('options,saved,expected', [
    ({}, 'old-media-cursor', [0, 'old-media-cursor']),
    ({'quoted': True}, '[0,"media-page"]', [0, 'media-page']),
    ({'quoted': True}, '[1,"quotes-page"]', [1, None]),
    ({'retweets': True}, '[1,"reposts-page"]', [1, None]),
])
def test_upgrade_x_account_cursor(client, options, saved, expected):
    identifier = client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice'], 'scope': options}).json()[0]['task_id']
    task = worker.claim(('download',))
    with db.connect(True) as conn:
        conn.execute('UPDATE schema_version SET version=14')
        conn.execute('INSERT INTO download_cursors VALUES(?,?)', (identifier, saved))
    db.init()
    active = DownloadRound(identifier, task['rounds'])
    assert [active.feed_index, active.cursor] == expected


def test_x_account_worker_counts_union_of_media_and_timeline(client, monkeypatch):
    with db.connect(True) as conn:
        identifiers = [str(image(conn, faces=False)) for _ in range(2)]
    identifier = client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice']}).json()[0]['task_id']
    script = '''
import sys
from datetime import datetime
from gallery_dl.extractor.twitter import TwitterAPI, TwitterExtractor
from app.downloader import main
shared, timeline_only = sys.argv.pop(1), sys.argv.pop(1)
TwitterExtractor.login = lambda self: None
TwitterAPI.user_by_screen_name = lambda self, name: {'protected': False}
def posts(*identifiers):
    return ({'id_str': identifier, 'user': {'protected': False}} for identifier in identifiers)
TwitterAPI.user_media_photos = lambda self, name: posts(shared)
TwitterAPI.user_original_timeline = lambda self, name: posts(shared, timeline_only)
TwitterExtractor._transform_tweet = lambda self, tweet: {'tweet_id': tweet['id_str'], 'author': {'name': 'alice'}, 'date': datetime(2026, 1, 1)}
TwitterExtractor._extract_files = lambda self, data, tweet: [{'url': 'https://pbs.twimg.com/' + data['id_str'] + '.png'}]
raise SystemExit(main())
'''
    popen = subprocess.Popen
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda command, **kwargs: popen(
        [sys.executable, '-c', script, *identifiers, *command[3:]], **kwargs))
    for done, status in [(1, 'queued'), (2, 'done')]:
        worker.execute(worker.claim(('download',)))
        row = get_task(identifier)
        assert (row['done'], row['status']) == (done, status), row['error']
        assert json.loads(row['result'])['skipped_existing'] == done


def test_instagram_worker_runs_each_selected_feed_once(client, monkeypatch, tmp_path):
    identifier = client.post('/api/v1/admin/import', json={
        'urls': ['https://instagram.com/alice'], 'scope': {'tagged': True, 'reposts': True},
    }).json()[0]['task_id']
    report = tmp_path / 'feeds.txt'
    script = '''
import sys
from gallery_dl.extractor.instagram import InstagramAPI, InstagramExtractor
from app.downloader import main
report = sys.argv.pop(1)
profile = {'id': '12', 'username': 'alice', 'is_private': False}
InstagramExtractor.login = lambda self: None
InstagramAPI.user = lambda self, name: profile
InstagramAPI._user_by_id_impl = lambda self, uid: profile
def empty_feed(api, *args):
    with open(report, 'a') as out:
        print(api.extractor.subcategory, file=out)
    return ()
InstagramAPI.user_feed = InstagramAPI.user_tagged = InstagramAPI.user_reposts = InstagramAPI.reels_media = empty_feed
raise SystemExit(main())
'''
    popen = subprocess.Popen
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda command, **kwargs: popen(
        [sys.executable, '-c', script, str(report), *command[3:]], **kwargs))
    for status in ('queued', 'queued', 'queued', 'done'):
        worker.execute(worker.claim(('download',)))
        row = get_task(identifier)
        assert row['status'] == status, row['error']
    assert report.read_text().splitlines() == ['stories', 'posts', 'tagged', 'reposts']


def test_monitor_scope_validation_snapshot_and_retry(client, monkeypatch):
    item = create(client, platform='instagram')
    endpoint = '/api/v1/admin/monitors'
    current = f"{endpoint}/{item['id']}"
    defaults = {'stories': True, 'tagged': False}
    for options in ({'reposts': True}, {'quoted': True}):
        assert client.post(endpoint, json={'platform': 'instagram', 'username': 'new', 'scope': options}).status_code == 422
        assert client.patch(current, json={'scope': options}).status_code == 422
    assert client.get(endpoint).json()[0]['scope'] == defaults
    updated = {'stories': False, 'tagged': True}
    assert client.patch(current, json={'scope': updated}).status_code == 200
    assert client.get(endpoint).json()[0]['scope'] == updated
    assert json.loads(get_task(item['task_id'])['payload'])['scope'] == defaults
    run(monkeypatch, failure=True)
    retry = client.post(f"/api/v1/admin/tasks/{item['task_id']}/retry").json()['task_id']
    assert json.loads(get_task(retry)['payload'])['scope'] == defaults
    run(monkeypatch)
    task = client.post(endpoint + '/batch', json={'ids': [item['id']], 'action': 'backfill', 'start': '2025-01-01T00:00:00Z'}).json()[0]
    assert json.loads(get_task(task['task_id'])['payload'])['scope'] == updated


@pytest.fixture
def extractor_hooks(monkeypatch):
    for cls, names in ((Extractor, ['initialize']), (TwitterExtractor, ['_transform_tweet', 'items']),
                       (InstagramExtractor, ['_parse_post', 'items']), (InstagramStoriesExtractor, ['posts', 'pattern'])):
        for name in names:
            monkeypatch.setattr(cls, name, getattr(cls, name))


def test_story_items_have_stable_identity_and_individual_privacy(extractor_hooks, monkeypatch):
    profile = {'id': '12', 'username': 'alice', 'is_private': False}
    def item(identifier, timestamp):
        return {'pk': identifier, 'taken_at': timestamp, 'image_versions2': {'candidates': [
            {'url': 'https://cdninstagram.com/image.jpg', 'width': 32, 'height': 32}]}}
    older, newer = item('1001', 100000), item('1002', 200000)
    reel = {'id': '12', 'user': profile, 'items': [older, newer]}
    monkeypatch.setattr(InstagramStoriesExtractor, 'posts', lambda self: [reel])
    state = install_policy(feed='stories')
    extractor = InstagramStoriesExtractor.from_url('https://www.instagram.com/stories/alice/')
    extractor.initialize()
    extractor.api = SimpleNamespace(_user_by_id_impl=lambda uid: profile)
    def snapshots():
        for story in extractor.posts():
            post = extractor._parse_post(story)
            yield metadata({'category': 'instagram', **post, **post['_files'][0]}, '')
    photos = list(snapshots())
    assert [(photo['key'], photo['media']) for photo in photos] == [('1002', '1'), ('1001', '1')]
    assert photos[0]['url'] == 'https://www.instagram.com/stories/alice/1002/'
    assert photos[0]['date'] > photos[1]['date']
    reel['items'] = [newer]
    assert list(snapshots()) == photos[:1]
    newer['audience'] = 'besties'
    with pytest.raises(ValueError):
        list(snapshots())
    assert state['denied']


@pytest.mark.parametrize('kind', ['retweet', 'quote'])
def test_x_share_keeps_original_id_and_date(extractor_hooks, monkeypatch, kind):
    shared_id = '1980000000000000000'
    original = {'legacy': {'id_str': '123'}, 'user': {'protected': False}}
    monkeypatch.setattr(TwitterExtractor, '_transform_tweet', lambda self, raw: {'tweet_id': raw['legacy']['id_str'], 'date': datetime(2020, 1, 1)})
    state = install_policy(scope={'retweets': True, 'quoted': True})
    extractor = SimpleNamespace(_tweetid_to_datetime=lambda ident: datetime(2026, 1, 1))
    if kind == 'quote':
        original['legacy']['quoted_by_id_str'] = shared_id
        raw = original
    else:
        raw = {'legacy': {'id_str': shared_id, 'retweeted_status_id_str': '123', 'retweeted_status_result': {'result': original}},
               'user': {'protected': False}}
    data = TwitterExtractor._transform_tweet(extractor, raw)
    assert data == {'tweet_id': '123', 'date': datetime(2026, 1, 1), 'source_date': datetime(2020, 1, 1)}
    original['user']['protected'] = True
    with pytest.raises(ValueError):
        TwitterExtractor._transform_tweet(extractor, raw)
    assert state['denied']
