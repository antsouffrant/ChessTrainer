"""Coaching ratings: append-only history plus compatible live projections.

All user feedback events are retained in feedback_events. Latest per-item,
per-model is a query, not a destructive update. Unrated solved positions
remain part of taxonomy-change denominators, never invented feedback rows.
"""
from __future__ import annotations

from coaching_taxonomy import CONTEXTS, MOVE_TYPES, CANONICAL_KEYS, EVALUATION_OUTCOMES, canonical_motif_key

import csv
import io
import hashlib
import re
from feedback_history import append_feedback, current_feedback

RATING_KINDS = ('position', 'explanation', 'motif', 'coaching', 'taxonomy_context', 'taxonomy_move_type', 'taxonomy_motif')
POSITION_KINDS = RATING_KINDS[:3]


def position_votes(conn, position_id, evaluation_run_id=None):
    """Selected thumbs for this position's *current* model, using history."""
    version = conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                           (position_id,)).fetchone()
    if not version:
        return {}
    ratings = {r['feedback_type']:r['rating'] for r in current_feedback(
        conn,position_id,version=version['coaching_version'],evaluation_run_id=evaluation_run_id)
        if r['feedback_type'] in POSITION_KINDS and
        (r['feedback_type']!='explanation' or r['continuation_key']=='solving')}
    # Position usefulness is model independent; an explicit withdrawal wins.
    pos = conn.execute('''SELECT e.rating FROM feedback_events e
        JOIN feedback_position_sources s ON s.position_key=e.position_key
        WHERE s.position_id=? AND e.feedback_type='position'
          AND (? IS NULL OR e.evaluation_run_id=?)
        ORDER BY e.id DESC LIMIT 1''',(position_id,evaluation_run_id,evaluation_run_id)).fetchone()
    if pos:
        if pos['rating']==0: ratings.pop('position',None)
        else: ratings['position']=pos['rating']
    return ratings


def position_feedback_details(conn, position_id, evaluation_run_id=None):
    version = conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                           (position_id,)).fetchone()
    if not version:
        return {}
    details={r['feedback_type']:{'suggested_text':r['suggested_text'] or '',
            'suggested_motif_key':r['suggested_motif_key'] or ''}
            for r in current_feedback(conn,position_id,version=version['coaching_version'],evaluation_run_id=evaluation_run_id)
            if r['feedback_type'] in POSITION_KINDS and
            (r['feedback_type']!='explanation' or r['continuation_key']=='solving')}
    independent=conn.execute('''SELECT e.rating,e.suggested_text,e.suggested_motif_key
        FROM feedback_events e JOIN feedback_position_sources s ON s.position_key=e.position_key
        WHERE s.position_id=? AND e.feedback_type='position'
          AND (? IS NULL OR e.evaluation_run_id=?) ORDER BY e.id DESC LIMIT 1''',
        (position_id,evaluation_run_id,evaluation_run_id)).fetchone()
    if independent:
        if independent['rating']==0: details.pop('position',None)
        else: details['position']={'suggested_text':independent['suggested_text'] or '',
                                  'suggested_motif_key':independent['suggested_motif_key'] or ''}
    return details


# Retain all historical explanation votes as feedback on the solving line.
# Failed continuations use root UCI as a stable per-position key across visits.
CONTINUATION_KEY = re.compile(r'^(?:game:)?[a-h][1-8][a-h][1-8][qrbn]?$')


def continuation_votes(conn, position_id, evaluation_run_id=None):
    row=conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                     (position_id,)).fetchone()
    if not row: return {}
    return {r['continuation_key']:r['rating'] for r in current_feedback(
        conn,position_id,version=row['coaching_version'],evaluation_run_id=evaluation_run_id)
        if r['feedback_type']=='explanation' and r['continuation_key'] not in (None,'solving')}


def continuation_feedback_details(conn, position_id, evaluation_run_id=None):
    row=conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                     (position_id,)).fetchone()
    if not row: return {}
    return {r['continuation_key']:{'suggested_text':r['suggested_text'] or ''}
            for r in current_feedback(conn,position_id,version=row['coaching_version'],evaluation_run_id=evaluation_run_id)
            if r['feedback_type']=='explanation' and r['continuation_key'] not in (None,'solving')}


def record_continuation_vote(conn, position_id, continuation_key, rating, *,
                             lesson_key='', text='', suggested_text=None, evaluation_run_id=None):
    if not isinstance(continuation_key, str) or not CONTINUATION_KEY.fullmatch(continuation_key):
        raise ValueError('A verified attempted move is required for continuation feedback')
    if rating not in (-1, 0, 1):
        raise ValueError('Invalid continuation rating')
    if suggested_text is not None:
        if not isinstance(suggested_text, str) or len(suggested_text) > 6000:
            raise ValueError('Correction must be text of at most 6000 characters')
        suggested_text = suggested_text.strip()
    row = conn.execute('''SELECT tp.learned, tp.coaching_version, j.account_id
        FROM training_positions tp JOIN analysis_jobs j ON j.id=tp.job_id
        WHERE tp.id=?''', (position_id,)).fetchone()
    if row is None:
        raise LookupError('Position not found')
    if not row['learned'] and not evaluation_run_id:
        raise PermissionError('Solve the position before submitting feedback')
    game_feedback = continuation_key.startswith('game:')
    root_key = continuation_key[5:] if game_feedback else continuation_key
    attempt = conn.execute('''SELECT 1 FROM coach_board_attempts
        WHERE position_id=? AND move_uci=? AND correct=0 LIMIT 1''',
        (position_id, root_key)).fetchone()
    original_game_move = conn.execute('''SELECT 1 FROM training_positions
        WHERE id=? AND played_move_uci=? AND explanatory_lines_json IS NOT NULL''',
        (position_id, root_key)).fetchone()
    if (game_feedback and not original_game_move) or (not game_feedback and not attempt and not original_game_move):
        raise ValueError('Continuation was not a verified attempt or saved game move')
    if evaluation_run_id:
        # An evaluation vote belongs exclusively to this run. Historical
        # compatibility projections are for ordinary training and must not
        # be overwritten by a benchmark rating.
        append_feedback(conn,position_id,'explanation',rating,
            continuation=continuation_key,lesson_key=lesson_key,
            content_snapshot=str(text or '')[:6000],
            coaching_version=row['coaching_version'],
            suggested_text=suggested_text if rating==-1 else None,
            evaluation_run_id=evaluation_run_id)
        conn.commit()
        return continuation_votes(conn,position_id,evaluation_run_id)
    if rating == 0:
        conn.execute('''DELETE FROM continuation_explanation_feedback
            WHERE position_id=? AND continuation_key=?''', (position_id, continuation_key))
    else:
        lesson = str(lesson_key or '').strip()[:150]
        if lesson and not conn.execute('SELECT 1 FROM learning_concepts WHERE key=?', (lesson,)).fetchone():
            lesson = ''
        conn.execute('''INSERT INTO continuation_explanation_feedback
            (position_id, continuation_key, account_id, rating, lesson_key, content_snapshot,
             coaching_version, suggested_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(position_id, continuation_key) DO UPDATE SET
                rating=excluded.rating, lesson_key=excluded.lesson_key,
                content_snapshot=excluded.content_snapshot,
                coaching_version=excluded.coaching_version,
                suggested_text=CASE
                  WHEN excluded.rating=1 THEN NULL
                  WHEN excluded.suggested_text IS NOT NULL THEN excluded.suggested_text
                  WHEN continuation_explanation_feedback.rating=-1
                       AND continuation_explanation_feedback.coaching_version IS excluded.coaching_version
                  THEN continuation_explanation_feedback.suggested_text
                  ELSE NULL END,
                updated_at=CURRENT_TIMESTAMP''',
            (position_id, continuation_key, row['account_id'], rating, lesson,
             str(text or '')[:6000], row['coaching_version'],
             None if rating == 1 else suggested_text))
    stored=conn.execute('''SELECT suggested_text FROM continuation_explanation_feedback
        WHERE position_id=? AND continuation_key=?''',(position_id,continuation_key)).fetchone()
    append_feedback(conn, position_id, 'explanation', rating,
        continuation=continuation_key, lesson_key=lesson_key,
        content_snapshot=str(text or '')[:6000], coaching_version=row['coaching_version'],
        suggested_text=stored['suggested_text'] if stored else None,
        evaluation_run_id=evaluation_run_id)
    conn.commit()
    return continuation_votes(conn, position_id, evaluation_run_id)


def motif_feedback_options(conn, position_id=None):
    """Return built-in and relevant personal motifs, never retired labels."""
    return [dict(row) for row in conn.execute('''
        SELECT lc.key, lc.name, lc.family FROM learning_concepts lc
        WHERE lc.key != 'candidate_evaluation' AND lc.status != 'retired'
          AND lc.family <> 'Evaluation'
          AND (lc.source = 'built_in' OR (lc.status IN ('personal','promoted')
               AND (lc.account_id IS NULL OR lc.account_id = (
                   SELECT j.account_id FROM training_positions tp
                   JOIN analysis_jobs j ON j.id = tp.job_id WHERE tp.id = ?))))
        ORDER BY lc.name COLLATE NOCASE, lc.family COLLATE NOCASE, lc.key''', (position_id,))]


def record_position_vote(conn, position_id, category, rating, lesson_key='', text='',
                         suggested_text=None, suggested_motif_key=None, evaluation_run_id=None):
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
    if not row['learned'] and not evaluation_run_id:
        raise PermissionError('Solve the position before submitting feedback')
    if evaluation_run_id:
        # Never mutate the ordinary learning thumbs projection for benchmark
        # feedback. Its immutable event carries the original displayed text.
        snapshot = (str(text or row['coach_explanation'] or '').strip()[:6000]
                    if category=='explanation' else
                    (row['primary_concept_name'] or '') if category=='motif' else '')
        append_feedback(conn,position_id,category,rating,
            continuation='solving' if category=='explanation' else None,
            lesson_key=lesson_key,content_snapshot=snapshot,
            coaching_version=row['coaching_version'],
            classifier_version=row['classifier_version_at_vote'],
            suggested_text=suggested_text if rating==-1 else None,
            suggested_motif_key=suggested_motif_key if rating==-1 else None,
            evaluation_run_id=evaluation_run_id)
        conn.commit()
        return position_votes(conn,position_id,evaluation_run_id)
    if rating == 0:
        # Unchecking a selected thumb withdraws both the vote and its correction.
        # A withdrawn rating must not appear in aggregates or regression exports.
        conn.execute('DELETE FROM position_feedback WHERE position_id = ? AND category = ?',
                     (position_id, category))
        append_feedback(conn, position_id, category, 0,
            continuation='solving' if category=='explanation' else None,
            coaching_version=row['coaching_version'],
            classifier_version=row['classifier_version_at_vote'],evaluation_run_id=evaluation_run_id)
        conn.commit()
        return position_votes(conn, position_id, evaluation_run_id)
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
                WHEN position_feedback.rating = -1
                    AND position_feedback.coaching_version IS excluded.coaching_version
                THEN position_feedback.suggested_text
                ELSE NULL END,
            suggested_motif_key = CASE
                WHEN excluded.rating = 1 THEN NULL
                WHEN excluded.suggested_motif_key IS NOT NULL THEN excluded.suggested_motif_key
                WHEN position_feedback.rating = -1
                    AND position_feedback.coaching_version IS excluded.coaching_version
                THEN position_feedback.suggested_motif_key
                ELSE NULL END,
            updated_at = CURRENT_TIMESTAMP
    ''', (position_id, row['account_id'], category, rating, lesson,
          row['primary_concept_key'], snapshot, row['coaching_version'],
          row['classifier_version_at_vote'], suggested_text, suggested_motif_key))
    stored=conn.execute('''SELECT suggested_text,suggested_motif_key FROM position_feedback
         WHERE position_id=? AND category=?''',(position_id,category)).fetchone()
    append_feedback(conn, position_id, category, rating,
        continuation='solving' if category=='explanation' else None,
        lesson_key=lesson, content_snapshot=snapshot,
        coaching_version=row['coaching_version'],
        classifier_version=row['classifier_version_at_vote'],
        suggested_text=stored['suggested_text'], suggested_motif_key=stored['suggested_motif_key'],
        model_key=row['primary_concept_key'] if category=='motif' else None,
        evaluation_run_id=evaluation_run_id)
    conn.commit()
    return position_votes(conn, position_id, evaluation_run_id)



TAXONOMY_FIELDS = ('context', 'move_type', 'motif')


def taxonomy_feedback_options(conn):
    """Canonical, non-retired curriculum labels, including evaluation outcomes."""
    rows = conn.execute("""SELECT key, name, family FROM learning_concepts
                           WHERE status <> 'retired' AND source = 'built_in'
                           ORDER BY name COLLATE NOCASE, key""").fetchall()
    return [dict(r) for r in rows if r['key'] in CANONICAL_KEYS]


def taxonomy_feedback_choices(conn, position_id, evaluation_run_id=None):
    current=conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                         (position_id,)).fetchone()
    active=current_feedback(conn,position_id,version=current['coaching_version'],evaluation_run_id=evaluation_run_id) if current else []
    selected={r['feedback_type'][9:]:r['selected_key'] for r in active
              if r['feedback_type'].startswith('taxonomy_') and r['selected_key']}
    tax = conn.execute("""SELECT context_key,move_type_key,motif_key,taxonomy_version
                         FROM position_motif_taxonomy WHERE position_id=?""", (position_id,)).fetchone()
    return {'selected': selected,
            'predicted': {'context': tax['context_key'] or '' if tax else '',
                          'move_type': tax['move_type_key'] or 'none' if tax else 'none',
                          'motif': tax['motif_key'] or '' if tax else ''},
            'options': {'context': [{'key': k, 'name': v} for k,v in CONTEXTS.items()],
                        'move_type': [{'key': 'none', 'name': 'No tactical/strategic qualifier'}] +
                                     [{'key': k, 'name': v} for k,v in MOVE_TYPES.items()],
                        'motif': taxonomy_feedback_options(conn)}}


def save_taxonomy_feedback(conn, position_id, field, selected_key, evaluation_run_id=None):
    """Overwrite one dropdown judgment; an empty value withdraws just that field.

    The model snapshot is captured only when the user makes a selection, and
    isn't altered by Refresh Metadata. Existing feedback for other fields and
    historical motif/thumbs feedback are preserved.
    """
    if field not in TAXONOMY_FIELDS or not isinstance(selected_key, str):
        raise ValueError('Invalid taxonomy feedback field or choice')
    row = conn.execute("""SELECT tp.learned, j.account_id, tx.context_key,
                                 tx.move_type_key, tx.motif_key, tx.taxonomy_version,
                                 tp.coaching_version
                          FROM training_positions tp
                          JOIN analysis_jobs j ON j.id = tp.job_id
                          LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
                          WHERE tp.id=?""", (position_id,)).fetchone()
    if row is None:
        raise LookupError('Position not found')
    if not row['learned'] and not evaluation_run_id:
        raise PermissionError('Solve the position before submitting feedback')
    if not row['motif_key']:
        raise ValueError('This position has no classified learning motif yet')
    valid = {'context': set(CONTEXTS),
             'move_type': set(MOVE_TYPES) | {'none'},
             'motif': {o['key'] for o in taxonomy_feedback_options(conn)}}[field]
    if selected_key and selected_key not in valid:
        raise ValueError('Choose a valid canonical taxonomy label')
    original = {'context': row['context_key'], 'move_type': row['move_type_key'] or 'none',
                'motif': row['motif_key']}[field]
    if evaluation_run_id:
        # The model's taxonomy stays fixed and the legacy global selection
        # remains untouched by the independent evaluation.
        append_feedback(conn,position_id,'taxonomy_'+field,
            0 if not selected_key else (1 if selected_key==original else -1),
            content_snapshot=original,coaching_version=row['coaching_version'],
            classifier_version=row['taxonomy_version'],taxonomy_version=row['taxonomy_version'],
            model_key=original,selected_key=selected_key,
            evaluation_run_id=evaluation_run_id)
        conn.commit()
        return taxonomy_feedback_choices(conn,position_id,evaluation_run_id)
    if not selected_key:
        conn.execute("""DELETE FROM position_taxonomy_feedback
                        WHERE position_id=? AND field_key=?""", (position_id,field))
    else:
        conn.execute("""INSERT INTO position_taxonomy_feedback
            (position_id,account_id,field_key,selected_key,model_key_at_vote,
             taxonomy_version_at_vote,coaching_version_at_vote)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(position_id,field_key) DO UPDATE SET
                selected_key=excluded.selected_key, model_key_at_vote=excluded.model_key_at_vote,
                taxonomy_version_at_vote=excluded.taxonomy_version_at_vote,
                coaching_version_at_vote=excluded.coaching_version_at_vote,
                updated_at=CURRENT_TIMESTAMP""",
            (position_id,row['account_id'],field,selected_key,original,
             row['taxonomy_version'],row['coaching_version']))
    append_feedback(conn,position_id,'taxonomy_'+field,
        0 if not selected_key else (1 if selected_key==original else -1),
        content_snapshot=original, coaching_version=row['coaching_version'],
        classifier_version=row['taxonomy_version'],taxonomy_version=row['taxonomy_version'],
        model_key=original, selected_key=selected_key,evaluation_run_id=evaluation_run_id)
    conn.commit()
    return taxonomy_feedback_choices(conn, position_id, evaluation_run_id)

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
         pf.created_at, pf.updated_at,
         CASE WHEN pf.category='explanation' THEN 'solving' ELSE NULL END AS continuation_key
  FROM position_feedback pf
  UNION ALL
  SELECT ef.position_id, NULL, 'explanation', ef.rating, ef.lesson_key,
         NULL, ef.content_snapshot, ef.coaching_version, NULL,
         ef.suggested_text, NULL, NULL, NULL, ef.created_at, ef.updated_at,
         ef.continuation_key
  FROM continuation_explanation_feedback ef
  UNION ALL
  SELECT cf.position_id, cf.message_id, 'coaching', cf.rating,
         cf.lesson_key, NULL, cm.content, cf.coaching_version_at_vote, NULL,
         cf.suggested_text, NULL,
         (SELECT question.content FROM coach_messages question
          WHERE question.thread_id = cm.thread_id AND question.role = 'user'
            AND question.id < cm.id ORDER BY question.id DESC LIMIT 1),
         cm.structured_json, cf.created_at, cf.updated_at, NULL
  FROM coach_message_feedback cf
  LEFT JOIN coach_messages cm ON cm.id = cf.message_id
  UNION ALL
  SELECT tf.position_id, NULL, 'taxonomy_' || tf.field_key,
         CASE WHEN tf.selected_key=tf.model_key_at_vote THEN 1 ELSE -1 END,
         NULL, NULL, tf.model_key_at_vote, tf.coaching_version_at_vote, tf.taxonomy_version_at_vote,
         NULL, CASE WHEN tf.field_key='motif' THEN tf.selected_key ELSE NULL END,
         NULL, NULL, tf.created_at, tf.updated_at, NULL
  FROM position_taxonomy_feedback tf
)
SELECT v.feedback_type, v.rating, v.created_at, v.updated_at,
       v.position_id, v.message_id, v.continuation_key, v.content_snapshot, v.coaching_version,
       COALESCE(NULLIF(v.coaching_version,''), tp.coaching_version) AS report_coaching_version,
       CASE WHEN NULLIF(v.coaching_version,'') IS NOT NULL THEN 'feedback_snapshot'
            ELSE 'current_position_fallback' END AS coaching_version_source,
       v.classifier_version_at_vote, v.chat_user_message, v.chat_structured_json,
       v.suggested_text, v.suggested_motif_key, suggested_motif.name AS suggested_motif_name,
       tx.context_key AS current_context_key,
       CASE tx.context_key WHEN 'attack' THEN 'Attacking Plans' WHEN 'defend' THEN 'Defensive Resources' END AS current_context_name,
       tx.move_type_key AS current_move_type_key,
       CASE tx.move_type_key WHEN 'tactical' THEN 'Tactical Calculation' WHEN 'strategic' THEN 'Strategic Comprehension' END AS current_move_type_name,
       tx.motif_key AS current_taxonomy_motif_key, tx.taxonomy_version AS current_taxonomy_version,
       CASE WHEN v.feedback_type='taxonomy_context' THEN v.content_snapshot END AS context_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_move_type' THEN v.content_snapshot END AS move_type_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_motif' THEN v.content_snapshot END AS taxonomy_motif_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_motif' THEN
         (SELECT lc.name FROM learning_concepts lc WHERE lc.key=v.content_snapshot)
       END AS model_taxonomy_name_at_feedback,
       CASE WHEN v.feedback_type LIKE 'taxonomy_%' THEN
           (SELECT tf.selected_key FROM position_taxonomy_feedback tf
            WHERE tf.position_id=v.position_id AND ('taxonomy_' || tf.field_key)=v.feedback_type)
       END AS selected_taxonomy_key,
       CASE WHEN v.feedback_type='taxonomy_context' THEN
         (SELECT CASE tf.selected_key WHEN 'attack' THEN 'Attacking Plans' WHEN 'defend' THEN 'Defensive Resources' END
          FROM position_taxonomy_feedback tf WHERE tf.position_id=v.position_id AND tf.field_key='context')
       WHEN v.feedback_type='taxonomy_move_type' THEN
         (SELECT CASE tf.selected_key WHEN 'none' THEN 'No move type' WHEN 'tactical' THEN 'Tactical Calculation' WHEN 'strategic' THEN 'Strategic Comprehension' END
          FROM position_taxonomy_feedback tf WHERE tf.position_id=v.position_id AND tf.field_key='move_type')
       WHEN v.feedback_type='taxonomy_motif' THEN
         (SELECT COALESCE(lc2.name, tf.selected_key) FROM position_taxonomy_feedback tf
          LEFT JOIN learning_concepts lc2 ON lc2.key=tf.selected_key
          WHERE tf.position_id=v.position_id AND tf.field_key='motif') END AS selected_taxonomy_name,
       tp.coaching_version AS current_coaching_version,
       tp.coach_prompt, tp.coach_explanation AS current_explanation,
       tp.fen, tp.previous_fen, tp.user_color,
       tp.opponent_move_uci, tp.opponent_move_san,
       tp.played_move_uci, tp.played_move_san,
       tp.best_move_uci, tp.best_move_san,
       tp.eval_before_cp, tp.eval_after_cp, tp.centipawn_loss,
       tp.mate_before, tp.mate_after,
       tp.best_pv_uci, tp.played_pv_uci, tp.alternative_pvs_json,
       tp.critical_events_json, tp.explanatory_lines_json, tp.proactive_coach_json,
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
LEFT JOIN position_motif_taxonomy tx ON tx.position_id = tp.id
LEFT JOIN learning_concepts lesson ON lesson.key = COALESCE(NULLIF(v.lesson_key, ''), v.voted_motif_key, pm.key)
LEFT JOIN learning_concepts voted_motif ON voted_motif.key = v.voted_motif_key
LEFT JOIN learning_concepts suggested_motif ON suggested_motif.key = v.suggested_motif_key
'''

HISTORY_REPORT_SQL = '''
WITH primary_motifs AS (
  SELECT pc.position_id, pc.concept_key AS key, lc.name, pc.confidence, pc.evidence, pc.classifier_version
  FROM position_concepts pc
  LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
  WHERE pc.is_primary = 1
), votes AS (
  SELECT e.source_position_id AS position_id,e.source_message_id AS message_id,
         e.feedback_type,e.rating,e.lesson_key,
         CASE WHEN e.feedback_type='motif' THEN e.model_key ELSE NULL END AS voted_motif_key,
         e.content_snapshot,e.coaching_version,e.classifier_version AS classifier_version_at_vote,
         e.suggested_text,e.suggested_motif_key,e.chat_user_message,e.chat_structured_json,
         e.created_at,e.created_at AS updated_at,fc.move_key AS continuation_key,
         e.id AS feedback_event_id,e.position_key,e.continuation_id,
         e.selected_key AS feedback_selected_key
  FROM feedback_events e LEFT JOIN feedback_continuations fc
    ON fc.continuation_id=e.continuation_id
  WHERE e.rating <> 0
    AND ( ? = 1 OR e.id = (
      SELECT MAX(e2.id) FROM feedback_events e2
      WHERE e2.position_key=e.position_key AND e2.feedback_type=e.feedback_type
        AND e2.coaching_version IS e.coaching_version
        AND e2.continuation_id IS e.continuation_id
        AND e2.source_message_id IS e.source_message_id ))
    AND NOT EXISTS ( SELECT 1 FROM feedback_events withdrawn
       WHERE withdrawn.id > e.id AND withdrawn.position_key=e.position_key
         AND withdrawn.feedback_type=e.feedback_type
         AND withdrawn.coaching_version IS e.coaching_version
         AND withdrawn.continuation_id IS e.continuation_id
         AND withdrawn.source_message_id IS e.source_message_id
         AND withdrawn.rating=0 AND ?=0)

)
SELECT v.feedback_type, v.rating, v.created_at, v.updated_at,
       v.position_id, v.message_id, v.continuation_key, v.content_snapshot, v.coaching_version,
       v.feedback_event_id, v.position_key, v.continuation_id,
       COALESCE(NULLIF(v.coaching_version,''), tp.coaching_version) AS report_coaching_version,
       CASE WHEN NULLIF(v.coaching_version,'') IS NOT NULL THEN 'feedback_snapshot'
            ELSE 'current_position_fallback' END AS coaching_version_source,
       v.classifier_version_at_vote, v.chat_user_message, v.chat_structured_json,
       v.suggested_text, v.suggested_motif_key, suggested_motif.name AS suggested_motif_name,
       tx.context_key AS current_context_key,
       CASE tx.context_key WHEN 'attack' THEN 'Attacking Plans' WHEN 'defend' THEN 'Defensive Resources' END AS current_context_name,
       tx.move_type_key AS current_move_type_key,
       CASE tx.move_type_key WHEN 'tactical' THEN 'Tactical Calculation' WHEN 'strategic' THEN 'Strategic Comprehension' END AS current_move_type_name,
       tx.motif_key AS current_taxonomy_motif_key, tx.taxonomy_version AS current_taxonomy_version,
       CASE WHEN v.feedback_type='taxonomy_context' THEN v.content_snapshot END AS context_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_move_type' THEN v.content_snapshot END AS move_type_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_motif' THEN v.content_snapshot END AS taxonomy_motif_at_feedback,
       CASE WHEN v.feedback_type='taxonomy_motif' THEN
         (SELECT lc.name FROM learning_concepts lc WHERE lc.key=v.content_snapshot)
       END AS model_taxonomy_name_at_feedback,
       CASE WHEN v.feedback_type LIKE 'taxonomy_%' THEN v.feedback_selected_key END AS selected_taxonomy_key,
       CASE v.feedback_type
         WHEN 'taxonomy_context' THEN CASE v.feedback_selected_key WHEN 'attack' THEN 'Attacking Plans' WHEN 'defend' THEN 'Defensive Resources' END
         WHEN 'taxonomy_move_type' THEN CASE v.feedback_selected_key WHEN 'none' THEN 'No move type' WHEN 'tactical' THEN 'Tactical Calculation' WHEN 'strategic' THEN 'Strategic Comprehension' END
         WHEN 'taxonomy_motif' THEN COALESCE((SELECT name FROM learning_concepts WHERE key=v.feedback_selected_key),v.feedback_selected_key)
       END AS selected_taxonomy_name,
       tp.coaching_version AS current_coaching_version,
       tp.coach_prompt, tp.coach_explanation AS current_explanation,
       COALESCE(tp.fen,fp.fen) AS fen, tp.previous_fen,
       COALESCE(tp.user_color,fp.user_color) AS user_color,
       tp.opponent_move_uci, tp.opponent_move_san,
       tp.played_move_uci, tp.played_move_san,
       tp.best_move_uci, tp.best_move_san,
       tp.eval_before_cp, tp.eval_after_cp, tp.centipawn_loss,
       tp.mate_before, tp.mate_after,
       tp.best_pv_uci, tp.played_pv_uci, tp.alternative_pvs_json,
       tp.critical_events_json, tp.explanatory_lines_json, tp.proactive_coach_json,
       tp.difficulty_score, tp.difficulty_version,
       tp.analysis_pass, tp.analysis_screen_depth, tp.analysis_deep_depth,
       tp.attempts, tp.correct_attempts, tp.created_at AS position_created_at,
       pm.key AS current_primary_motif_key,
       pm.name AS current_primary_motif_name,
       pm.confidence AS current_primary_motif_confidence,
       pm.evidence AS current_primary_motif_evidence,
       pm.classifier_version AS current_classifier_version,
       v.voted_motif_key AS motif_at_vote_key,
       COALESCE(tp.job_id,fp.source_job_id) AS job_id,
       COALESCE(tp.game_id,fp.game_id) AS game_id, tp.game_date, tp.opponent,
       tp.learning_mode, tp.category AS position_category, tp.move_number,
       tp.opening_key, tp.opening_name, tp.opening_variation, tp.opening_eco,
       tp.estimated_rating, tp.learned, j.date_range, j.source_type, j.source_username,
       COALESCE(a.username,fp.username) AS username,
       COALESCE(a.provider,fp.provider) AS provider,
       COALESCE(NULLIF(v.lesson_key, ''), v.voted_motif_key, pm.key, '') AS lesson_key,
       COALESCE(lesson.name, '') AS lesson_name,
       COALESCE(v.voted_motif_key, pm.key, '') AS primary_motif_key,
       COALESCE(voted_motif.name, pm.name, '') AS primary_motif_name
FROM votes v
JOIN feedback_positions fp ON fp.position_key = v.position_key
LEFT JOIN training_positions tp ON tp.id = v.position_id
LEFT JOIN analysis_jobs j ON j.id = COALESCE(tp.job_id,fp.source_job_id)
LEFT JOIN accounts a ON a.id = fp.account_id
LEFT JOIN primary_motifs pm ON pm.position_id = tp.id
LEFT JOIN position_motif_taxonomy tx ON tx.position_id = tp.id
LEFT JOIN learning_concepts lesson ON lesson.key = COALESCE(NULLIF(v.lesson_key, ''), v.voted_motif_key, pm.key)
LEFT JOIN learning_concepts voted_motif ON voted_motif.key = v.voted_motif_key
LEFT JOIN learning_concepts suggested_motif ON suggested_motif.key = v.suggested_motif_key
'''
FILTERS = ('job_id', 'lesson_key', 'opening_key', 'primary_motif_key', 'learning_mode', 'feedback_type', 'rating', 'coaching_version', 'position_category',
           'current_context_key', 'current_move_type_key', 'continuation_key')


def report_rows(conn, filters=None):
    filters = filters or {}
    clauses, params = [], []
    for name in FILTERS:
        value = str(filters.get(name) or '').strip()
        if not value:
            continue
        if name == 'continuation_key' and len(value) > 12:
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
        # Feedback snapshots survive metadata refreshes. The version filter
        # must use the recorded version, falling back to the current position
        # only for legacy chat/taxonomy rows without a version snapshot.
        column = 'report_coaching_version' if name == 'coaching_version' else name
        clauses.append(f'voted.{column} = ?')
    continuation_scope = str(filters.get('continuation_scope') or '').strip()
    if continuation_scope == 'solving':
        clauses.append("voted.continuation_key = 'solving'")
    elif continuation_scope == 'attempted':
        clauses.append("voted.continuation_key IS NOT NULL AND voted.continuation_key != 'solving' AND voted.continuation_key NOT LIKE 'game:%'")
    elif continuation_scope == 'game':
        clauses.append("voted.continuation_key LIKE 'game:%'")
    ledger = conn.execute('SELECT 1 FROM feedback_events LIMIT 1').fetchone() is not None
    sql = 'SELECT * FROM (' + (HISTORY_REPORT_SQL if ledger else REPORT_SQL) + ') AS voted'
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    sql += ' ORDER BY voted.updated_at DESC, voted.position_id DESC, voted.message_id DESC'
    if ledger:
        all_events = str(filters.get('history') or '').lower() == 'all'
        params = [int(all_events),int(all_events)] + params
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
    # The current position version is mutable; user feedback records preserve
    # older versions. UNION both so a refresh never hides historical choices.
    versions = [dict(row) for row in conn.execute('''
        SELECT value, value AS label FROM (
            SELECT coaching_version AS value FROM training_positions
            UNION SELECT coaching_version FROM position_feedback
            UNION SELECT coaching_version FROM continuation_explanation_feedback
            UNION SELECT coaching_version_at_vote FROM position_taxonomy_feedback
            UNION SELECT coaching_version_at_vote FROM coach_message_feedback
            UNION SELECT coaching_version FROM feedback_events
        ) WHERE value IS NOT NULL AND value != '' ORDER BY value DESC
    ''')]
    return {'game_lists': jobs, 'lessons': lessons, 'openings': openings,
            'contexts': [{'value': k, 'label': v} for k,v in CONTEXTS.items()],
            'move_types': [{'value': k, 'label': v} for k,v in MOVE_TYPES.items()],
            'motifs': lessons, 'coaching_versions': versions,
            'position_categories': categories,
            'learning_modes': [{'value': row['learning_mode'], 'label': row['learning_mode'].replace('_', ' ').title()}
                               for row in conn.execute('SELECT DISTINCT learning_mode FROM training_positions WHERE learning_mode IS NOT NULL ORDER BY learning_mode')]}



# Player-facing accuracy measures are coverage based, NOT percentages of
# submitted dropdown feedback. All learned positions are the denominator,
# including those where the user never touched the coach's proposed label.
# A selection equal to the *current* coach assignment (or cleared selection)
# is unchanged, even if the user previously corrected it and changed it back.
# At-selection snapshots remain independently available in feedback exports.
SOLVED_FILTER_COLUMNS = {
    'job_id': 'tp.job_id',
    'opening_key': 'tp.opening_key',
    'learning_mode': 'tp.learning_mode',
    'coaching_version': 'tp.coaching_version',
    'position_category': 'tp.category',
    'current_context_key': 'tx.context_key',
    'current_move_type_key': 'tx.move_type_key',
    'primary_motif_key': 'pc.concept_key',
    'lesson_key': 'pc.concept_key',
}


def solved_taxonomy_rows(conn, filters=None):
    """One row per solved puzzle, including puzzles with zero feedback edits."""
    filters = filters or {}
    clauses = ['tp.learned = 1']
    params = []
    for key, column in SOLVED_FILTER_COLUMNS.items():
        value = str(filters.get(key) or '').strip()
        if not value:
            continue
        if key == 'job_id':
            if not value.isdecimal():
                continue
            value = int(value)
        clauses.append(f'{column} = ?')
        params.append(value)
    sql = f"""
    SELECT tp.id AS position_id, tp.job_id, tp.game_id, tp.fen,
           tp.opening_key, tp.opening_name, tp.opening_eco, tp.learning_mode,
           pc.concept_key AS primary_motif_key, lc.name AS primary_motif_name,
           tx.motif_key AS taxonomy_motif_key, tx_motif.name AS taxonomy_motif_name,
           j.date_range AS game_list_label,
           tp.category AS position_category,
           tp.coaching_version, tx.taxonomy_version,
           tx.context_key, tx.move_type_key, tx.motif_key,
           MAX(CASE WHEN tf.field_key = 'context' THEN tf.selected_key END) AS chosen_context,
           MAX(CASE WHEN tf.field_key = 'move_type' THEN tf.selected_key END) AS chosen_move_type,
           MAX(CASE WHEN tf.field_key = 'motif' THEN tf.selected_key END) AS chosen_motif,
           MAX(CASE WHEN tf.field_key = 'context' THEN tf.model_key_at_vote END) AS original_context_at_selection,
           MAX(CASE WHEN tf.field_key = 'move_type' THEN tf.model_key_at_vote END) AS original_move_type_at_selection,
           MAX(CASE WHEN tf.field_key = 'motif' THEN tf.model_key_at_vote END) AS original_motif_at_selection
    FROM training_positions tp
    LEFT JOIN position_motif_taxonomy tx ON tx.position_id = tp.id
    LEFT JOIN position_concepts pc ON pc.position_id = tp.id AND pc.is_primary = 1
    LEFT JOIN position_taxonomy_feedback tf ON tf.position_id = tp.id
        AND tf.coaching_version_at_vote IS tp.coaching_version
    LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
    LEFT JOIN learning_concepts tx_motif ON tx_motif.key = tx.motif_key
    LEFT JOIN analysis_jobs j ON j.id = tp.job_id
    WHERE {' AND '.join(clauses)}
    GROUP BY tp.id
    ORDER BY tp.job_id, tp.id
    """
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def taxonomy_change_rates(conn, filters=None):
    """Current correction rates among distinct solved positions in scope.

    Feedback-type and thumb-rating filters intentionally do not narrow the
    solved-position denominator. These controls apply to feedback records,
    while taxonomy change rates always describe the matching position set.
    """
    positions = solved_taxonomy_rows(conn, filters)
    total = len(positions)
    result = {}
    for field in TAXONOMY_FIELDS:
        changed = sum(1 for row in positions if taxonomy_field_changed(row, field))
        result[field] = {
            'solved': total, 'total': total, 'changed': changed,
            'unchanged': total - changed,
            'change_pct': round(100 * changed / total, 1) if total else None,
            'unchanged_pct': round(100 * (total - changed) / total, 1) if total else None,
        }
    return result




def effective_feedback_rows(conn, position_ids, *, collapse_versions=False):
    """Latest rating per entity, area, continuation/message and model version.

    Re-votes never inflate denominators, and a withdrawn event is uncounted.
    """
    if not position_ids: return []
    rows=[]
    for start in range(0,len(position_ids),700):
        subset=position_ids[start:start+700]
        slots=','.join('?' for _ in subset)
        rows.extend(dict(r) for r in conn.execute(f"""WITH ranked AS (
          SELECT e.source_position_id AS position_id,e.feedback_type AS area,
            e.rating,e.coaching_version AS version,fc.move_key AS continuation_key,
            ROW_NUMBER() OVER (PARTITION BY e.position_key,e.feedback_type,
               {'' if collapse_versions else 'e.coaching_version,'}
               e.continuation_id,e.source_message_id ORDER BY e.id DESC) AS rn
          FROM feedback_events e LEFT JOIN feedback_continuations fc
            ON fc.continuation_id=e.continuation_id
          WHERE e.source_position_id IN ({slots})
        ) SELECT * FROM ranked WHERE rn=1 AND rating <> 0""",subset))
    return rows


# A consolidated, parameterized Coach comparison. Group membership and both
# percentages are measured per DISTINCT solved position. Thumbs have their own
# *rated-position* denominator; absence of a vote is never treated as a downvote.
# Taxonomy change uses ALL solved positions, including untouched dropdowns.
# The two 100%-stacked tracks share one scale but must NEVER be summed: a
# position can have an approved explanation and a corrected primary motif.
COACH_CHART_GROUPS = ('motif', 'opening', 'lesson', 'version', 'context',
                      'move_type', 'learning_mode', 'game_list')
COACH_CHART_APPROVAL = ('any', 'position', 'explanation', 'coaching')
COACH_CHART_CHANGE = ('any',) + TAXONOMY_FIELDS


def coaching_comparison(conn, filters=None, group_by='opening',
                        approval_area='any', change_area='any', max_groups=30):
    """Compare per-position approval and taxonomy change on parallel 0-100 axes.

    An aggregate approval is true if ANY selected thumbs category has a positive
    vote for that position, divided by positions with any selected thumbs vote.
    An aggregate change is true if ANY taxonomy field's current selection differs
    from the current prediction, divided by all solved positions in the group.

    For coach-version grouping, the thumbs snapshot version and the CURRENT
    position version are deliberately separate: historical change rates cannot
    be reconstructed from current editable taxonomy choices.
    """
    filters = filters or {}
    group_by = group_by if group_by in COACH_CHART_GROUPS else 'opening'
    approval_area = approval_area if approval_area in COACH_CHART_APPROVAL else 'any'
    change_area = change_area if change_area in COACH_CHART_CHANGE else 'any'

    # Version is a historical feedback attribute. Use the current POSITION
    # filters to select the population, but select rated history by its recorded
    # version independently. This prevents a refreshed position from losing
    # its older thumb votes in the version comparison.
    scope_filters = {k: v for k, v in filters.items() if k != 'coaching_version'}
    positions = solved_taxonomy_rows(conn, scope_filters)
    position_by_id = {int(r['position_id']): r for r in positions}
    selected_version = str(filters.get('coaching_version') or '').strip()

    # A lesson is a position-to-concept relationship, not just its primary
    # label. A single solved position may belong to multiple lessons, but it
    # counts only once in each lesson's numerator and denominator.
    lesson_membership = {}
    if group_by == 'lesson' and positions:
        ids = list(position_by_id)
        for start in range(0, len(ids), 700):
            batch = ids[start:start + 700]
            slots = ','.join('?' for _ in batch)
            for r in conn.execute(f"""SELECT pc.position_id, pc.concept_key, lc.name
                FROM position_concepts pc
                LEFT JOIN learning_concepts lc ON lc.key = pc.concept_key
                WHERE pc.position_id IN ({slots})""", batch):
                lesson_membership.setdefault(r['position_id'], set()).add(
                    (str(r['concept_key'] or ''), str(r['name'] or r['concept_key'] or '')))

    def current_memberships(row):
        if group_by == 'motif':
            return [(str(row['taxonomy_motif_key'] or row['primary_motif_key'] or '__none__'),
                     str(row['taxonomy_motif_name'] or row['primary_motif_name'] or 'Unclassified'))]
        if group_by == 'opening':
            return [(str(row['opening_key'] or '__none__'),
                     str(row['opening_name'] or row['opening_eco'] or 'No opening'))]
        if group_by == 'lesson':
            return sorted(lesson_membership.get(row['position_id']) or {
                (str(row['primary_motif_key'] or '__none__'),
                 str(row['primary_motif_name'] or 'No lesson'))})
        if group_by == 'version':
            return [(str(row['coaching_version'] or '__none__'),
                     str(row['coaching_version'] or 'Unversioned'))]
        if group_by == 'context':
            return [(str(row['context_key'] or '__none__'),
                     CONTEXTS.get(row['context_key'], 'No context'))]
        if group_by == 'move_type':
            return [(str(row['move_type_key'] or 'none'),
                     MOVE_TYPES.get(row['move_type_key'], 'No move type'))]
        if group_by == 'learning_mode':
            mode = str(row['learning_mode'] or 'unknown')
            return [(mode, mode.replace('_', ' ').title())]
        return [(str(row['job_id']),
                 f"{row['game_list_label'] or 'Game list'} (#{row['job_id']})")]

    groups = {}
    position_groups = {}
    def ensure_group(key, name):
        return groups.setdefault(key, {'key': key, 'name': name,
                  'solved_ids': set(), 'changed_ids': set(),
                  'rated_ids': set(), 'approved_ids': set()})

    for position_id, row in position_by_id.items():
        group_keys = current_memberships(row)
        position_groups[position_id] = group_keys
        changed = (any(taxonomy_field_changed(row, field) for field in TAXONOMY_FIELDS)
                   if change_area == 'any' else taxonomy_field_changed(row, change_area))
        for key, name in group_keys:
            group = ensure_group(key, name)
            if not selected_version or row['coaching_version'] == selected_version:
                group['solved_ids'].add(position_id)
                if changed:
                    group['changed_ids'].add(position_id)

    # Query only small feedback attributes, not the expensive board/PV JSON
    # used by the full regression export. Enforce SQLite's parameter limit.
    votes_by_position = {}
    ids = list(position_by_id)
    if conn.execute('SELECT 1 FROM feedback_events LIMIT 1').fetchone():
        for r in effective_feedback_rows(conn,ids,
                collapse_versions=(group_by!='version' and not selected_version)):
            area=r['area']
            if area not in ('position','explanation','coaching'):
                continue
            if approval_area != 'any' and area != approval_area:
                continue
            votes_by_position.setdefault(r['position_id'],[]).append(
                (area,r['rating'],r['version']))
    else:
        for start in range(0,len(ids),700):
            batch=ids[start:start+700];slots=','.join('?' for _ in batch)
            for r in conn.execute(f"""SELECT position_id,category AS area,rating,coaching_version AS version
                 FROM position_feedback WHERE category IN ('position','explanation')
                 AND position_id IN ({slots})""",batch):
                votes_by_position.setdefault(r['position_id'],[]).append((r['area'],r['rating'],r['version']))
            for r in conn.execute(f"""SELECT position_id,'explanation' AS area,rating,coaching_version AS version
                 FROM continuation_explanation_feedback WHERE position_id IN ({slots})""",batch):
                votes_by_position.setdefault(r['position_id'],[]).append((r['area'],r['rating'],r['version']))
            for r in conn.execute(f"""SELECT cf.position_id,'coaching' AS area,cf.rating,cf.coaching_version_at_vote AS version
                 FROM coach_message_feedback cf WHERE cf.position_id IN ({slots})""",batch):
                votes_by_position.setdefault(r['position_id'],[]).append((r['area'],r['rating'],r['version']))

    for position_id, votes in votes_by_position.items():
        included = [(area, rating, str(version or position_by_id[position_id]['coaching_version'] or ''))
                    for area, rating, version in votes
                    if approval_area == 'any' or area == approval_area]
        if selected_version:
            included = [v for v in included if v[2] == selected_version]
        if not included:
            continue
        if group_by == 'version':
            # Attribute approval to the VERSION AT FEEDBACK, not the mutable
            # current version of the position. Any vote in the version forms a
            # rated-position denominator, even after a later refresh.
            versions = {version for _, _, version in included}
            for version in versions:
                current = [rating for _, rating, v in included if v == version]
                group = ensure_group(version or '__none__', version or 'Unversioned')
                group['rated_ids'].add(position_id)
                if 1 in current:
                    group['approved_ids'].add(position_id)
        else:
            for key, name in position_groups[position_id]:
                group = ensure_group(key, name)
                group['rated_ids'].add(position_id)
                if any(rating == 1 for _, rating, _ in included):
                    group['approved_ids'].add(position_id)

    def percent(num, total):
        return round(100 * num / total, 1) if total else None

    output = []
    for group in groups.values():
        solved = len(group['solved_ids'])
        changed = len(group['changed_ids'])
        rated = len(group['rated_ids'])
        approved = len(group['approved_ids'])
        if not solved and not rated:
            continue
        output.append({'key': group['key'], 'name': group['name'],
                       'solved': solved, 'changed': changed,
                       'change_pct': percent(changed, solved),
                       'rated': rated, 'approved': approved,
                       'approval_pct': percent(approved, rated)})
    output.sort(key=lambda r: (-max(r['solved'], r['rated']), r['name'].lower()))
    return {'group_by': group_by, 'approval_area': approval_area,
            'change_area': change_area, 'rows': output[:max_groups],
            'groups_count': len(output),
            'approval_denominator': 'distinct solved positions with thumbs feedback in selected approval area',
            'change_denominator': 'all solved positions in each group',
            'historical_version_note': group_by == 'version' or bool(selected_version)}

# v75: independent dashboard measures. Each chart has a CATEGORY control only:
# taxonomy changes use any corrected field; thumbs approval uses any approved
# vote within the selected category. A vote's feedback area is a category, not
# an additional metric. All rates count DISTINCT positions.
COACH_METRIC_GROUPS = COACH_CHART_GROUPS + ('taxonomy_field', 'feedback_area', 'continuation_kind')


def coaching_metric_chart(conn, filters=None, metric='changes', group_by=None, max_groups=30):
    """One rate per group with appropriate solved/rated denominators.

    Changes: distinct corrected solved positions / all solved positions.
    Approval: distinct thumbs-up solved positions / rated solved positions.
    Historical coach-version approvals use feedback-time snapshots. Changes
    refer only to the current taxonomy, never to a fabricated prior version.
    """
    filters = filters or {}
    metric = metric if metric in ('changes', 'approval') else 'changes'
    default = 'motif' if metric == 'changes' else 'feedback_area'
    valid = COACH_CHART_GROUPS + (('taxonomy_field',) if metric == 'changes' else ('feedback_area', 'continuation_kind'))
    group_by = group_by if group_by in valid else default

    def as_row(key, name, numerator, denominator):
        return {'key': key, 'name': name, 'numerator': numerator,
                'denominator': denominator,
                'rate': round(100 * numerator / denominator, 1) if denominator else None}

    selected_version = str(filters.get('coaching_version') or '').strip()
    if group_by == 'taxonomy_field':
        positions = solved_taxonomy_rows(conn, {k: v for k, v in filters.items() if k != 'coaching_version'})
        if selected_version:
            positions = [r for r in positions if str(r['coaching_version'] or '') == selected_version]
        rows = []
        for field, label in (('context','Position context'),('move_type','Move type'),('motif','Learning motif')):
            rows.append(as_row(field, label,
                sum(taxonomy_field_changed(r, field) for r in positions), len(positions)))
        return {'metric': metric, 'group_by': group_by, 'rows': rows,
                'groups_count': len(rows), 'historical_version_note': bool(selected_version)}

    if group_by == 'continuation_kind' and conn.execute('SELECT 1 FROM feedback_events LIMIT 1').fetchone():
        positions=solved_taxonomy_rows(conn,{k:v for k,v in filters.items() if k!='coaching_version'})
        counts={k:[0,0] for k in ('solving','attempted','game','chat')}
        for r in effective_feedback_rows(conn,[int(p['position_id']) for p in positions],
                collapse_versions=not selected_version):
            if selected_version and str(r['version'] or '') != selected_version: continue
            if r['area']=='coaching': key='chat'
            elif r['area']=='explanation':
                key = ('solving' if r['continuation_key']=='solving' else
                       'game' if str(r['continuation_key'] or '').startswith('game:') else 'attempted')
            else: continue
            counts[key][1]+=1
            if r['rating']==1: counts[key][0]+=1
        names={'solving':'Solving continuations','attempted':'Learning · attempted moves',
               'game':'Your game · original moves','chat':'Other coach messages'}
        rows=[as_row(k,names[k],*counts[k]) for k in counts]
        return {'metric':metric,'group_by':group_by,'rows':rows,'groups_count':len(rows),
                'historical_version_note':bool(selected_version),'approval_denominator':'rated individual continuation or coach messages'}

    if group_by == 'feedback_area' and conn.execute('SELECT 1 FROM feedback_events LIMIT 1').fetchone():
        positions=solved_taxonomy_rows(conn,{k:v for k,v in filters.items() if k!='coaching_version'})
        rated={k:set() for k in ('position','explanation','coaching')}
        approved={k:set() for k in rated}
        for r in effective_feedback_rows(conn,[int(p['position_id']) for p in positions],
                collapse_versions=not selected_version):
            if selected_version and str(r['version'] or '')!=selected_version: continue
            area=r['area']
            if area not in rated: continue
            rated[area].add(r['position_id'])
            if r['rating']==1: approved[area].add(r['position_id'])
        names={'position':'Training positions','explanation':'Explanations','coaching':'Chat coaching'}
        rows=[as_row(k,names[k],len(approved[k]),len(rated[k])) for k in names]
        return {'metric':metric,'group_by':group_by,'rows':rows,'groups_count':len(rows),
                'historical_version_note':bool(selected_version)}

    if group_by == 'continuation_kind':
        # This approval breakdown uses the MESSAGE/CONTINUATION as its unit,
        # not the distinct-position denominator of the broader charts.
        scoped = solved_taxonomy_rows(conn, {k: v for k, v in filters.items() if k != 'coaching_version'})
        ids = [int(r['position_id']) for r in scoped]
        counts = {k: [0, 0] for k in ('solving', 'attempted', 'chat')}
        for start in range(0, len(ids), 700):
            batch = ids[start:start + 700]
            placeholders = ','.join('?' for _ in batch)
            for key, query in (
                ('solving', f"""SELECT rating, coaching_version AS version
                     FROM position_feedback WHERE category='explanation'
                     AND position_id IN ({placeholders})"""),
                ('attempted', f"""SELECT rating, coaching_version AS version
                     FROM continuation_explanation_feedback
                     WHERE position_id IN ({placeholders})"""),
                ('chat', f"""SELECT cf.rating,
                         COALESCE(NULLIF(cf.coaching_version_at_vote,''),tp.coaching_version) AS version
                     FROM coach_message_feedback cf
                     JOIN training_positions tp ON tp.id=cf.position_id
                     WHERE cf.position_id IN ({placeholders})"""),
            ):
                for record in conn.execute(query, batch):
                    if selected_version and str(record['version'] or '') != selected_version:
                        continue
                    counts[key][1] += 1
                    if record['rating'] == 1: counts[key][0] += 1
        names = {'solving': 'Solving continuations',
                 'attempted': 'Earlier / game continuations',
                 'chat': 'Other coach messages'}
        rows = [as_row(key, names[key], *counts[key]) for key in counts]
        return {'metric': metric, 'group_by': group_by, 'rows': rows,
                'groups_count': len(rows), 'historical_version_note': bool(selected_version),
                'approval_denominator': 'rated individual continuation or coach messages'}

    if group_by == 'feedback_area':
        # Obtain the SAME scoped, solved-position population as the ordinary
        # grouped approval query. A separate area can have multiple chat votes,
        # but its denominator is still distinct positions with at least one vote.
        positions = solved_taxonomy_rows(conn, {k: v for k, v in filters.items() if k != 'coaching_version'})
        ids = [int(r['position_id']) for r in positions]
        rated = {a: set() for a in ('position','explanation','coaching')}
        approved = {a: set() for a in rated}
        for start in range(0, len(ids), 700):
            batch = ids[start:start + 700]
            placeholders = ','.join('?' for _ in batch)
            for r in conn.execute(f"""SELECT position_id, category AS area, rating,
                        coaching_version AS version FROM position_feedback
                        WHERE category IN ('position','explanation')
                        AND position_id IN ({placeholders})""", batch):
                if selected_version and str(r['version'] or '') != selected_version:
                    continue
                area, pid = r['area'], int(r['position_id'])
                rated[area].add(pid)
                if r['rating'] == 1: approved[area].add(pid)
            for r in conn.execute(f"""SELECT position_id, rating, coaching_version AS version
                        FROM continuation_explanation_feedback
                        WHERE position_id IN ({placeholders})""", batch):
                if selected_version and str(r['version'] or '') != selected_version:
                    continue
                pid = int(r['position_id'])
                rated['explanation'].add(pid)
                if r['rating'] == 1: approved['explanation'].add(pid)
            for r in conn.execute(f"""SELECT cf.position_id, cf.rating,
                        COALESCE(NULLIF(cf.coaching_version_at_vote,''),tp.coaching_version) AS version
                        FROM coach_message_feedback cf
                        JOIN training_positions tp ON tp.id=cf.position_id
                        WHERE cf.position_id IN ({placeholders})""", batch):
                if selected_version and str(r['version'] or '') != selected_version:
                    continue
                pid = int(r['position_id'])
                rated['coaching'].add(pid)
                if r['rating'] == 1: approved['coaching'].add(pid)
        names = {'position':'Training positions','explanation':'Explanations','coaching':'Chat coaching'}
        rows = [as_row(a, names[a], len(approved[a]), len(rated[a])) for a in names]
        return {'metric': metric, 'group_by': group_by, 'rows': rows,
                'groups_count': len(rows), 'historical_version_note': bool(selected_version)}

    old = coaching_comparison(conn, filters, group_by=group_by,
                              approval_area='any', change_area='any', max_groups=max_groups)
    numerator = 'changed' if metric == 'changes' else 'approved'
    denominator = 'solved' if metric == 'changes' else 'rated'
    rows = [as_row(r['key'], r['name'], r[numerator], r[denominator]) for r in old['rows']]
    return {'metric': metric, 'group_by': group_by, 'rows': rows,
            'groups_count': old['groups_count'],
            'historical_version_note': old['historical_version_note']}


def taxonomy_field_changed(row, field):
    """A current changed selection; a cleared or reverted edit is unchanged."""
    selected = row.get('chosen_' + field)
    predicted = row.get(field + '_key') or ('none' if field == 'move_type' else '')
    return selected is not None and selected != predicted


SOLVED_TAXONOMY_COLUMNS = (
    'position_id', 'job_id', 'game_id', 'fen', 'opening_key',
    'learning_mode', 'position_category', 'coaching_version', 'taxonomy_version',
    'context_key', 'chosen_context', 'context_changed', 'original_context_at_selection',
    'move_type_key', 'chosen_move_type', 'move_type_changed', 'original_move_type_at_selection',
    'motif_key', 'chosen_motif', 'motif_changed', 'original_motif_at_selection',
)


def solved_taxonomy_csv(rows):
    """Auditable change-rate denominator: every solved position, even no edit."""
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=SOLVED_TAXONOMY_COLUMNS, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        record = {**row, **{f + '_changed': int(taxonomy_field_changed(row, f)) for f in TAXONOMY_FIELDS}}
        # Prevent spreadsheet formula execution in user-sourced text fields.
        for key, value in record.items():
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
                record[key] = "'" + value
        writer.writerow(record)
    return output.getvalue().encode('utf-8-sig')


def current_taxonomy_status(row):
    """Current selection compared with current model, not historical vote."""
    kind = str(row.get('feedback_type') or '')
    field = kind.removeprefix('taxonomy_')
    if kind not in ('taxonomy_context', 'taxonomy_move_type', 'taxonomy_motif'):
        return ''
    current = {'context': 'current_context_key',
               'move_type': 'current_move_type_key',
               'motif': 'current_taxonomy_motif_key'}[field]
    model = row.get(current) or ('none' if field == 'move_type' else '')
    return 'changed' if row.get('selected_taxonomy_key') != model else 'unchanged'


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
            # Grouped thumbs-up rates must not mix in dropdown change judgments.
            if row.get('feedback_type') not in ('position', 'explanation', 'coaching', 'motif'):
                continue
            key = row.get(field) or ''
            if not key:
                continue
            names[key] = row.get(field.replace('_key', '_name')) or key
            groups.setdefault(key, []).append(row)
        return sorted(({'key': key, 'name': names[key], **_stats(items)} for key, items in groups.items()),
                      key=lambda x: (-x['total'], x['name'].lower()))[:30]
    return {'overall': _stats(rows),
            'thumbs': _stats([r for r in rows if r['feedback_type'] in ('position','explanation','motif','coaching')]),
            'taxonomy': _stats([r for r in rows if r['feedback_type'].startswith('taxonomy_')]),
            'categories': by_kind,
            'by_motif': breakdown('primary_motif_key'),
            'by_opening': breakdown('opening_key'),
            'by_lesson': breakdown('lesson_key'),
            'by_coaching_version': breakdown('report_coaching_version')}


# Stable machine-readable schema for coaching development. One row per latest
# rating; IDs permit joining multiple ratings on one position, and at-vote
# snapshots remain separate from the CURRENT regenerated coach and motifs.
EXPORT_COLUMNS = [
    'feedback_type', 'feedback_question', 'rating', 'rating_label', 'continuation_key',
    'current_context_key', 'current_context_name', 'current_move_type_key',
    'current_move_type_name', 'current_taxonomy_motif_key', 'current_taxonomy_version',
    'context_at_feedback', 'move_type_at_feedback', 'taxonomy_motif_at_feedback',
    'selected_taxonomy_key', 'selected_taxonomy_name', 'taxonomy_model_at_feedback_name',
    'current_taxonomy_model_key', 'current_taxonomy_change_status',
    'legacy_suggested_motif_canonical_key', 'legacy_motif_at_vote_canonical_key',
    'regression_case_id', 'regression_candidate', 'review_status',
    'created_at', 'updated_at', 'feedback_event_id', 'position_key', 'continuation_id', 'position_id', 'message_id',
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
    'alternative_pvs_json', 'critical_events_json', 'explanatory_lines_json', 'proactive_coach_json',
    'analysis_pass', 'analysis_screen_depth', 'analysis_deep_depth',
    'coaching_version', 'report_coaching_version', 'coaching_version_source',
    'current_coaching_version', 'coach_prompt',
    'content_snapshot', 'suggested_text', 'suggested_motif_key', 'suggested_motif_name',
    'current_explanation', 'chat_user_message',
    'chat_structured_json',
]

FEEDBACK_QUESTIONS = {
    'position': 'Is this training position helpful?',
    'explanation': 'Is this explanation helpful?',
    'motif': 'Does the primary learning motif fit this position?',
    'coaching': 'Is this chat coaching response helpful?',
    'taxonomy_context': 'Which coaching context best fits this position?',
    'taxonomy_move_type': 'Which tactical or strategic move type applies?',
    'taxonomy_motif': 'Which canonical primary learning motif best fits?',
}


def is_regression_candidate(row):
    if str(row.get('feedback_type') or '').startswith('taxonomy_'):
        return row.get('rating') == -1 and bool(row.get('selected_taxonomy_key'))
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
            elif col == 'legacy_suggested_motif_canonical_key':
                val = canonical_motif_key(row.get('suggested_motif_key')) or ''
            elif col == 'legacy_motif_at_vote_canonical_key':
                val = canonical_motif_key(row.get('motif_at_vote_key')) or ''
            elif col == 'taxonomy_model_at_feedback_name':
                key = str(row.get('content_snapshot') or '')
                field = str(row.get('feedback_type') or '')
                if field == 'taxonomy_context':
                    val = CONTEXTS.get(key, key)
                elif field == 'taxonomy_move_type':
                    val = MOVE_TYPES.get(key, 'No move type' if key == 'none' else key)
                elif field == 'taxonomy_motif':
                    # This key belongs to the snapshot, not the current model.
                    val = row.get('model_taxonomy_name_at_feedback') or key
                else:
                    val = ''
            elif col == 'current_taxonomy_change_status':
                val = current_taxonomy_status(row)
            elif col == 'current_taxonomy_model_key':
                kind = str(row.get('feedback_type') or '')
                key = {'taxonomy_context': 'current_context_key',
                       'taxonomy_move_type': 'current_move_type_key',
                       'taxonomy_motif': 'current_taxonomy_motif_key'}.get(kind)
                val = (row.get(key) or ('none' if kind == 'taxonomy_move_type' else '')) if key else ''
            elif col == 'rating_label':
                if str(row.get('feedback_type') or '').startswith('taxonomy_'):
                    val = 'agrees_with_prediction' if row.get('rating') == 1 else 'corrected_prediction'
                else:
                    val = 'thumbs_up' if row.get('rating') == 1 else 'thumbs_down'
            elif col == 'regression_case_id':
                # FEN + played move + feedback kind persist across engine revisions.
                # Chat examples additionally distinguish their question/response.
                signature = '|'.join(str(row.get(key) or '') for key in
                                     ('feedback_type', 'fen', 'played_move_uci', 'continuation_key'))
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
