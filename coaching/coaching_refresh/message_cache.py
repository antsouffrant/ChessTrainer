"""Authoritative *active* coaching-message cache.

The only reusable teaching-text cache. Three message kinds map to the three
training cards: best_move, attempted_move, game_move. Only a single active
record is kept for each position/kind/continuation. Historical ratings and
model outputs live in the independent immutable feedback/evaluation ledgers.

The legacy training_positions.coach_explanation fields are compatibility
projections, never a second reusable cache. coach_messages is a conversation
transcript, never a source for current teaching messages.
"""
from __future__ import annotations

import hashlib

KINDS = frozenset(('best_move', 'attempted_move', 'game_move'))


def cache_message(conn, position_id, message_type, continuation_key, version,
                  content, *, evidence_fingerprint='', prompt=''):
    if message_type not in KINDS:
        raise ValueError('Unknown coaching message type')
    if not version or not str(content or '').strip():
        raise ValueError('Generated coaching requires original version and nonempty text')
    key = str(continuation_key or 'solving')
    digest = hashlib.sha256(str(content).encode('utf-8')).hexdigest()
    conn.execute('''INSERT INTO coaching_message_cache
       (position_id,message_type,continuation_key,generation_version,content,
        content_sha256,evidence_fingerprint,coach_prompt)
       VALUES (?,?,?,?,?,?,?,?)
       ON CONFLICT(position_id,message_type,continuation_key) DO UPDATE SET
          generation_version=excluded.generation_version,
          content=excluded.content, content_sha256=excluded.content_sha256,
          evidence_fingerprint=excluded.evidence_fingerprint,
          coach_prompt=excluded.coach_prompt,
          updated_at=CURRENT_TIMESTAMP''',
        (position_id, message_type, key, version, content, digest,
         evidence_fingerprint or '', prompt or ''))
    return get_message(conn, position_id, message_type, key)


def get_message(conn, position_id, message_type, continuation_key='solving',
                *, version=None, fingerprint=None):
    result = conn.execute('''SELECT * FROM coaching_message_cache
         WHERE position_id=? AND message_type=? AND continuation_key=?''',
         (position_id, message_type, str(continuation_key or 'solving'))).fetchone()
    if result is None:
        return None
    if version is not None and result['generation_version'] != version:
        return None
    if fingerprint is not None and result['evidence_fingerprint'] != fingerprint:
        return None
    return result


def note_kind(note):
    if note.get('origin') == 'game':
        return 'game_move'
    if note.get('origin') == 'solving':
        return 'best_move'
    return 'attempted_move'


def note_key(note):
    return 'solving' if note_kind(note) == 'best_move' else str(note.get('move_uci') or '')


def is_current_recap(conn, position_id, metadata, version):
    """Verify a saved recap against each live typed message, not transcript age."""
    if not isinstance(metadata, dict) or metadata.get('kind') != 'solved_attempt_recap':
        return False
    if metadata.get('coaching_version') != version:
        return False
    notes = metadata.get('attempt_comments') or []
    if not notes:
        return False
    for note in notes:
        if not isinstance(note, dict):
            return False
        cached = get_message(conn, position_id, note_kind(note), note_key(note), version=version)
        if cached is None or cached['content'] != note.get('text'):
            return False
    return True


def visible_in_active_history(conn, position_id, message, active_version):
    """A conversation transcript isn't permission to replay obsolete coaching."""
    if message.get('role') != 'assistant':
        return True  # A user's own questions are not generated coaching.
    import json
    try:
        meta = json.loads(message.get('structured_json') or '{}')
    except (TypeError, ValueError, AttributeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    generation = message.get('generation_version') or meta.get('coaching_version')
    if generation != active_version:
        return False
    if meta.get('kind') == 'solved_attempt_recap':
        return is_current_recap(conn, position_id, meta, active_version)
    return True
