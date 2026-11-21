import json
import os
import time
from typing import Literal, TypedDict

from . import db as storage


class CacheConfig(TypedDict):
    reported_at: float
    low_bytes: int | None
    target_bytes: int | None


class Inventory(TypedDict):
    folder: str
    present: int
    evicted: int
    missing: int
    unknown: int


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
    volumes: list[Volume]


def record(key, value):
    with storage.connect(True) as db:
        db.execute('INSERT OR REPLACE INTO private_config VALUES(?,?)', ('media-cache:' + key, json.dumps(value)))


def report_config(limits):
    low, target = limits or (None, None)
    record('config', CacheConfig(reported_at=time.time(), low_bytes=low, target_bytes=target))


def status() -> CacheStatus:
    from .media_cache import FOLDERS, device, free_bytes
    inventory = []
    volumes = {}
    with storage.connect() as db:
        db.execute('BEGIN')
        reports = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM private_config WHERE key GLOB 'media-cache:*'")}
        for variant, folder in FOLDERS.items():
            try:
                with os.scandir(storage.DATA / folder) as entries:
                    names = {entry.name for entry in entries if entry.is_file()}
            except OSError:
                names = None
            counts = Inventory(folder=folder, present=0, evicted=0, missing=0, unknown=0)
            column = 'filename' if variant == 'image' else 'original_filename'
            for name, evicted in db.execute(f'SELECT {column},{variant}_evicted FROM images WHERE hidden=0'):
                bucket = 'unknown' if names is None else 'present' if name in names else 'evicted' if evicted else 'missing'
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
    return CacheStatus(config=reports.get('media-cache:config'), inventory=inventory, volumes=list(volumes.values()))
