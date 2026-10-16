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
