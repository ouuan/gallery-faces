import json
from datetime import timedelta

import pytest
from gallery_dl import dt, util, exception
from app import db, importer, worker
from app.downloader import date_options
from test_workflows import client


def test_import_task_ranges(client):
    body = {'urls': ['https://x.com/alice'], 'start': '2026-11-18T00:00:00+08:00', 'end': '2026-11-19T00:00:00+08:00'}
    first = client.post('/api/v1/admin/import', json=body).json()[0]
    assert first['status'] == 'queued'
    assert client.post('/api/v1/admin/import', json=body).json()[0] == {**first, 'status': 'duplicate'}
    second = client.post('/api/v1/admin/import', json={**body, 'start': ''}).json()[0]
    assert second['status'] == 'queued' and second['task_id'] != first['task_id']
    with db.connect(True) as conn:
        payload = json.loads(conn.execute('SELECT payload FROM tasks WHERE id=?', (first['task_id'],)).fetchone()[0])
        assert payload['start'] == '2026-11-17T16:00:00Z'
        assert payload['end'] == '2026-11-18T16:00:00Z'
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (first['task_id'],))
    assert client.post('/api/v1/admin/import', json=body).json()[0]['status'] == 'queued'
    assert client.post('/api/v1/admin/import', json={**body, 'end': '2026-11-17'}).status_code == 400
    for dates in ({}, {'start': '2026-11-18T00:00:00+08:00'}, {'end': '2026-11-19T00:00:00+08:00'}):
        response = client.post('/api/v1/admin/import', json={'urls': body['urls'], **dates})
        assert response.status_code == 200
        assert client.post('/api/v1/admin/import', json={'urls': body['urls'], **dates}).json()[0]['status'] == 'duplicate'


@pytest.mark.parametrize('start,end', [(None, None), ('2026-11-17T16:00:00Z', None), (None, '2026-11-18T16:00:00Z'), ('2026-11-17T16:00:00Z', '2026-11-18T16:00:00Z')])
def test_native_date_filter(start, end):
    options = date_options(start, end)
    config = dict(zip(options[::2], options[1::2]))
    if not (start or end):
        assert options == []
        return
    before = dt.convert(end) if end else None
    after = dt.convert(config['--date-after']) if start else None
    predicate = util.predicate_build([util.predicate_filter(config['--post-filter'], 'post'), util.predicate_date(before, after)])
    lower = dt.convert('2026-11-17T16:00:00Z')
    upper = dt.convert('2026-11-18T16:00:00Z')
    # A rejected pinned post must not abort before a newer normal post.
    assert predicate('', {'date': lower - timedelta(seconds=1), 'pinned': [123]}) is (not bool(start))
    assert predicate('', {'date': lower})
    assert predicate('', {'date': upper - timedelta(seconds=1)})
    assert predicate('', {'date': upper}) is (not bool(end))
    assert not predicate('', {})
    if start:
        with pytest.raises(exception.StopExtraction):
            predicate('', {'date': lower - timedelta(seconds=1)})


def test_missing_date_not_imported_when_bounded(tmp_path):
    # Must reject before even reading/downloading the media file.
    assert importer.import_file(tmp_path / 'absent.jpg', {'category': 'x'}, start='2026-01-01T00:00:00Z') is None


def test_worker_passes_date_options(client, monkeypatch):
    captured = []
    environment = {}
    class Process:
        returncode = 0
        def __init__(self, command, **kwargs):
            captured.extend(command)
            environment.update(kwargs['env'])
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def poll(self): return 0
    monkeypatch.setattr(worker.subprocess, 'Popen', Process)
    result = client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice'], 'hashtags': ['#Live'], 'start': '2026-11-18T00:00:00+08:00', 'end': '2026-11-19T00:00:00+08:00'}).json()[0]
    task = worker.claim(('download',))
    assert task['id'] == result['task_id']
    worker.import_task(task)
    assert captured[captured.index('--date-after') + 1] == '2026-11-17T15:59:59+00:00'
    assert captured[captured.index('--date-before') + 1] == '2026-11-18T16:00:00Z'
    assert '--post-filter' in captured
    assert json.loads(environment['GALLERY_FACES_HASHTAGS']) == ['live']


def test_download_dispatch_skips_outside_media():
    from types import SimpleNamespace
    from gallery_dl.job import Job
    from gallery_dl.extractor.common import Message
    options = date_options('2026-11-17T16:00:00Z', '2026-11-18T16:00:00Z')
    config = dict(zip(options[::2], options[1::2]))
    downloaded = []
    handler = SimpleNamespace(
        metadata_url=None, extractor=SimpleNamespace(config=lambda _: None),
        update_kwdict=lambda _: None, handle_directory=lambda _: None,
        handle_url=lambda url, _: downloaded.append(url), pred_url=lambda *_: True,
        pred_post=util.predicate_build([
            util.predicate_filter(config['--post-filter'], 'post'),
            util.predicate_date(dt.convert(config['--date-before']), dt.convert(config['--date-after'])),
        ]),
    )
    messages = []
    for name, date, pinned in [
        ('old-pinned', '2026-01-01T00:00:00Z', True),
        ('too-new', '2026-11-18T16:00:00Z', False),
        ('inside', '2026-11-17T16:00:00Z', False),
        ('missing-date', None, False),
    ]:
        metadata = {'date': dt.convert(date), 'pinned': pinned}
        messages += [(Message.Directory, '', metadata), (Message.Url, name, metadata)]
    Job.dispatch(handler, messages)
    assert downloaded == ['inside']



@pytest.mark.parametrize('start,end,expected', [
    ('2026-03-08T00:00:00-05:00', '2026-03-09T00:00:00-04:00', ('2026-03-08T05:00:00Z','2026-03-09T04:00:00Z')),
    ('2026-11-01T00:00:00-04:00', '2026-11-02T00:00:00-05:00', ('2026-11-01T04:00:00Z','2026-11-02T05:00:00Z')),
    ('2026-01-01T00:00:00+05:45', '', ('2025-12-31T18:15:00Z',None)),
    ('', '2026-01-01T00:00:00+05:30', (None,'2025-12-31T18:30:00Z')),
])
def test_explicit_offsets(client, start, end, expected):
    task = client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice'], 'start': start, 'end': end}).json()[0]
    with db.connect() as conn:
        payload = json.loads(conn.execute('SELECT payload FROM tasks WHERE id=?', (task['task_id'],)).fetchone()[0])
    assert (payload['start'], payload['end']) == expected
    assert 'timezone' not in client.get('/api/v1/site').json()

@pytest.mark.parametrize('params', [
    {'start': '2026-11-18T12:34:56'}, {'start': '20261118'},
    {'start': '2026-02-30'}, {'end': '9999-12-31'},
    {'start': '2026-11-19T00:00:00Z', 'end': '2026-11-18T00:00:00Z'},
    {'start': '2026-11-18T00:00:00Z', 'end': '2026-11-18T00:00:00Z'},
])
def test_invalid_dates_rejected_consistently(client, params):
    assert client.get('/api/v1/gallery', params=params).status_code == 400
    assert client.get('/api/v1/admin/images', params=params).status_code == 400
    assert client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice'], **params}).status_code == 400
