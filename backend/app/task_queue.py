from typing import Literal


Subtype = Literal['post', 'account', 'list', 'monitor_scheduled', 'monitor_now', 'monitor_initial',
                  'monitor_backfill', 'monitor', 'auto', 'highres', 'unknown', 'all_faces', 'import', 'restore', 'avatar']
Tier = Literal['avatar', 'single', 'scheduled', 'bulk', 'maintenance']
TIERS = ('avatar', 'single', 'scheduled', 'bulk', 'maintenance')
NEXT_RANK = "(SELECT coalesce(max(queue_rank_at),0)+1 FROM tasks WHERE status='queued')"
COMPUTE = "kind IN ('detect','rematch')"


def priority(column):
    return 'CASE ' + column + ' ' + ' '.join(f"WHEN '{tier}' THEN {rank}" for rank, tier in enumerate(TIERS)) + ' END'


def migrate(db, columns):
    inferred = """CASE subtype WHEN 'avatar' THEN 'avatar' WHEN 'post' THEN 'single'
        WHEN 'restore' THEN 'single' WHEN 'highres' THEN 'single' WHEN 'all_faces' THEN 'single'
        WHEN 'unknown' THEN 'maintenance' WHEN 'monitor_scheduled' THEN 'scheduled'
        WHEN 'monitor_now' THEN 'scheduled' ELSE 'bulk' END"""
    if 'tier' not in columns:
        db.execute('''ALTER TABLE tasks ADD COLUMN subtype TEXT GENERATED ALWAYS AS (CASE kind
            WHEN 'download' THEN CASE
                WHEN json_extract(payload,'$.url') GLOB '*/i/lists/*' THEN 'list'
                WHEN json_extract(payload,'$.url') GLOB '*x.com/*/status/*'
                  OR json_extract(payload,'$.url') GLOB '*twitter.com/*/status/*'
                  OR json_extract(payload,'$.url') GLOB '*instagram.com/p/*'
                  OR json_extract(payload,'$.url') GLOB '*instagram.com/reel/*'
                  OR json_extract(payload,'$.url') GLOB '*instagram.com/tv/*' THEN 'post' ELSE 'account' END
            WHEN 'monitor' THEN CASE WHEN json_extract(payload,'$.mode')='backfill' THEN 'monitor_backfill'
                ELSE coalesce(json_extract(payload,'$.trigger'),'monitor') END
            WHEN 'detect' THEN CASE WHEN json_extract(payload,'$.mode')='highres' THEN 'highres' ELSE 'auto' END
            WHEN 'rematch' THEN CASE WHEN json_extract(payload,'$.refresh_all') THEN 'all_faces' ELSE 'unknown' END
            ELSE kind END) VIRTUAL''')
        db.execute('ALTER TABLE tasks ADD COLUMN tier TEXT')
        db.execute(f'UPDATE tasks SET tier={inferred}')
        db.execute("UPDATE tasks SET queue_rank_at=queue_rank_at-300 WHERE status='queued' AND rounds>0")
        db.execute('DROP TRIGGER IF EXISTS task_queue_rank')
        for index in ('task_queue', 'task_compute_queue', 'task_io_queue'):
            db.execute(f'DROP INDEX IF EXISTS {index}')
    elif db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='task_default_tier'").fetchone():
        db.execute('DROP TRIGGER task_default_tier')
        db.execute("UPDATE tasks SET tier='scheduled' WHERE subtype='monitor_now' AND tier='bulk' AND status IN ('queued','running')")
    db.execute(f'''CREATE TRIGGER IF NOT EXISTS task_infer_tier AFTER INSERT ON tasks WHEN NEW.tier IS NULL BEGIN
        UPDATE tasks SET tier={inferred} WHERE id=NEW.id; END''')
    db.execute("CREATE INDEX IF NOT EXISTS task_queue_tail ON tasks(queue_rank_at) WHERE status='queued'")
    db.execute(f'''CREATE TRIGGER IF NOT EXISTS task_queue_rank AFTER INSERT ON tasks
        WHEN NEW.queue_rank_at IS NULL AND NEW.status='queued' BEGIN
        UPDATE tasks SET queue_rank_at={NEXT_RANK} WHERE id=NEW.id; END''')
    db.execute(f"CREATE INDEX IF NOT EXISTS task_io_queue ON tasks(({priority('tier')}),queue_rank_at,id) WHERE status='queued' AND NOT ({COMPUTE})")
    db.execute(f"CREATE INDEX IF NOT EXISTS task_compute_queue ON tasks(({priority('tier')}),(kind='rematch') DESC,id) WHERE status='queued' AND {COMPUTE}")
    db.execute("CREATE INDEX IF NOT EXISTS task_single_redetect ON tasks(image_id,id) WHERE status='queued' AND kind='detect' AND tier='single' AND subtype='highres'")
    db.execute("CREATE INDEX IF NOT EXISTS task_image_queue ON tasks(image_id,id) WHERE status IN ('queued','running')")
    db.execute('''CREATE TABLE IF NOT EXISTS directory_items(task_id INTEGER REFERENCES tasks ON DELETE CASCADE,
        path TEXT, image_id INTEGER REFERENCES images, PRIMARY KEY(task_id,path,image_id)) WITHOUT ROWID''')
    db.execute('''CREATE TRIGGER IF NOT EXISTS directory_done AFTER UPDATE OF status ON tasks
        WHEN NEW.kind='import' AND NEW.status='done' BEGIN DELETE FROM directory_items WHERE task_id=NEW.id; END''')
