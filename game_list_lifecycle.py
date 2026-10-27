"""Deletion of an individual game list without erasing the independent feedback ledger."""


def delete_list_records(conn, job_id: int) -> None:
    """Delete one list and list-specific artifacts inside caller's transaction.

    Analyzed game results belong to the account's reusable analysis cache, so
    they are detached instead of erased. Feedback events deliberately do not
    foreign-key to training_positions and remain in the immutable ledger.
    """
    conn.execute('UPDATE analyzed_games SET source_job_id=NULL WHERE source_job_id=?', (job_id,))
    conn.execute('UPDATE feedback_positions SET source_job_id=NULL WHERE source_job_id=?', (job_id,))
    # Older schemas may lack ON DELETE CASCADE on training_positions.job_id.
    conn.execute('DELETE FROM training_positions WHERE job_id=?', (job_id,))
    conn.execute('DELETE FROM analysis_candidates WHERE job_id=?', (job_id,))
    conn.execute('DELETE FROM analysis_jobs WHERE id=?', (job_id,))
    conn.commit()
