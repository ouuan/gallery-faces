import json
import os
import time
from typing import Literal, NotRequired, TypedDict

from . import db as storage


class CacheConfig(TypedDict):
    reported_at: float
    low_bytes: int | None
    target_bytes: int | None
    min_idle_seconds: NotRequired[float]


class Inventory(TypedDict):
    folder: str
    present: int
    evicted: int
    lost: int
    missing: int
    unknown: int


class Activity(TypedDict):
    folder: str
    hits: int
    misses: int
    recoveries: int


class Evictions(TypedDict):
    count: int
    min_idle_days: float | None
    min_score: float | None


class Cleanup(TypedDict):
    finished_at: float
    before_bytes: int
    after_bytes: int | None
    target_bytes: int
    outcome: Literal['target', 'exhausted', 'error']
    removals: dict[str, Evictions]


class Volume(TypedDict):
    folders: list[str]
    free_bytes: int | None
    last_cleanup: Cleanup | None


class CacheStatus(TypedDict):
    config: CacheConfig | None
    inventory: list[Inventory]
    activity_24h: list[Activity]
    volumes: list[Volume]


def record(key, value):
    with storage.connect(True) as db:
        db.execute('INSERT OR REPLACE INTO private_config VALUES(?,?)', ('media-cache:' + key, json.dumps(value)))


def report_config(limits, min_idle):
    low, target = limits or (None, None)
    record('config', CacheConfig(reported_at=time.time(), low_bytes=low, target_bytes=target, min_idle_seconds=min_idle))


def count_activity(db, now, variant, *, hits=0, misses=0, recoveries=0):
    db.execute('''INSERT INTO media_cache_activity(minute,variant,hits,misses,recoveries) VALUES(?,?,?,?,?)
                  ON CONFLICT(minute,variant) DO UPDATE SET hits=hits+excluded.hits, misses=misses+excluded.misses,
                  recoveries=recoveries+excluded.recoveries''', (int(now // 60), variant, hits, misses, recoveries))


def status() -> CacheStatus:
    from .media_cache import FOLDERS, device, free_bytes
    inventory = []
    activity = []
    volumes = {}
    with storage.connect() as db:
        db.execute('BEGIN')
        reports = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM private_config WHERE key GLOB 'media-cache:*'")}
        minute = int(time.time() // 60)
        for variant, folder in FOLDERS.items():
            hits, misses, recoveries = db.execute('''SELECT coalesce(sum(hits),0), coalesce(sum(misses),0), coalesce(sum(recoveries),0)
                                                     FROM media_cache_activity WHERE minute BETWEEN ? AND ? AND variant=?''',
                                                  (minute - 1439, minute, variant)).fetchone()
            activity.append(Activity(folder=folder, hits=hits, misses=misses, recoveries=recoveries))
            try:
                with os.scandir(storage.DATA / folder) as entries:
                    names = {entry.name for entry in entries if entry.is_file()}
            except OSError:
                names = None
            counts = Inventory(folder=folder, present=0, evicted=0, lost=0, missing=0, unknown=0)
            column = 'filename' if variant == 'image' else 'original_filename'
            for name, evicted, lost in db.execute(f'SELECT {column},{variant}_evicted,original_lost FROM images WHERE hidden=0'):
                bucket = ('lost' if variant == 'original' and lost else 'unknown' if names is None else
                          'present' if name in names else 'evicted' if evicted else 'missing')
                counts[bucket] += 1
            inventory.append(counts)
    for folder in ('data', *FOLDERS.values()):
        path = storage.DATA if folder == 'data' else storage.DATA / folder
        try:
            volume = device(path)
        except OSError:
            volume = folder
        if volume not in volumes:
            try:
                remaining = free_bytes(path)
            except OSError:
                remaining = None
            volumes[volume] = Volume(folders=[], free_bytes=remaining, last_cleanup=reports.get(f'media-cache:volume:{volume}'))
        volumes[volume]['folders'].append(folder)
    return CacheStatus(config=reports.get('media-cache:config'), inventory=inventory, activity_24h=activity, volumes=list(volumes.values()))
