"""Immutable feedback history, independent of ephemeral coaching/cache tables.

The position/continuation dictionaries are durable identities, not foreign keys to
chat messages. `feedback_events` is append-only except an explicit user-initiated
RESET FEEDBACK. A zero rating is a withdrawal event, never an unrated puzzle.
"""
from __future__ import annotations

import hashlib
import json


def _identity(parts, prefix):
    raw = json.dumps(parts, ensure_ascii=False, separators=(',', ':'), default=str)
    return prefix + hashlib.sha256(raw.encode('utf8')).hexdigest()[:28]


def register_position(conn, position_id):
    # Read-only fast path: repeated thumbs lookups should not acquire SQLite
    # write locks by executing INSERT OR IGNORE on every page rendering.
    existing=conn.execute('''SELECT fps.position_key,fp.account_id
        FROM feedback_position_sources fps
        JOIN feedback_positions fp ON fp.position_key=fps.position_key
        JOIN training_positions tp ON tp.id=fps.position_id
        WHERE fps.position_id=?''',(position_id,)).fetchone()
    if existing:
        return existing['position_key'],existing['account_id']
    row = conn.execute('''SELECT tp.id,tp.job_id,tp.game_id,tp.mistake_ply,
        tp.move_number,tp.fen,tp.user_color,j.account_id,a.provider,a.username
        FROM training_positions tp JOIN analysis_jobs j ON j.id=tp.job_id
        JOIN accounts a ON a.id=j.account_id WHERE tp.id=?''', (position_id,)).fetchone()
    if row is None:
        raise LookupError('Position not found')
    game = str(row['game_id'] or ('job:' + str(row['job_id']) + ':position:' + str(position_id)))
    # Ignore halfmove/fullmove counters. These are not part of board identity.
    board = ' '.join(str(row['fen'] or '').split()[:4])
    position_key = _identity([row['provider'], row['username'], row['job_id'], game,
        row['mistake_ply'] if row['mistake_ply'] is not None else row['move_number'],
        board, row['user_color']], 'pos_')
    conn.execute('''INSERT OR IGNORE INTO feedback_positions
       (position_key,account_id,provider,username,game_id,source_job_id,ply,fen,board_identity,user_color)
       VALUES (?,?,?,?,?,?,?,?,?,?)''', (position_key,row['account_id'],row['provider'],
            row['username'],game,row['job_id'],row['mistake_ply'] if row['mistake_ply'] is not None else row['move_number'],
            row['fen'],board,row['user_color']))
    conn.execute('''INSERT INTO feedback_position_sources(position_id,position_key)
        VALUES (?,?) ON CONFLICT(position_id) DO UPDATE SET
        position_key=excluded.position_key''',(position_id,position_key))
    return position_key, row['account_id']


def register_continuation(conn, position_key, root_move):
    if root_move is None:
        return None
    move = str(root_move).strip().lower()
    if move.startswith('game:'):
        move = 'game:' + move[5:]
        underlying = move[5:]
    else:
        underlying = move
    if move != 'solving' and not (
        len(underlying) in (4,5) and underlying[0] in 'abcdefgh' and underlying[1] in '12345678'
        and underlying[2] in 'abcdefgh' and underlying[3] in '12345678'
        and (len(underlying)==4 or underlying[4] in 'qrbn')):
        raise ValueError('Invalid continuation identifier')
    key = _identity([position_key, move], 'cont_')
    conn.execute('''INSERT OR IGNORE INTO feedback_continuations
       (continuation_id,position_key,move_key) VALUES(?,?,?)''',(key,position_key,move))
    return key


def append_feedback(conn, position_id, feedback_type, rating, *, continuation=None,
                    lesson_key='', content_snapshot='', coaching_version=None,
                    classifier_version=None, taxonomy_version=None, suggested_text=None,
                    suggested_motif_key=None, model_key=None, selected_key=None,
                    message_id=None, message_snapshot_id=None, chat_user_message=None, chat_structured_json=None,
                    source='vote', source_reference=None, created_at=None, evaluation_run_id=None):
    """Append a single deliberate rating/withdrawal; caller manages transaction.

    The lookup dictionary and the event commit atomically with the live UI
    projection. A re-vote always creates another event, including same model.
    """
    if int(rating) not in (-1,0,1):
        raise ValueError('Invalid feedback rating')
    position_key, account_id = register_position(conn, position_id)
    continuation_id = register_continuation(conn, position_key, continuation)
    if source_reference is not None:
        exists = conn.execute('SELECT id FROM feedback_events WHERE source_reference=?',
                              (source_reference,)).fetchone()
        if exists:
            return exists['id'] if hasattr(exists,'keys') else exists[0]
    cursor = conn.execute('''INSERT INTO feedback_events
      (position_key,continuation_id,source_position_id,account_id,feedback_type,rating,
       lesson_key,content_snapshot,coaching_version,classifier_version,taxonomy_version,
       suggested_text,suggested_motif_key,model_key,selected_key,source_message_id,
       chat_user_message,chat_structured_json,source,source_reference,created_at,evaluation_run_id,message_snapshot_id)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP),?,?)''',
       (position_key,continuation_id,position_id,account_id,feedback_type,int(rating),
        lesson_key or None,content_snapshot or None,coaching_version,
        classifier_version,taxonomy_version,suggested_text or None,
        suggested_motif_key or None,model_key,selected_key or None,message_id,
        chat_user_message,chat_structured_json,source,source_reference,created_at,evaluation_run_id,message_snapshot_id))
    return cursor.lastrowid


def current_feedback(conn, position_id, *, version=None, evaluation_run_id=None):
    """Effective latest vote per item for a particular model; withdrawals hidden."""
    position_key, _ = register_position(conn, position_id)
    return conn.execute('''WITH ordered AS (
      SELECT e.*, fc.move_key AS continuation_key,
             ROW_NUMBER() OVER (PARTITION BY e.feedback_type,
               COALESCE(fc.move_key,''),COALESCE(e.source_message_id,-1),COALESCE(e.message_snapshot_id,-1)
               ORDER BY e.id DESC) AS rn
      FROM feedback_events e LEFT JOIN feedback_continuations fc
        ON fc.continuation_id=e.continuation_id
      WHERE e.position_key=? AND e.coaching_version IS ?
        AND (? IS NULL OR e.evaluation_run_id=?) )
      SELECT * FROM ordered WHERE rn=1 AND rating != 0''',(position_key,version,evaluation_run_id,evaluation_run_id)).fetchall()


def _legacy_row_migrations(conn):
    """Copy every available legacy *latest* vote once, never delete originals.

    Older releases overwrote repeated votes, so only their surviving snapshots
    can be recovered. Legacy interactive thumbs are copied *before* chat reset.
    """
    for r in conn.execute('''SELECT * FROM position_feedback''').fetchall():
        append_feedback(conn,r['position_id'],r['category'],r['rating'],
            continuation='solving' if r['category']=='explanation' else None,
            lesson_key=r['lesson_key'],content_snapshot=r['content_snapshot'],
            coaching_version=r['coaching_version'],classifier_version=r['classifier_version_at_vote'],
            suggested_text=r['suggested_text'],suggested_motif_key=r['suggested_motif_key'],
            source='legacy',source_reference=f"legacy:position:{r['position_id']}:{r['category']}",
            created_at=r['updated_at'])
    for r in conn.execute('SELECT * FROM continuation_explanation_feedback').fetchall():
        append_feedback(conn,r['position_id'],'explanation',r['rating'],continuation=r['continuation_key'],
            lesson_key=r['lesson_key'],content_snapshot=r['content_snapshot'],
            coaching_version=r['coaching_version'],suggested_text=r['suggested_text'],
            source='legacy',source_reference=f"legacy:continuation:{r['position_id']}:{r['continuation_key']}",
            created_at=r['updated_at'])
    for r in conn.execute('''SELECT cf.*,cm.content AS content_snapshot,cm.structured_json AS chat_structured_json,
          (SELECT question.content FROM coach_messages question WHERE question.thread_id=cm.thread_id
           AND question.role='user' AND question.id<cm.id ORDER BY question.id DESC LIMIT 1) AS chat_user_message
          FROM coach_message_feedback cf LEFT JOIN coach_messages cm ON cm.id=cf.message_id''').fetchall():
        append_feedback(conn,r['position_id'],'coaching',r['rating'],
            lesson_key=r['lesson_key'],content_snapshot=r['content_snapshot'],
            coaching_version=r['coaching_version_at_vote'],suggested_text=r['suggested_text'],
            message_id=r['message_id'],chat_user_message=r['chat_user_message'],
            chat_structured_json=r['chat_structured_json'],source='legacy',
            source_reference=f"legacy:chat:{r['message_id']}",created_at=r['updated_at'])
    for r in conn.execute('SELECT * FROM position_taxonomy_feedback').fetchall():
        append_feedback(conn,r['position_id'],'taxonomy_'+r['field_key'],
            1 if r['selected_key']==r['model_key_at_vote'] else -1,
            content_snapshot=r['model_key_at_vote'],coaching_version=r['coaching_version_at_vote'],
            classifier_version=r['taxonomy_version_at_vote'],taxonomy_version=r['taxonomy_version_at_vote'],
            model_key=r['model_key_at_vote'],selected_key=r['selected_key'],
            suggested_motif_key=r['selected_key'] if r['field_key']=='motif' else None,
            source='legacy',source_reference=f"legacy:taxonomy:{r['position_id']}:{r['field_key']}",
            created_at=r['updated_at'])


def migrate_legacy_feedback(conn):
    """Idempotent startup import; run only after schema and column migrations."""
    _legacy_row_migrations(conn)
