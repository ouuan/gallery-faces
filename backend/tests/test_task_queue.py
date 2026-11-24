import json
import sqlite3
from types import SimpleNamespace

from app import db, importer, monitors, task_queue, worker
from app.download_round import DownloadRound
from app.metadata import metadata
from test_monitors import create, get_task
from test_restart_recovery import RAW, source
from test_workflows import client, image


def test_backfill_recognizable_types_and_leave_legacy_monitor_unattributed():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY, kind, payload, image_id, rounds, status, queue_rank_at)')
        conn.executemany("INSERT INTO tasks(kind,payload) VALUES(?,?)", [
            ('monitor', '{"mode":"incremental"}'), ('monitor', '{"mode":"backfill"}'),
            ('download', '{"url":"https://instagram.com/p/xyz"}'), ('detect', '{"mode":"highres"}'),
            ('download', '{"url":"https://instagram.com/status/photos"}')])
        task_queue.migrate(conn, set())
        task_queue.migrate(conn, {'tier'})
        assert conn.execute('SELECT subtype,tier FROM tasks ORDER BY id').fetchall() == [
            ('monitor', 'bulk'), ('monitor_backfill', 'bulk'), ('post', 'single'), ('highres', 'single'), ('account', 'bulk')]


def test_upgrade_active_manual_updates(client):
    with db.connect(True) as conn:
        conn.execute('DROP TRIGGER task_infer_tier')
        conn.execute("""CREATE TRIGGER task_default_tier AFTER INSERT ON tasks WHEN NEW.tier IS NULL BEGIN
            UPDATE tasks SET tier='bulk' WHERE id=NEW.id; END""")
        payload = json.dumps({'mode': 'incremental', 'trigger': 'monitor_now'})
        conn.executemany("INSERT INTO tasks(kind,payload,status) VALUES('monitor',?,?)",
                         [(payload, status) for status in ('queued', 'running', 'done')])
    db.init()
    with db.connect(True) as conn:
        conn.execute("INSERT INTO tasks(kind,payload) VALUES('monitor',?)", (payload,))
        assert [row['tier'] for row in conn.execute("SELECT tier FROM tasks WHERE subtype='monitor_now' ORDER BY id")] == [
            'scheduled', 'scheduled', 'bulk', 'scheduled']


def test_manual_incremental_update_precedes_backfill(client):
    manual = create(client)
    history = create(client, username='bob')
    for monitor in (manual, history):
        monitors.edit(monitor['id'], monitors.Edit(paused=True))
    backfill = monitors.batch(monitors.Batch(ids=[history['id']], action='backfill', start='2020-01-01T00:00:00Z'))[0]
    update = monitors.batch(monitors.Batch(ids=[manual['id']], action='update'))[0]
    for expected, subtype, tier in [(update, 'monitor_now', 'scheduled'), (backfill, 'monitor_backfill', 'bulk')]:
        task = worker.claim(('monitor',))
        assert (task['id'], task['subtype'], task['tier']) == (expected['task_id'], subtype, tier)


def test_io_origin_rotation_and_derived_work(client, tmp_path, monkeypatch):
    api = '/api/v1/admin'
    def submit(*urls):
        return [row['task_id'] for row in client.post(api + '/import', json={'urls': urls}).json()]

    batch = submit('https://x.com/alice/status/1', 'https://x.com/alice/media', 'https://x.com/i/lists/123')
    assert [(get_task(key)['subtype'], get_task(key)['tier']) for key in batch] == [
        ('post', 'bulk'), ('account', 'bulk'), ('list', 'bulk')]
    monitor = create(client)
    initial = get_task(monitor['task_id'])
    assert (initial['subtype'], initial['tier']) == ('monitor_initial', 'scheduled')
    monitors.schedule_due()
    assert get_task(initial['id']) == initial
    with db.connect(True) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (initial['id'],))
    monitors.schedule_due()
    scheduled = get_task(monitors.listing()[0]['active_task_id'])
    assert monitors.batch(monitors.Batch(action='update', ids=[monitor['id']]))[0]['task_id'] == scheduled['id']
    assert get_task(scheduled['id']) == scheduled
    items = client.post(api + '/import', json={'urls': ['https://instagram.com/p/one', '', 'https://instagram.com/p/one/']}).json()
    assert [row['status'] for row in items] == ['queued', 'duplicate']
    single = items[0]['task_id']
    assert get_task(single)['tier'] == 'single'
    kinds = ('download', 'monitor')
    assert worker.claim(kinds)['id'] == single
    task = worker.claim(kinds)
    assert (task['id'], task['subtype'], task['tier']) == (scheduled['id'], 'monitor_scheduled', 'scheduled')
    worker.recover_tasks()
    assert worker.claim(kinds)['id'] == single
    task = worker.claim(kinds)
    download = DownloadRound(task['id'], task['rounds'])
    path = source(tmp_path)
    download.stage(path, metadata(RAW, path.name), tmp_path)
    download.import_ready()
    with db.connect(True) as conn:
        bulk = db.schedule_detection(conn, image(conn))
        highres = db.schedule_detection(conn, image(conn), 'highres')
        conn.execute("UPDATE tasks SET status='failed' WHERE id=?", (task['id'],))
    retry = client.post(f"{api}/tasks/{task['id']}/retry").json()['task_id']
    assert (get_task(retry)['tier'], get_task(retry)['payload']) == ('scheduled', task['payload'])
    assert worker.claim(('detect', 'rematch'))['id'] == highres
    detect = worker.claim(('detect', 'rematch'))
    assert (detect['subtype'], detect['tier']) == ('auto', 'scheduled')
    monkeypatch.setattr(worker, 'Vision', lambda: SimpleNamespace(detect=lambda *args, **kw: [([1, 1, 5, 5], b'x')]))
    worker.execute(detect)
    match = worker.claim(('detect', 'rematch'))
    assert (match['subtype'], match['tier'], match['image_id']) == ('unknown', 'scheduled', detect['image_id'])
    assert worker.claim(('detect', 'rematch'))['id'] == bulk


def test_only_blocking_library_match_is_expedited(client):
    with db.connect(True) as conn:
        other, target = image(conn), image(conn)
        db.schedule_rematch(conn)
        scheduled = db.schedule_detection(conn, image(conn), tier='scheduled')
        manual = db.schedule_detection(conn, target, 'highres')
    kinds = ('detect', 'rematch')
    prerequisite = worker.claim(kinds)
    assert (prerequisite['image_id'], prerequisite['kind'], prerequisite['tier']) == (target, 'rematch', 'maintenance')
    assert worker.claim(kinds)['id'] == scheduled
    with db.connect(True) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (prerequisite['id'],))
    assert worker.claim(kinds)['id'] == manual
    assert worker.claim(kinds)['image_id'] == other


def test_directory_counts_visible_on_commit_and_replay(client, tmp_path, monkeypatch):
    directory = tmp_path / 'fixtures'
    directory.mkdir()
    monkeypatch.setattr(importer, 'IMPORT', directory)
    photo = source(directory)
    photo.with_suffix('.json').write_text(json.dumps(RAW))
    (directory / 'bad.png').touch()
    task_id = client.post('/api/v1/admin/import', json={'directory': '.'}).json()[0]['task_id']
    query = '/api/v1/admin/tasks?has_imported=true'
    finish = importer.finish_deduplication
    observed = []
    def after_commit(image_id):
        observed.extend(row['id'] for row in client.get(query + '&status=running').json()['items'])
        finish(image_id)
    monkeypatch.setattr(importer, 'finish_deduplication', after_commit)
    task = worker.claim(('import',))
    importer.import_file(photo, RAW, task_id=task_id)
    worker.recover_tasks()
    worker.execute(worker.claim(('import',)))
    failed = client.get(query + '&status=failed').json()
    assert failed['total'] == 1 and failed['items'][0]['id'] == task['id']
    assert client.post(f'/api/v1/admin/tasks/{task_id}/retry').status_code == 200
    (directory / 'bad.png').unlink()
    worker.execute(worker.claim(('import',)))
    assert observed == [task_id] * 3
    assert json.loads(get_task(task_id)['result']) == {'imported': 1, 'skipped_existing': 0, 'skipped_trashed': 0}
    client.post('/api/v1/admin/import', json={'directory': '.'})
    worker.execute(worker.claim(('import',)))
    assert client.get(query).json()['total'] == 1


def test_filter_unions_intersections_count_and_page(client):
    with db.connect(True) as conn:
        for kind, payload, status, tier, count in [
            ('monitor', {}, 'failed', 'bulk', 2), ('download', {'url': 'https://x.com/a/status/2'}, 'failed', 'bulk', 1),
            ('download', {'url': 'https://x.com/a'}, 'failed', 'bulk', 3), ('import', {}, 'done', 'bulk', 1),
            ('download', {'url': 'https://x.com/a/status/3'}, 'failed', 'single', 1), ('monitor', {}, 'failed', 'bulk', 0)]:
            conn.execute('INSERT INTO tasks(kind,payload,status,tier,result) VALUES(?,?,?,?,?)',
                         (kind, json.dumps(payload), status, tier, json.dumps({'imported': count, 'skipped_trashed': 1})))
    query = '/api/v1/admin/tasks?kind=monitor&subtype=post&tier=bulk&status=failed&has_imported=true&page_size=1'
    for page, kind in [(1, 'download'), (2, 'monitor'), (3, 'monitor')]:
        data = client.get(query + f'&page={page}').json()
        assert (data['page'], data['total'], [row['kind'] for row in data['items']]) == (min(page, 2), 2, [kind])
