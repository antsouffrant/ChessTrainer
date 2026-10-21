"""Version-scoped, evidence-fingerprinted coaching explanation cache.

Cached copy may only be replayed for the exact rule version and evidence. This
keeps older coaching snapshots useful without relabeling old text as new output.
Startup never upgrades a previous version; the Stockfish-backed refresh does.
"""
import hashlib
import json

from coaching import COACHING_VERSION, generate_coaching_text
from coaching_taxonomy import MotifPath, TAXONOMY_VERSION

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


def _store(conn, position_id, version, fingerprint, prompt, explanation):
    if version and prompt is not None and explanation is not None:
        conn.execute('''INSERT OR IGNORE INTO coaching_explanation_cache
           (position_id,coaching_version,evidence_fingerprint,coach_prompt,coach_explanation)
           VALUES (?,?,?,?,?)''',
           (position_id, version, fingerprint, prompt, explanation))


def preserve_previous_coaching_copy(conn, position_id):
    """Archive a pre-refresh copy with its ORIGINAL version and evidence.

    This intentionally never relabels the snapshot as the running model. The
    active position remains the only current coaching output for that position.
    """
    source = _source(conn, position_id)
    if source is None:
        return False
    row, labels, taxonomy = source
    if not row['coaching_version'] or row['coach_explanation'] is None:
        return False
    _store(conn, position_id, row['coaching_version'],
           _fingerprint(row, labels, taxonomy),
           row['coach_prompt'], row['coach_explanation'])
    return True


def rebuild_coaching_copy(conn, position_id):
    source = _source(conn, position_id)
    if source is None:
        return False
    row, labels, taxonomy = source
    fingerprint = _fingerprint(row, labels, taxonomy)
    existing = conn.execute('''SELECT coach_prompt,coach_explanation
       FROM coaching_explanation_cache
       WHERE position_id=? AND coaching_version=? AND evidence_fingerprint=?''',
       (position_id, COACHING_VERSION, fingerprint)).fetchone()
    if existing:
        prompt, explanation = existing['coach_prompt'], existing['coach_explanation']
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
        _store(conn, position_id, COACHING_VERSION, fingerprint, prompt, explanation)
    conn.execute('''UPDATE training_positions SET coach_prompt=?,coach_explanation=?,
       coaching_version=? WHERE id=?''',
       (prompt, explanation, COACHING_VERSION, position_id))
    return True
