from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from app import worker


@pytest.mark.parametrize("value,expected", [(None, 300), ("0", 0), ("1", 1), ("900", 900)])
def test_idle_timeout_configuration(monkeypatch, value, expected):
    monkeypatch.delenv("WORKER_IDLE_TIMEOUT_SECONDS", raising=False)
    if value is not None:
        monkeypatch.setenv("WORKER_IDLE_TIMEOUT_SECONDS", value)
    assert worker.worker_idle_timeout() == expected


@pytest.mark.parametrize("value", ["", "-1", "1.5", "nan", "auto", " 300", "²"])
def test_invalid_idle_timeout_fails_before_dispatch(monkeypatch, value):
    monkeypatch.setenv("WORKER_CONCURRENCY", "1")
    monkeypatch.setenv("WORKER_IDLE_TIMEOUT_SECONDS", value)
    with pytest.raises(ValueError, match="WORKER_IDLE_TIMEOUT_SECONDS"):
        worker.run_worker(None)


@pytest.mark.parametrize("kind", ["detect", "rematch", "import", "download"])
@pytest.mark.parametrize("timeout", ["0", "300"])
@pytest.mark.parametrize("arrival", [299, 300, 601])
def test_idle_release_and_resume(monkeypatch, kind, timeout, arrival):
    monkeypatch.setenv("WORKER_CONCURRENCY", "1")
    monkeypatch.setenv("WORKER_IDLE_TIMEOUT_SECONDS", timeout)
    ticks = iter([0, 299, 300, 600, 601, 1000, 1001, 1300, 1301, 2000])
    clock = SimpleNamespace(now=next(ticks))
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock.now))
    pending = Future()
    claimed, releases = [], []

    class Executor:
        def __init__(self, max_workers):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            assert pending.done()

        def submit(self, fn, task):
            assert task["kind"] == kind
            return pending

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _):
            clock.now = next(ticks, None)
            if clock.now is None:
                self.stopped = True
            elif clock.now == 1001:
                pending.set_result(True)

    def claim(kinds):
        if clock.now == arrival and kind in kinds and not claimed:
            claimed.append(kind)
            return {"kind": kind}

    monkeypatch.setattr(worker, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "cleanup_deleted_files", lambda: None)
    monkeypatch.setattr(worker, "release_idle_memory", lambda: releases.append(clock.now))
    worker.run_worker(Stop())
    assert claimed == [kind]
    expected = [300, 1301] if arrival == 601 else [1301]
    assert releases == (expected if timeout == "300" else [])


def test_shutdown_skips_idle_release(monkeypatch):
    import threading

    stop = threading.Event()
    monkeypatch.setenv("WORKER_CONCURRENCY", "1")
    monkeypatch.setenv("WORKER_IDLE_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(worker, "claim", lambda _: stop.set())
    monkeypatch.setattr(worker, "cleanup_deleted_files", lambda: None)
    monkeypatch.setattr(worker, "release_idle_memory", lambda: pytest.fail("released during shutdown"))
    worker.run_worker(stop)


@pytest.fixture(autouse=True)
def isolate_scheduler(monkeypatch):
    from app import monitors
    monkeypatch.setattr(monitors, 'schedule_due', lambda: None)
