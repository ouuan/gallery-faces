import hashlib
import io
import json
import re
import subprocess
import sys
import time

from fastapi import HTTPException

from . import db
from .security import download_url, public_user


def account_url(platform, username):
    pattern = {'x': r'[a-z0-9_]{1,15}', 'instagram': r'[a-z0-9_.]{1,30}'}.get(platform)
    if not pattern or not re.fullmatch(pattern, username) or username in ('.', '..'):
        raise ValueError('无效账号')
    return download_url(f'https://{platform}.com/{username}')[1]


def public_account(platform='?', username='?'):
    return f'''EXISTS(SELECT 1 FROM posts p WHERE p.platform={platform} AND lower(p.author)={username}
        AND EXISTS(SELECT 1 FROM public_group_posts link WHERE link.post_id=p.id))'''


def status(platform, username):
    username = username.lower()
    try:
        account_url(platform, username)
    except ValueError:
        raise HTTPException(404) from None
    payload = json.dumps({'platform': platform, 'username': username})
    with db.connect(True) as conn:
        if not conn.execute('SELECT ' + public_account(), (platform, username)).fetchone()[0]:
            raise HTTPException(404)
        row = conn.execute('SELECT digest,next_check FROM publisher_avatars WHERE platform=? AND username=?',
                           (platform, username)).fetchone()
        pending = not row or row['next_check'] <= time.time()
        if pending:
            conn.execute("INSERT OR IGNORE INTO tasks(kind,payload) VALUES('avatar',?)", (payload,))
        digest = row and row['digest']
        return {'image_url': f'/api/v1/publisher-avatars/by-hash/{digest}' if digest else None, 'pending': pending}


def image_bytes(digest):
    with db.connect() as conn:
        row = conn.execute('SELECT image FROM publisher_avatars a WHERE digest=? AND '
                           + public_account('a.platform', 'a.username')
                           + ' LIMIT 1', (digest,)).fetchone()
        if not row:
            raise HTTPException(404)
        return row[0]


def fetch(platform, username):
    from gallery_dl import config, extractor
    from PIL import Image, ImageOps
    from .download_transport import install
    install(platform)
    cookie = db.DATA / 'cookies' / f'{platform}.txt'
    if cookie.is_file():
        config.set(('extractor',), 'cookies', str(cookie))
    config.set(('extractor',), 'cookies-update', False)
    config.set(('extractor',), 'netrc', False)
    config.set(('extractor',), 'user-cache', False)
    profile = extractor.find(account_url(platform, username) + ('/photo' if platform == 'x' else '/avatar/'))
    profile.initialize()
    profile.login()
    if platform == 'x':
        user = profile.api.user_by_screen_name(username)
        public_user(user, platform)
        actual = (user.get('core') or user.get('legacy') or {}).get('screen_name')
        url = (user.get('avatar') or {}).get('image_url') or user['legacy']['profile_image_url_https']
    else:
        user = profile.api.user(username)
        public_user(user, platform)
        actual = user['username']
        url = user.get('profile_pic_url') or user['hd_profile_pic_url_info']['url']
    if not actual or actual.lower() != username:
        raise ValueError('发布者不匹配')
    data = io.BytesIO()
    with profile.session.get(url, stream=True, timeout=12) as response:
        response.raise_for_status()
        for chunk in response.iter_content(65536):
            data.write(chunk)
            if data.tell() > 5 * 1024 * 1024:
                raise ValueError('头像过大')
    data.seek(0)
    with Image.open(data) as picture:
        if picture.width * picture.height > 16_000_000:
            raise ValueError('头像尺寸过大')
        result = io.BytesIO()
        ImageOps.fit(picture.convert('RGB'), (96, 96)).save(result, 'JPEG', quality=90)
        return result.getvalue()


def refresh(payload):
    account = payload['platform'], payload['username']
    with db.connect() as conn:
        if not conn.execute('SELECT ' + public_account(), account).fetchone()[0]:
            return
    try:
        image = subprocess.run([sys.executable, '-m', 'app.publisher_avatars', *account], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, timeout=45, check=True).stdout
        if not image:
            raise ValueError('未返回头像')
    except (ValueError, subprocess.SubprocessError):
        with db.connect(True) as conn:
            conn.execute('''INSERT INTO publisher_avatars(platform,username,next_check,failures) VALUES(?,?,unixepoch()+300,1)
                ON CONFLICT(platform,username) DO UPDATE SET failures=failures+1,
                next_check=unixepoch()+min(86400,300*(1 << min(9,failures)))''', account)
        raise ValueError('发布者头像暂不可用') from None
    with db.connect(True) as conn:
        conn.execute('''INSERT INTO publisher_avatars(platform,username,digest,image,next_check) VALUES(?,?,?,?,unixepoch()+86400)
            ON CONFLICT(platform,username) DO UPDATE SET digest=excluded.digest,image=excluded.image,
            next_check=excluded.next_check,failures=0''', (*account, hashlib.sha256(image).hexdigest(), image))


if __name__ == '__main__':
    sys.stdout.buffer.write(fetch(*sys.argv[1:]))
