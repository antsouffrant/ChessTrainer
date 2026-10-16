"""Persisted game-list process transitions.

A manual Analyze request resumes an unfinished checkpoint; after completion it
starts a new *deeper pass* over the saved PGN, never a new retrieval or a reset
of the accumulated training curriculum.
"""

def queue_analysis(conn, job_id, status, *, completed_passes=0, max_passes=1):
    if status == 'complete':
        next_pass = max(1, int(completed_passes or 0) + 1,
                        int(max_passes or 1) + 1)
        conn.execute('''UPDATE analysis_jobs SET status='queued', error=NULL,
            finished_at=NULL, force_reanalysis=0, max_passes=?, current_pass=?,
            checkpoint_pass=?, checkpoint_game_index=0, checkpoint_file_offset=0,
            games_processed=0 WHERE id=?''',
            (next_pass, next_pass, next_pass, job_id))
        return 'refining'
    # A failed or interrupted pass restarts at the last fully committed game.
    # In particular, do NOT reset checkpoint_pass/index/offset or positions_found.
    conn.execute('''UPDATE analysis_jobs SET status='queued', error=NULL,
        finished_at=NULL WHERE id=?''', (job_id,))
    return 'resuming'


def restart_analysis(conn, job_id, settings, *, queued=True):
    """Clean-slate reanalysis for one list, retaining only the saved PGN.

    Clears this list's derived positions, concepts, explanations, coaching
    threads and ratings via SQLite foreign-key cascades, plus its analysis
    cache and checkpoint. Other lists and the downloaded PGN are untouched.
    Refresh Metadata remains the non-destructive alternative.
    """
    from app_settings import serialize_settings

    # Called only after any old analysis worker has drained. A game-list reset
    # deliberately discards previous training progress and Coach feedback for
    # that list. A separate Coach reset clears ratings without deleting puzzles.
    conn.execute('DELETE FROM training_positions WHERE job_id=?', (job_id,))
    conn.execute('DELETE FROM analyzed_games WHERE source_job_id=?', (job_id,))
    conn.execute('DELETE FROM analysis_candidates WHERE job_id=?', (job_id,))
    conn.execute('''UPDATE metadata_processes
        SET status='idle', cursor=0,processed=0,total=0,updated=0,
            failed=0,without_pgn=0,error=NULL,updated_at=CURRENT_TIMESTAMP
        WHERE job_id=?''', (job_id,))

    passes = max(1, int(settings.get('max_passes', 1))) if settings.get('progressive_depths_enabled', True) else 1
    conn.execute('''UPDATE analysis_jobs SET status=?, error=NULL, finished_at=NULL,
        force_reanalysis=1, passes_completed=0, current_pass=1, max_passes=?,
        checkpoint_pass=1, checkpoint_game_index=0, checkpoint_file_offset=0,
        games_processed=0, games_screened=0, positions_found=0,
        metadata_refreshed_at=NULL,
        screen_depth=?, deep_depth=?, screen_seconds=?, deep_seconds=?,
        current_screen_depth=?, current_deep_depth=?, settings_json=?
        WHERE id=?''', (
        'queued' if queued else 'paused', passes,
        int(settings['base_screen_depth']), int(settings['base_deep_depth']),
        float(settings['screen_seconds']), float(settings['deep_seconds']),
        int(settings['base_screen_depth']), int(settings['base_deep_depth']),
        serialize_settings(settings), job_id,
    ))
    conn.execute('DELETE FROM analysis_candidates WHERE job_id=?', (job_id,))
