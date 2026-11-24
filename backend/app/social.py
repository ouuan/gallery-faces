import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as XML

from . import list_queries
from .metadata import validate_url


RSS_PATH = '/api/v1/gallery/rss.xml'
FILTERS = ('people', 'match', 'publishers', 'start', 'end', 'include_no_faces')


def query(params, **extra):
    values = {key: params[key] for key in FILTERS if params.get(key)}
    if values.get('match') == 'any':
        values.pop('match')
    if values.get('include_no_faces') == 'false':
        values.pop('include_no_faces')
    encoded = urlencode(values | extra)
    return '?' + encoded if encoded else ''


def post_key(row):
    return f"{row['platform']}:{row['embed_id'] or 'record:' + str(row['id'])}"


def find_post(db, key):
    platform, _, identity = key.partition(':')
    if platform not in ('x', 'instagram'):
        return None
    if identity.startswith('record:'):
        where, value = 'p.embed_id IS NULL AND p.id=?', identity[7:]
    else:
        where, value = 'p.embed_id=?', identity
    return db.execute(f'''SELECT p.id FROM posts p WHERE p.platform=? AND {where} AND EXISTS(
        SELECT 1 FROM public_group_posts link WHERE link.post_id=p.id) ORDER BY p.id LIMIT 1''',
                      (platform, value)).fetchone()


def picture_rows(db, seeds, conditions=(), args=(), *, thumbs=None):
    where = ' AND ' + ' AND '.join(conditions) if conditions else ''
    join = 'LEFT JOIN' if thumbs is not None else 'JOIN'
    eligible = '(member.hidden=1 OR g.representative IS NOT NULL)' if thumbs is not None else 'member.hidden=0'
    rows = db.execute(f'''WITH seeds AS (SELECT p.* FROM json_each(?) seed JOIN posts p ON p.id=seed.value),
        aliases(root,id) AS (SELECT id,id FROM seeds WHERE embed_id IS NULL UNION ALL
            SELECT s.id,p.id FROM seeds s JOIN posts p ON p.platform=s.platform AND p.embed_id=s.embed_id),
        pictures AS (SELECT a.root,CASE WHEN member.hidden=1 THEN member.id ELSE g.representative END AS selected_id,
            min(s.id) position FROM aliases a
            JOIN posts p ON p.id=a.id JOIN sources s ON s.post_id=p.id JOIN images member ON member.id=s.image_id
            {join} public_groups g ON g.group_id=member.group_id WHERE {eligible} AND member.detection='done'
            AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL {where}
            GROUP BY a.root,selected_id)
        SELECT pictures.root,i.* FROM pictures JOIN images i ON i.id=pictures.selected_id
        ORDER BY pictures.root,pictures.position''', [seeds, *args])
    chosen = {}
    for row in rows:
        key = row['root'], row['group_id']
        if not row['hidden'] or (key not in chosen and (thumbs / row['filename']).is_file()):
            chosen[key] = row
    return chosen.values()


def hydrate(db, post_ids, media_urls, gallery_labels, people=(), match='any', source='', args=(), include_no_faces=True, *, thumbs=None):
    if not post_ids:
        return []
    seeds = json.dumps(post_ids)
    posts = {}
    for row in db.execute('SELECT p.* FROM json_each(?) seed JOIN posts p ON p.id=seed.value', (seeds,)):
        posts[row['id']] = {name: row[name] for name in ('id', 'platform', 'url', 'author', 'author_name', 'published_at', 'post_text')}
        posts[row['id']].update(key=post_key(row), coauthors=json.loads(row['coauthors'] or '[]'), images=[])
    conditions, bindings = [], list(args)
    if source:
        conditions.append(source)
    if people:
        selected, selected_args = list_queries.matching_groups('public', people, match)
        conditions.append(f'g.group_id IN ({selected})')
        bindings.extend(selected_args)
    elif not include_no_faces:
        conditions.append('g.has_face=1')
    rows = picture_rows(db, seeds, conditions, bindings, thumbs=thumbs)
    labels = gallery_labels(db, list({row['id'] for row in rows if not row['hidden']})) if rows else {}
    for row in rows:
        post = posts[row['root']]
        if row['hidden']:
            urls = dict(image_url=None, thumbnail_url=f"/api/v1/posts/{quote(post['key'], safe=':')}/thumbnails/{row['group_id']}")
        else:
            urls = media_urls(row)
        post['images'].append(dict(id=row['group_id'], width=row['width'], height=row['height'],
            image_url=urls['image_url'], thumbnail_url=urls['thumbnail_url'], people=labels.get(row['id'], [])))
    return [posts[identifier] for identifier in post_ids]


def render_feed(title, origin, params, posts):
    suffix = query(params)
    root = XML.Element('rss', version='2.0', attrib={'xmlns:atom': 'http://www.w3.org/2005/Atom'})
    channel = XML.SubElement(root, 'channel')
    def text(parent, name, value, **attrs):
        XML.SubElement(parent, name, attrs).text = value
    text(channel, 'title', title)
    text(channel, 'link', origin + '/' + suffix)
    text(channel, 'description', '图库最新帖子')
    XML.SubElement(channel, 'atom:link', href=origin + RSS_PATH + suffix, rel='self', type='application/rss+xml')
    for post in posts:
        item = XML.SubElement(channel, 'item')
        url = origin + '/posts/' + quote(post['key'], safe=':')
        text(item, 'guid', url, isPermaLink='false')
        text(item, 'link', url + suffix)
        author = '@' + post['author'].lstrip('@')
        label = f"{post['author_name']} ({author})" if post['author_name'] else author
        text(item, 'title', label + ' 的帖子')
        stamp = datetime.fromisoformat(post['published_at']).astimezone(timezone.utc)
        text(item, 'pubDate', format_datetime(stamp, usegmt=True))
        publisher = origin + '/?' + urlencode({'publishers': post['platform'] + ':' + post['author']})
        content = [f'<p><a href="{escape(publisher)}">{escape(label)}</a></p>']
        if post['post_text']:
            content.append('<p>' + '<br>'.join(map(escape, post['post_text'].splitlines())) + '</p>')
        for image in post['images']:
            names = '、'.join(person['name'] for person in image['people']) or '照片'
            photo = origin + '/' + query(params, photo=image['id'])
            content.append(f'<p><a href="{escape(photo)}"><img src="{escape(origin + image["image_url"])}" alt="{escape(names)}"></a><br>{escape(names)}</p>')
        if validate_url(post['url']):
            content.append(f'<p><a href="{escape(post["url"])}">打开原帖</a></p>')
        text(item, 'description', ''.join(content))
    xml = XML.tostring(root, encoding='unicode', xml_declaration=True)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]', '', xml)
