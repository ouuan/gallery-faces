import json
from types import SimpleNamespace

import pytest
from gallery_dl.job import DownloadJob
from app import db, monitors
from app.downloader import install_library_filter
from test_monitors import create, get_task, run
from test_workflows import client


def test_download_deduplication(client):
    def submit(tags):
        return client.post('/api/v1/admin/import', json={'urls': ['https://x.com/alice'], 'hashtags': tags})

    first = submit(['#LIVE', '摄影']).json()[0]
    assert first['status'] == 'queued'
    assert submit(['＃摄影', 'live', '#Live']).json()[0] == {**first, 'status': 'duplicate'}
    assert submit(['摄影']).json()[0]['status'] == 'queued'
    assert submit(['#']).status_code == 400
    assert submit(['live or True']).status_code == 400
    unfiltered = submit([]).json()[0]
    with db.connect(True) as conn:
        conn.execute("UPDATE tasks SET payload=json_remove(payload,'$.hashtags') WHERE id=?", (unfiltered['task_id'],))
    assert submit([]).json()[0] == {**unfiltered, 'status': 'duplicate'}


def test_monitor_snapshot_and_backfill(client, monkeypatch):
    monitor = create(client, hashtags=['#LIVE'])
    path = f"/api/v1/admin/monitors/{monitor['id']}"
    assert client.patch(path, json={'hashtags': ['摄影']}).status_code == 200
    assert client.get('/api/v1/admin/monitors').json()[0]['hashtags'] == ['摄影']
    assert json.loads(get_task(monitor['task_id'])['payload'])['hashtags'] == ['live']
    run(monkeypatch)
    progress = monitors.listing()[0]['progress_at']
    backfill = monitors.batch(monitors.Batch(ids=[monitor['id']], action='backfill', start='2020-01-01T00:00:00Z'))[0]
    assert json.loads(get_task(backfill['task_id'])['payload'])['hashtags'] == ['摄影']
    assert client.patch(path, json={'hashtags': []}).status_code == 200
    assert monitors.listing()[0]['progress_at'] == progress
    assert monitors.listing()[0]['hashtags'] == []


@pytest.mark.parametrize('platform,tags_field,text_field', [('twitter', 'hashtags', 'content'), ('instagram', 'tags', 'description')])
def test_filter_before_media_request(client, monkeypatch, tmp_path, platform, tags_field, text_field):
    calls = []
    monkeypatch.setattr(DownloadJob, 'handle_url', lambda job, url, raw: calls.append(url))
    report = tmp_path / 'skipped.jsonl'
    install_library_filter(report, hashtags=['live', '摄影'])
    job = SimpleNamespace(extractor=SimpleNamespace(category=platform))
    for raw, url in [({tags_field: ['#LiVE']}, 'structured'), ({text_field: '今日 ＃摄影。'}, 'caption'),
                     ({text_field: '#LiveMusic https://example.org/#live'}, 'longer'), ({}, 'missing'),
                     ({tags_field: ['another'], text_field: '#live'}, 'not-an-entity')]:
        DownloadJob.handle_url(job, url, raw)
    assert calls == ['structured', 'caption']
    assert not report.exists()
