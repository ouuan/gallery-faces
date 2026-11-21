import json
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app import db, main, worker, importer


@pytest.fixture
def client(tmp_path, monkeypatch):
    for module in (db, main, worker, importer):
        monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with TestClient(main.app) as client:
        client.post("/api/v1/login", json={"password": "test-password"})
        client.headers["X-Gallery-Request"] = "1"
        yield client


def image(dbh, faces=True, date="2026-01-01T00:00:00Z", author="alice", group=None):
    group = (
        group or dbh.execute("INSERT INTO duplicate_groups DEFAULT VALUES").lastrowid
    )
    i = dbh.execute(
        "INSERT INTO images(sha256,filename,width,height,group_id,detection) VALUES(?,?,?,?,?,?)",
        (
            str(dbh.execute("SELECT count(*) FROM images").fetchone()[0]),
            "fixture.jpg",
            100,
            100,
            group,
            "done",
        ),
    ).lastrowid
    p = dbh.execute(
        "INSERT INTO posts(platform,post_key,author,published_at,url,post_text) VALUES(?,?,?,?,?,?)",
        (
            "x",
            str(i),
            author,
            date,
            f"https://x.com/{author}/status/{i}",
            "hello\nworld 🐈",
        ),
    ).lastrowid
    dbh.execute(
        "INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,?)", (i, p, "1")
    )
    if faces:
        dbh.execute(
            "INSERT INTO faces(image_id,box,embedding,model_version) VALUES(?,?,?,?)",
            (
                i,
                "[0,0,20,20]",
                np.array([1, 0] + [0] * 510, dtype="float32").tobytes(),
                worker.MODEL_VERSION,
            ),
        )
    return i


def recycle(client, ids):
    preview = client.post('/api/v1/admin/images/recycle-preview', json={'ids': ids})
    if preview.status_code != 200:
        return preview
    return client.post('/api/v1/admin/images/actions', json={'action': 'delete', 'ids': ids, 'scope_token': preview.json()['scope_token']})


def test_detection_tracks_image_speed_even_without_faces(client, monkeypatch):
    (db.DATA / 'images' / 'fixture.jpg').touch()
    clock = SimpleNamespace(monotonic=lambda: 10.0)
    monkeypatch.setattr(worker, "time", clock)
    with db.connect(True) as conn:
        target = image(conn, faces=False)
        task_id = conn.execute(
            "INSERT INTO tasks(kind,image_id) VALUES('detect',?)", (target,)
        ).lastrowid

    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0.35' WHERE key='detection_threshold'")

    def detect(_, **kwargs):
        assert kwargs["threshold"] == 0.35
        with db.connect() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            assert (task["done"], task["total"], task["speed"]) == (0, 1, 0)
        clock.monotonic = lambda: 12.0
        return []

    monkeypatch.setattr(worker, "Vision", lambda: SimpleNamespace(detect=detect))
    worker.step()
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert task["status"] == "done"
        assert (task["done"], task["total"], task["speed"]) == (1, 1, 0.5)
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='rematch'").fetchone()[0] == 0


def test_recycle_unrelated_image_does_not_schedule_rematch(client):
    with db.connect(True) as conn:
        image(conn)
        other = image(conn, faces=False)
    assert recycle(client, [other]).status_code == 200
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='rematch'").fetchone()[0] == 0


@pytest.mark.parametrize("face_count", [0, 2])
def test_rematch_tracks_face_progress_and_speed(client, monkeypatch, face_count):
    clock = SimpleNamespace(monotonic=lambda: 10.0)
    monkeypatch.setattr(worker, "time", clock)
    with db.connect(True) as conn:
        target = image(conn, faces=False)
        for _ in range(face_count):
            conn.execute(
                "INSERT INTO faces(image_id,box,embedding,model_version) VALUES(?, '[0,0,20,20]', ?, ?)",
                (target, np.array([1, 0] + [0] * 510, dtype="float32").tobytes(), worker.MODEL_VERSION),
            )
        task_id = conn.execute(
            "INSERT INTO tasks(kind,image_id) VALUES('rematch',?)", (target,)
        ).lastrowid
    calls = 0

    def candidates(*_):
        nonlocal calls
        with db.connect() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            assert task["done"] == calls
            assert task["total"] == face_count
            assert task["speed"] == (0.5 if calls else 0)
        calls += 1
        clock.monotonic = lambda: 10.0 + calls * 2
        return []

    monkeypatch.setattr(worker, "candidates", candidates)
    worker.step()
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert task["status"] == "done"
        assert task["done"] == task["total"] == face_count
        assert task["speed"] == (0.5 if face_count else 0)


@pytest.mark.parametrize("scores,expected_match", [
    ((0.0, 1.0), True),
    ((-1.0, 0.3), False),
    ((0.75, 0.8), False),
    (None, False),
])
def test_redetect_refreshes_candidates_and_reconsiders_unlocked_labels(
    client, monkeypatch, scores, expected_match
):
    (db.DATA / 'images' / 'fixture.jpg').touch()
    embedding = np.array([1, 0] + [0] * 510, dtype="float32").tobytes()
    with db.connect(True) as conn:
        target = image(conn, faces=False)
        a = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        b = conn.execute("INSERT INTO people(name) VALUES('B')").lastrowid
        if scores:
            for person, score in zip((a, b), scores):
                feature = np.array([score, np.sqrt(1 - score ** 2)] + [0] * 510, dtype="float32").tobytes()
                conn.execute("INSERT INTO reference_images(person_id,embedding,model_version) VALUES(?,?,?)",
                             (person, feature, worker.MODEL_VERSION))
        old_candidates = json.dumps([{"person_id": a, "score": 0.123}])
        states = [(a, 0, 0, embedding), (a, 1, 0, embedding),
                  (None, 1, 0, embedding), (None, 1, 1, embedding),
                  (a, 1, 0, None), (None, 0, 0, None)]
        ids = []
        for index, (person, locked, ignored, feature) in enumerate(states):
            ids.append(conn.execute(
                "INSERT INTO faces(image_id,box,embedding,model_version,person_id,locked,ignored,candidates) VALUES(?,?,?,?,?,?,?,?)",
                (target, json.dumps([index * 12, 0, 10, 10]), feature, worker.MODEL_VERSION,
                 person, locked, ignored, old_candidates if feature else '[]'),
            ).lastrowid)
    assert client.post('/api/v1/admin/images/actions', json={'action': 'redetect', 'ids': [target]}).status_code == 200
    # A reference change can queue a rematch behind detection. Its queue position
    # and unrelated payload must survive promotion to a complete refresh.
    with db.connect(True) as conn:
        queued = conn.execute("INSERT INTO tasks(kind,image_id,payload) VALUES('rematch',?,?)",
                              (target, '{"existing":true}')).lastrowid
    monkeypatch.setattr(worker, "Vision", lambda: SimpleNamespace(
        detect=lambda *args, **kwargs: [([0, 0, 10, 10], embedding),
                                       ([60, 0, 10, 10], embedding),
                                       ([80, 0, 10, 10], embedding)]))
    assert worker.step()
    with db.connect() as conn:
        queued_task = conn.execute("SELECT * FROM tasks WHERE kind='rematch'").fetchone()
        assert queued_task['id'] == queued
        assert json.loads(queued_task['payload']) == {'existing': True, 'refresh_all': True}
    assert worker.step()
    faces = client.get(f'/api/v1/admin/images?state=all&image_id={target}').json()[0]['faces']
    by_id = {face['id']: face for face in faces}
    assert len(faces) == 7
    for index, face_id in enumerate(ids[:3]):
        face = by_id[face_id]
        assert face['person_id'] == ((b if expected_match else None) if index == 0 else states[index][0])
        assert face['locked'] == states[index][1]
        assert face['revision'] == 1
        assert [c['person_id'] for c in face['candidates']] == ([b, a] if scores else [])
        if scores:
            assert [c['score'] for c in face['candidates']] == pytest.approx(list(reversed(scores)))
    for index in (3, 4, 5):
        face = by_id[ids[index]]
        assert (face['person_id'], face['locked'], face['ignored'], face['revision']) == (*states[index][:3], 0)
        assert face['candidates'] == (json.loads(old_candidates) if index == 3 else [])
        assert face['has_embedding'] == (index == 3)
    new_face = next(face for face in faces if face['id'] not in ids)
    assert new_face['person_id'] == (b if expected_match else None)
    assert new_face['candidates'] == by_id[ids[0]]['candidates']
    with db.connect() as conn:
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (queued,)).fetchone()
        assert (task['status'], task['done'], task['total']) == ('done', 4, 4)


@pytest.mark.parametrize('locked', [0, 1])
@pytest.mark.parametrize('change', ['reference', 'delete'])
def test_full_refresh_reference_races_without_unknown_faces(client, monkeypatch, locked, change):
    with db.connect(True) as conn:
        target = image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        conn.execute('UPDATE faces SET person_id=?,locked=?', (person, locked))
        conn.execute('INSERT INTO reference_images(person_id,embedding,model_version) SELECT ?,embedding,model_version FROM faces', (person,))
        conn.execute("INSERT INTO tasks(kind,image_id,payload) VALUES('rematch',?,?)", (target, '{"refresh_all":true}'))
    original = worker.candidates
    calls = []

    def change_references(embedding, refs):
        result = original(embedding, refs)
        calls.append(1)
        if len(calls) == 1:
            if change == 'delete':
                assert client.delete(f'/api/v1/admin/people/{person}').status_code == 200
            else:
                with db.connect(True) as conn:
                    conn.execute('DELETE FROM reference_images')
                    db.schedule_rematch(conn)
        return result

    monkeypatch.setattr(worker, 'candidates', change_references)
    worker.step()
    assert len(calls) == 2
    with db.connect() as conn:
        face = conn.execute('SELECT * FROM faces').fetchone()
        assert json.loads(face['candidates']) == []
        assert face['person_id'] == (person if locked and change == 'reference' else None)
        tasks = conn.execute('SELECT * FROM tasks').fetchall()
        assert len(tasks) == 1
        assert (tasks[0]['status'], tasks[0]['processed_version']) == ('done', 1)


@pytest.mark.parametrize('action', ['confirm', 'ignore', 'cancel'])
def test_full_refresh_protects_concurrent_decisions_and_cancellation(client, monkeypatch, action):
    with db.connect(True) as conn:
        target = image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        conn.execute('UPDATE faces SET person_id=?', (person,))
        face_id = conn.execute('SELECT id FROM faces').fetchone()[0]
        task_id = conn.execute("INSERT INTO tasks(kind,image_id,payload) VALUES('rematch',?,?)", (target, '{"refresh_all":true}')).lastrowid

    def concurrent_change(*args):
        if action == 'cancel':
            assert client.post(f'/api/v1/admin/tasks/{task_id}/cancel').status_code == 200
        else:
            assert client.put(f'/api/v1/admin/faces/{face_id}', json={
                'revision': 0, 'person_id': person, 'ignored': action == 'ignore',
            }).status_code == 200
        return [{'person_id': person, 'score': 1}]

    monkeypatch.setattr(worker, 'candidates', concurrent_change)
    worker.step()
    with db.connect() as conn:
        face = conn.execute('SELECT * FROM faces').fetchone()
        assert json.loads(face['candidates']) == []
        assert face['revision'] == (0 if action == 'cancel' else 1)
        assert face['person_id'] == (None if action == 'ignore' else person)
        assert face['locked'] == (action != 'cancel')
        assert face['ignored'] == (action == 'ignore')
        assert conn.execute('SELECT status FROM tasks').fetchone()[0] == ('cancelled' if action == 'cancel' else 'done')


@pytest.mark.parametrize('status', ['failed', 'running'])
def test_full_refresh_survives_retry_and_recovery(client, status):
    with db.connect(True) as conn:
        target = image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        conn.execute('UPDATE faces SET person_id=?', (person,))
        task_id = conn.execute("INSERT INTO tasks(kind,image_id,payload,status) VALUES('rematch',?,?,?)",
                               (target, '{"refresh_all":true}', status)).lastrowid
    if status == 'failed':
        assert client.post(f'/api/v1/admin/tasks/{task_id}/retry').status_code == 200
    else:
        worker.recover_tasks()
    worker.step()
    with db.connect() as conn:
        assert conn.execute('SELECT person_id FROM faces').fetchone()[0] is None
        assert conn.execute('SELECT status FROM tasks').fetchone()[0] == 'done'


@pytest.mark.parametrize('assigned,locked,old_score,new_score,changed', [
    (False, 0, None, None, False),
    (False, 0, 0.2, 0.2, False),
    (False, 0, 0.2, 0.3, True),
    (True, 0, 1.0, 1.0, False),
    (False, 0, 1.0, 1.0, True),
    (True, 0, None, None, True),
    (False, 1, 1.0, 1.0, False),
    (True, 1, 0.2, 0.2, False),
    (True, 1, 0.2, 0.3, True),
])
def test_rematch_revision_only_changes_with_saved_values(
    client, monkeypatch, assigned, locked, old_score, new_score, changed
):
    with db.connect(True) as conn:
        target = image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        old_candidates = [] if old_score is None else [{'person_id': person, 'score': old_score}]
        result = [] if new_score is None else [{'person_id': person, 'score': new_score}]
        # JSON whitespace is not a change to the candidates themselves.
        conn.execute('UPDATE faces SET person_id=?,locked=?,candidates=?',
                     (person if assigned else None, locked, json.dumps(old_candidates, indent=2)))
        face_id = conn.execute('SELECT id FROM faces').fetchone()[0]
        conn.execute("INSERT INTO tasks(kind,image_id,payload) VALUES('rematch',?,?)",
                     (target, '{"refresh_all":true}'))
    monkeypatch.setattr(worker, 'candidates', lambda *_: result)
    assert worker.step()
    with db.connect() as conn:
        face = conn.execute('SELECT * FROM faces').fetchone()
        assert face['revision'] == int(changed)
        assert json.loads(face['candidates']) == result
        expected_person = (person if assigned else None) if locked else (person if new_score == 1.0 else None)
        assert face['person_id'] == expected_person
        task = conn.execute('SELECT * FROM tasks').fetchone()
        assert (task['status'], task['done'], task['total']) == ('done', 1, 1)
    # A page loaded before matching can still save if its data has not changed.
    response = client.put(f'/api/v1/admin/faces/{face_id}', json={'revision': 0, 'person_id': person})
    assert response.status_code == (409 if changed else 200)


def test_reference_changes_only_rematch_unknown_faces(client):
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        for assigned, locked in [(person, 0), (person, 1), (None, 1), (None, 0)]:
            target = image(conn)
            conn.execute('UPDATE faces SET person_id=?,locked=? WHERE image_id=?', (assigned, locked, target))
        conn.execute('INSERT INTO reference_images(person_id,embedding,model_version) SELECT ?,embedding,model_version FROM faces LIMIT 1', (person,))
        db.schedule_rematch(conn)
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1
    worker.step()
    with db.connect() as conn:
        faces = conn.execute('SELECT * FROM faces ORDER BY id').fetchall()
        assert [face['revision'] for face in faces] == [0, 0, 0, 1]
        assert faces[-1]['person_id'] == person


def test_task_pagination(client):
    empty = client.get("/api/v1/admin/tasks").json()
    assert empty == {"items": [], "total": 0, "page": 1, "page_size": 20}
    with db.connect(True) as conn:
        conn.executemany("INSERT INTO tasks(kind) VALUES(?)", [("import",)] * 305)
    first = client.get("/api/v1/admin/tasks").json()
    assert first["total"] == 305
    assert [task["id"] for task in first["items"]] == list(range(305, 285, -1))
    second = client.get("/api/v1/admin/tasks?page=2").json()
    assert [task["id"] for task in second["items"]] == list(range(285, 265, -1))
    last = client.get("/api/v1/admin/tasks?page=999").json()
    assert last["page"] == 16
    assert [task["id"] for task in last["items"]] == [5, 4, 3, 2, 1]
    custom = client.get("/api/v1/admin/tasks?page=4&page_size=100").json()
    assert custom["page_size"] == 100
    assert [task["id"] for task in custom["items"]] == [5, 4, 3, 2, 1]


@pytest.mark.parametrize("query", ["page=0", "page=-1", "page_size=0", "page_size=101"])
def test_task_pagination_rejects_invalid_parameters(client, query):
    assert client.get(f"/api/v1/admin/tasks?{query}").status_code == 422


@pytest.mark.parametrize("query,kinds,statuses", [
    ("kind=download", {"download"}, None),
    ("status=failed", None, {"failed"}),
    ("kind=import&kind=detect", {"import", "detect"}, None),
    ("status=queued&status=running", None, {"queued", "running"}),
    ("kind=download&kind=import&status=failed&status=cancelled",
     {"download", "import"}, {"failed", "cancelled"}),
])
def test_task_filters(client, query, kinds, statuses):
    with db.connect(True) as conn:
        conn.executemany("INSERT INTO tasks(kind,status) VALUES(?,?)", [
            (kind, status)
            for kind in ("download", "import", "detect", "rematch")
            for status in ("queued", "running", "done", "failed", "cancelled")
            for _ in range(7)
        ])
        expected_ids = [row["id"] for row in conn.execute("SELECT id,kind,status FROM tasks ORDER BY id DESC")
                        if (kinds is None or row["kind"] in kinds)
                        and (statuses is None or row["status"] in statuses)]
    for requested_page in (1, 2, 999):
        data = client.get(f"/api/v1/admin/tasks?{query}&page={requested_page}").json()
        page = min(requested_page, (len(expected_ids) + 19) // 20)
        assert data["total"] == len(expected_ids)
        assert data["page"] == page
        assert [task["id"] for task in data["items"]] == expected_ids[(page - 1) * 20:page * 20]


def test_task_filters_empty(client):
    with db.connect(True) as conn:
        conn.execute("INSERT INTO tasks(kind,status) VALUES('import','failed')")
    data = client.get("/api/v1/admin/tasks?kind=detect&status=failed&page=999").json()
    assert data == {"items": [], "total": 0, "page": 1, "page_size": 20}


@pytest.mark.parametrize("query", ["kind=unknown", "status=unknown", "kind=import&kind=bad", "status=failed&status=bad"])
def test_task_filters_reject_invalid_values(client, query):
    assert client.get(f"/api/v1/admin/tasks?{query}").status_code == 422


def test_retry_resets_task_statistics(client):
    with db.connect(True) as conn:
        task_id = conn.execute(
            "INSERT INTO tasks(kind,status,done,total,speed) VALUES('import','failed',2,3,0.5)"
        ).lastrowid
    assert client.post(f"/api/v1/admin/tasks/{task_id}/retry").status_code == 200
    with db.connect() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        assert task["status"] == "queued"
        assert task["done"] == task["total"] == task["speed"] == 0


def test_admin_image_link_beyond_list_limit(client):
    with db.connect(True) as conn:
        ids = [image(conn, faces=False) for _ in range(501)]
    target = ids[-1]
    assert target not in {
        row["id"] for row in client.get("/api/v1/admin/images?state=all").json()
    }
    response = client.get(f"/api/v1/admin/images?state=all&image_id={target}")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [target]
    assert response.json()[0]["sources"]
    assert client.get("/api/v1/admin/images?state=all&image_id=99999").json() == []
    client.cookies.clear()
    assert client.get(f"/api/v1/admin/images?state=all&image_id={target}").status_code == 401


def test_manual_face_without_person_remains_unknown(client):
    with db.connect(True) as conn:
        target = image(conn, faces=False)
    response = client.post(
        f"/api/v1/admin/images/{target}/faces",
        json={"box": [0, 0, 20, 20], "person_id": None},
    )
    assert response.status_code == 200
    unknown = client.get(f"/api/v1/admin/images?state=unknown&image_id={target}").json()
    assert len(unknown) == 1
    assert unknown[0]["faces"][0]["locked"] == 0


def test_groups_transaction_and_concurrency(client):
    p = client.post(
        "/api/v1/admin/people", json={"name": "Alice", "new_groups": [" Team ", "Team"]}
    ).json()["id"]
    group = client.get("/api/v1/groups").json()[0]
    assert group["name"] == "Team"
    assert (
        client.put(
            f"/api/v1/admin/people/{p}",
            json={"name": "Alice", "new_groups": ["Rollback"], "group_ids": [999]},
        ).status_code
        == 400
    )
    assert len(client.get("/api/v1/groups").json()) == 1
    client.put(f"/api/v1/admin/people/{p}", json={"name": "Alice"})
    assert client.get("/api/v1/groups").json()[0]["members"] == 0

    def create(n):
        return main.save_person(
            main.PersonInput(name=f"Person {n}", new_groups=["Concurrent"])
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(create, range(8)))
    assert [g["name"] for g in client.get("/api/v1/groups").json()].count(
        "Concurrent"
    ) == 1


def test_no_faces_visibility_and_access(client):
    with db.connect(True) as conn:
        known = image(conn)
        empty = image(conn, False)
        failed = image(conn, False)
        conn.execute("UPDATE images SET detection='failed' WHERE id=?", (failed,))
    assert len(client.get("/api/v1/gallery").json()["items"]) == 1
    assert len(client.get("/api/v1/gallery?include_no_faces=true").json()["items"]) == 2
    assert (
        recycle(client, [known]).status_code
        == 200
    )
    assert client.get(f"/api/v1/gallery/{known}").status_code == 404
    assert client.get(f"/api/v1/media/{known}").status_code == 404
    client.cookies.clear()
    assert client.get("/api/v1/admin/tasks").status_code == 401
    assert client.get("/api/v1/admin/reference-media/a.jpg").status_code == 401


def test_source_filters_and_all_same_image(client):
    with db.connect(True) as conn:
        first = image(conn, date="2025-12-31T16:00:00Z")
        second = image(conn, date="2026-01-03T00:00:00Z", author="bob", group=first)
        a = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        b = conn.execute("INSERT INTO people(name) VALUES('B')").lastrowid
        conn.execute("UPDATE faces SET person_id=? WHERE image_id=?", (a, first))
        conn.execute("UPDATE faces SET person_id=? WHERE image_id=?", (b, second))
    assert not client.get("/api/v1/gallery?publishers=x:alice&start=2026-01-02T16:00:00Z").json()[
        "items"
    ]
    assert (
        len(
            client.get("/api/v1/gallery?start=2025-12-31T16:00:00Z&end=2026-01-01T16:00:00Z").json()[
                "items"
            ]
        )
        == 1
    )
    assert not client.get(f"/api/v1/gallery?people={a},{b}&match=all").json()["items"]
    assert client.get(f"/api/v1/gallery?people={a},{b}&match=all").json()["total"] == 0
    result = client.get("/api/v1/gallery?publishers=x:bob").json()["items"][0]
    detail = client.get(
        f"/api/v1/gallery/{first}?matched_post={result['matched_source']['post_id']}"
    ).json()
    assert (
        detail["matched_source"]["author"] == "bob"
        and detail["earliest_source"]["author"] == "alice"
    )
    assert "post_text" not in result["matched_source"]
    assert detail["sources"][0]["post_text"] == "hello\nworld 🐈"


def test_people_match_modes_across_gallery_posts_and_review(client):
    with db.connect(True) as conn:
        conn.execute("INSERT INTO people(id,name) VALUES(1,'A'),(2,'B'),(3,'C')")
        def photo(people):
            image_id = image(conn, faces=False)
            conn.executemany("INSERT INTO faces(image_id,box,person_id) VALUES(?,'[0,0,20,20]',?)",
                             [(image_id, person) for person in people])
            return image_id

        pair = photo([1, 2])
        with_unknown = photo([1, 2, 2, None])
        conn.execute("INSERT INTO faces(image_id,box,person_id,ignored) VALUES(?,'[0,0,20,20]',3,1)", (with_unknown,))
        extra = photo([1, 2, 3])
        partial_extra = photo([1, 3])
        partial = photo([1, None])
        photo([None])
        photo([3])

    for mode, expected in [
        ("any", {pair, with_unknown, extra, partial_extra, partial}),
        ("all", {pair, with_unknown, extra}),
        ("subset", {pair, with_unknown, partial}),
        ("exact", {pair, with_unknown}),
    ]:
        params = {"people": "1,2", "match": mode}
        gallery = client.get("/api/v1/gallery", params=params).json()
        assert gallery["total"] == len(expected)
        assert {item["image_id"] for item in gallery["items"]} == expected
        posts = client.get("/api/v1/posts", params=params).json()
        assert {item["embed_id"] for item in posts["items"]} == {str(identifier) for identifier in expected}
        review = client.get("/api/v1/admin/images", params={**params, "state": "all"}).json()
        assert {item["id"] for item in review} == expected


def test_queue_dedup_preserves_position_and_manual_decisions(client, monkeypatch):
    with db.connect(True) as conn:
        i = image(conn)
        image(conn, False)
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        conn.execute(
            "INSERT INTO reference_images(person_id,embedding,model_version) VALUES(?,?,?)",
            (person, np.array([1, 0] + [0] * 510, dtype="float32").tobytes(), worker.MODEL_VERSION),
        )

    def schedule(_):
        with db.connect(True) as conn:
            db.schedule_rematch(conn)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(schedule, range(12)))
    with db.connect() as conn:
        tasks = conn.execute("SELECT * FROM tasks").fetchall()
        assert len(tasks) == 1 and tasks[0]["target_version"] == 12
        task = dict(tasks[0])
        face = conn.execute("SELECT * FROM faces").fetchone()
    original = worker.candidates

    def concurrent_edit(embedding, refs):
        with db.connect(True) as conn:
            conn.execute(
                "UPDATE faces SET locked=1,revision=revision+1 WHERE id=?",
                (face["id"],),
            )
            db.schedule_rematch(conn)
        return original(embedding, refs)

    monkeypatch.setattr(worker, "candidates", concurrent_edit)
    worker.step()
    with db.connect() as conn:
        result = conn.execute("SELECT * FROM faces").fetchone()
        assert result["person_id"] is None and result["locked"] == 1
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT status FROM tasks").fetchone()[0] == "done"


def test_running_ref_update_reuses_task(client, monkeypatch):
    with db.connect(True) as conn:
        i = image(conn)
        db.schedule_rematch(conn)
    calls = []

    def candidate(embedding, refs):
        calls.append(1)
        if len(calls) == 1:
            with db.connect(True) as conn:
                db.schedule_rematch(conn)
        return []

    monkeypatch.setattr(worker, "candidates", candidate)
    worker.step()
    assert len(calls) == 2
    with db.connect() as conn:
        tasks = conn.execute("SELECT * FROM tasks").fetchall()
        assert len(tasks) == 1 and tasks[0]["processed_version"] == 2


def test_review_undo_and_ignored_no_faces(client):
    with db.connect(True) as conn:
        i = image(conn)
    face = client.get("/api/v1/admin/images").json()[0]["faces"][0]
    assert (
        client.put(
            f"/api/v1/admin/faces/{face['id']}", json={"revision": 0, "ignored": True}
        ).status_code
        == 200
    )
    assert not client.get("/api/v1/gallery").json()["items"]
    assert (
        client.put(
            f"/api/v1/admin/faces/{face['id']}", json={"revision": 0, "ignored": False}
        ).status_code
        == 409
    )
    assert client.post(f"/api/v1/admin/faces/{face['id']}/undo").status_code == 200
    assert len(client.get("/api/v1/gallery").json()["items"]) == 1


def test_stable_pagination(client):
    with db.connect(True) as conn:
        for _ in range(5):
            group = image(conn)
        image(conn, group=group)
        image(conn, False)
    first = client.get("/api/v1/gallery?limit=2").json()
    second = client.get(
        "/api/v1/gallery", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert first["total"] == second["total"] == 5
    assert not set(p["id"] for p in first["items"]) & set(
        p["id"] for p in second["items"]
    )


def test_import_idempotence_and_text_backfill(client, tmp_path):
    from PIL import Image

    path = tmp_path / "test.jpg"
    Image.new("RGB", (30, 40), "red").save(path)
    raw = {
        "category": "twitter",
        "tweet_id": "123",
        "user": {"name": "alice"},
        "date": "2026-01-01T00:00:00Z",
        "num": 1,
    }
    first = importer.import_file(path, raw)
    raw["content"] = "backfilled 🐈"
    second = importer.import_file(path, raw)
    assert first == second
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 1
        assert (
            conn.execute("SELECT post_text FROM posts").fetchone()[0] == "backfilled 🐈"
        )


def test_actual_author_not_collection_account(client):
    raw = {
        "category": "twitter",
        "tweet_id": "123",
        "user": {"name": "collector"},
        "author": {"name": "actual"},
        "date": "2026-01-01T00:00:00Z",
    }
    meta = importer.metadata(raw, "one.jpg")
    assert meta["author"] == "actual" and meta["collected"] == "collector"
    assert meta["url"] == "https://x.com/actual/status/123"
    assert not importer.validate_url("https://x.com:bad/hello")


def test_duplicate_split_memory_and_hidden_member(client):
    with db.connect(True) as conn:
        a = image(conn)
        b = image(conn, group=a)
    assert (
        client.post(
            "/api/v1/admin/duplicates", json={"a": a, "b": b, "action": "separate"}
        ).status_code
        == 200
    )
    with db.connect() as conn:
        assert (
            conn.execute("SELECT count(DISTINCT group_id) FROM images").fetchone()[0]
            == 2
        )
        assert (
            conn.execute("SELECT decision FROM duplicate_decisions").fetchone()[0]
            == "separate"
        )
    client.post("/api/v1/admin/duplicates", json={"a": a, "b": b, "action": "merge"})
    # A partially restored group may have both visible and trashed members.
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET hidden=1 WHERE id=?", (b,))
    detail = client.get(f"/api/v1/gallery/{a}").json()
    assert len(detail["sources"]) == 1 and detail["source_count"] == 1


def test_original_bytes_retained(client, tmp_path):
    from PIL import Image

    path = tmp_path / "original.png"
    Image.new("RGB", (40, 30), "blue").save(path)
    raw = {
        "category": "twitter",
        "tweet_id": "99",
        "author": {"name": "actual"},
        "date": "2026-01-01T00:00:00Z",
    }
    i = importer.import_file(path, raw)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (i,))
    assert client.get(f"/api/v1/media/{i}?download=true").content == path.read_bytes()


def test_create_person_from_face_atomic_and_undo(client, monkeypatch):
    with db.connect(True) as conn:
        image(conn)
        image(conn)
    face = client.get('/api/v1/admin/images').json()[0]['faces'][0]
    endpoint = f"/api/v1/admin/faces/{face['id']}/person"
    assert face['has_embedding']
    assert client.post(endpoint, json={'name': '  ', 'revision': 0}).status_code == 400
    assert client.post(endpoint, json={'name': 'A', 'revision': 9}).status_code == 409
    original = main.schedule_rematch

    def fail_schedule(conn):
        raise RuntimeError('simulated failure')

    monkeypatch.setattr(main, 'schedule_rematch', fail_schedule)
    with pytest.raises(RuntimeError):
        client.post(endpoint, json={'name': 'Rollback', 'revision': 0})
    assert client.get('/api/v1/people').json() == []
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM review_history').fetchone()[0] == 0
        assert conn.execute('SELECT revision FROM faces WHERE id=?', (face['id'],)).fetchone()[0] == 0
    monkeypatch.setattr(main, 'schedule_rematch', original)
    result = client.post(endpoint, json={'name': '  新人物  ', 'revision': 0})
    assert result.status_code == 200
    person = result.json()['id']
    assert client.get('/api/v1/people').json()[0]['name'] == '新人物'
    with db.connect() as conn:
        saved = conn.execute('SELECT * FROM faces WHERE id=?', (face['id'],)).fetchone()
        assert (saved['person_id'], saved['locked'], saved['revision']) == (person, 1, 1)
        ref = conn.execute('SELECT * FROM reference_images').fetchone()
        assert ref['face_id'] == face['id'] and ref['embedding'] == saved['embedding']
        assert conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 1
    assert client.post(endpoint, json={'name': 'Duplicate submit', 'revision': 0}).status_code == 409
    assert len(client.get('/api/v1/people').json()) == 1
    assert client.post(f"/api/v1/admin/faces/{face['id']}/undo").status_code == 200
    with db.connect() as conn:
        assert conn.execute('SELECT person_id FROM faces WHERE id=?', (face['id'],)).fetchone()[0] is None


def test_create_person_from_face_without_embedding_and_auth(client):
    with db.connect(True) as conn:
        image(conn)
        conn.execute('UPDATE faces SET embedding=NULL')
    face = client.get('/api/v1/admin/images').json()[0]['faces'][0]
    assert not face['has_embedding']
    endpoint = f"/api/v1/admin/faces/{face['id']}/person"
    body = {'name': 'Manual', 'revision': 0}
    assert client.post(endpoint, json=body).status_code == 400
    assert client.get('/api/v1/people').json() == []
    body['add_reference'] = False
    result = client.post(endpoint, json=body)
    assert result.status_code == 200
    assert client.get('/api/v1/people').json()[0]['reference_count'] == 0
    person = result.json()['id']
    client.cookies.clear()
    assert client.post(endpoint, json=body).status_code == 401
    assert client.delete(f'/api/v1/admin/people/{person}').status_code == 401


def test_delete_person_cleans_labels_candidates_history_and_keeps_images(client):
    person = client.post('/api/v1/admin/people', json={
        'name': 'Delete', 'new_groups': ['Keep group'],
        'accounts': [{'platform': 'x', 'username': 'alice'}],
    }).json()['id']
    other = client.post('/api/v1/admin/people', json={'name': 'Keep'}).json()['id']
    with db.connect(True) as conn:
        image(conn)
        image(conn)
        faces = conn.execute('SELECT id FROM faces ORDER BY id').fetchall()
    a, b = [row[0] for row in faces]
    for face_id in (a, b):
        assert client.put(f'/api/v1/admin/faces/{face_id}', json={'revision': 0, 'person_id': person}).status_code == 200
    assert client.put(f'/api/v1/admin/faces/{b}', json={'revision': 1, 'person_id': other}).status_code == 200
    assert client.post(f'/api/v1/admin/people/{person}/references', json={'face_id': a}).status_code == 200
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET candidates=?', (json.dumps([{'person_id': person, 'score': 1}, {'person_id': other, 'score': .5}]),))
    assert client.delete(f'/api/v1/admin/people/{person}').status_code == 200
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM sources').fetchone()[0] == 2
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM accounts').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM person_groups').fetchone()[0] == 0
        first = conn.execute('SELECT * FROM faces WHERE id=?', (a,)).fetchone()
        assert (first['person_id'], first['locked'], first['ignored']) == (None, 0, 0)
        assert conn.execute('SELECT person_id FROM faces WHERE id=?', (b,)).fetchone()[0] == other
        for face in conn.execute('SELECT candidates FROM faces'):
            assert json.loads(face[0]) == [{'person_id': other, 'score': .5}]
        assert conn.execute("SELECT count(*) FROM review_history WHERE json_extract(before_json,'$.person_id')=?", (person,)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM tasks WHERE kind='rematch'").fetchone()[0] == 1
    assert client.post(f'/api/v1/admin/faces/{b}/undo').status_code == 409
    assert client.get('/api/v1/groups').json()[0]['name'] == 'Keep group'
    assert client.delete(f'/api/v1/admin/people/{person}').status_code == 404


def test_delete_person_during_rematch_discards_stale_identity(client, monkeypatch):
    with db.connect(True) as conn:
        image(conn)
        person = conn.execute("INSERT INTO people(name) VALUES('Delete')").lastrowid
        conn.execute('INSERT INTO reference_images(person_id,embedding,model_version) VALUES(?,?,?)',
                     (person, np.array([1, 0] + [0] * 510, dtype='float32').tobytes(), worker.MODEL_VERSION))
        db.schedule_rematch(conn)
    original = worker.candidates
    calls = []

    def during_match(embedding, refs):
        result = original(embedding, refs)
        if not calls:
            calls.append(1)
            assert client.delete(f'/api/v1/admin/people/{person}').status_code == 200
        return result

    monkeypatch.setattr(worker, 'candidates', during_match)
    worker.step()
    with db.connect() as conn:
        face = conn.execute('SELECT * FROM faces').fetchone()
        assert face['person_id'] is None and json.loads(face['candidates']) == []
        assert conn.execute('SELECT status FROM tasks').fetchone()[0] == 'done'


def test_person_from_face_groups_accounts_transaction(client):
    existing = client.post('/api/v1/admin/people', json={'name': 'Existing', 'new_groups': ['Existing group']}).json()['id']
    group = client.get('/api/v1/groups').json()[0]['id']
    with db.connect(True) as conn:
        image(conn)
    face = client.get('/api/v1/admin/images').json()[0]['faces'][0]
    endpoint = f"/api/v1/admin/faces/{face['id']}/person"
    body = {'name': 'New', 'name_ja': ' 新人 ', 'revision': 0, 'group_ids': [group, 999], 'new_groups': [{'name': 'New group', 'name_ja': ' 新組 '}], 'accounts': [{'platform': 'x', 'username': 'alice'}]}
    assert client.post(endpoint, json=body).status_code == 400
    assert len(client.get('/api/v1/people').json()) == 1
    assert len(client.get('/api/v1/groups').json()) == 1
    body['group_ids'] = [group]
    body['new_groups'] += [{'name': ' Existing group ', 'name_ja': '変更しない'}]
    result = client.post(endpoint, json=body)
    assert result.status_code == 200
    person = next(p for p in client.get('/api/v1/people').json() if p['id'] == result.json()['id'])
    assert person['name_ja'] == '新人'
    assert {g['name']: g['name_ja'] for g in person['groups']} == {'Existing group': None, 'New group': '新組'}
    assert person['accounts'][0]['username'] == 'alice'
    assert person['reference_count'] == 1


def test_multiple_confirmed_face_references_atomic_and_deduplicated(client):
    person = client.post('/api/v1/admin/people', json={'name': 'A'}).json()['id']
    other = client.post('/api/v1/admin/people', json={'name': 'Other'}).json()['id']
    with db.connect(True) as conn:
        for _ in range(6):
            image(conn)
        faces = [r[0] for r in conn.execute('SELECT id FROM faces ORDER BY id')]
        conn.execute('UPDATE faces SET person_id=?,locked=1', (person,))
        conn.execute('UPDATE faces SET person_id=? WHERE id=?', (other, faces[3]))
        conn.execute('UPDATE faces SET locked=0 WHERE id=?', (faces[4],))
        conn.execute('UPDATE faces SET embedding=NULL WHERE id=?', (faces[5],))
    listing = f'/api/v1/admin/people/{person}/confirmed-faces'
    edit = f'/api/v1/admin/people/{person}'
    offered = client.get(listing).json()
    assert {f['id'] for f in offered} == {faces[0], faces[1], faces[2], faces[5]}
    assert not next(f for f in offered if f['id'] == faces[5])['has_embedding']
    for invalid in (faces[3], faces[4], faces[5], 999):
        result = client.put(edit, json={'name': 'Should roll back', 'new_groups': ['Rollback refs'], 'reference_face_ids': [faces[0], invalid]})
        assert result.status_code == 409
        assert client.get('/api/v1/groups').json() == []
        with db.connect() as conn:
            assert conn.execute('SELECT name FROM people WHERE id=?', (person,)).fetchone()[0] == 'A'
            assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 0
    body = {'name': 'Renamed', 'reference_face_ids': [faces[0], faces[1], faces[0]]}
    assert client.put(edit, json=body).status_code == 200
    with db.connect() as conn:
        version = db.settings(conn)['reference_version']
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 2
    assert client.put(edit, json=body).status_code == 200
    with db.connect() as conn:
        assert db.settings(conn)['reference_version'] == version
    assert sum(f['is_reference'] for f in client.get(listing).json()) == 2
    # A face changed since the picker opened cannot become this person's reference.
    with db.connect(True) as conn:
        conn.execute('UPDATE faces SET person_id=? WHERE id=?', (other, faces[2]))
    assert client.put(edit, json={'name': 'Stale', 'reference_face_ids': [faces[2]]}).status_code == 409
    client.cookies.clear()
    assert client.get(listing).status_code == 401


def test_publisher_person_matches_all_platforms_and_same_source_date(client):
    person = client.post('/api/v1/admin/people', json={'name': 'Alice', 'accounts': [
        {'platform': 'x', 'username': 'Alice'},
        {'platform': 'instagram', 'username': 'alice_ig'},
    ]}).json()['id']
    with db.connect(True) as conn:
        x = image(conn, author='alice', date='2026-01-01T00:00:00Z')
        ig = image(conn, author='ALICE_IG', date='2026-01-02T00:00:00Z')
        conn.execute("UPDATE posts SET platform='instagram',author_name='Instagram 昵称' WHERE post_key=?", (str(ig),))
        unrelated = image(conn, author='alice_ig', date='2026-01-03T00:00:00Z')
        image(conn, author='other', date='2026-01-04T00:00:00Z', group=x)
    query = f'/api/v1/gallery?publishers=person:{person}'
    items = client.get(query).json()['items']
    assert {p['id'] for p in items} == {x, ig}
    assert next(p for p in items if p['id'] == ig)['matched_source']['author_name'] == 'Instagram 昵称'
    assert client.get(f'/api/v1/gallery/{ig}').json()['matched_source']['author_name'] == 'Instagram 昵称'
    assert not client.get(query + '&start=2026-01-03T16:00:00Z').json()['items']
    assert {p['id'] for p in client.get(query + ',x:alice_ig').json()['items']} == {x, ig, unrelated}
    for invalid in ('person:no', 'person:-1', 'person:99999999999999999999999', 'person:'):
        assert client.get('/api/v1/gallery', params={'publishers': invalid}).status_code == 400
    client.put(f'/api/v1/admin/people/{person}', json={'name': 'Alice', 'accounts': []})
    assert not client.get(query).json()['items']


def test_nickname_metadata_backfill_and_actual_publisher(client, tmp_path):
    from PIL import Image
    path = tmp_path / 'nickname.jpg'
    Image.new('RGB', (30, 40), 'red').save(path)
    raw = {'category': 'twitter', 'tweet_id': 'nick', 'user': {'name': 'collector', 'nick': '收藏者'},
           'author': {'name': 'author'}, 'date': '2026-01-01T00:00:00Z'}
    i = importer.import_file(path, raw)
    raw['author']['nick'] = '发布者昵称'
    importer.import_file(path, raw)
    del raw['author']['nick']
    importer.import_file(path, raw)
    with db.connect() as conn:
        row = conn.execute('SELECT author,author_name FROM posts').fetchone()
        assert tuple(row) == ('author', '发布者昵称')
    assert importer.metadata({'category': 'twitter', 'author': {'screen_name': 'handle', 'name': 'X 昵称'}}, 'a')['author_name'] == 'X 昵称'
    assert importer.metadata({'category': 'instagram', 'username': 'ig', 'fullname': 'IG 昵称'}, 'a')['author_name'] == 'IG 昵称'
    assert importer.metadata({'category': 'instagram', 'owner': {'username': 'ig', 'full_name': 'IG 昵称'}}, 'a')['author_name'] == 'IG 昵称'


def test_instagram_coauthor_keeps_primary_nickname_and_detail_authors(client, tmp_path):
    from PIL import Image

    path = tmp_path / 'coauthor.jpg'
    Image.new('RGB', (30, 40), 'red').save(path)
    raw = {
        'category': 'instagram',
        'post_id': 'coauthor-post',
        'post_url': 'https://www.instagram.com/p/coauthor-post/',
        'user': {'username': 'coauthor_ig', 'full_name': '共同作者昵称'},
        'username': 'main_author',
        'fullname': '主作者昵称',
        'coauthors': [{'username': 'coauthor_ig', 'full_name': '共同作者昵称'}],
        'date': '2026-01-01T00:00:00Z',
        'num': 1,
    }
    image_id = importer.import_file(path, raw)
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET detection='done' WHERE id=?", (image_id,))
    assert importer.metadata(raw, path.name)['author'] == 'main_author'
    assert importer.metadata(raw, path.name)['author_name'] == '主作者昵称'
    detail = client.get(f'/api/v1/gallery/{image_id}').json()
    assert detail['sources'][0]['coauthors'] == [
        {'username': 'coauthor_ig', 'full_name': '共同作者昵称'},
    ]


def test_nickname_schema_upgrade_preserves_existing_posts(client):
    with db.connect(True) as conn:
        image(conn)
        conn.execute('DROP INDEX post_publisher')
        conn.execute('ALTER TABLE posts DROP COLUMN author_name')
        conn.execute('ALTER TABLE reference_images DROP COLUMN box')
        conn.execute('UPDATE schema_version SET version=1')
    db.init()
    db.init()
    with db.connect() as conn:
        assert conn.execute('SELECT author,author_name FROM posts').fetchone()['author'] == 'alice'
        assert 'coauthors' in {row[1] for row in conn.execute('PRAGMA table_info(posts)')}
        assert [r[0] for r in conn.execute('SELECT version FROM schema_version')] == [13]


def test_reference_avatars_crop_selected_face_and_recover_legacy_uploads(client, monkeypatch):
    import base64
    import io
    from PIL import Image
    person = client.post('/api/v1/admin/people', json={'name': 'Avatar'}).json()['id']
    assert client.get('/api/v1/people').json()[0]['avatar_reference_id'] is None
    photo = Image.new('RGB', (100, 100), 'blue')
    photo.paste('red', (50, 10, 70, 40))
    photo.save(db.DATA / 'images' / 'fixture.jpg', quality=100)
    with db.connect(True) as conn:
        image(conn)
        face = conn.execute('SELECT id FROM faces').fetchone()[0]
        conn.execute("UPDATE faces SET box='[50,10,20,30]' WHERE id=?", (face,))
    client.post(f'/api/v1/admin/people/{person}/references', json={'face_id': face})
    avatar = client.get('/api/v1/people').json()[0]['avatar_reference_id']
    crop_url = f'/api/v1/admin/references/{avatar}/crop'
    crop = Image.open(io.BytesIO(client.get(crop_url).content))
    assert crop.size == (20, 30)
    assert crop.getpixel((10, 15))[0] > 240

    token = 'a' * 32
    photo.save(db.DATA / 'references' / f'{token}.jpg', quality=100)
    vectors = [np.array([1, 0] + [0] * 510, dtype='float32').tobytes(), np.array([0, 1] + [0] * 510, dtype='float32').tobytes()]
    boxes = [[0, 0, 20, 20], [50, 10, 20, 30]]
    (db.DATA / 'references' / f'{token}.json').write_text(json.dumps({'model_version': worker.MODEL_VERSION, 'faces': [
        {'box': box, 'embedding': base64.b64encode(vector).decode()} for box, vector in zip(boxes, vectors)
    ]}))
    assert client.post(f'/api/v1/admin/people/{person}/uploaded-reference', json={'token': token, 'index': 1}).status_code == 200
    refs = client.get(f'/api/v1/admin/people/{person}/references').json()
    uploaded = next(r['id'] for r in refs if r['filename'])
    url = f'/api/v1/admin/references/{uploaded}/crop'
    assert Image.open(io.BytesIO(client.get(url).content)).size == (20, 30)
    # Existing uploaded references recover the selected face by embedding.
    with db.connect(True) as conn:
        conn.execute('UPDATE reference_images SET box=NULL WHERE id=?', (uploaded,))
    calls = []
    class FakeVision:
        def detect(self, path, **kwargs):
            calls.append(path)
            return list(zip(boxes, vectors))
    monkeypatch.setattr(main, 'Vision', FakeVision)
    recovered = Image.open(io.BytesIO(client.get(url).content))
    assert recovered.size == (20, 30) and recovered.getpixel((10, 15))[0] > 240
    assert client.get(url).status_code == 200 and len(calls) == 1
    client.delete(f'/api/v1/admin/references/{avatar}')
    assert client.get('/api/v1/people').json()[0]['avatar_reference_id'] == uploaded
    assert client.get(crop_url).status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_recycle_preserves_records_and_other_groups(client):
    person = client.post('/api/v1/admin/people', json={'name': 'Keep person'}).json()['id']
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn, group=first)
        third = image(conn)
        conn.execute("UPDATE images SET filename='deleted.jpg' WHERE id=?", (first,))
        conn.execute('INSERT INTO sources(image_id,post_id,media_key) VALUES(?,?,?)', (second, first, 'shared'))
        face = conn.execute('SELECT id FROM faces WHERE image_id=?', (first,)).fetchone()[0]
        conn.execute('INSERT INTO duplicate_decisions(a,b,decision) VALUES(?,?,?)', (first, second, 'separate'))
        conn.execute("INSERT INTO tasks(kind,image_id) VALUES('detect',?)", (first,))
    client.put(f'/api/v1/admin/faces/{face}', json={'person_id': person, 'revision': 0})
    client.post(f'/api/v1/admin/people/{person}/references', json={'face_id': face})
    for relative in ('images/deleted.jpg', 'thumbs/deleted.jpg', 'originals/0.png'):
        (db.DATA / relative).write_bytes(b'delete me')
    keep = db.DATA / 'images' / 'fixture.jpg'
    keep.write_bytes(b'keep me')
    response = recycle(client, [first, first])
    assert response.status_code == 200 and response.json()['deleted'] == 2
    assert set(response.json()['ids']) == {first, second}
    assert client.get('/api/v1/people').json()[0]['reference_count'] == 0
    assert (db.DATA / 'thumbs/deleted.jpg').exists()
    for relative in ('images/deleted.jpg', 'originals/0.png'):
        assert not (db.DATA / relative).exists()
    assert keep.read_bytes() == b'keep me'
    with db.connect() as conn:
        assert {r[0] for r in conn.execute('SELECT id FROM images')} == {first, second, third}
        assert {r[0] for r in conn.execute('SELECT id FROM images WHERE hidden=1')} == {first, second}
        assert conn.execute('SELECT count(*) FROM people').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM review_history').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM duplicate_decisions').fetchone()[0] == 1
        assert not conn.execute("SELECT 1 FROM tasks WHERE image_id=? AND status IN ('queued','running')", (first,)).fetchone()
        assert not conn.execute("SELECT 1 FROM tasks WHERE image_id=? AND status IN ('queued','running')", (second,)).fetchone()
        assert conn.execute('SELECT 1 FROM posts WHERE id=?', (first,)).fetchone()
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    assert client.get(f'/api/v1/admin/media/{first}').status_code == 404
    assert client.get(f'/api/v1/admin/faces/{face}/crop').status_code == 404
    assert recycle(client, [second, third]).status_code == 200
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM images WHERE hidden=0').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM posts').fetchone()[0] == 3
        assert conn.execute('SELECT count(*) FROM duplicate_groups').fetchone()[0] == 2
    assert not keep.exists()


def test_delete_images_is_atomic_and_blocks_running_work(client, monkeypatch):
    with db.connect(True) as conn:
        first = image(conn)
        second = image(conn)
    body = {'action': 'delete', 'ids': [first, 999]}
    assert client.post('/api/v1/admin/images/actions', json=body).status_code == 404
    body['ids'] = [first, second]
    body['scope_token'] = client.post('/api/v1/admin/images/recycle-preview', json={'ids': body['ids']}).json()['scope_token']
    for kind, image_id in [('detect', first), ('rematch', second), ('import', None), ('download', None)]:
        with db.connect(True) as conn:
            task = conn.execute("INSERT INTO tasks(kind,image_id,status) VALUES(?,?,'running')", (kind, image_id)).lastrowid
        assert client.post('/api/v1/admin/images/actions', json=body).status_code == 409
        with db.connect(True) as conn:
            assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 2
            conn.execute('DELETE FROM tasks WHERE id=?', (task,))
    client.cookies.clear()
    assert client.post('/api/v1/admin/images/actions', json=body).status_code == 401


def test_deleted_file_cleanup_retries_and_protects_reimport(client, tmp_path, monkeypatch):
    from pathlib import Path
    from PIL import Image
    source = tmp_path / 'import-source.png'
    Image.new('RGB', (32, 32), 'red').save(source)
    raw = {'category': 'twitter', 'tweet_id': '123', 'author': {'name': 'alice'}, 'date': '2026-01-01T00:00:00Z'}
    i = importer.import_file(source, raw)
    original_unlink = Path.unlink
    def blocked(path, *args, **kwargs):
        if path.parent in (db.DATA/'images', db.DATA/'originals', db.DATA/'thumbs'):
            raise PermissionError('simulated file lock')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', blocked)
    result = recycle(client, [i])
    assert result.status_code == 200 and result.json()['cleanup_pending'] == 2
    assert source.exists()
    reimported = importer.import_file(source, raw)
    assert reimported == i
    assert client.post('/api/v1/admin/images/actions', json={'action': 'restore', 'ids': [i]}).status_code == 200
    worker.execute(worker.claim(('restore',)))
    monkeypatch.setattr(Path, 'unlink', original_unlink)
    assert db.cleanup_deleted_files() == 0
    with db.connect() as conn:
        filename = conn.execute('SELECT filename FROM images WHERE id=?', (reimported,)).fetchone()[0]
    assert (db.DATA/'images'/filename).exists()
    assert recycle(client, [reimported]).status_code == 200
    assert not (db.DATA/'images'/filename).exists() and source.exists()


def test_image_delete_rolls_back_on_reference_update_failure(client, monkeypatch):
    person = client.post('/api/v1/admin/people', json={'name':'A'}).json()['id']
    with db.connect(True) as conn:
        i = image(conn)
        face = conn.execute('SELECT id FROM faces').fetchone()[0]
    client.post(f'/api/v1/admin/people/{person}/references', json={'face_id':face})
    asset = db.DATA/'images'/'fixture.jpg'
    asset.write_bytes(b'original')
    def fail_schedule(conn):
        raise RuntimeError('simulate transaction failure')
    monkeypatch.setattr(db, 'schedule_rematch', fail_schedule)
    with pytest.raises(RuntimeError):
        recycle(client, [i])
    assert asset.read_bytes() == b'original'
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM reference_images').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM pending_file_deletions').fetchone()[0] == 0


def test_default_review_includes_all_unresolved_categories(client):
    with db.connect(True) as conn:
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        unknown = image(conn)
        automatic = image(conn)
        no_faces = image(conn, False)
        failed = image(conn, False)
        pending = image(conn, False)
        incomplete = image(conn)
        confirmed = image(conn)
        skipped = image(conn)
        ignored = image(conn)
        hidden = image(conn)
        conn.execute('UPDATE faces SET person_id=? WHERE image_id=?', (person, automatic))
        conn.execute("UPDATE images SET detection='failed' WHERE id=?", (failed,))
        conn.execute("UPDATE images SET detection='pending' WHERE id=?", (pending,))
        conn.execute('DELETE FROM sources WHERE image_id=?', (incomplete,))
        conn.execute('UPDATE faces SET person_id=?,locked=1 WHERE image_id IN (?,?)', (person, confirmed, incomplete))
        conn.execute('UPDATE faces SET locked=1 WHERE image_id=?', (skipped,))
        conn.execute('UPDATE faces SET ignored=1,locked=1 WHERE image_id=?', (ignored,))
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (hidden,))
    expected = {unknown, automatic, no_faces, failed, pending, incomplete}
    assert {row['id'] for row in client.get('/api/v1/admin/images').json()} == expected
    assert {row['id'] for row in client.get('/api/v1/admin/images?state=review').json()} == expected
    assert {row['id'] for row in client.get('/api/v1/admin/images?state=hidden').json()} == {hidden}
    assert len(client.get('/api/v1/admin/images?state=all').json()) == 9
    assert automatic not in {row['id'] for row in client.get('/api/v1/admin/images?state=unknown').json()}
    face = next(row for row in client.get('/api/v1/admin/images').json() if row['id'] == automatic)['faces'][0]
    assert client.put(f"/api/v1/admin/faces/{face['id']}", json={'revision':face['revision'],'person_id':person}).status_code == 200
    assert automatic not in {row['id'] for row in client.get('/api/v1/admin/images').json()}


def test_x_details_text_compatibility_preserves_existing_and_long_posts():
    from app.downloader import normalize_twitter_text
    from gallery_dl.extractor.twitter import TwitterExtractor
    class Stub:
        _user = None
        _transform_user = staticmethod(lambda user: {'name':'fixture'})
        _tweetid_to_datetime = staticmethod(lambda value: 'date')
        _extract_media_source = staticmethod(lambda *args: None)
    raw = {'id_str':'2122604348073230483', 'lang':'ja', 'author':{}, 'entities':{},
           'details': {'full_text':'正文\n🐈 https://t.co/media', 'hashtag_entities':[]}}
    assert TwitterExtractor._transform_tweet(Stub(), raw)['content'] == ''
    normalized = normalize_twitter_text(raw)
    assert 'full_text' not in raw
    assert TwitterExtractor._transform_tweet(Stub(), normalized)['content'] == '正文\n🐈'
    raw['full_text'] = '已有完整正文'
    assert normalize_twitter_text(raw) is raw
    assert TwitterExtractor._transform_tweet(Stub(), normalize_twitter_text(raw))['content'] == '已有完整正文'
    del raw['full_text']
    raw['note_tweet'] = {'note_tweet_results': {'result': {'text':'长文优先', 'entity_set':{}}}}
    assert TwitterExtractor._transform_tweet(Stub(), normalize_twitter_text(raw))['content'] == '长文优先'
    del raw['note_tweet']
    nested = {'legacy':{k:v for k,v in raw.items() if k not in ('details','author')}, 'details':raw['details'], 'author':{}}
    assert TwitterExtractor._transform_tweet(Stub(), normalize_twitter_text(nested))['content'] == '正文\n🐈'


def test_x_import_text_fallback_does_not_use_image_alt_text(client, tmp_path):
    from PIL import Image
    base = {'category':'twitter','tweet_id':'fallback','author':{'name':'alice'},'date':'2026-01-01T00:00:00Z'}
    for fields in ({'content':'正文','post_text':None}, {'content':'','details':{'full_text':'正文'}}, {'full_text':'正文'}):
        assert importer.metadata({**base,**fields},'test.jpg')['text'] == '正文'
    assert importer.metadata({**base,'description':'图片替代文字'},'test.jpg')['text'] is None
    path=tmp_path/'text.png'
    Image.new('RGB',(32,32),'red').save(path)
    importer.import_file(path,{**base,'content':''})
    importer.import_file(path,{**base,'content':'','details':{'full_text':'补全正文'}})
    importer.import_file(path,{**base,'content':'   '})
    with db.connect() as conn:
        assert conn.execute('SELECT post_text FROM posts').fetchone()[0] == '补全正文'
        assert conn.execute('SELECT count(*) FROM images').fetchone()[0] == 1


def test_edit_person_references_atomic(client):
    import base64
    person = client.post('/api/v1/admin/people', json={'name': 'Before'}).json()['id']
    other = client.post('/api/v1/admin/people', json={'name': 'Other'}).json()['id']
    with db.connect(True) as conn:
        image(conn)
        image(conn)
        faces = [r[0] for r in conn.execute('SELECT id FROM faces ORDER BY id')]
        conn.execute('UPDATE faces SET person_id=?,locked=1', (person,))
    endpoint = f'/api/v1/admin/people/{person}'
    client.put(endpoint, json={'name': 'Before', 'reference_face_ids': [faces[0]]})
    reference = client.get(endpoint + '/references').json()[0]['id']
    assert client.put(f'/api/v1/admin/people/{other}', json={
        'name': 'Other', 'removed_reference_ids': [reference],
    }).status_code == 409
    token = 'a' * 32
    staged = main.DATA / 'references' / f'{token}.json'
    staged.write_text(json.dumps({'model_version': worker.MODEL_VERSION, 'faces': [{'box': [0, 0, 20, 20], 'embedding': base64.b64encode(np.eye(1, 512, dtype='float32').tobytes()).decode()}]}))
    body = {'name': 'After', 'removed_reference_ids': [reference],
            'reference_face_ids': [faces[1]], 'uploaded_references': [{'token': token, 'index': 9}]}
    assert client.put(endpoint, json=body).status_code == 400
    assert staged.exists()
    assert [r['id'] for r in client.get(endpoint + '/references').json()] == [reference]
    with db.connect() as conn:
        assert conn.execute('SELECT name FROM people WHERE id=?', (person,)).fetchone()[0] == 'Before'
    body['uploaded_references'][0]['index'] = 0
    assert client.put(endpoint, json=body).status_code == 200
    refs = client.get(endpoint + '/references').json()
    assert len(refs) == 2
    assert {r['face_id'] for r in refs} == {faces[1], None}
    assert not staged.exists()


def test_detection_upgrade_append_retry(client):
    with db.connect(True) as conn:
        target = image(conn, faces=False)
        first = db.schedule_detection(conn, target)
        assert db.schedule_detection(conn, target, 'highres') == first
        assert json.loads(conn.execute('SELECT payload FROM tasks WHERE id=?', (first,)).fetchone()[0])['mode'] == 'highres'
        conn.execute("UPDATE tasks SET payload='{}',status='running' WHERE id=?", (first,))
        second = db.schedule_detection(conn, target, 'highres')
        assert second != first
        assert db.schedule_detection(conn, target, 'highres') == second
        conn.execute("UPDATE tasks SET status='failed' WHERE id=?", (second,))
    assert client.post(f'/api/v1/admin/tasks/{second}/retry').status_code == 200
    with db.connect() as conn:
        assert json.loads(conn.execute('SELECT payload FROM tasks WHERE id=?', (second,)).fetchone()[0])['mode'] == 'highres'
    assert worker.claim(('detect',)) is None


@pytest.mark.parametrize('kinds', [(('detect', 'rematch'),), ()], ids=['compute', 'all'])
def test_claim_prioritizes_ready_rematches(client, kinds):
    with db.connect(True) as conn:
        first_image = image(conn)
        first_detect = db.schedule_detection(conn, first_image)
        blocked = conn.execute("INSERT INTO tasks(kind,image_id) VALUES('rematch',?)", (first_image,)).lastrowid
        second_detect = db.schedule_detection(conn, image(conn))
        ready = [conn.execute("INSERT INTO tasks(kind,image_id) VALUES('rematch',?)", (image(conn),)).lastrowid for _ in range(2)]

    assert [worker.claim(*kinds)['id'] for _ in range(4)] == [*ready, first_detect, second_detect]
    assert worker.claim(*kinds) is None
    with db.connect(True) as conn:
        conn.execute("UPDATE tasks SET status='done' WHERE id=?", (first_detect,))
    assert worker.claim(*kinds)['id'] == blocked


def test_worker_parallel_slots_and_order(client, monkeypatch):
    monkeypatch.setenv('WORKER_CONCURRENCY', '2')
    stop, release = threading.Event(), threading.Event()
    entered = threading.Condition()
    active, history = set(), []
    counts = {'compute': 0, 'io': 0}
    peak = dict(counts)
    with db.connect(True) as conn:
        first, second = image(conn, False), image(conn, False)
        db.schedule_detection(conn, first)
        conn.execute("INSERT INTO tasks(kind,image_id) VALUES('rematch',?)", (first,))
        db.schedule_detection(conn, second)
        conn.execute("INSERT INTO tasks(kind) VALUES('import')")
        conn.execute("INSERT INTO tasks(kind) VALUES('download')")
    def work(task):
        category = 'compute' if task['image_id'] else 'io'
        with entered:
            assert task['image_id'] is None or task['image_id'] not in active
            if task['image_id']:
                active.add(task['image_id'])
            history.append((task['kind'], task['image_id']))
            counts[category] += 1
            peak[category] = max(peak[category], counts[category])
            entered.notify_all()
        assert release.wait(5)
        with entered:
            counts[category] -= 1
            active.discard(task['image_id'])
        if task['kind'] == 'detect' and task['image_id'] == first:
            raise ValueError('isolated failure')
    monkeypatch.setattr(worker, 'detect', work)
    monkeypatch.setattr(worker, 'import_task', work)
    def rematch(task):
        work(task)
        with db.connect(True) as conn:
            conn.execute("UPDATE tasks SET status='done' WHERE id=?", (task['id'],))
        stop.set()
    monkeypatch.setattr(worker, 'rematch', rematch)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.run_worker, stop, limits=None, min_idle=0)
        try:
            with entered:
                assert entered.wait_for(lambda: len(history) == 3, timeout=5)
            assert peak == {'compute': 2, 'io': 1}
        finally:
            release.set()
        future.result(timeout=10)
    assert history.index(('rematch', first)) > history.index(('detect', first))
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM tasks WHERE kind='detect' AND image_id=?", (first,)).fetchone()[0] == 'failed'
        assert conn.execute("SELECT status FROM tasks WHERE kind='detect' AND image_id=?", (second,)).fetchone()[0] == 'done'


def test_cancel_detection_before_write(client, monkeypatch):
    (db.DATA / 'images' / 'fixture.jpg').touch()
    with db.connect(True) as conn:
        target = image(conn)
        task_id = db.schedule_detection(conn, target)
    def detect(*args, **kwargs):
        assert kwargs['mode'] == 'auto'
        with db.connect(True) as conn:
            conn.execute('UPDATE tasks SET cancel_requested=1 WHERE id=?', (task_id,))
        return []
    monkeypatch.setattr(worker, 'Vision', lambda: SimpleNamespace(detect=detect))
    worker.step()
    with db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM faces').fetchone()[0] == 1
        assert conn.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()[0] == 'cancelled'


def test_reject_old_face_and_staged_features(client):
    with db.connect(True) as conn:
        target = image(conn)
        conn.execute("UPDATE faces SET model_version='old'")
        face_id = conn.execute('SELECT id FROM faces').fetchone()[0]
        person = conn.execute("INSERT INTO people(name) VALUES('A')").lastrowid
        db.schedule_rematch(conn)
    assert client.post(f'/api/v1/admin/people/{person}/references', json={'face_id': face_id}).status_code == 400
    token = 'b' * 32
    (db.DATA / 'references' / f'{token}.json').write_text('[]')
    assert client.post(f'/api/v1/admin/people/{person}/uploaded-reference', json={'token': token, 'index': 0}).status_code == 400
    worker.step()
    with db.connect() as conn:
        assert conn.execute('SELECT status FROM tasks WHERE image_id=?', (target,)).fetchone()[0] == 'failed'


def test_recovery_preserves_payload_and_cancellation(client):
    with db.connect(True) as conn:
        first, second = image(conn, False), image(conn, False)
        a = db.schedule_detection(conn, first, 'highres')
        b = db.schedule_detection(conn, second)
        conn.execute("UPDATE tasks SET status='running'")
        conn.execute('UPDATE tasks SET cancel_requested=1 WHERE id=?', (b,))
    worker.recover_tasks()
    with db.connect() as conn:
        rows = {row['id']: row for row in conn.execute('SELECT * FROM tasks')}
        assert rows[a]['status'] == 'queued'
        assert json.loads(rows[a]['payload'])['mode'] == 'highres'
        assert rows[b]['status'] == 'cancelled'


def test_reference_upload_uses_highres(client, monkeypatch):
    import io
    from PIL import Image
    content = io.BytesIO()
    Image.new('RGB', (100, 100)).save(content, format='PNG')
    with db.connect(True) as conn:
        conn.execute("UPDATE settings SET value='0.3' WHERE key='detection_threshold'")
    def detect(path, mode, threshold):
        assert threshold == 0.3
        assert mode == 'highres'
        return [([0, 0, 50, 50], np.eye(1, 512, dtype=np.float32).tobytes())]
    monkeypatch.setattr(main, 'Vision', lambda: SimpleNamespace(detect=detect))
    response = client.post('/api/v1/admin/reference-upload', files={'file': ('face.png', content.getvalue(), 'image/png')})
    assert response.status_code == 200
    staged = json.loads((db.DATA / 'references' / (response.json()['token'] + '.json')).read_text())
    assert staged['model_version'] == worker.MODEL_VERSION


def test_detection_threshold_settings_and_migration(client):
    endpoint = "/api/v1/admin/settings"
    config = client.get(endpoint).json()
    assert float(config["detection_threshold"]) == 0.5
    for value in (0, 0.3, 1):
        config["detection_threshold"] = value
        assert client.put(endpoint, json=config).status_code == 200
        assert float(client.get(endpoint).json()["detection_threshold"]) == value
    for value in (-0.01, 1.01, None, "bad"):
        config["detection_threshold"] = value
        assert client.put(endpoint, json=config).status_code == 422
    # Older clients can still save settings without resetting the new value.
    config.pop("detection_threshold")
    assert client.put(endpoint, json=config).status_code == 200
    db.init()
    assert float(client.get(endpoint).json()["detection_threshold"]) == 1
    with db.connect(True) as conn:
        conn.execute("DELETE FROM settings WHERE key='detection_threshold'")
    db.init()
    assert float(client.get(endpoint).json()["detection_threshold"]) == 0.5

def test_representative_original_size(client):
    with db.connect(True) as conn:
        first = image(conn)
        group = conn.execute("SELECT group_id FROM images WHERE id=?", (first,)).fetchone()[0]
        second = image(conn, group=group)
        hidden = image(conn, group=group)
        conn.execute("UPDATE images SET width=2000,file_size=10 WHERE id=?", (first,))
        conn.execute("UPDATE images SET file_size=20 WHERE id=?", (second,))
        conn.execute("UPDATE images SET file_size=100,hidden=1 WHERE id=?", (hidden,))
    assert client.get(f"/api/v1/gallery/{group}").json()["image_id"] == second
    with db.connect(True) as conn:
        conn.execute("UPDATE images SET file_size=20 WHERE id=?", (first,))
    assert client.get(f"/api/v1/gallery/{group}").json()["image_id"] == first


def test_original_size_migration(client, caplog):
    with db.connect(True) as conn:
        first = image(conn)
        image(conn)
        conn.execute('DROP INDEX image_public_group')
        conn.execute('DROP INDEX image_review_group')
        conn.execute("ALTER TABLE images DROP COLUMN file_size")
        conn.execute("UPDATE schema_version SET version=5")
    (db.DATA / "originals" / "0.png").write_bytes(b"original")
    db.init()
    db.init()
    with db.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT file_size FROM images ORDER BY id")] == [8, 0]
    assert "Original unavailable" in caplog.text

def test_title_uses_representative_face_centers(client):
    with db.connect(True) as conn:
        first = image(conn, faces=False)
        group = conn.execute("SELECT group_id FROM images WHERE id=?", (first,)).fetchone()[0]
        second = image(conn, faces=False, group=group)
        for name in ("wide", "left", "ignored", "other"):
            conn.execute("INSERT INTO people(name) VALUES(?)", (name,))
        for target, person, box, ignored in [
            (first, 1, [0, 0, 100, 10], 0),
            (first, 2, [20, 0, 10, 10], 0),
            (first, 2, [90, 0, 10, 10], 0),
            (first, 3, [0, 0, 1, 1], 1),
            (second, 4, [0, 0, 1, 1], 0),
        ]:
            conn.execute("INSERT INTO faces(image_id,person_id,box,ignored) VALUES(?,?,?,?)",
                         (target, person, json.dumps(box), ignored))
    detail = client.get(f"/api/v1/gallery/{group}").json()
    assert [p["name"] for p in detail["people"]] == ["left", "wide"]
    assert client.get("/api/v1/gallery").json()["items"][0]["people"] == detail["people"]


def test_detail_sources_dimensions(client):
    with db.connect(True) as conn:
        first = image(conn)
        group = conn.execute("SELECT group_id FROM images WHERE id=?", (first,)).fetchone()[0]
        second = image(conn, group=group)
        hidden = image(conn, group=group)
        conn.execute("UPDATE images SET width=200 WHERE id=?", (second,))
        conn.execute("UPDATE images SET hidden=1 WHERE id=?", (hidden,))
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) VALUES(?,1,'extra')", (second,))
    detail = client.get(f"/api/v1/gallery/{group}?matched_post=2").json()
    assert [s["id"] for s in detail["sources"]] == [1, 2]
    assert detail["sources"][0]["images"] == [
        {"image_id": first, "width": 100, "height": 100},
        {"image_id": second, "width": 200, "height": 100},
    ]
    assert detail["sources"][1]["images"] == [{"image_id": second, "width": 200, "height": 100}]


@pytest.mark.parametrize('separate_first', [False, True])
@pytest.mark.parametrize('automatic', [False, True])
def test_duplicate_review_follows_current_groups(client, monkeypatch, separate_first, automatic):
    url = '/api/v1/admin/duplicates'
    with db.connect(True) as conn:
        left, other, copy = [image(conn) for _ in range(3)]
        conn.execute("UPDATE images SET phash='0'")
        conn.executemany("INSERT INTO duplicate_decisions VALUES(?,?,'pending',?)", [
            (left, other, .95), (other, copy, .8),
        ])
        config = db.settings(conn)

    def decide(first, second, action):
        assert client.post(url, json={'a': first, 'b': second, 'action': action}).status_code == 200

    def pending():
        return [(row['a'], row['b']) for row in client.get(url, params={'decision': 'pending'}).json()]

    if separate_first:
        decide(left, other, 'separate')
        assert pending() == [(other, copy)]
    if automatic:
        (db.DATA / 'images' / 'fixture.jpg').touch()
        monkeypatch.setattr(importer, 'pair_score', lambda *_: 1)
        importer.consider_pair(left, copy, config)
    else:
        decide(left, copy, 'merge')
    if not separate_first:
        assert pending() == [(left, other)]
        assert client.get(url + '?decision=pending&page=2&page_size=1').json()['total'] == 1
        decide(left, other, 'separate')
    assert pending() == []
    assert [row['decision'] for row in client.get(url).json()] == ['separate', 'auto' if automatic else 'merge']
    decide(left, copy, 'separate')
    assert pending() == [(other, copy)]


def test_duplicate_review_ranks_eligible_pairs_only(client):
    with db.connect(True) as conn:
        first, second = image(conn), image(conn)
        third = image(conn, group=first)
        fourth = image(conn, group=second)
        conn.executemany("INSERT INTO duplicate_decisions VALUES(?,?,'pending',?)", [
            (first, second, None), (first, third, 1), (first, fourth, .9), (second, third, .9),
        ])
    url = '/api/v1/admin/duplicates?decision=pending'
    assert [(row['a'], row['b']) for row in client.get(url).json()] == [(first, fourth)]
    with db.connect(True) as conn:
        conn.execute('UPDATE images SET hidden=1 WHERE id=?', (fourth,))
    assert [(row['a'], row['b']) for row in client.get(url).json()] == [(second, third)]
    assert client.post('/api/v1/admin/duplicates', json={'a': second, 'b': third, 'action': 'merge'}).status_code == 200
    assert client.get(url).json() == []


def test_duplicate_thresholds_and_status_filters(client):
    endpoint = '/api/v1/admin/settings'
    config = client.get(endpoint).json()
    assert float(config['review_ssim_threshold']) == 0.5
    with db.connect(True) as conn:
        ids = [image(conn) for _ in range(7)]
        for i, (decision, score) in enumerate([('pending', .49), ('pending', .5), ('pending', None), ('auto', .4), ('merge', .3), ('separate', None)]):
            conn.execute('INSERT INTO duplicate_decisions VALUES(?,?,?,?)', (ids[0], ids[i+1], decision, score))
    url = '/api/v1/admin/duplicates'
    pending = client.get(url, params={'decision': 'pending'}).json()
    assert [r['score'] for r in pending] == [.5, None]
    assert len(client.get(url).json()) == 5
    assert len(client.get(url + '?decision=auto&decision=merge').json()) == 2
    assert client.get(url, params={'decision': 'invalid'}).status_code == 422
    config['review_ssim_threshold'] = .4
    assert client.put(endpoint, json=config).status_code == 200
    assert len(client.get(url, params={'decision': 'pending'}).json()) == 3
    for lower in (-.01, 1.01, None, 'invalid', .99):
        assert client.put(endpoint, json={**config, 'review_ssim_threshold': lower}).status_code == 422
    assert float(client.get(endpoint).json()['review_ssim_threshold']) == .4
    config.pop('review_ssim_threshold')
    assert client.put(endpoint, json=config).status_code == 200
    db.init()
    assert float(client.get(endpoint).json()['review_ssim_threshold']) == .4
    pair = pending[0]
    assert client.post(url, json={'a': pair['a'], 'b': pair['b'], 'action': 'merge'}).status_code == 200
    assert len(client.get(url, params={'decision': 'pending'}).json()) == 2
    assert len(client.get(url, params={'decision': 'merge'}).json()) == 2
    with db.connect(True) as conn:
        conn.execute("DELETE FROM settings WHERE key='review_ssim_threshold'")
        conn.execute("UPDATE settings SET value='0.3' WHERE key='ssim_threshold'")
    db.init()
    assert float(client.get(endpoint).json()['review_ssim_threshold']) == .3
    config = client.get(endpoint).json()
    assert client.put(endpoint, json=config).status_code == 200


@pytest.mark.parametrize('score,phash,width,decision,visible', [
    (.49, '0', 100, 'pending', False),
    (.5, '0', 100, 'pending', True),
    (.98, '0', 100, 'auto', True),
    (.99, '1f', 100, 'pending', True),
    (.99, '0', 200, 'pending', True),
])
def test_duplicate_threshold_classification(client, monkeypatch, score, phash, width, decision, visible):
    (db.DATA / 'images' / 'fixture.jpg').write_bytes(b'fixture')
    with db.connect(True) as conn:
        a, b = image(conn), image(conn)
        conn.execute("UPDATE images SET phash='0' WHERE id=?", (a,))
        conn.execute('UPDATE images SET phash=?,width=? WHERE id=?', (phash, width, b))
    monkeypatch.setattr(importer, 'similarity', lambda *_: score)
    importer.deduplicate(b)
    with db.connect() as conn:
        assert conn.execute('SELECT decision FROM duplicate_decisions').fetchone()[0] == decision
    assert bool(client.get('/api/v1/admin/duplicates').json()) == visible
    client.post('/api/v1/admin/duplicates', json={'a': a, 'b': b, 'action': 'separate'})
    importer.deduplicate(b)
    with db.connect() as conn:
        assert conn.execute('SELECT decision FROM duplicate_decisions').fetchone()[0] == 'separate'
        assert conn.execute('SELECT count(DISTINCT group_id) FROM images').fetchone()[0] == 2


def test_batch_face_edit_partial_failure_retry_and_undo(client):
    with db.connect(True) as conn:
        for _ in range(4):
            image(conn)
        ids = [row[0] for row in conn.execute("SELECT id FROM faces ORDER BY id")]
        person = conn.execute("INSERT INTO people(name) VALUES('Batch')").lastrowid
    edits = [{"id": id, "revision": 0, "person_id": person} for id in ids]
    edits[1]["revision"] = 1
    edits[2]["person_id"] = person + 100
    edits.append({"id": 9999, "revision": 0})
    response = client.put('/api/v1/admin/faces', json={"faces": edits})
    assert response.status_code == 200
    result = response.json()
    assert result["saved"] == [ids[0], ids[3]]
    assert [(f["id"], f["status"]) for f in result["failures"]] == [(ids[1], 409), (ids[2], 400), (9999, 404)]
    with db.connect() as conn:
        assert [r[0] for r in conn.execute("SELECT revision FROM faces ORDER BY id")] == [1, 0, 0, 1]
        assert conn.execute("SELECT count(*) FROM review_history").fetchone()[0] == 2
    retry = [{"id": id, "revision": 0, "person_id": person} for id in ids[1:3]]
    assert client.put('/api/v1/admin/faces', json={"faces": retry}).json() == {"saved": ids[1:3], "failures": []}
    for id in ids:
        assert client.post(f'/api/v1/admin/faces/{id}/undo').status_code == 200
    with db.connect() as conn:
        assert all(r[0] is None and not r[1] for r in conn.execute("SELECT person_id,locked FROM faces"))


def test_batch_face_edit_validation_and_auth(client):
    with db.connect(True) as conn:
        image(conn)
        id = conn.execute("SELECT id FROM faces").fetchone()[0]
    edit = {"id": id, "revision": 0}
    assert client.put('/api/v1/admin/faces', json={"faces": []}).status_code == 422
    assert client.put('/api/v1/admin/faces', json={"faces": [edit, edit]}).status_code == 400
    with db.connect() as conn:
        assert conn.execute("SELECT revision FROM faces").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM review_history").fetchone()[0] == 0
    client.cookies.clear()
    assert client.put('/api/v1/admin/faces', json={"faces": [edit]}).status_code == 401
