import asyncio
import stat
from types import SimpleNamespace
import pytest
from app.security import download_url, cookie_bytes, public_user, public_post, save_cookie
from app.request_guard import RequestGuard, client_key
from test_workflows import client


@pytest.mark.parametrize('url', ['https://x.com/i/bookmarks', 'https://x.com/search?q=a', 'https://instagram.com/stories/a', 'https://x.com/a/likes', 'https://x.com@localhost/a', 'https://x.com:443/a', 'https://x.com/a%2fstatus%2f1', 'http://x.com/a'])
def test_bad_urls(url):
    with pytest.raises(ValueError):
        download_url(url)


def test_urls_and_privacy():
    assert download_url('https://www.twitter.com/alice/status/123?s=20') == ('x', 'https://twitter.com/alice/status/123')
    assert download_url('https://instagram.com/p/abc_-')[0] == 'instagram'
    for user in ({}, {'protected': True}, {'protected': 0}, {'protected': 'false'}):
        with pytest.raises(ValueError):
            public_user(user, 'x')
    public_user({'privacy': {'protected': False}}, 'x')
    public_user({'legacy': {'protected': False}}, 'x')
    public_user({'is_private': False}, 'instagram')
    with pytest.raises(ValueError):
        public_post({'is_close_friends': True})


def cookie(domain='.x.com'):
    return f'# Netscape HTTP Cookie File\n#HttpOnly_{domain}\tTRUE\t/\tTRUE\t0\tauth_token\tsecret\n'.encode()


def test_cookies(tmp_path):
    content = cookie_bytes(cookie(), 'x')
    target = tmp_path / 'cookie.txt'
    save_cookie(target, content)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    for data in (cookie('.evil.com'), cookie('.x.com.evil.com'), b'# Netscape HTTP Cookie File\n', cookie() + b'bad\n'):
        with pytest.raises(ValueError):
            cookie_bytes(data, 'x')
    with pytest.raises(ValueError):
        cookie_bytes(cookie(), 'instagram')


def test_cookie_api_and_input_bounds(client):
    assert client.post('/api/v1/admin/cookies/x', files={'file': ('cookies.txt', cookie())}).status_code == 200
    assert client.post('/api/v1/admin/cookies/x', files={'file': ('cookies.txt', cookie('.evil.com'))}).status_code == 400
    assert client.get('/api/v1/gallery', params={'people': ','.join(map(str, range(51)))}).status_code == 400
    assert client.get('/api/v1/gallery?x=' + 'a' * 8200).status_code == 414
    client.cookies.clear()
    assert client.post('/api/v1/login', content=b'x' * 16385).status_code == 413
    assert client.post('/api/v1/admin/reference-upload', content=b'x' * 16385).status_code == 401


def test_limiter_and_chunked_body():
    async def run():
        called = []
        async def app(scope, receive, send):
            called.append(True)
        guard = RequestGuard(app)
        scope = {'type': 'http', 'path': '/api/v1/login', 'headers': [], 'client': ('::ffff:192.0.2.1', 1), 'query_string': b''}
        events = []
        async def send(event): events.append(event)
        async def receive(): return {'type': 'http.request', 'body': b'a' * 9000, 'more_body': True}
        await guard(scope, receive, send)
        assert events[0]['status'] == 413 and not called
        guard.total[0] = 0
        events.clear()
        await guard(scope, receive, send)
        assert events[0]['status'] == 429
    asyncio.run(run())
    assert client_key('::ffff:192.0.2.1') == '192.0.2.1'
    assert client_key('2001:db8::1') == client_key('2001:db8::2')


def test_network_policy(monkeypatch):
    import requests
    import socket
    import urllib3.util.connection as connection
    from app.download_transport import install
    sent = []
    monkeypatch.setattr(requests.Session, 'send', lambda self, request, **kwargs: sent.append((request, kwargs)))
    monkeypatch.setattr(connection, 'create_connection', connection.create_connection)
    install('x')
    session = requests.Session()
    session.trust_env = False
    for url in ('https://localhost/a', 'https://x.com.evil.com/a', 'http://x.com/a'):
        with pytest.raises(ValueError):
            session.send(requests.Request('GET', url).prepare())
    request = requests.Request('GET', 'https://pbs.twimg.com/a.jpg', headers={'Cookie': 'secret', 'Authorization': 'secret', 'X-Csrf-Token': 'secret'}).prepare()
    proxies = {'https': 'http://proxy.example:8080'}
    session.send(request, proxies=proxies)
    assert not request.headers and sent[-1][1]['proxies'] == proxies
    session.send(request)
    assert sent[-1][1]['proxies'] == {}
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))])
    with pytest.raises(ValueError):
        connection.create_connection(('x.com', 443))


def test_private_tweet_rejected_before_transform(monkeypatch):
    from app.downloader import install_policy
    from gallery_dl.extractor.common import Extractor
    from gallery_dl.extractor.twitter import TwitterExtractor
    from gallery_dl.extractor.instagram import InstagramExtractor
    for cls, names in ((Extractor, ['initialize']), (TwitterExtractor, ['_transform_tweet', 'items']), (InstagramExtractor, ['_parse_post', 'items'])):
        for name in names:
            monkeypatch.setattr(cls, name, getattr(cls, name))
    state = install_policy()
    with pytest.raises(ValueError):
        TwitterExtractor._transform_tweet(None, {'user': {'protected': True}})
    assert state['denied']


def test_download_attempt_cleanup(client, monkeypatch):
    import json
    from app import worker
    paths = []
    def attempt(task, directory):
        paths.append(directory)
        (directory / 'secret.jpg').write_bytes(b'private')
        raise ValueError('blocked')
    monkeypatch.setattr(worker, '_import_task', attempt)
    for _ in range(2):
        with pytest.raises(ValueError):
            worker.import_task({'id': 1, 'kind': 'download', 'payload': json.dumps({'url': 'https://x.com/a'})})
    assert paths[0] != paths[1] and all(not p.exists() for p in paths)


def test_public_post_hooks_and_unknown_owner(monkeypatch):
    from app.downloader import install_policy
    from gallery_dl.extractor.common import Extractor
    from gallery_dl.extractor.twitter import TwitterExtractor
    from gallery_dl.extractor.instagram import InstagramExtractor
    for cls, names in ((Extractor, ['initialize']), (TwitterExtractor, ['items']), (InstagramExtractor, ['items'])):
        for name in names:
            monkeypatch.setattr(cls, name, getattr(cls, name))
    monkeypatch.setattr(TwitterExtractor, '_transform_tweet', lambda self, raw: raw)
    monkeypatch.setattr(InstagramExtractor, '_parse_post', lambda self, raw: raw)
    state = install_policy()
    tweet = {'user': {'protected': False}}
    assert TwitterExtractor._transform_tweet(None, tweet) == tweet
    raw = {'user': {'pk': 123}}
    extractor = SimpleNamespace(api=SimpleNamespace(_user_by_id_impl=lambda uid: {'id': uid, 'is_private': False}))
    assert InstagramExtractor._parse_post(extractor, raw) == raw
    extractor.api._user_by_id_impl = lambda uid: {'id': '456', 'is_private': False}
    with pytest.raises(ValueError):
        InstagramExtractor._parse_post(extractor, raw)
    assert state['denied']


def test_dns_validation_uses_same_address(monkeypatch):
    import socket
    import requests
    import urllib3.util.connection as connection
    from app.download_transport import install
    monkeypatch.setattr(requests.Session, 'send', requests.Session.send)
    monkeypatch.setattr(connection, 'create_connection', connection.create_connection)
    install('x')
    resolved, connected = [], []
    def resolve(*args, **kwargs):
        resolved.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(socket, 'socket', lambda *a: SimpleNamespace(settimeout=lambda t: None, connect=lambda addr: connected.append(addr)))
    connection.create_connection(('x.com', 443), timeout=1)
    assert len(resolved) == 1 and connected == [('1.1.1.1', 443)]


class ProxySocketReached(Exception):
    pass


@pytest.fixture
def proxy_network(monkeypatch):
    import requests
    import socket
    import urllib3.util.connection as connection
    from app.download_transport import install
    for name in ('https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY',
                 'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(requests.Session, 'send', requests.Session.send)
    monkeypatch.setattr(connection, 'create_connection', connection.create_connection)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))
    ])
    connected = []
    def connect(address):
        connected.append(address)
        # Stop before any network I/O, after the real Requests/urllib3 proxy routing.
        raise ProxySocketReached()
    monkeypatch.setattr(socket, 'socket', lambda *a: SimpleNamespace(
        settimeout=lambda t: None, setsockopt=lambda *a: None,
        connect=connect, close=lambda: None,
    ))
    return install('x'), connected


@pytest.mark.parametrize('source, proxy, port', [
    ('https_proxy', 'http://127.0.0.1:7890', 7890),
    ('HTTPS_PROXY', 'http://localhost:8080', 8080),
    ('ALL_PROXY', 'http://localhost:8080', 8080),
    ('https_proxy', 'https://localhost', 443),
    ('https_proxy', 'http://localhost', 80),
    ('https_proxy', 'http://[::1]:8080', 8080),
    ('session', 'http://user:secret@localhost:8080', 8080),
    ('request', 'http://localhost:8080', 8080),
])
def test_local_proxy_allowed_only_for_selected_request(proxy_network, monkeypatch, source, proxy, port):
    import requests
    import urllib3.util.connection as connection
    state, connected = proxy_network
    session = requests.Session()
    kwargs = {}
    if source == 'session':
        session.proxies = {'https': proxy}
    elif source == 'request':
        kwargs['proxies'] = {'https': proxy}
    else:
        monkeypatch.setenv(source, proxy)
    with pytest.raises(ProxySocketReached):
        session.get('https://x.com/alice', **kwargs)
    assert connected == [('127.0.0.1', port)] and not state['denied']
    # The exception must not leak the proxy exemption into later connections.
    with pytest.raises(ValueError, match='非公网 IP'):
        connection.create_connection(('localhost', port))
    assert len(connected) == 1


@pytest.mark.parametrize('bypass', ['no_proxy', 'trust_env', 'explicit_direct'])
def test_proxy_bypass_keeps_private_destination_blocked(proxy_network, monkeypatch, bypass):
    import requests
    state, connected = proxy_network
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:7890')
    session = requests.Session()
    if bypass == 'no_proxy':
        monkeypatch.setenv('no_proxy', 'x.com')
    elif bypass == 'trust_env':
        session.trust_env = False
    with pytest.raises(ValueError, match='非公网 IP'):
        if bypass == 'explicit_direct':
            session.send(requests.Request('GET', 'https://x.com/alice').prepare(), proxies={})
        else:
            session.get('https://x.com/alice')
    assert state['denied'] and not connected


def test_proxy_does_not_allow_redirect_outside_whitelist(proxy_network, monkeypatch):
    import requests
    state, connected = proxy_network
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:7890')
    sent = []
    class RedirectAdapter(requests.adapters.HTTPAdapter):
        def send(self, request, **kwargs):
            sent.append(request.url)
            response = requests.Response()
            response.status_code = 302
            response.headers['Location'] = 'https://127.0.0.1/private?secret=token'
            response._content = b''
            response.url = request.url
            response.request = request
            return response
    session = requests.Session()
    session.mount('https://', RedirectAdapter())
    with pytest.raises(ValueError, match='白名单'):
        session.get('https://x.com/alice')
    assert sent == ['https://x.com/alice'] and not connected
    assert 'secret' not in state['reason']


@pytest.mark.parametrize('url, reason, host', [
    ('http://x.com/private?token=secret', '仅允许 HTTPS', 'x.com'),
    ('https://user:secret@x.com/private', '包含用户名或密码', 'x.com'),
    ('https://x.com:8443/private', '实际端口为 8443', 'x.com'),
    ('https://x.com:invalid/private', 'URL 端口无效', 'x.com'),
    ('https://outside.example/private?token=secret', '白名单', 'outside.example'),
    ('https://x.com.evil.com/private', '白名单', 'x.com.evil.com'),
    ('https://[invalid/private?token=secret', 'URL 格式无效', '未知'),
])
def test_network_denial_report(monkeypatch, tmp_path, url, reason, host):
    import requests
    import urllib3.util.connection as connection
    from app.download_transport import install
    monkeypatch.setattr(requests.Session, 'send', requests.Session.send)
    monkeypatch.setattr(connection, 'create_connection', connection.create_connection)
    report = tmp_path / 'policy-error.txt'
    state = install('x', report)
    with pytest.raises(ValueError):
        requests.Session().send(SimpleNamespace(url=url))
    message = report.read_text()
    assert reason in message and f'主机：{host}' in message
    assert state['denied'] and state['reason'] == message
    assert all(value not in message for value in ('secret', 'private', 'token=', 'user:'))
    # Keep the first failure even if the extractor continues with other requests.
    with pytest.raises(ValueError):
        requests.Session().send(SimpleNamespace(url='https://later.example/'))
    assert report.read_text() == message


@pytest.mark.parametrize('addresses, reason', [
    ([], 'DNS 解析结果为空'),
    (['1.1.1.1', '127.0.0.1'], '非公网 IP：127.0.0.1'),
    (['::1'], '非公网 IP：::1'),
])
def test_dns_denial_report(monkeypatch, tmp_path, addresses, reason):
    import requests
    import socket
    import urllib3.util.connection as connection
    from app.download_transport import install
    monkeypatch.setattr(requests.Session, 'send', requests.Session.send)
    monkeypatch.setattr(connection, 'create_connection', connection.create_connection)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses
    ])
    report = tmp_path / 'policy-error.txt'
    install('x', report)
    with pytest.raises(ValueError):
        connection.create_connection(('x.com', 443))
    assert reason in report.read_text() and '主机：x.com' in report.read_text()


@pytest.mark.parametrize('returncode, report_enabled', [(21, True), (20, True), (1, True), (21, False)])
def test_policy_report_saved_in_task(client, monkeypatch, returncode, report_enabled):
    import json
    import sys
    from app import db, worker
    popen = worker.subprocess.Popen
    script = '''
import os
import sys
import requests
from app.download_transport import install
install('x', os.environ.get('GALLERY_FACES_POLICY_REPORT'))
try:
    requests.Session().send(requests.Request('GET', 'https://outside.example/private?token=secret').prepare())
except ValueError:
    sys.exit(int(sys.argv[1]))
'''
    def download(command, **kwargs):
        if not report_enabled:
            kwargs['env'].pop('GALLERY_FACES_POLICY_REPORT')
        return popen([sys.executable, '-c', script, str(returncode)], **kwargs)
    monkeypatch.setattr(worker.subprocess, 'Popen', download)
    with db.connect(True) as conn:
        task_id = conn.execute(
            "INSERT INTO tasks(kind,payload) VALUES('download',?)",
            (json.dumps({'url': 'https://x.com/alice'}),),
        ).lastrowid
    worker.step()
    with db.connect() as conn:
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    assert task['status'] == 'failed'
    if report_enabled:
        assert '白名单' in task['error'] and 'outside.example' in task['error']
        assert 'secret' not in task['error'] and 'private' not in task['error']
    else:
        assert task['error'] == '下载被安全策略拒绝'
    assert not list((worker.DATA / 'downloads').iterdir())


def test_public_query_execution_budget(client, monkeypatch):
    from app import db
    from app.request_guard import public_query
    from fastapi import HTTPException
    import time
    marker = public_query.set(True)
    try:
        with pytest.raises(HTTPException) as error:
            with db.connect() as conn:
                monkeypatch.setattr(time, 'monotonic', lambda: 0)
                # Use a finite but deliberately expensive query; deadline interrupts it.
                conn.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<1000000000) SELECT sum(x) FROM n').fetchone()
        assert error.value.status_code == 503
    finally:
        public_query.reset(marker)
