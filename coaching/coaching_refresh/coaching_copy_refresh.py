"""Generate best-move text using the one active typed teaching-message cache.

Position text fields are compatibility projections, not a second cache.
Historical generations live in immutable feedback and evaluation archives.
"""
import hashlib
import json

from coaching.narrative_composition.coaching import COACHING_VERSION, generate_coaching_text
from coaching.motif_selection.coaching_taxonomy import MotifPath, TAXONOMY_VERSION

# Explicit input list prevents unrelated fields (learned, attempts, ratings)
# from invalidating explanations, while changing PVs/labels/probe data does.
INPUT_COLUMNS = (
    'fen', 'previous_fen', 'opponent_move_uci', 'opponent_move_san',
    'played_move_uci', 'played_move_san', 'best_move_uci', 'best_move_san',
    'category', 'mate_before', 'best_pv_uci', 'played_pv_uci',
    'alternative_pvs_json', 'eval_before_cp', 'eval_after_cp',
    'critical_events_json', 'explanatory_lines_json', 'proactive_coach_json',
)


def _source(conn, position_id):
    row = conn.execute('SELECT * FROM training_positions WHERE id=?', (position_id,)).fetchone()
    if row is None:
        return None
    labels = conn.execute('''SELECT concept_key AS key, confidence, is_primary, evidence
       FROM position_concepts WHERE position_id=?
       ORDER BY is_primary DESC, confidence DESC''', (position_id,)).fetchall()
    taxonomy = conn.execute('SELECT * FROM position_motif_taxonomy WHERE position_id=?',
                            (position_id,)).fetchone()
    return row, labels, taxonomy


def _fingerprint(row, labels, taxonomy):
    payload = {
        'fingerprint_schema': 1,
        'taxonomy_version': TAXONOMY_VERSION,
        'inputs': {key: row[key] for key in INPUT_COLUMNS},
        'labels': [dict(label) for label in labels],
        'taxonomy': dict(taxonomy) if taxonomy else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def preserve_previous_coaching_copy(conn, position_id):
    """Historical versions belong to immutable feedback/evaluation archives.

    Never archive another playable coaching copy on refresh. The typed active
    cache replaces a previous generation only when new text is ready.
    """
    return False


def rebuild_coaching_copy(conn, position_id):
    source = _source(conn, position_id)
    if source is None:
        return False
    row, labels, taxonomy = source
    fingerprint = _fingerprint(row, labels, taxonomy)
    from coaching.coaching_refresh.message_cache import cache_message, get_message
    existing = get_message(conn, position_id, 'best_move', 'position',
                           version=COACHING_VERSION, fingerprint=fingerprint)
    if existing:
        prompt, explanation = existing['coach_prompt'], existing['content']
    else:
        path = (MotifPath(taxonomy['context_key'], taxonomy['move_type_key'],
                          taxonomy['motif_key'], taxonomy['confidence'], taxonomy['evidence'])
                if taxonomy else None)
        prompt, explanation = generate_coaching_text(
            fen=row['fen'], previous_fen=row['previous_fen'],
            opponent_move_uci=row['opponent_move_uci'],
            opponent_move_san=row['opponent_move_san'],
            played_move_uci=row['played_move_uci'],
            played_move_san=row['played_move_san'],
            best_move_uci=row['best_move_uci'], best_move_san=row['best_move_san'],
            category=row['category'], labels=labels, taxonomy_path=path,
            mate_before=row['mate_before'], best_pv_uci=row['best_pv_uci'],
            played_pv_uci=row['played_pv_uci'],
            alternative_pvs_json=row['alternative_pvs_json'],
            eval_before_cp=row['eval_before_cp'], eval_after_cp=row['eval_after_cp'],
            critical_events_json=row['critical_events_json'],
            explanatory_lines_json=row['explanatory_lines_json'],
            proactive_coach_json=row['proactive_coach_json'])
        cache_message(conn, position_id, 'best_move', 'position', COACHING_VERSION,
                      explanation, evidence_fingerprint=fingerprint, prompt=prompt)
    conn.execute('''UPDATE training_positions SET coach_prompt=?,coach_explanation=?,
       coaching_version=? WHERE id=?''',
       (prompt, explanation, COACHING_VERSION, position_id))
    return True
