"""Bounded, single-process request admission before multipart/JSON parsing."""
import asyncio
import hashlib
import math
import ipaddress
import os
import sqlite3
import time
from collections import OrderedDict
from contextvars import ContextVar
from starlette.responses import JSONResponse

public_query = ContextVar('public_query', default=False)


def client_key(host):
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, ipaddress.IPv6Address):
            address = address.ipv4_mapped or ipaddress.ip_network(f'{address}/64', strict=False).network_address
        return str(address)
    except ValueError:
        return host


class RequestGuard:
    def __init__(self, app):
        self.app = app
        self.rate = float(os.getenv('REQUEST_RATE_PER_SECOND', '10'))
        self.global_rate = float(os.getenv('REQUEST_GLOBAL_RATE_PER_SECOND', '50'))
        self.max_concurrency = int(os.getenv('REQUEST_MAX_CONCURRENCY', '64'))
        if not all(math.isfinite(v) and v > 0 for v in (self.rate, self.global_rate, self.max_concurrency)):
            raise ValueError('Request limits must be finite positive numbers')
        self.clients = OrderedDict()
        self.total = [200.0, time.monotonic()]
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            self.clients.clear()
            self.total = [200.0, time.monotonic()]
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def reject(code, message):
            await JSONResponse({'detail': message}, code, headers={'Retry-After': '1'} if code in (429, 503) else {})(scope, receive, send)
        now = time.monotonic()
        host = client_key((scope.get('client') or ('unknown',))[0])
        for key in list(self.clients):
            if self.clients[key][1] > now - 120:
                break
            self.clients.pop(key)
        if host not in self.clients and len(self.clients) >= 10000:
            return await reject(429, '请求过于频繁')
        bucket = self.clients.pop(host, [120.0, now])
        self.clients[host] = bucket
        rate = self.rate
        total_rate = self.global_rate
        for entry, refill, capacity in ((bucket, rate, 120), (self.total, total_rate, 200)):
            entry[0] = min(capacity, entry[0] + (now - entry[1]) * refill)
            entry[1] = now
        if bucket[0] < 1 or self.total[0] < 1:
            return await reject(429, '请求过于频繁')
        bucket[0] -= 1
        self.total[0] -= 1
        if self.active >= self.max_concurrency:
            return await reject(503, '服务繁忙，请稍后重试')
        if len(scope.get('query_string', b'')) > 8192:
            return await reject(414, '查询参数过长')
        self.active += 1
        marker = public_query.set(True)
        try:
            headers = dict(scope['headers'])
            authenticated = False
            if scope['path'].startswith('/api/v1/admin/'):
                from http.cookies import SimpleCookie
                from fastapi import HTTPException
                from .db import connect
                cookies = SimpleCookie()
                try:
                    cookies.load(headers.get(b'cookie', b'').decode('latin1'))
                    token = cookies.get('session')
                    if token:
                        with connect() as db:
                            authenticated = bool(db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires>?', (hashlib.sha256(token.value.encode()).hexdigest(), time.time())).fetchone())
                except HTTPException:
                    return await reject(503, "服务繁忙，请稍后重试")
                except (ValueError, sqlite3.Error):
                    pass
                if not authenticated:
                    return await reject(401, '请先登录管理员')
            public_query.set(not authenticated)
            limit = 21 * 1024 * 1024 if authenticated else 16 * 1024
            # Read with a total deadline before handing anything to the multipart parser.
            chunks = []
            size = 0
            try:
                async with asyncio.timeout(10):
                    while True:
                        message = await receive()
                        if message['type'] == 'http.disconnect':
                            return
                        size += len(message.get('body', b''))
                        if size > limit:
                            return await reject(413, '请求体过大')
                        if message.get('body'):
                            chunks.append(message['body'])
                        if not message.get('more_body'):
                            break
            except TimeoutError:
                return await reject(408, '请求体读取超时')
            delivered = False
            async def replay():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
            await self.app(scope, replay, send)
        finally:
            public_query.reset(marker)
            self.active -= 1
