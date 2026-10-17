"""Persistent ratings and filterable feedback reporting.

Ratings are *latest per item*: one (position, category) vote or one chat
message vote. Re-voting updates the row rather than inflating sample sizes.
"""
from __future__ import annotations

import csv
import io
import hashlib

RATING_KINDS = ('position', 'explanation', 'motif', 'coaching')
POSITION_KINDS = RATING_KINDS[:3]


def position_votes(conn, position_id):
    return {row['category']: row['rating'] for row in conn.execute(
        'SELECT category, rating FROM position_feedback WHERE position_id = ?', (position_id,)
    )}


def position_feedback_details(conn, position_id):
    return {row['category']: {'suggested_text': row['suggested_text'] or '',
                              'suggested_motif_key': row['suggested_motif_key'] or ''}
            for row in conn.execute('''SELECT category, suggested_text, suggested_motif_key
                                       FROM position_feedback WHERE position_id=?''', (position_id,))}


def motif_feedback_options(conn, position_id=None):
    """Return built-in and relevant personal motifs, never retired labels."""
    return [dict(row) for row in conn.execute('''
        SELECT lc.key, lc.name, lc.family FROM learning_concepts lc
        WHERE lc.key != 'candidate_evaluation' AND lc.status != 'retired'
          AND (lc.source = 'built_in' OR (lc.status IN ('personal','promoted')
               AND (lc.account_id IS NULL OR lc.account_id = (
                   SELECT j.account_id FROM training_positions tp
                   JOIN analysis_jobs j ON j.id = tp.job_id WHERE tp.id = ?))))
        ORDER BY lc.name COLLATE NOCASE, lc.family COLLATE NOCASE, lc.key''', (position_id,))]


def record_position_vote(conn, position_id, category, rating, lesson_key='', text='',
                         suggested_text=None, suggested_motif_key=None):
    if category not in POSITION_KINDS or rating not in (-1, 0, 1):
        raise ValueError('Invalid feedback category or rating')
    if suggested_text is not None:
        if not isinstance(suggested_text, str) or len(suggested_text) > 6000:
            raise ValueError('Correction must be text of at most 6000 characters')
        if category == 'motif':
            raise ValueError('Select a replacement motif instead of text')
        suggested_text = suggested_text.strip()
    if suggested_motif_key is not None:
        if category != 'motif' or not isinstance(suggested_motif_key, str):
            raise ValueError('Replacement motif is only valid for motif feedback')
        if suggested_motif_key and not any(o['key'] == suggested_motif_key for o in motif_feedback_options(conn, position_id)):
            raise ValueError('Choose a valid learning motif')
    if rating == 1:
        suggested_text = None
        suggested_motif_key = None
    row = conn.execute('''
        SELECT tp.id, tp.learned, j.account_id, tp.coaching_version,
               tp.coach_explanation, tp.opening_key,
               pc.concept_key AS primary_concept_key, lc.name AS primary_concept_name,
               pc.classifier_version AS classifier_version_at_vote
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
    if rating == 0:
        # Unchecking a selected thumb withdraws both the vote and its correction.
        # A withdrawn rating must not appear in aggregates or regression exports.
        conn.execute('DELETE FROM position_feedback WHERE position_id = ? AND category = ?',
                     (position_id, category))
        conn.commit()
        return position_votes(conn, position_id)
    # Persist the actual displayed explanation for longitudinal QA. The browser
    # may have shown a legal near-optimal alternative instead of the default.
    snapshot = str(text or row['coach_explanation'] or '').strip()[:6000] if category == 'explanation' else (row['primary_concept_name'] or '') if category == 'motif' else ''
    lesson = str(lesson_key or '').strip()[:150]
    if lesson and not conn.execute('SELECT 1 FROM learning_concepts WHERE key = ?', (lesson,)).fetchone():
        lesson = ''
    conn.execute('''
        INSERT INTO position_feedback
          (position_id, account_id, category, rating, lesson_key, primary_motif_key,
           content_snapshot, coaching_version, classifier_version_at_vote,
           suggested_text, suggested_motif_key)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(position_id, category) DO UPDATE SET
            rating = excluded.rating, lesson_key = excluded.lesson_key,
            primary_motif_key = excluded.primary_motif_key,
            content_snapshot = excluded.content_snapshot,
            coaching_version = excluded.coaching_version,
            classifier_version_at_vote = excluded.classifier_version_at_vote,
            suggested_text = CASE
                WHEN excluded.rating = 1 THEN NULL
                WHEN excluded.suggested_text IS NOT NULL THEN excluded.suggested_text
                WHEN position_feedback.rating = -1 THEN position_feedback.suggested_text
                ELSE NULL END,
            suggested_motif_key = CASE
                WHEN excluded.rating = 1 THEN NULL
                WHEN excluded.suggested_motif_key IS NOT NULL THEN excluded.suggested_motif_key
                WHEN position_feedback.rating = -1 THEN position_feedback.suggested_motif_key
                ELSE NULL END,
            updated_at = CURRENT_TIMESTAMP
    ''', (position_id, row['account_id'], category, rating, lesson,
          row['primary_concept_key'], snapshot, row['coaching_version'],
          row['classifier_version_at_vote'], suggested_text, suggested_motif_key))
    conn.commit()
    return position_votes(conn, position_id)


# A single record model across the three position votes and chat ratings.
# The lesson is the selected lesson when provided, otherwise the primary motif.
REPORT_SQL = '''
WITH primary_motifs AS (
  SELECT pc.position_id, pc.concept_key AS key, lc.name, pc.confidence, pc.evidence, pc.classifier_version
  FROM position_concepts pc
  LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
  WHERE pc.is_primary = 1
), votes AS (
  SELECT pf.position_id, NULL AS message_id, pf.category AS feedback_type,
         pf.rating, pf.lesson_key, pf.primary_motif_key AS voted_motif_key,
         pf.content_snapshot, pf.coaching_version, pf.classifier_version_at_vote,
         pf.suggested_text, pf.suggested_motif_key,
         NULL AS chat_user_message, NULL AS chat_structured_json,
         pf.created_at, pf.updated_at
  FROM position_feedback pf
  UNION ALL
  SELECT cf.position_id, cf.message_id, 'coaching', cf.rating,
         cf.lesson_key, NULL, cm.content, NULL, NULL,
         cf.suggested_text, NULL,
         (SELECT question.content FROM coach_messages question
          WHERE question.thread_id = cm.thread_id AND question.role = 'user'
            AND question.id < cm.id ORDER BY question.id DESC LIMIT 1),
         cm.structured_json, cf.created_at, cf.updated_at
  FROM coach_message_feedback cf
  LEFT JOIN coach_messages cm ON cm.id = cf.message_id
)
SELECT v.feedback_type, v.rating, v.created_at, v.updated_at,
       v.position_id, v.message_id, v.content_snapshot, v.coaching_version,
       v.classifier_version_at_vote, v.chat_user_message, v.chat_structured_json,
       v.suggested_text, v.suggested_motif_key, suggested_motif.name AS suggested_motif_name,
       tp.coaching_version AS current_coaching_version,
       tp.coach_prompt, tp.coach_explanation AS current_explanation,
       tp.fen, tp.previous_fen, tp.user_color,
       tp.opponent_move_uci, tp.opponent_move_san,
       tp.played_move_uci, tp.played_move_san,
       tp.best_move_uci, tp.best_move_san,
       tp.eval_before_cp, tp.eval_after_cp, tp.centipawn_loss,
       tp.mate_before, tp.mate_after,
       tp.best_pv_uci, tp.played_pv_uci, tp.alternative_pvs_json,
       tp.critical_events_json, tp.explanatory_lines_json,
       tp.difficulty_score, tp.difficulty_version,
       tp.analysis_pass, tp.analysis_screen_depth, tp.analysis_deep_depth,
       tp.attempts, tp.correct_attempts, tp.created_at AS position_created_at,
       pm.key AS current_primary_motif_key,
       pm.name AS current_primary_motif_name,
       pm.confidence AS current_primary_motif_confidence,
       pm.evidence AS current_primary_motif_evidence,
       pm.classifier_version AS current_classifier_version,
       v.voted_motif_key AS motif_at_vote_key,
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
LEFT JOIN learning_concepts suggested_motif ON suggested_motif.key = v.suggested_motif_key
'''
FILTERS = ('job_id', 'lesson_key', 'opening_key', 'primary_motif_key', 'learning_mode', 'feedback_type', 'rating', 'coaching_version', 'position_category')


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
    categories = [{'value': row['category'],
                   'label': row['category'].replace('_', ' ').title()}
                  for row in conn.execute('''
        SELECT DISTINCT category FROM training_positions ORDER BY category
    ''')]
    versions = [dict(row) for row in conn.execute('''
        SELECT DISTINCT coaching_version AS value, coaching_version AS label
        FROM training_positions WHERE coaching_version IS NOT NULL AND coaching_version != ''
        ORDER BY coaching_version DESC
    ''')]
    return {'game_lists': jobs, 'lessons': lessons, 'openings': openings,
            'motifs': lessons, 'coaching_versions': versions,
            'position_categories': categories,
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
            'by_lesson': breakdown('lesson_key'),
            'by_coaching_version': breakdown('coaching_version')}


# Stable machine-readable schema for coaching development. One row per latest
# rating; IDs permit joining multiple ratings on one position, and at-vote
# snapshots remain separate from the CURRENT regenerated coach and motifs.
EXPORT_COLUMNS = [
    'feedback_type', 'feedback_question', 'rating', 'rating_label',
    'regression_case_id', 'regression_candidate', 'review_status',
    'created_at', 'updated_at', 'position_id', 'message_id',
    'position_url', 'job_id', 'username', 'provider', 'date_range',
    'source_type', 'source_username', 'game_id', 'game_date', 'opponent',
    'learning_mode', 'position_category', 'move_number', 'user_color',
    'lesson_key', 'lesson_name', 'motif_at_vote_key',
    'primary_motif_key', 'primary_motif_name', 'current_primary_motif_key',
    'current_primary_motif_name', 'current_primary_motif_confidence',
    'current_primary_motif_evidence', 'current_classifier_version',
    'classifier_version_at_vote', 'opening_key', 'opening_name', 'opening_variation', 'opening_eco',
    'estimated_rating', 'difficulty_score', 'difficulty_version',
    'learned', 'attempts', 'correct_attempts', 'position_created_at',
    'fen', 'previous_fen', 'opponent_move_uci', 'opponent_move_san',
    'played_move_uci', 'played_move_san', 'best_move_uci', 'best_move_san',
    'eval_before_cp', 'eval_after_cp', 'centipawn_loss',
    'mate_before', 'mate_after', 'best_pv_uci', 'played_pv_uci',
    'alternative_pvs_json', 'critical_events_json', 'explanatory_lines_json',
    'analysis_pass', 'analysis_screen_depth', 'analysis_deep_depth',
    'coaching_version', 'current_coaching_version', 'coach_prompt',
    'content_snapshot', 'suggested_text', 'suggested_motif_key', 'suggested_motif_name',
    'current_explanation', 'chat_user_message',
    'chat_structured_json',
]

FEEDBACK_QUESTIONS = {
    'position': 'Is this training position helpful?',
    'explanation': 'Is this explanation helpful?',
    'motif': 'Does the primary learning motif fit this position?',
    'coaching': 'Is this chat coaching response helpful?',
}


def is_regression_candidate(row):
    return row.get('rating') == -1 and bool(
        str(row.get('suggested_text') or '').strip() or
        str(row.get('suggested_motif_key') or '').strip())


def regression_candidate_rows(rows):
    return [row for row in rows if is_regression_candidate(row)]


def csv_bytes(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=EXPORT_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Spreadsheet-safe CSV: escape text that looks like a formula.
        item = {}
        for col in EXPORT_COLUMNS:
            if col == 'feedback_question':
                val = FEEDBACK_QUESTIONS.get(row.get('feedback_type'), '')
            elif col == 'rating_label':
                val = 'thumbs_up' if row.get('rating') == 1 else 'thumbs_down'
            elif col == 'regression_case_id':
                # FEN + played move + feedback kind persist across engine revisions.
                # Chat examples additionally distinguish their question/response.
                signature = '|'.join(str(row.get(key) or '') for key in
                                     ('feedback_type', 'fen', 'played_move_uci'))
                if row.get('feedback_type') == 'coaching':
                    signature += '|' + '|'.join(str(row.get(k) or '') for k in
                                                ('chat_user_message', 'content_snapshot'))
                val = hashlib.sha256(signature.encode('utf-8')).hexdigest()[:20]
            elif col == 'regression_candidate':
                val = int(is_regression_candidate(row))
            elif col == 'review_status':
                val = 'proposed' if is_regression_candidate(row) else ''
            elif col == 'position_url':
                val = (f'/trainer/{row["job_id"]}?position={row["position_id"]}'
                       if row.get('position_id') and row.get('job_id') else '')
            else:
                val = row.get(col)
            if isinstance(val, str) and val.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                val = "'" + val
            item[col] = val if val is not None else ''
        writer.writerow(item)
    return output.getvalue().encode('utf-8-sig')
