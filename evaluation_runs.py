"""One authoritative evaluation per game list and coaching version.

The fixed cohort is shared by models. Explicit new evaluations supersede an
earlier evaluation of that same model, preserving its feedback ledger and
attempt history as non-authoritative archival evidence.
"""


def current_evaluation_run(conn, job_id, coaching_version):
    return conn.execute('''SELECT * FROM evaluation_runs WHERE job_id=?
        AND coaching_version=? AND status!='superseded'
        ORDER BY id DESC LIMIT 1''',(job_id,coaching_version)).fetchone()


def ensure_evaluation_run(conn, job_id, coaching_version):
    """On coaching refresh, create only if this model has no evaluation."""
    current=current_evaluation_run(conn,job_id,coaching_version)
    return int(current['id']) if current else start_evaluation_run(conn,job_id,coaching_version)


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
    # Only the latest run is the model's feedback source of truth. Do not
    # delete earlier run/attempt rows: the append-only feedback ledger refers
    # to those run IDs and must remain historically accurate.
    conn.execute('''UPDATE evaluation_runs SET status='superseded'
       WHERE job_id=? AND coaching_version=? AND status!='superseded' ''',
       (job_id,benchmark['coaching_version']))
    inserted=conn.execute('''INSERT INTO evaluation_runs(job_id,benchmark_run_id,coaching_version)
        VALUES (?,?,?)''',(job_id,benchmark['id'],benchmark['coaching_version']))
    run_id=int(inserted.lastrowid)
    conn.execute('''INSERT INTO evaluation_run_positions(run_id,position_id)
       SELECT ?,position_id FROM coach_benchmark_positions WHERE job_id=?''',
       (run_id,job_id))
    return run_id


def resolve_run(conn, job_id, run_id=None, current_coaching_version=None):
    if run_id:
        row=conn.execute('''SELECT * FROM evaluation_runs WHERE id=? AND job_id=?
                          AND status!='superseded' ''',
                         (run_id,job_id)).fetchone()
    else:
        row=conn.execute('''SELECT * FROM evaluation_runs WHERE job_id=?
                          AND status!='superseded'
                          AND (? IS NULL OR coaching_version=?)
                          ORDER BY id DESC LIMIT 1''',
                         (job_id,current_coaching_version,current_coaching_version)).fetchone()
    if row is not None and current_coaching_version is not None and row['coaching_version'] != current_coaching_version:
        return None  # Frozen model runs can contribute to analytics, not training.
    return row


def run_position(conn,run_id,position_id,job_id=None,current_coaching_version=None):
    return conn.execute("""SELECT er.id,er.job_id,er.coaching_version,erp.status,erp.attempts
       FROM evaluation_runs er JOIN evaluation_run_positions erp ON erp.run_id=er.id
       WHERE er.id=? AND er.status!='superseded'
         AND erp.position_id=? AND (? IS NULL OR er.job_id=?)
         AND (? IS NULL OR er.coaching_version=?)""",
       (run_id,position_id,job_id,job_id,current_coaching_version,current_coaching_version)).fetchone()


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


def run_history(conn,job_id,current_coaching_version=None):
    rows=conn.execute("""SELECT er.id,er.coaching_version,er.status,er.created_at,er.completed_at,
       COUNT(erp.position_id) AS total,
       COALESCE(SUM(CASE WHEN erp.status='solved' THEN 1 ELSE 0 END),0) AS solved
       FROM evaluation_runs er LEFT JOIN evaluation_run_positions erp ON erp.run_id=er.id
       WHERE er.job_id=? AND er.status!='superseded'
         AND (? IS NULL OR er.coaching_version=?)
       GROUP BY er.id ORDER BY er.id DESC""",
       (job_id,current_coaching_version,current_coaching_version)).fetchall()
    return [dict(row) for row in rows]


def featured_evaluation(conn, job_id, coaching_version):
    """Return an unfinished current-model benchmark for the Lessons/Openings hero."""
    current = current_evaluation_run(conn, job_id, coaching_version)
    if current:
        progress = conn.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status='solved' THEN 1 ELSE 0 END),0) AS solved
            FROM evaluation_run_positions WHERE run_id=?""", (current['id'],)).fetchone()
        total, solved = int(progress['total']), int(progress['solved'])
        # Completion is not a discovery or resume action. The exact run
        # remains accessible from Coach while this model is current.
        if current['status'] == 'completed' or total <= 0 or solved >= total:
            return None
        return {'run_id': current['id'], 'total': total, 'solved': solved,
                'ready': True, 'model': coaching_version,
                'href': f'/trainer/{job_id}?benchmark=1&run_id={current["id"]}'}
    snapshot = conn.execute("""SELECT expected_positions,captured_positions
        FROM coach_benchmark_runs WHERE job_id=? AND coaching_version=?
        ORDER BY id DESC LIMIT 1""", (job_id,coaching_version)).fetchone()
    # Older standalone evaluation fixtures can predate the cohort table.
    cohort_exists = conn.execute("""SELECT 1 FROM sqlite_master
        WHERE type='table' AND name='coach_benchmark_cohorts'""").fetchone()
    cohort = (conn.execute("SELECT sample_size FROM coach_benchmark_cohorts WHERE job_id=?",
                           (job_id,)).fetchone() if cohort_exists else None)
    # Still display 0/36 in the featured slot if run creation has failed.
    # A broken refresh must not make the current evaluation invisible.
    total = int(cohort['sample_size']) if cohort else (int(snapshot['expected_positions']) if snapshot else 0)
    return {'run_id': None, 'total': total, 'solved': 0,
            'ready': False, 'model': coaching_version,
            'href': f'/processes?job_id={job_id}'}


def retire_v33_evaluation_feedback(conn):
    """One-time, deliberately narrow cleanup of v33 evaluation events.

    Do not remove standalone v33 ratings, global learning state, underlying
    snapshots or unrelated coach conversation records.
    """
    runs = [row['id'] for row in conn.execute("""SELECT id FROM evaluation_runs
        WHERE coaching_version='rules-v33' OR coaching_version LIKE 'rules-v33-%'""")]
    if not runs:
        return 0
    marks = ','.join('?' for _ in runs)
    removed = conn.execute(
        f"DELETE FROM feedback_events WHERE evaluation_run_id IN ({marks})", runs).rowcount
    conn.execute(f"UPDATE evaluation_runs SET status='superseded' WHERE id IN ({marks})", runs)
    return removed


def activate_current_evaluation(conn, job_id, coaching_version, taxonomy_version):
    """Idempotently reconcile a *finished* refresh with the active evaluation.

    Safe to call during refresh finalization and from a playlist page after an
    earlier (v104) refresh silently failed evaluation creation. Never edits a
    snapshot referenced by an evaluation run, or any previous model's snapshot.

    Returns a status dictionary for the UI, rather than swallowing exceptions.
    The caller owns commit/rollback and should report `reason` to the user.
    """
    current = current_evaluation_run(conn, job_id, coaching_version)
    if current:
        return {'ready': True, 'run_id': int(current['id']), 'reason': None,
                'state': 'existing'}
    process = conn.execute('''SELECT status FROM metadata_processes WHERE job_id=?''',
                           (job_id,)).fetchone()
    if process is None or process['status'] != 'complete':
        return {'ready': False, 'run_id': None, 'state': 'refresh_needed',
                'reason': 'Complete Coaching refresh to create this model evaluation.'}
    cohort = conn.execute('''SELECT sample_size FROM coach_benchmark_cohorts
        WHERE job_id=?''', (job_id,)).fetchone()
    if cohort is None or not int(cohort['sample_size']):
        return {'ready': False, 'run_id': None, 'state': 'cohort_missing',
                'reason': 'This game list has no benchmark cohort. Start Coaching refresh in Process.'}
    expected = int(cohort['sample_size'])
    eligible = conn.execute('''SELECT COUNT(*) FROM coach_benchmark_positions bp
        JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
        WHERE bp.job_id=? AND tp.coaching_version=?
          AND tp.coach_explanation IS NOT NULL
          AND length(trim(tp.coach_explanation))>0''',
        (job_id, coaching_version)).fetchone()[0]
    if eligible != expected:
        return {'ready': False, 'run_id': None, 'state': 'positions_incomplete',
                'expected': expected, 'current': eligible,
                'reason': (f'{eligible}/{expected} benchmark positions have current-model '
                           'explanations. In Process, choose Prepare and open current evaluation; this can repair saved evidence without replacing the evaluation.')}

    snapshot = conn.execute('''SELECT id,expected_positions,captured_positions
        FROM coach_benchmark_runs WHERE job_id=? AND coaching_version=?
        ORDER BY id DESC LIMIT 1''', (job_id,coaching_version)).fetchone()
    if snapshot is not None:
        # A snapshot with 36 rows can still be stale. Previous versions only
        # repaired *partial* snapshots, leaving the new evaluation unusable
        # when the final refresh changed prose or taxonomy after capture.
        snapshot_count = conn.execute('''SELECT COUNT(*) FROM coach_benchmark_snapshots
            WHERE run_id=?''', (snapshot['id'],)).fetchone()[0]
        mismatched = conn.execute('''SELECT COUNT(*) FROM coach_benchmark_positions bp
            JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
            LEFT JOIN coach_benchmark_snapshots bs
                 ON bs.run_id=? AND bs.position_id=bp.position_id
            LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
            WHERE bp.job_id=? AND (bs.position_id IS NULL
              OR bs.explanation IS NOT tp.coach_explanation
              OR bs.coach_prompt IS NOT tp.coach_prompt
              OR bs.motif_key IS NOT tx.motif_key
              OR bs.context_key IS NOT tx.context_key
              OR bs.move_type_key IS NOT tx.move_type_key)''',
            (snapshot['id'],job_id)).fetchone()[0]
        if (snapshot['expected_positions'] != expected
                or snapshot['captured_positions'] != expected
                or snapshot_count != expected or mismatched):
            referenced = conn.execute('''SELECT 1 FROM evaluation_runs
                WHERE benchmark_run_id=? LIMIT 1''', (snapshot['id'],)).fetchone()
            if referenced:
                return {'ready': False, 'run_id': None, 'state': 'snapshot_frozen',
                        'reason': ('A benchmark snapshot is already referenced by an evaluation. '
                                   'It cannot be overwritten; review this version in Coach.')}
            # This is an unused snapshot for the CURRENT model only. Rebuild
            # transactionally from the fully refreshed position rows.
            conn.execute('DELETE FROM coach_benchmark_snapshots WHERE run_id=?', (snapshot['id'],))
            conn.execute('DELETE FROM coach_benchmark_runs WHERE id=?', (snapshot['id'],))
            snapshot = None

    if snapshot is None:
        from coach_benchmark import snapshot_completed_refresh
        captured = snapshot_completed_refresh(conn,job_id,coaching_version,taxonomy_version)
        if captured != expected:
            return {'ready': False, 'run_id': None, 'state': 'snapshot_incomplete',
                    'reason': f'Only {captured}/{expected} model snapshots were captured. Retry Coaching refresh.'}
    try:
        run_id = ensure_evaluation_run(conn,job_id,coaching_version)
    except ValueError as exc:
        return {'ready': False, 'run_id': None, 'state': 'snapshot_mismatch',
                'reason': f'Could not activate evaluation: {exc}'}
    return {'ready': True, 'run_id': run_id, 'reason': None, 'state': 'created'}
