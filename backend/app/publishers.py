import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import db as storage


Platform = Literal['x', 'instagram']
Source = Literal['all', 'retweets', 'quoted', 'tagged', 'reposts']
View = Literal['posts', 'rules']


class BlockRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    blocked: list[Source]


class PurgeRequest(BlockRule):
    scope_token: str


class PublisherSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    usernames: list[str] = Field(min_length=1, max_length=100)


class BatchRule(PublisherSelection, BlockRule):
    pass


class BatchPurge(PublisherSelection):
    scope_token: str
    blocked: list[Source] | None = None


class PurgeResult(BaseModel):
    posts: int
    cleanup_pending: int


class Publisher(BlockRule):
    username: str
    label: str
    posts: int
    linked: bool


class PublisherPage(BaseModel):
    items: list[Publisher]
    posts_count: int
    rules_count: int
    page: int
    page_size: int


class Reference(BaseModel):
    image_id: int
    reference_id: int
    person: str


class PurgePreview(BlockRule):
    posts: int
    exclusive: int
    shared: int
    references: list[Reference]
    scope_token: str


LIST = '''WITH counts AS (
    SELECT lower(author) AS account,count(*) AS posts,
        coalesce(max(id) FILTER (WHERE trim(author_name)<>''),max(id)) AS latest
    FROM posts WHERE platform=:platform AND author IS NOT NULL AND trim(author)<>'' GROUP BY lower(author)
), publishers AS (
    SELECT p.author AS username,coalesce(nullif(trim(p.author_name),''),p.author) AS label,c.posts,r.blocked
    FROM counts c JOIN posts p ON p.id=c.latest
    LEFT JOIN publisher_rules r ON r.platform=:platform AND r.username=c.account
    UNION ALL SELECT r.username,r.label,0,r.blocked FROM publisher_rules r WHERE r.platform=:platform
        AND NOT EXISTS(SELECT 1 FROM counts c WHERE c.account=lower(r.username))
), matched AS (
    SELECT *,EXISTS(SELECT 1 FROM accounts a WHERE a.platform=:platform AND lower(a.username)=lower(p.username)) AS linked
    FROM publishers p WHERE instr(lower(username),lower(:search)) OR instr(lower(label),lower(:search))
), visible AS (SELECT * FROM matched WHERE NOT linked OR blocked IS NOT NULL) '''


def account(db, platform, username):
    row = db.execute('''SELECT author AS username,coalesce(nullif(trim(author_name),''),author) AS label
        FROM posts WHERE platform=? AND lower(author)=lower(?) AND trim(author)<>''
        ORDER BY (nullif(trim(author_name),'') IS NOT NULL) DESC,id DESC LIMIT 1''', (platform, username)).fetchone()
    rule = db.execute('SELECT * FROM publisher_rules WHERE platform=? AND username=?', (platform, username)).fetchone()
    if not row and not rule:
        raise HTTPException(404, '发布者不存在，请刷新列表')
    linked = db.execute('SELECT 1 FROM accounts WHERE platform=? AND lower(username)=lower(?) LIMIT 1',
                        (platform, username)).fetchone()
    return row or rule, json.loads(rule['blocked']) if rule else [], bool(linked)


def save_rule(db, platform, row, blocked):
    choices = ('retweets', 'quoted') if platform == 'x' else ('tagged', 'reposts')
    if blocked != ['all'] and (set(blocked).difference(choices) or len(set(blocked)) != len(blocked)):
        raise HTTPException(422, '请选择当前平台的来源；全部来源不能与其他来源同时选择')
    if blocked:
        db.execute('INSERT OR REPLACE INTO publisher_rules VALUES(?,?,?,?)',
                   (platform, row['username'], row['label'], json.dumps([key for key in ('all', *choices) if key in blocked])))
    else:
        db.execute('DELETE FROM publisher_rules WHERE platform=? AND username=?', (platform, row['username']))


def scope(db, platform, usernames):
    rows = []
    rules = {}
    db.execute('CREATE TEMP TABLE target_posts(id INTEGER PRIMARY KEY,post_key TEXT)')
    for username in sorted({name.lower() for name in usernames}):
        row, blocked, linked = account(db, platform, username)
        if linked:
            raise HTTPException(409, f'@{username} 已关联人物，不能删除帖子')
        if not db.execute('INSERT INTO target_posts SELECT id,post_key FROM posts WHERE platform=? AND lower(author)=?',
                          (platform, username)).rowcount:
            raise HTTPException(409, f'@{username} 已没有帖子')
        rows.append(row)
        rules[username] = blocked
    posts = db.execute('SELECT count(*) FROM target_posts').fetchone()[0]
    db.execute('CREATE TEMP TABLE target_images(id INTEGER PRIMARY KEY,exclusive INTEGER NOT NULL)')
    db.execute('''INSERT INTO target_images SELECT DISTINCT s.image_id,NOT EXISTS(
        SELECT 1 FROM sources other WHERE other.image_id=s.image_id AND other.post_id NOT IN (SELECT id FROM target_posts))
        FROM sources s WHERE s.post_id IN (SELECT id FROM target_posts)''')
    exclusive, shared = db.execute('SELECT count(*) FILTER (WHERE exclusive),count(*) FILTER (WHERE NOT exclusive) FROM target_images').fetchone()
    references = [dict(record) for record in db.execute('''SELECT coalesce(r.image_id,f.image_id) AS image_id,
        r.id AS reference_id,p.name AS person FROM reference_images r JOIN people p ON p.id=r.person_id
        LEFT JOIN faces f ON f.id=r.face_id WHERE coalesce(r.image_id,f.image_id) IN
        (SELECT id FROM target_images WHERE exclusive) ORDER BY image_id,r.id''')]
    digest = hashlib.sha256(json.dumps([platform, rules, references]).encode())
    for query in ('SELECT * FROM target_posts ORDER BY id', 'SELECT * FROM target_images ORDER BY id',
                  'SELECT id,image_id,post_id,media_key FROM sources WHERE post_id IN (SELECT id FROM target_posts) ORDER BY id'):
        for record in db.execute(query):
            digest.update(json.dumps(list(record)).encode())
    common = next(iter(rules.values()))
    return rows, PurgePreview(posts=posts, exclusive=exclusive, shared=shared, blocked=common if all(rule == common for rule in rules.values()) else [],
                             references=references, scope_token=digest.hexdigest())


def clean_reviews(db, platform, images):
    exclusive = '(SELECT id FROM target_images WHERE exclusive)'
    db.execute(f'''CREATE TEMP TABLE affected_snapshots AS SELECT batch,image_id FROM review_snapshots s
        WHERE EXISTS(SELECT 1 FROM json_each(s.snapshot,'$.sources') source WHERE json_extract(source.value,'$.platform')=?
        AND json_extract(source.value,'$.post_key') IN (SELECT post_key FROM target_posts)) OR
        EXISTS(SELECT 1 FROM json_each(s.snapshot,'$.member_ids') member WHERE member.value IN {exclusive})''', (platform,))
    batches = '(SELECT batch FROM affected_snapshots)'
    if db.execute(f"SELECT 1 FROM review_batches WHERE id IN {batches} AND status='building'").fetchone():
        raise HTTPException(409, '相关审核包正在生成，请等待完成后重试')
    db.execute(f"UPDATE review_batches SET expires=0 WHERE id IN {batches} AND status='ready'")
    db.execute(f'''CREATE TEMP TABLE target_suggestions AS SELECT id,attachment FROM review_suggestions
        WHERE image_id IN {exclusive} OR ((batch,image_id) IN affected_snapshots AND json_extract(payload,'$.kind')='correct_source'
        AND json_extract(payload,'$.post_id') IN (SELECT id FROM target_posts))''')
    db.execute('DELETE FROM review_result_keys WHERE suggestion IN (SELECT id FROM target_suggestions)')
    db.execute('DELETE FROM review_suggestions WHERE id IN (SELECT id FROM target_suggestions)')
    db.execute(f'DELETE FROM review_snapshots WHERE image_id IN {exclusive}')
    attachments = '(SELECT attachment FROM target_suggestions WHERE attachment IS NOT NULL)'
    db.execute(f'''DELETE FROM review_detections WHERE attachment IN {attachments} AND id NOT IN
        (SELECT detection_id FROM review_suggestions WHERE detection_id IS NOT NULL)''')
    db.execute(f'''DELETE FROM review_attachments WHERE digest IN {attachments} AND digest NOT IN
        (SELECT attachment FROM review_suggestions WHERE attachment IS NOT NULL) AND digest NOT IN (SELECT attachment FROM review_detections)''')
    removed = {image['id'] for image in images}
    keys = {row[0] for row in db.execute('SELECT post_key FROM target_posts')}
    for batch, image_id, raw in db.execute('SELECT * FROM review_snapshots WHERE (batch,image_id) IN affected_snapshots'):
        snapshot = json.loads(raw)
        snapshot['sources'] = [source for source in snapshot['sources']
                               if source['platform'] != platform or source['post_key'] not in keys]
        for field in ('member_ids', 'incomplete_image_ids'):
            snapshot[field] = [identifier for identifier in snapshot[field] if identifier not in removed]
        snapshot['members'] = [member for member in snapshot['members'] if member['id'] not in removed]
        snapshot['pending_feedback'] = [entry for entry in snapshot['pending_feedback'] if entry['image_id'] not in removed]
        db.execute('UPDATE review_snapshots SET snapshot=? WHERE batch=? AND image_id=?', (json.dumps(snapshot), batch, image_id))


def purge(db, platform):
    exclusive = '(SELECT id FROM target_images WHERE exclusive)'
    posts = '(SELECT id FROM target_posts)'
    faces = f'(SELECT id FROM faces WHERE image_id IN {exclusive})'
    if db.execute(f'''SELECT 1 FROM tasks WHERE status='running' AND
        (kind IN ('download','monitor','import') OR image_id IN {exclusive}) LIMIT 1''').fetchone():
        raise HTTPException(409, '下载、导入或相关图片任务正在运行，请等待完成后重试')
    images = db.execute(f'SELECT * FROM images WHERE id IN {exclusive}').fetchall()
    clean_reviews(db, platform, images)
    if images:
        db.execute('''INSERT INTO private_config VALUES('purged_image_id',?) ON CONFLICT(key) DO UPDATE SET
            value=max(CAST(private_config.value AS INTEGER),CAST(excluded.value AS INTEGER))''', (max(row['id'] for row in images),))
        originals = {row['sha256']: [] for row in images}
        for path in (storage.DATA / 'originals').iterdir():
            if path.stem in originals:
                originals[path.stem].append(path)
        for row in images:
            storage.queue_image_cleanup(db, row, originals[row['sha256']], thumbnail=True)
    for table in ('directory_items', 'tasks'):
        db.execute(f'DELETE FROM {table} WHERE image_id IN {exclusive}')
    db.execute(f'DELETE FROM download_items WHERE image_id IN {exclusive} OR (platform=? AND post_key IN (SELECT post_key FROM target_posts))', (platform,))
    db.execute('DELETE FROM download_item_errors WHERE platform=? AND post_key IN (SELECT post_key FROM target_posts)', (platform,))
    db.execute(f'DELETE FROM review_history WHERE face_id IN {faces}')
    db.execute(f'DELETE FROM duplicate_decisions WHERE a IN {exclusive} OR b IN {exclusive}')
    db.execute(f'DELETE FROM faces WHERE image_id IN {exclusive}')
    db.execute(f'DELETE FROM sources WHERE post_id IN {posts}')
    db.execute(f'DELETE FROM posts WHERE id IN {posts}')
    db.execute(f'DELETE FROM images WHERE id IN {exclusive}')
    db.execute('DELETE FROM daily_picks WHERE group_id IN dirty_groups AND NOT EXISTS(SELECT 1 FROM images WHERE group_id=daily_picks.group_id)')
    db.execute('DELETE FROM duplicate_groups WHERE id IN dirty_groups AND NOT EXISTS(SELECT 1 FROM images WHERE group_id=duplicate_groups.id)')


def install(app, admin):
    router = APIRouter(prefix='/api/v1/admin/publishers', dependencies=[Depends(admin)])

    @router.get('', response_model=PublisherPage)
    def list_publishers(platform: Platform, view: View = 'posts', search: str = '', page: int = Query(1, ge=1),
                        page_size: int = Query(30, ge=1, le=100)):
        params = {'platform': platform, 'search': search.strip().removeprefix('@')}
        with storage.connect() as db:
            db.execute('BEGIN')
            posts, rules = db.execute(LIST + 'SELECT count(*) FILTER (WHERE posts>0), count(*) FILTER (WHERE posts=0) FROM visible', params).fetchone()
            total = posts if view == 'posts' else rules
            page = min(page, max(1, (total + page_size - 1) // page_size))
            rows = db.execute(LIST + '''SELECT * FROM visible WHERE (posts>0)=:has_posts
                ORDER BY posts DESC,lower(label),lower(username) LIMIT :limit OFFSET :offset''',
                              {**params, 'has_posts': view == 'posts', 'limit': page_size, 'offset': (page-1)*page_size})
            return PublisherPage(items=[Publisher(**dict(row) | {'blocked': json.loads(row['blocked'] or '[]')}) for row in rows],
                                 posts_count=posts, rules_count=rules, page=page, page_size=page_size)

    def update_rules(platform, usernames, blocked):
        with storage.connect(True) as db:
            for username in sorted({name.lower() for name in usernames}):
                row, previous, linked = account(db, platform, username)
                if linked and not previous:
                    raise HTTPException(409, f'@{username} 已关联人物，请刷新列表')
                save_rule(db, platform, row, blocked)
        return BlockRule(blocked=blocked)

    @router.put('/{platform}/batch-rule', response_model=BlockRule)
    def batch_rule(platform: Platform, body: BatchRule):
        return update_rules(platform, body.usernames, body.blocked)

    @router.put('/{platform}/{username}/rule', response_model=BlockRule)
    def update_rule(platform: Platform, username: str, body: BlockRule):
        return update_rules(platform, [username], body.blocked)

    @router.post('/{platform}/batch-purge-preview', response_model=PurgePreview)
    def batch_preview(platform: Platform, body: PublisherSelection):
        with storage.connect() as db:
            db.execute('BEGIN')
            return scope(db, platform, body.usernames)[1]

    @router.get('/{platform}/{username}/purge-preview', response_model=PurgePreview)
    def purge_preview(platform: Platform, username: str):
        return batch_preview(platform, PublisherSelection(usernames=[username]))

    @router.post('/{platform}/batch-purge', response_model=PurgeResult)
    def batch_purge(platform: Platform, body: BatchPurge):
        with storage.connect(True) as db:
            rows, preview = scope(db, platform, body.usernames)
            if preview.scope_token != body.scope_token:
                raise HTTPException(409, '删除范围或规则已变化，请重新预览')
            if preview.references:
                raise HTTPException(409, '独占图片用作人物参考，请先移除对应参考')
            if body.blocked is not None:
                for row in rows:
                    save_rule(db, platform, row, body.blocked)
            purge(db, platform)
        return {'posts': preview.posts, 'cleanup_pending': storage.cleanup_deleted_files()}

    @router.post('/{platform}/{username}/purge', response_model=PurgeResult)
    def purge_posts(platform: Platform, username: str, body: PurgeRequest):
        return batch_purge(platform, BatchPurge(usernames=[username], **body.model_dump()))

    app.include_router(router)
