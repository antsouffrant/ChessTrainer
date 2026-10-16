"""Persistent ratings and filterable feedback reporting.

Ratings are *latest per item*: one (position, category) vote or one chat
message vote. Re-voting updates the row rather than inflating sample sizes.
"""
from __future__ import annotations

import csv
import io

RATING_KINDS = ('position', 'explanation', 'motif', 'coaching')
POSITION_KINDS = RATING_KINDS[:3]


def position_votes(conn, position_id):
    return {row['category']: row['rating'] for row in conn.execute(
        'SELECT category, rating FROM position_feedback WHERE position_id = ?', (position_id,)
    )}


def record_position_vote(conn, position_id, category, rating, lesson_key='', text=''):
    if category not in POSITION_KINDS or rating not in (-1, 1):
        raise ValueError('Invalid feedback category or rating')
    row = conn.execute('''
        SELECT tp.id, tp.learned, j.account_id, tp.coaching_version,
               tp.coach_explanation, tp.opening_key,
               pc.concept_key AS primary_concept_key, lc.name AS primary_concept_name
        FROM training_positions tp
        JOIN analysis_jobs j ON j.id = tp.job_id
        LEFT JOIN position_concepts pc ON pc.position_id = tp.id AND pc.is_primary = 1
        LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
        WHERE tp.id = ?
    ''', (position_id,)).fetchone()
    if row is None:
        raise LookupError('Position not found')
    if not row['learned']:
        raise PermissionError('Solve the position before submitting feedback')
    # Persist the actual displayed explanation for longitudinal QA. The browser
    # may have shown a legal near-optimal alternative instead of the default.
    snapshot = str(text or row['coach_explanation'] or '').strip()[:6000] if category == 'explanation' else (row['primary_concept_name'] or '') if category == 'motif' else ''
    lesson = str(lesson_key or '').strip()[:150]
    if lesson and not conn.execute('SELECT 1 FROM learning_concepts WHERE key = ?', (lesson,)).fetchone():
        lesson = ''
    conn.execute('''
        INSERT INTO position_feedback
          (position_id, account_id, category, rating, lesson_key, primary_motif_key,
           content_snapshot, coaching_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(position_id, category) DO UPDATE SET
            rating = excluded.rating, lesson_key = excluded.lesson_key,
            primary_motif_key = excluded.primary_motif_key,
            content_snapshot = excluded.content_snapshot,
            coaching_version = excluded.coaching_version,
            updated_at = CURRENT_TIMESTAMP
    ''', (position_id, row['account_id'], category, rating, lesson,
          row['primary_concept_key'], snapshot, row['coaching_version']))
    conn.commit()
    return position_votes(conn, position_id)


# A single record model across the three position votes and chat ratings.
# The lesson is the selected lesson when provided, otherwise the primary motif.
REPORT_SQL = '''
WITH primary_motifs AS (
  SELECT pc.position_id, pc.concept_key AS key, lc.name
  FROM position_concepts pc
  LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
  WHERE pc.is_primary = 1
), votes AS (
  SELECT pf.position_id, NULL AS message_id, pf.category AS feedback_type,
         pf.rating, pf.lesson_key, pf.primary_motif_key AS voted_motif_key,
         pf.content_snapshot, pf.coaching_version,
         pf.created_at, pf.updated_at
  FROM position_feedback pf
  UNION ALL
  SELECT cf.position_id, cf.message_id, 'coaching', cf.rating,
         cf.lesson_key, NULL, cm.content, NULL, cf.created_at, cf.updated_at
  FROM coach_message_feedback cf
  LEFT JOIN coach_messages cm ON cm.id = cf.message_id
)
SELECT v.feedback_type, v.rating, v.created_at, v.updated_at,
       v.position_id, v.message_id, v.content_snapshot, v.coaching_version,
       tp.job_id, tp.game_id, tp.game_date, tp.opponent,
       tp.learning_mode, tp.category AS position_category, tp.move_number,
       tp.opening_key, tp.opening_name, tp.opening_variation, tp.opening_eco,
       tp.estimated_rating, tp.learned, j.date_range, j.source_type, j.source_username,
       a.username, a.provider,
       COALESCE(NULLIF(v.lesson_key, ''), v.voted_motif_key, pm.key, '') AS lesson_key,
       COALESCE(lesson.name, '') AS lesson_name,
       COALESCE(v.voted_motif_key, pm.key, '') AS primary_motif_key,
       COALESCE(voted_motif.name, pm.name, '') AS primary_motif_name
FROM votes v
JOIN training_positions tp ON tp.id = v.position_id
JOIN analysis_jobs j ON j.id = tp.job_id
JOIN accounts a ON a.id = j.account_id
LEFT JOIN primary_motifs pm ON pm.position_id = tp.id
LEFT JOIN learning_concepts lesson ON lesson.key = COALESCE(NULLIF(v.lesson_key, ''), v.voted_motif_key, pm.key)
LEFT JOIN learning_concepts voted_motif ON voted_motif.key = v.voted_motif_key
'''
FILTERS = ('job_id', 'lesson_key', 'opening_key', 'primary_motif_key', 'learning_mode', 'feedback_type', 'rating')


def report_rows(conn, filters=None):
    filters = filters or {}
    clauses, params = [], []
    for name in FILTERS:
        value = str(filters.get(name) or '').strip()
        if not value:
            continue
        if name == 'job_id':
            if not value.isdecimal():
                continue
            params.append(int(value))
        elif name == 'rating':
            if value not in ('1', '-1'):
                continue
            params.append(int(value))
        elif name == 'feedback_type':
            if value not in RATING_KINDS:
                continue
            params.append(value)
        else:
            params.append(value[:150])
        clauses.append(f'voted.{name} = ?')
    sql = 'SELECT * FROM (' + REPORT_SQL + ') AS voted'
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY voted.updated_at DESC, voted.position_id DESC, voted.message_id DESC'
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def report_facets(conn):
    jobs = [dict(row) for row in conn.execute('''
        SELECT j.id AS value, a.username || ' · ' || j.date_range || ' (#' || j.id || ')' AS label
        FROM analysis_jobs j JOIN accounts a ON a.id = j.account_id
        ORDER BY j.id DESC
    ''')]
    lessons = [dict(row) for row in conn.execute('''
        SELECT DISTINCT lc.key AS value, lc.name AS label
        FROM learning_concepts lc JOIN position_concepts pc ON pc.concept_key = lc.key
        ORDER BY lc.name
    ''')]
    openings = [dict(row) for row in conn.execute('''
        SELECT opening_key AS value, COALESCE(MAX(NULLIF(opening_name, '')), opening_key) AS label
        FROM training_positions WHERE opening_key IS NOT NULL AND opening_key != ''
        GROUP BY opening_key ORDER BY label
    ''')]
    return {'game_lists': jobs, 'lessons': lessons, 'openings': openings,
            'motifs': lessons,
            'learning_modes': [{'value': row['learning_mode'], 'label': row['learning_mode'].replace('_', ' ').title()}
                               for row in conn.execute('SELECT DISTINCT learning_mode FROM training_positions WHERE learning_mode IS NOT NULL ORDER BY learning_mode')]}


def _stats(rows):
    positive = sum(1 for row in rows if row['rating'] == 1)
    return {'total': len(rows), 'up': positive, 'down': len(rows)-positive,
            'up_pct': round(100 * positive / len(rows), 1) if rows else None}


def report_summary(rows):
    by_kind = {name: _stats([r for r in rows if r['feedback_type'] == name]) for name in RATING_KINDS}
    def breakdown(field):
        names = {}
        groups = {}
        for row in rows:
            key = row.get(field) or ''
            if not key:
                continue
            names[key] = row.get(field.replace('_key', '_name')) or key
            groups.setdefault(key, []).append(row)
        return sorted(({'key': key, 'name': names[key], **_stats(items)} for key, items in groups.items()),
                      key=lambda x: (-x['total'], x['name'].lower()))[:30]
    return {'overall': _stats(rows), 'categories': by_kind,
            'by_motif': breakdown('primary_motif_key'),
            'by_opening': breakdown('opening_key'),
            'by_lesson': breakdown('lesson_key')}


EXPORT_COLUMNS = [
    'feedback_type', 'rating', 'created_at', 'updated_at', 'position_id', 'message_id',
    'job_id', 'username', 'provider', 'date_range', 'source_type', 'source_username',
    'game_id', 'game_date', 'opponent', 'learning_mode', 'position_category',
    'move_number', 'lesson_key', 'lesson_name', 'primary_motif_key', 'primary_motif_name',
    'opening_key', 'opening_name', 'opening_variation', 'opening_eco',
    'estimated_rating', 'learned', 'coaching_version', 'content_snapshot',
]


def csv_bytes(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Spreadsheet-safe CSV: escape text that looks like a formula.
        item = {}
        for col in EXPORT_COLUMNS:
            val = row.get(col)
            if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                val = "'" + val
            item[col] = val if val is not None else ''
        writer.writerow(item)
    return output.getvalue().encode('utf-8-sig')
