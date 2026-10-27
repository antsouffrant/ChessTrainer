"""Immutable generated-message identity for ordinary/evaluation feedback.

A position+continuation is a chess context, not a unique generated explanation.
The content hash and generation model distinguish messages for that context.
The browser sends a message ID; the server resolves immutable text and version.
"""
from __future__ import annotations

import hashlib
from feedback_history import append_feedback


def ensure_message(conn, position_id, continuation_key, generation_version, content):
    content = str(content or '').strip()
    # Never guess the model of pre-versioned copy. It remains independently
    # rateable in ordinary training under an explicit unknown-generation tag.
    version = str(generation_version or '').strip() or 'legacy-unknown'
    if not content:
        return None
    continuation_key = str(continuation_key or 'solving')
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    args=(position_id, continuation_key, version, digest)
    lookup='''SELECT id FROM feedback_message_snapshots
        WHERE position_id=? AND continuation_key=? AND generation_version=? AND content_sha256=?'''
    row=conn.execute(lookup,args).fetchone()
    if row: return row['id']
    conn.execute('''INSERT OR IGNORE INTO feedback_message_snapshots
        (position_id, continuation_key, generation_version, content_snapshot, content_sha256)
        VALUES (?,?,?,?,?)''', (position_id, continuation_key, version, content, digest))
    return conn.execute(lookup,args).fetchone()['id']


def snapshot(conn, snapshot_id, position_id, continuation_key):
    try:
        snapshot_id = int(snapshot_id)
    except (ValueError, TypeError):
        raise ValueError('A valid explanation message identifier is required')
    row = conn.execute('''SELECT id,position_id,continuation_key,generation_version,content_snapshot
        FROM feedback_message_snapshots WHERE id=? AND position_id=? AND continuation_key=?''',
        (snapshot_id, position_id, continuation_key)).fetchone()
    if row is None:
        raise LookupError('This explanation message no longer exists for the selected continuation')
    return row


def message_feedback(conn, position_id, evaluation_run_id=None):
    """Most recent rating per *message*; evaluation and regular training isolated."""
    rows = conn.execute('''WITH ranked AS (
        SELECT e.message_snapshot_id, e.rating, e.suggested_text,
               ROW_NUMBER() OVER (PARTITION BY e.message_snapshot_id ORDER BY e.id DESC) AS rn
        FROM feedback_events e JOIN feedback_message_snapshots m ON m.id=e.message_snapshot_id
        WHERE m.position_id=? AND e.feedback_type='explanation'
          AND e.evaluation_run_id IS ?
    ) SELECT message_snapshot_id,rating,suggested_text FROM ranked WHERE rn=1''',
        (position_id,evaluation_run_id)).fetchall()
    return ({str(r['message_snapshot_id']):r['rating'] for r in rows if r['rating'] != 0},
            {str(r['message_snapshot_id']):{'suggested_text':r['suggested_text'] or ''}
             for r in rows if r['rating'] != 0})


def record_message_feedback(conn, position_id, continuation_key, message_id, rating,
                            *, lesson_key='', suggested_text=None, evaluation_run_id=None):
    if rating not in (-1, 0, 1):
        raise ValueError('Rating must be -1, 0, or 1')
    if suggested_text is not None:
        if not isinstance(suggested_text, str) or len(suggested_text)>6000:
            raise ValueError('Correction must be text of at most 6000 characters')
        suggested_text = suggested_text.strip()
    message = snapshot(conn, message_id, position_id, continuation_key)
    if evaluation_run_id:
        run = conn.execute('''SELECT er.coaching_version,erp.status
            FROM evaluation_runs er JOIN evaluation_run_positions erp ON erp.run_id=er.id
            WHERE er.id=? AND erp.position_id=?''',(evaluation_run_id,position_id)).fetchone()
        if not run or run['status'] != 'solved' or run['coaching_version'] != message['generation_version']:
            raise PermissionError('This message is not rateable in this evaluation run')
    else:
        learned = conn.execute('SELECT learned FROM training_positions WHERE id=?',(position_id,)).fetchone()
        if not learned or not learned['learned']:
            raise PermissionError('Solve the position before submitting feedback')
    previous = conn.execute('''SELECT rating,suggested_text FROM feedback_events
        WHERE message_snapshot_id=? AND feedback_type='explanation' AND evaluation_run_id IS ?
        ORDER BY id DESC LIMIT 1''',(message['id'],evaluation_run_id)).fetchone()
    correction = (suggested_text if suggested_text is not None else
                  (previous['suggested_text'] if previous and previous['rating']==-1 and rating==-1 else None))
    append_feedback(conn,position_id,'explanation',rating,
        continuation=continuation_key,lesson_key=lesson_key,
        content_snapshot=message['content_snapshot'],
        coaching_version=message['generation_version'],
        suggested_text=correction if rating==-1 else None,
        message_snapshot_id=message['id'],evaluation_run_id=evaluation_run_id)
    conn.commit()
    return message_feedback(conn,position_id,evaluation_run_id)


def hydrate_recap(conn, position_id, metadata):
    """Attach stable IDs to saved (including legacy) comments without rewriting text."""
    if not isinstance(metadata,dict) or metadata.get('kind')!='solved_attempt_recap':
        return metadata
    version = metadata.get('coaching_version')
    for note in metadata.get('attempt_comments') or []:
        if not isinstance(note,dict): continue
        key = ('game:' if note.get('origin')=='game' else '') + str(note.get('move_uci') or '')
        if note.get('origin')=='solving': key='solving'
        note['feedback_message_id'] = ensure_message(conn,position_id,key,version,note.get('text'))
    return metadata


def backfill_legacy_message_attribution(conn):
    """One-time conservative metadata enrichment of earlier explanation events.

    Use ONLY the text and model already recorded in each historical event.
    Never infer a missing generation version from the current position.
    Existing votes, content, timestamps, and identifiers are unchanged.
    """
    events=conn.execute('''SELECT e.id,e.source_position_id,e.coaching_version,
         e.content_snapshot,COALESCE(fc.move_key,'solving') AS continuation_key
         FROM feedback_events e
         LEFT JOIN feedback_continuations fc ON fc.continuation_id=e.continuation_id
         WHERE e.feedback_type='explanation' AND e.message_snapshot_id IS NULL
           AND TRIM(COALESCE(e.coaching_version,'')) != ''
           AND TRIM(COALESCE(e.content_snapshot,'')) != ''
         ORDER BY e.id''').fetchall()
    for event in events:
        msg_id=ensure_message(conn,event['source_position_id'],event['continuation_key'],
                              event['coaching_version'],event['content_snapshot'])
        if msg_id:
            conn.execute('''UPDATE feedback_events SET message_snapshot_id=?
                 WHERE id=? AND message_snapshot_id IS NULL''',(msg_id,event['id']))
    return len(events)
