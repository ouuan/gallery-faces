"""Download policy shared by the API, worker and isolated downloader."""
import os
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit


def download_url(value):
    try:
        p = urlsplit(value)
        if p.scheme != 'https' or p.username or p.password or p.port or any(ord(c) < 33 for c in value):
            raise ValueError()
        host = (p.hostname or '').removeprefix('www.')
        path = p.path.rstrip('/')
        if host in ('x.com', 'twitter.com'):
            platform = 'x'
            if re.fullmatch(r'/i/lists/[0-9]+', path):
                return platform, urlunsplit(('https', 'x.com', path, '', ''))
            match = re.fullmatch(r'/([A-Za-z0-9_]{1,15})(?:/(media|status/[0-9]+)(?:/photo/[1-4])?)?', path)
            reserved = {'i', 'home', 'search', 'explore', 'messages', 'settings', 'notifications', 'compose', 'intent', 'login', 'logout'}
        elif host == 'instagram.com':
            platform = 'instagram'
            match = re.fullmatch(r'/([A-Za-z0-9_.]{1,30})(?:/(posts|photos|reels))?', path)
            if re.fullmatch(r'/(p|reel|tv)/[A-Za-z0-9_-]+', path):
                match = True
            reserved = {'accounts', 'direct', 'stories', 'explore', 'saved', 'share'}
        else:
            raise ValueError()
        if not match or path.split('/')[1].lower() in reserved:
            raise ValueError()
        return platform, urlunsplit(('https', host, path, '', ''))
    except (ValueError, AttributeError):
        raise ValueError('仅支持平台账号主页、媒体页、单帖和 Twitter List 链接') from None


def cookie_bytes(content, platform):
    if len(content) > 1024 * 1024:
        raise ValueError('Cookie 文件不能超过 1 MiB')
    try:
        text = content.decode('utf-8')
        if not text.startswith('# Netscape HTTP Cookie File'):
            raise ValueError()
        count = 0
        roots = ('x.com', 'twitter.com') if platform == 'x' else ('instagram.com',)
        for line in text.splitlines():
            if line.startswith('#HttpOnly_'):
                line = line[10:]
            elif not line or line.startswith('#'):
                continue
            fields = line.split('\t')
            if len(fields) != 7:
                raise ValueError()
            domain, subdomains, path, secure, expires, name, value = fields
            domain = domain.lstrip('.').lower()
            if not any(domain == root or domain.endswith('.' + root) for root in roots):
                raise ValueError()
            if subdomains not in ('TRUE', 'FALSE') or secure not in ('TRUE', 'FALSE') or not expires.isascii() or not expires.isdigit() or not path.startswith('/') or not name:
                raise ValueError()
            if any(ord(c) < 32 or ord(c) == 127 for c in ''.join(fields)):
                raise ValueError()
            count += 1
        if not count:
            raise ValueError()
    except (UnicodeError, ValueError):
        raise ValueError('请上传仅含当前平台域名的有效 Netscape Cookie 文件') from None
    return content


def save_cookie(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.cookie-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def public_user(user, platform):
    if not isinstance(user, dict):
        raise ValueError('无法确认账号公开状态')
    if platform == 'x':
        state = (user.get('privacy') or user.get('legacy') or user).get('protected')
    else:
        state = user.get('is_private')
    if state is not False:
        raise ValueError('账号非公开或无法确认公开状态')


def public_post(post):
    # Only explicit restriction flags block; account privacy must separately be explicit.
    for key in ('is_paid_content', 'is_exclusive', 'exclusive_tweet', 'super_follows_only', 'is_close_friends', 'is_unpublished', 'super_follow_exclusive', 'trusted_friends_info', 'limited_actions', 'subscription_media_visibility', 'is_private'):
        if post.get(key):
            raise ValueError('不允许下载受限内容')
    if post.get('audience') not in (None, 'everyone', 'public'):
        raise ValueError('不允许下载受限内容')
