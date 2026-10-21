"""Explicit, list-scoped invalidation of derived teaching material.

Never delete Stockfish's root evaluations, principal variations, imported games,
recorded player attempts, learned state, or historical feedback_events.
Deleting coach threads cascades disposable chat messages and their latest-vote
projections, but the immutable feedback ledger retains those ratings and their
message snapshots. Callers must still warn about lost chat *conversations*.
"""


def clear_coaching_cache(conn, job_id):
    """Invalidate coaching artifacts for one list in the caller's transaction.

    A metadata refresh must follow. Do not call while retrieval, analysis, or
    refresh workers are writing; the HTTP route owns that synchronization.
    """
    exists = conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()
    if not exists:
        raise LookupError('Game list not found')

    positions = '(SELECT id FROM training_positions WHERE job_id=?)'
    counts = {}
    counts['positions'] = conn.execute(
        'SELECT COUNT(*) FROM training_positions WHERE job_id=?', (job_id,)
    ).fetchone()[0]

    # Each per-position thread owns its assistant/user messages. Foreign-key
    # cascades remove recaps, proactive-message markers, coach claims and their
    # chat thumbs. The user explicitly confirms this irreversible deletion.
    counts['chat_messages'] = conn.execute(
        'SELECT COUNT(*) FROM coach_messages WHERE thread_id IN '
        '(SELECT id FROM coach_threads WHERE position_id IN ' + positions + ')',
        (job_id,),
    ).fetchone()[0]
    counts['chat_feedback_projections'] = conn.execute(
        'SELECT COUNT(*) FROM coach_message_feedback WHERE position_id IN ' + positions,
        (job_id,),
    ).fetchone()[0]
    counts['chat_feedback'] = counts['chat_feedback_projections']  # compatibility count
    history_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feedback_events'").fetchone()
    counts['historical_feedback_preserved'] = (conn.execute(
        'SELECT COUNT(*) FROM feedback_events WHERE source_position_id IN ' + positions,
        (job_id,),
    ).fetchone()[0] if history_table else 0)
    conn.execute('DELETE FROM coach_threads WHERE position_id IN ' + positions, (job_id,))

    # Defensive cleanup for historical rows that may not have a surviving
    # thread/message, without impacting any other game list.
    # Explicit cache clearing drops every generated explanation snapshot for
    # this list, but never the immutable feedback or benchmark history.
    has_copy_cache = conn.execute('''SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='coaching_explanation_cache' ''').fetchone()
    counts['cached_explanations'] = (conn.execute(
        'DELETE FROM coaching_explanation_cache WHERE position_id IN ' + positions,
        (job_id,),
    ).rowcount if has_copy_cache else 0)
    conn.execute('DELETE FROM coach_proactive_history WHERE job_id=?', (job_id,))
    conn.execute('DELETE FROM coach_proactive_spotlights WHERE job_id=?', (job_id,))
    conn.execute('DELETE FROM coach_solve_recaps WHERE position_id IN ' + positions, (job_id,))
    conn.execute('DELETE FROM concept_evidence WHERE position_id IN ' + positions, (job_id,))
    conn.execute('DELETE FROM coach_claims WHERE position_id IN ' + positions, (job_id,))

    counts['classification_rows'] = conn.execute(
        'DELETE FROM position_concepts WHERE position_id IN ' + positions, (job_id,)
    ).rowcount
    counts['taxonomy_rows'] = conn.execute(
        'DELETE FROM position_motif_taxonomy WHERE position_id IN ' + positions, (job_id,)
    ).rowcount
    counts['cleared_explanations'] = conn.execute('''UPDATE training_positions SET
        coach_prompt=NULL, coach_explanation=NULL, coaching_version=NULL,
        proactive_coach_json=NULL, explanatory_lines_json=NULL,
        critical_events_json=NULL WHERE job_id=?''', (job_id,)).rowcount

    # A dedicated needs_refresh state prevents startup's cheap text backfill
    # from silently reusing the old causal/continuation evidence. Only the
    # explicit Stockfish-backed refresh marks the list current again.
    conn.execute('''INSERT INTO metadata_processes
        (job_id,status,cursor,processed,total,updated,failed,without_pgn,perf_json,error)
        VALUES (?,'needs_refresh',0,0,0,0,0,0,NULL,NULL)
        ON CONFLICT(job_id) DO UPDATE SET
        status='needs_refresh',cursor=0,processed=0,total=0,updated=0,
        failed=0,without_pgn=0,perf_json=NULL,error=NULL,
        updated_at=CURRENT_TIMESTAMP''', (job_id,))
    conn.execute('UPDATE analysis_jobs SET metadata_refreshed_at=NULL WHERE id=?', (job_id,))
    return counts
