"""Transactional group indexes shared by the API and worker."""

REVIEW_FLAGS = ('review', 'unknown', 'no_faces', 'failed', 'pending', 'incomplete', 'feedback', 'repeated_person')
REPEATED_PERSON_SQL = '''EXISTS(SELECT 1 FROM faces WHERE image_id=representative AND ignored=0
    AND person_id IS NOT NULL GROUP BY person_id HAVING count(*) > 1)'''
SCOPES = ('public', 'review')
GAME_FACE_SCORE = '''CASE WHEN length(f.embedding)>0 THEN (SELECT json_extract(candidate.value,'$.score')
    FROM json_each(f.candidates) candidate WHERE json_extract(candidate.value,'$.person_id')=f.person_id) END'''


def install_game_scores(db):
    if 'game_score' not in {row[1] for row in db.execute('PRAGMA table_info(public_group_people)')}:
        db.execute('ALTER TABLE public_group_people ADD COLUMN game_score REAL')
        db.execute(f'''UPDATE public_group_people AS who SET game_score=(SELECT max({GAME_FACE_SCORE})
            FROM public_groups g JOIN faces f ON f.image_id=g.representative WHERE g.group_id=who.group_id
            AND f.person_id=who.person_id AND f.ignored=0)''')
    db.execute('''CREATE INDEX IF NOT EXISTS public_game_people ON public_group_people(person_id,game_score,group_id)
        WHERE game_score IS NOT NULL''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS dirty_game_score AFTER UPDATE OF embedding,candidates ON faces
        WHEN OLD.embedding IS NOT NEW.embedding OR OLD.candidates IS NOT NEW.candidates BEGIN
        INSERT OR IGNORE INTO dirty_groups SELECT group_id FROM images WHERE id=NEW.image_id; END''')


def install(db):
    db.execute('CREATE TABLE IF NOT EXISTS dirty_groups(group_id INTEGER PRIMARY KEY)')
    db.execute('''CREATE TABLE IF NOT EXISTS public_groups(group_id INTEGER PRIMARY KEY,
        representative INTEGER NOT NULL, has_face INTEGER NOT NULL, first_post INTEGER NOT NULL, stamp TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS review_groups(group_id INTEGER PRIMARY KEY,
        representative INTEGER NOT NULL, ''' + ','.join(f'{flag} INTEGER NOT NULL' for flag in REVIEW_FLAGS) + ')')
    for scope in SCOPES:
        for kind, key in [('people', 'person_id'), ('posts', 'post_id')]:
            table = f'{scope}_group_{kind}'
            db.execute(f'''CREATE TABLE IF NOT EXISTS {table}(group_id INTEGER, {key} INTEGER,
                PRIMARY KEY(group_id,{key})) WITHOUT ROWID''')
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_reverse ON {table}({key},group_id)')
    install_game_scores(db)
    db.execute('CREATE INDEX IF NOT EXISTS public_group_date ON public_groups(stamp,group_id)')
    db.execute('CREATE INDEX IF NOT EXISTS public_face_date ON public_groups(stamp,group_id) WHERE has_face=1')
    for flag in REVIEW_FLAGS:
        db.execute(f'CREATE INDEX IF NOT EXISTS review_group_{flag} ON review_groups(group_id) WHERE {flag}=1')
    db.execute('CREATE INDEX IF NOT EXISTS source_image_post ON sources(image_id,post_id)')
    db.execute('CREATE INDEX IF NOT EXISTS source_post_image ON sources(post_id,image_id)')
    db.execute('CREATE INDEX IF NOT EXISTS publisher_date ON posts(platform,lower(author),published_at,id)')
    db.execute('CREATE INDEX IF NOT EXISTS decision_pairs ON duplicate_decisions(decision,a,b,score)')

    image_group = 'SELECT group_id FROM images WHERE id={row}.image_id'
    for table, columns, groups in (
        ('images', ('group_id', 'file_size', 'hidden', 'detection'), 'SELECT {row}.group_id WHERE true'),
        ('sources', ('image_id', 'post_id'), image_group),
        ('faces', ('image_id', 'person_id', 'ignored', 'locked'), image_group),
        ('feedback', ('image_id', 'status'), image_group),
        ('posts', ('author', 'published_at', 'url'),
         'SELECT i.group_id FROM sources s JOIN images i ON i.id=s.image_id WHERE s.post_id={row}.id'),
    ):
        for event, timing, rows in [('insert', 'AFTER', ('NEW',)), ('delete', 'BEFORE', ('OLD',)),
                                    ('update', 'AFTER', ('OLD', 'NEW'))]:
            if table == 'posts' and event == 'insert':
                continue
            operation = event
            condition = ''
            if event == 'update':
                operation += ' OF ' + ','.join(columns)
                condition = 'WHEN ' + ' OR '.join(f'OLD.{column} IS NOT NEW.{column}' for column in columns)
                if table == 'posts':
                    rows = ('NEW',)
            mark = ' '.join('INSERT INTO dirty_groups ' + groups.format(row=row) +
                            ' ON CONFLICT(group_id) DO NOTHING;' for row in rows)
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS dirty_{table}_{event} {timing} {operation} ON {table}
                {condition} BEGIN {mark} END''')
    db.execute('INSERT OR IGNORE INTO dirty_groups SELECT id FROM duplicate_groups')
    refresh(db)
    from .representatives import complete_source_sql
    for scope in SCOPES:
        eligible = "AND i.detection='done' AND " + complete_source_sql('i') if scope == 'public' else ''
        expected = db.execute(f'SELECT count(DISTINCT group_id) FROM images i WHERE hidden=0 {eligible}').fetchone()[0]
        if db.execute(f'SELECT count(*) FROM {scope}_groups').fetchone()[0] != expected:
            raise RuntimeError(f'Incomplete {scope} group index backfill')
    db.execute('ANALYZE')


def refresh(db):
    if not db.execute('SELECT 1 FROM dirty_groups LIMIT 1').fetchone():
        return
    from .representatives import complete_source_sql, representative_sql

    for scope in SCOPES:
        for table in (f'{scope}_groups', f'{scope}_group_posts', f'{scope}_group_people'):
            db.execute(f'DELETE FROM {table} WHERE group_id IN (SELECT group_id FROM dirty_groups)')
        public = scope == 'public'
        eligible = "AND i.detection='done' AND p.author IS NOT NULL AND p.published_at IS NOT NULL AND p.url IS NOT NULL" if public else ''
        post_join = 'CROSS JOIN posts p ON p.id=s.post_id' if public else ''
        db.execute(f'''INSERT INTO {scope}_group_posts SELECT DISTINCT d.group_id,s.post_id
            FROM dirty_groups d CROSS JOIN images i ON i.group_id=d.group_id CROSS JOIN sources s ON s.image_id=i.id
            {post_join} WHERE i.hidden=0 {eligible}''')
        reps = f'''WITH reps AS MATERIALIZED (SELECT group_id,{representative_sql('d.group_id', public=public)} representative
            FROM dirty_groups d)'''
        if public:
            db.execute(reps + ''' , firsts AS MATERIALIZED (SELECT reps.*,(SELECT p.id FROM public_group_posts link
                CROSS JOIN posts p ON p.id=link.post_id WHERE link.group_id=reps.group_id
                ORDER BY p.published_at,p.id LIMIT 1) first_post FROM reps WHERE representative IS NOT NULL)
                INSERT INTO public_groups SELECT firsts.group_id,representative,
                EXISTS(SELECT 1 FROM faces WHERE image_id=representative AND ignored=0),p.id,p.published_at
                FROM firsts CROSS JOIN posts p ON p.id=first_post''')
        else:
            db.execute(reps + f''', flags AS MATERIALIZED (SELECT reps.*,i.detection,
                NOT EXISTS(SELECT 1 FROM faces WHERE image_id=representative) AS empty,
                EXISTS(SELECT 1 FROM faces WHERE image_id=representative AND ignored=0 AND locked=0) AS unlocked,
                EXISTS(SELECT 1 FROM faces WHERE image_id=representative AND ignored=0 AND locked=0 AND person_id IS NULL) AS unknown,
                {REPEATED_PERSON_SQL} AS repeated_person,
                NOT EXISTS(SELECT 1 FROM faces WHERE image_id=representative AND ignored=0) AS no_active,
                EXISTS(SELECT 1 FROM images m WHERE m.group_id=reps.group_id AND m.hidden=0 AND NOT {complete_source_sql('m')}) AS incomplete,
                EXISTS(SELECT 1 FROM images m JOIN feedback f ON f.image_id=m.id WHERE m.group_id=reps.group_id AND m.hidden=0 AND f.status='pending') AS feedback
                FROM reps CROSS JOIN images i ON i.id=representative)
                INSERT INTO review_groups SELECT group_id,representative,
                detection IN ('pending','failed') OR empty OR unlocked OR incomplete OR feedback OR repeated_person,unknown,
                detection='done' AND no_active,detection='failed',detection='pending',incomplete,feedback,
                repeated_person FROM flags''')
        score = f',max({GAME_FACE_SCORE})' if public else ''
        db.execute(f'''INSERT INTO {scope}_group_people SELECT d.group_id,f.person_id{score} FROM dirty_groups d
            CROSS JOIN {scope}_groups g ON g.group_id=d.group_id CROSS JOIN faces f ON f.image_id=g.representative
            WHERE f.ignored=0 AND f.person_id IS NOT NULL GROUP BY d.group_id,f.person_id''')
    db.execute('DELETE FROM dirty_groups')
