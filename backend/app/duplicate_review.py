def scope_sql(groups):
    if not groups:
        return '', 'duplicate_decisions'
    marks = ','.join('?' for _ in groups)
    return f'''WITH members AS (SELECT id FROM images WHERE group_id IN ({marks})),
        scoped AS (SELECT d.* FROM members m CROSS JOIN duplicate_decisions d ON d.a=m.id
        UNION SELECT d.* FROM members m CROSS JOIN duplicate_decisions d ON d.b=m.id) ''', 'scoped'


def joined(decisions):
    return f'''FROM {decisions} d CROSS JOIN images l NOT INDEXED ON l.id=d.a
        CROSS JOIN images r NOT INDEXED ON r.id=d.b'''


def pending_sql(decisions):
    members = joined(decisions)
    first_group, second_group = 'min(l.group_id,r.group_id)', 'max(l.group_id,r.group_id)'
    return f'''SELECT * FROM (SELECT d.*, {first_group} AS first_id, {second_group} AS second_id,
        row_number() OVER (PARTITION BY {first_group},{second_group} ORDER BY score DESC,a,b) AS rank
        {members} LEFT JOIN (
            SELECT DISTINCT {first_group} AS first_id,{second_group} AS second_id
            {members} WHERE decision='separate'
        ) rejected ON rejected.first_id={first_group} AND rejected.second_id={second_group}
        WHERE decision='pending' AND (score IS NULL OR score>=?) AND rejected.first_id IS NULL
        AND l.hidden=0 AND r.hidden=0 AND l.group_id<>r.group_id) WHERE rank=1'''
