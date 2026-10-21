"""Independent benchmark evaluation sessions; never reuse global learned state.

The frozen coach_benchmark_positions are the playlist definition. Each
completed coaching refresh (or explicit new evaluation) creates a separate run.
Historical runs and their attempts are not changed by cache invalidation.
"""


def start_evaluation_run(conn, job_id, coaching_version=None):
    benchmark = conn.execute('''SELECT id,coaching_version,expected_positions,captured_positions
        FROM coach_benchmark_runs WHERE job_id=?
        AND (? IS NULL OR coaching_version=?) ORDER BY id DESC LIMIT 1''',
        (job_id,coaching_version,coaching_version)).fetchone()
    if not benchmark:
        raise ValueError('Complete a Coaching refresh before starting an evaluation.')
    if int(benchmark['captured_positions']) != int(benchmark['expected_positions']):
        raise ValueError('Benchmark snapshot is incomplete. Refresh coaching before evaluation.')
    # Only a currently served version can be evaluated; older versions are
    # retained for reporting but must not be silently evaluated with new prose.
    stale = conn.execute('''SELECT COUNT(*) FROM coach_benchmark_positions bp
        LEFT JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
        WHERE bp.job_id=? AND (tp.id IS NULL OR tp.coaching_version!=?)''',
        (job_id,benchmark['coaching_version'])).fetchone()[0]
    if stale:
        raise ValueError('The current coaching version does not match the selected benchmark snapshot.')
    # A cache refresh may have changed evidence without changing the model
    # label. Do not evaluate updated prose against an earlier frozen snapshot.
    mismatched=conn.execute('''SELECT COUNT(*) FROM coach_benchmark_positions bp
        JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
        LEFT JOIN coach_benchmark_snapshots bs ON bs.position_id=bp.position_id
           AND bs.run_id=?
        LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
        WHERE bp.job_id=? AND (bs.position_id IS NULL
          OR bs.explanation IS NOT tp.coach_explanation
          OR bs.motif_key IS NOT tx.motif_key
          OR bs.context_key IS NOT tx.context_key
          OR bs.move_type_key IS NOT tx.move_type_key)''',
        (benchmark['id'],job_id)).fetchone()[0]
    if mismatched:
        raise ValueError('Current explanations or taxonomy differ from the fixed model snapshot. Use a new coaching model version before evaluating.')
    inserted=conn.execute('''INSERT INTO evaluation_runs(job_id,benchmark_run_id,coaching_version)
        VALUES (?,?,?)''',(job_id,benchmark['id'],benchmark['coaching_version']))
    run_id=int(inserted.lastrowid)
    conn.execute('''INSERT INTO evaluation_run_positions(run_id,position_id)
       SELECT ?,position_id FROM coach_benchmark_positions WHERE job_id=?''',
       (run_id,job_id))
    return run_id


def resolve_run(conn, job_id, run_id=None):
    if run_id:
        row=conn.execute('''SELECT * FROM evaluation_runs WHERE id=? AND job_id=?''',
                         (run_id,job_id)).fetchone()
    else:
        row=conn.execute('''SELECT * FROM evaluation_runs WHERE job_id=? ORDER BY id DESC LIMIT 1''',
                         (job_id,)).fetchone()
    return row


def run_position(conn,run_id,position_id,job_id=None):
    return conn.execute('''SELECT er.id,er.job_id,er.coaching_version,erp.status,erp.attempts
       FROM evaluation_runs er JOIN evaluation_run_positions erp ON erp.run_id=er.id
       WHERE er.id=? AND erp.position_id=? AND (? IS NULL OR er.job_id=?)''',
       (run_id,position_id,job_id,job_id)).fetchone()


def record_evaluation_attempt(conn,run_id,position_id,correct,move_uci):
    item=run_position(conn,run_id,position_id)
    if item is None:
        raise ValueError('Position does not belong to this evaluation run.')
    if item['status']=='solved':
        raise ValueError('This position was already solved in this evaluation run.')
    conn.execute('''INSERT INTO evaluation_attempts(run_id,position_id,move_uci,correct)
       VALUES(?,?,?,?)''',(run_id,position_id,move_uci,int(correct)))
    conn.execute('''UPDATE evaluation_run_positions SET attempts=attempts+1,
         status=CASE WHEN ? THEN 'solved' ELSE status END,
         solved_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE solved_at END
         WHERE run_id=? AND position_id=?''',(int(correct),int(correct),run_id,position_id))
    if not conn.execute('''SELECT 1 FROM evaluation_run_positions
        WHERE run_id=? AND status!='solved' LIMIT 1''',(run_id,)).fetchone():
        conn.execute("UPDATE evaluation_runs SET status='completed', completed_at=CURRENT_TIMESTAMP WHERE id=?",(run_id,))


def evaluation_manifest(conn,job_id,run_id):
    return [dict(row) for row in conn.execute('''SELECT bp.position_id AS id,
       CASE WHEN erp.status='solved' THEN 1 ELSE 0 END AS learned,
       erp.attempts AS evaluation_attempts
       FROM coach_benchmark_positions bp
       JOIN evaluation_run_positions erp ON erp.position_id=bp.position_id AND erp.run_id=?
       JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
       WHERE bp.job_id=? ORDER BY bp.ordinal''',(run_id,job_id)).fetchall()]


def run_history(conn,job_id):
    rows=conn.execute('''SELECT er.id,er.coaching_version,er.status,er.created_at,er.completed_at,
      COUNT(erp.position_id) AS total,
      COALESCE(SUM(CASE WHEN erp.status='solved' THEN 1 ELSE 0 END),0) AS solved
      FROM evaluation_runs er LEFT JOIN evaluation_run_positions erp ON erp.run_id=er.id
      WHERE er.job_id=? GROUP BY er.id ORDER BY er.id DESC''',(job_id,)).fetchall()
    return [dict(row) for row in rows]
