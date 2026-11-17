"""Network confinement for the downloader subprocess only."""
import ipaddress
import socket
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlsplit


def install(platform, report_path=None):
    import requests
    import urllib3.util.connection
    from requests.utils import prepend_scheme_if_needed, resolve_proxies, select_proxy
    from urllib3.util import parse_url
    roots = ('x.com', 'twitter.com') if platform == 'x' else ('instagram.com',)
    cdns = ('twimg.com',) if platform == 'x' else ('cdninstagram.com', 'fbcdn.net')
    state = {'denied': False}
    original_send = requests.Session.send
    proxy_endpoint = ContextVar('download_proxy_endpoint', default=None)

    def deny(reason, host):
        # Only retain the hostname, never URL paths, query strings or credentials.
        host = ''.join(c for c in str(host)[:253] if c.isascii() and (c.isalnum() or c in '.-_:'))
        message = f'下载被安全策略拒绝：{reason}（主机：{host or "未知"}）'
        if not state['denied']:
            state.update(denied=True, reason=message)
            if report_path is not None:
                Path(report_path).write_text(message, encoding='utf-8')
        raise ValueError(message)

    def send(session, request, **kwargs):
        try:
            p = urlsplit(request.url)
            host = (p.hostname or '').lower()
        except ValueError:
            deny('URL 格式无效', '')
        matches = lambda domains: any(host == d or host.endswith('.' + d) for d in domains)
        if p.scheme != 'https':
            deny('仅允许 HTTPS 请求', host)
        if p.username or p.password:
            deny('URL 包含用户名或密码', host)
        try:
            port = p.port
        except ValueError:
            deny('URL 端口无效', host)
        if port not in (None, 443):
            deny(f'仅允许 443 端口，实际端口为 {port}', host)
        if not matches(roots + cdns):
            deny('域名不在当前平台的白名单内', host)
        kwargs['verify'] = True
        if not matches(roots):
            for key in list(request.headers):
                if key.lower() not in ('user-agent', 'accept', 'accept-encoding', 'range'):
                    del request.headers[key]
        if 'proxies' not in kwargs:
            kwargs['proxies'] = resolve_proxies(request, session.proxies, session.trust_env)
        proxy = select_proxy(request.url, kwargs['proxies'])
        endpoint = None
        if proxy:
            parsed = parse_url(prepend_scheme_if_needed(proxy, 'http'))
            if parsed.host and parsed.scheme in ('http', 'https'):
                endpoint = (parsed.host.strip('[]').lower(),
                            parsed.port or (443 if parsed.scheme == 'https' else 80))
        # Only the proxy selected for this request may use a private address.
        # The proxy resolves the destination; URL checks above still apply to
        # every request, including redirects. Never exempt a proxy globally.
        token = proxy_endpoint.set(endpoint)
        try:
            return original_send(session, request, **kwargs)
        finally:
            proxy_endpoint.reset(token)

    def connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
        host, port = address
        host = host.strip('[]')
        is_proxy = (host.lower(), port) == proxy_endpoint.get()
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not records:
            deny('DNS 解析结果为空', host)
        for record in records:
            address = ipaddress.ip_address(record[4][0])
            if not address.is_global and not is_proxy:
                deny(f'DNS 解析包含非公网 IP：{address}', host)
        last = None
        for family, socktype, proto, _, sockaddr in records:
            sock = socket.socket(family, socktype, proto)
            try:
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                for option in socket_options or ():
                    sock.setsockopt(*option)
                if source_address:
                    sock.bind(source_address)
                sock.connect(sockaddr)
                return sock
            except OSError as error:
                last = error
                sock.close()
        raise last

    requests.Session.send = send
    urllib3.util.connection.create_connection = connect
    return state
