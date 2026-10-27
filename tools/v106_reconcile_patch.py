from pathlib import Path
root=Path('/mnt/data/chess_v106')
p=root/'evaluation_runs.py'
s=p.read_text()
start=s.index("    snapshot = conn.execute('''SELECT id,expected_positions,captured_positions")
end=s.index('    if snapshot is None:',start)
s=s[:start]+'''    snapshot = conn.execute(\'\'\'SELECT id,expected_positions,captured_positions
        FROM coach_benchmark_runs WHERE job_id=? AND coaching_version=?
        ORDER BY id DESC LIMIT 1\'\'\', (job_id,coaching_version)).fetchone()
    if snapshot is not None:
        # A snapshot with 36 rows can still be stale. Previous versions only
        # repaired *partial* snapshots, leaving the new evaluation unusable
        # when the final refresh changed prose or taxonomy after capture.
        snapshot_count = conn.execute(\'\'\'SELECT COUNT(*) FROM coach_benchmark_snapshots
            WHERE run_id=?\'\'\', (snapshot['id'],)).fetchone()[0]
        mismatched = conn.execute(\'\'\'SELECT COUNT(*) FROM coach_benchmark_positions bp
            JOIN training_positions tp ON tp.id=bp.position_id AND tp.job_id=bp.job_id
            LEFT JOIN coach_benchmark_snapshots bs
                 ON bs.run_id=? AND bs.position_id=bp.position_id
            LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
            WHERE bp.job_id=? AND (bs.position_id IS NULL
              OR bs.explanation IS NOT tp.coach_explanation
              OR bs.coach_prompt IS NOT tp.coach_prompt
              OR bs.motif_key IS NOT tx.motif_key
              OR bs.context_key IS NOT tx.context_key
              OR bs.move_type_key IS NOT tx.move_type_key)\'\'\',
            (snapshot['id'],job_id)).fetchone()[0]
        if (snapshot['expected_positions'] != expected
                or snapshot['captured_positions'] != expected
                or snapshot_count != expected or mismatched):
            referenced = conn.execute(\'\'\'SELECT 1 FROM evaluation_runs
                WHERE benchmark_run_id=? LIMIT 1\'\'\', (snapshot['id'],)).fetchone()
            if referenced:
                return {'ready': False, 'run_id': None, 'state': 'snapshot_frozen',
                        'reason': ('A benchmark snapshot is already referenced by an evaluation. '
                                   'It cannot be overwritten; review this version in Coach.')}
            # This is an unused snapshot for the CURRENT model only. Rebuild
            # transactionally from the fully refreshed position rows.
            conn.execute('DELETE FROM coach_benchmark_snapshots WHERE run_id=?', (snapshot['id'],))
            conn.execute('DELETE FROM coach_benchmark_runs WHERE id=?', (snapshot['id'],))
            snapshot = None

'''+s[end:]
p.write_text(s)

p=root/'app.py'; s=p.read_text()
marker="@app.post('/api/jobs/<int:job_id>/evaluations')\ndef create_evaluation(job_id):"
assert marker in s
endpoint='''@app.post('/api/jobs/<int:job_id>/evaluations/activate')
def activate_evaluation(job_id):
    """Safely open/create the CURRENT model evaluation without replacing it.

    Retryable reconciliation for refreshes that finished before a run was
    created. Never resets a run, an attempt, feedback, or a frozen model.
    """
    with connect() as conn:
        if not conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?',(job_id,)).fetchone():
            return jsonify({'error':'Game list not found'}),404
        activation=activate_current_evaluation(conn,job_id,COACHING_VERSION,TAXONOMY_VERSION)
        if not activation['ready']:
            return jsonify({'error':activation['reason'], 'state':activation['state'],
                            'expected':activation.get('expected'),
                            'current':activation.get('current')}),409
        if activation['state']=='created':
            conn.commit()
        run_id=activation['run_id']
        return jsonify({'ok':True,'state':activation['state'], 'run_id':run_id,
                        'url':f'/trainer/{job_id}?benchmark=1&run_id={run_id}'})


'''
s=s.replace(marker,endpoint+marker,1)
# The detailed list has a current-model-only evaluation and a recovery action.
needle="                    item['evaluation_run'] = history[0] if history else None\n                    details.append(item)"
rep="""                    item['evaluation_run'] = history[0] if history else None
                    item['current_coaching_model'] = COACHING_VERSION
                    feature = featured_evaluation(conn,row['id'],COACHING_VERSION)
                    item['evaluation_pending'] = (feature is not None and item['evaluation_run'] is None)
                    item['evaluation_expected'] = feature['total'] if feature else None
                    details.append(item)"""
assert needle in s
s=s.replace(needle,rep,1)
p.write_text(s)
print('patched evaluation run reconciliation and idempotent activation route')
