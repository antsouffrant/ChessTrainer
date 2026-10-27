"""Safe current-model evaluation repair from saved engine analysis.

Does not invoke Stockfish, clear cache, alter historical evaluation runs,
or create a new cohort. Used only after a refresh has stopped and only for
existing fixed-cohort positions missing the current model's coaching copy.
"""
from __future__ import annotations

from coaching.coaching_refresh.coaching_copy_refresh import rebuild_coaching_copy


def repair_cohort_copy(conn, job_id, coaching_version, *, reclassify=None,
                       rebuild=None, validate=None):
    """Repair unfinished *current* model copy on the immutable evaluation cohort.

    Returns a record with position IDs and useful error diagnostics. Each
    position is transactional: if reconstruction fails, no half-written
    taxonomy/explanation for that position is retained.
    """
    if reclassify is None:
        from analysis import _refresh_position_labels
        reclassify = lambda c, pid, row: _refresh_position_labels(
            c, pid, row, regenerate_copy=False)
    if rebuild is None:
        rebuild = rebuild_coaching_copy
    if validate is None:
        def validate(row):
            import chess
            board=chess.Board(row['fen'])
            move=chess.Move.from_uci(row['best_move_uci'])
            if move not in board.legal_moves:
                raise ValueError('Stored best move is illegal in this position')
    cohort = conn.execute('''SELECT bp.position_id FROM coach_benchmark_positions bp
        WHERE bp.job_id=? ORDER BY bp.ordinal''', (job_id,)).fetchall()
    done=[]
    rewritten=0
    issues=[]
    for entry in cohort:
        pid=int(entry['position_id'])
        row=conn.execute('SELECT * FROM training_positions WHERE id=? AND job_id=?',
                         (pid,job_id)).fetchone()
        if row is None:
            issues.append({'id':pid,'error':'Training position is missing'})
            continue
        if row['coaching_version']==coaching_version and str(row['coach_explanation'] or '').strip():
            done.append(pid)
            continue
        conn.execute('SAVEPOINT coaching_position_repair')
        try:
            validate(row)
            # Recompute labels/taxonomy from stored deep-analysis PVs and FEN.
            # The cached *previous-version* text must never be relabeled.
            reclassify(conn,pid,row)
            if not rebuild(conn,pid):
                raise ValueError('Rebuild returned no coaching copy')
            check=conn.execute('''SELECT coaching_version,coach_explanation
                FROM training_positions WHERE id=?''',(pid,)).fetchone()
            if (check is None or check['coaching_version']!=coaching_version
                    or not str(check['coach_explanation'] or '').strip()):
                raise ValueError('No verified current-version explanation was stored')
            conn.execute('RELEASE coaching_position_repair')
            done.append(pid)
            rewritten += 1
        except Exception as exc:
            conn.execute('ROLLBACK TO coaching_position_repair')
            conn.execute('RELEASE coaching_position_repair')
            issues.append({'id':pid,'error':f'{type(exc).__name__}: {exc}'[:250]})
    return {'total':len(cohort),'ready':len(done),'repaired':rewritten,'failures':issues}
