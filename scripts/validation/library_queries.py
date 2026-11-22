"""Benchmark complete list responses using synthetic metadata, without touching an existing library."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db, main


def seed(size):
    with db.connect(True) as conn:
        conn.execute('CREATE TEMP TABLE samples(id INTEGER PRIMARY KEY)')
        conn.executemany('INSERT INTO samples VALUES(?)', ((number,) for number in range(1, size + 1)))
        conn.execute('INSERT INTO duplicate_groups SELECT id FROM samples WHERE id%5<>0')
        conn.execute("""INSERT INTO images(id,sha256,filename,width,height,group_id,detection,hidden,file_size)
            SELECT id,printf('%064x',id),'sample.jpg',1200,800,id-(id%5=0),'done',id%20=1,id FROM samples""")
        conn.execute("""INSERT INTO posts(id,platform,post_key,author,url,published_at)
            SELECT id,'x',id,'u'||(id%400),'https://x.com/u/status/'||id,
            strftime('%Y-%m-%dT%H:%M:%SZ','2024-01-01','+'||(id%800)||' days') FROM samples""")
        conn.execute("INSERT INTO sources(image_id,post_id,media_key) SELECT id,id,'1' FROM samples")
        people = max(1, size // 100)
        conn.execute("INSERT INTO people(id,name) SELECT id,'person'||id FROM samples WHERE id<=?", (people,))
        conn.execute("INSERT INTO faces(image_id,person_id,box) SELECT id,1+id%?,'[1,2,3,4]' FROM samples", (people,))
        if people >= 2:
            conn.execute("INSERT INTO faces(image_id,person_id,box) SELECT id,1+id%2,'[4,3,2,1]' FROM samples")
            conn.execute("INSERT INTO faces(image_id,person_id,box) SELECT id,2-id%2,'[4,3,2,1]' FROM samples WHERE id%997=0")
        conn.execute("INSERT INTO reference_images(person_id,image_id,embedding,model_version) SELECT 1+id%?,id,x'01','v' FROM samples WHERE id<=?", (people, 2 * people))
        conn.execute("INSERT INTO duplicate_decisions(a,b,decision,score) SELECT id-1,id,'auto',.99 FROM samples WHERE id%5=0")


def measure(client, name, endpoint, repeats, **params):
    times = []
    for _ in range(repeats):
        start = perf_counter()
        response = client.get('/api/v1/' + endpoint, params=params)
        times.append((perf_counter() - start) * 1000)
        response.raise_for_status()
    statements = []

    @contextmanager
    def traced():
        with db.connect() as conn:
            conn.set_trace_callback(statements.append)
            yield conn

    with patch.object(main, 'connect', traced):
        client.get('/api/v1/' + endpoint, params=params).raise_for_status()
    reads = sum(sql.lstrip().upper().startswith(('SELECT', 'WITH')) and 'FROM sessions ' not in sql for sql in statements)
    print(f'{name:24} {median(times):9.2f} {reads:6} {len(response.content):10}', flush=True)
    return response.json()


def benchmark(size, repeats):
    with TemporaryDirectory(prefix='gallery-query-benchmark-') as directory, patch.object(db, 'DATA', Path(directory)), \
            patch.object(main, 'DATA', Path(directory)), patch.dict(os.environ, {'ADMIN_PASSWORD': 'benchmark', 'COOKIE_SECURE': 'false'}), \
            TestClient(main.app) as client:
        client.post('/api/v1/login', json={'password': 'benchmark'}).raise_for_status()
        seed(size)
        print(f'\n{size} images\n{"endpoint":24} {"median ms":>9} {"reads":>6} {"bytes":>10}')
        gallery = measure(client, 'gallery', 'gallery', repeats)
        measure(client, 'gallery cursor', 'gallery', repeats, cursor=gallery['next_cursor'], include_total=False)
        posts = measure(client, 'posts', 'posts', repeats)
        measure(client, 'posts cursor', 'posts', repeats, cursor=posts['next_cursor'])
        measure(client, 'posts sparse publisher', 'posts', repeats, publishers='x:u314')
        sparse = measure(client, 'gallery sparse', 'gallery', repeats, limit=10, publishers='x:u314')
        if sparse['next_cursor']:
            measure(client, 'gallery sparse cursor', 'gallery', repeats, cursor=sparse['next_cursor'], limit=10, include_total=False, publishers='x:u314')
        for endpoint in ('gallery', 'posts', 'admin/images'):
            page = {'page': 1} if endpoint == 'admin/images' else {}
            for match in ('any', 'all', 'exact', 'subset'):
                measure(client, f'{endpoint} pair {match}', endpoint, repeats, people='1,2', match=match, **page)
            measure(client, f'{endpoint} pair + source', endpoint, repeats, people='1,2', match='all', publishers='x:u314', **page)
        for endpoint in ('admin/images', 'admin/trash', 'admin/duplicates'):
            measure(client, endpoint, endpoint, repeats, page=1)
        measure(client, 'people', 'people', repeats)
        with db.connect(True) as conn:
            conn.execute("UPDATE posts SET published_at='2025-01-01T00:00:00Z'")
        tied = measure(client, 'gallery tied dates', 'gallery', repeats)
        measure(client, 'gallery tied cursor', 'gallery', repeats, cursor=tied['next_cursor'], include_total=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', type=int, nargs='+', default=[10_000, 50_000])
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or any(size < 100 for size in args.sizes):
        parser.error('use at least one repeat and at least 100 images')
    for size in args.sizes:
        benchmark(size, args.repeats)
