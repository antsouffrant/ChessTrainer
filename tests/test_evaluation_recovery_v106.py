"""v106: recover a current-model run without replacing prior-model feedback."""
import unittest

from tests.test_evaluation_activation_v105 import EvaluationActivation, V34, V35
from evaluation_runs import activate_current_evaluation, current_evaluation_run, featured_evaluation


class RecoverUnreferencedCurrentModelSnapshot(EvaluationActivation):
    def test_full_stale_explanations_rebuilt_without_replacing_v34(self):
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM evaluation_run_positions WHERE run_id=? AND status=\'solved\'',(self.old_run,)).fetchone()[0],1)
        snapshot=self.conn.execute('''INSERT INTO coach_benchmark_runs
            (job_id,coaching_version,taxonomy_version,expected_positions,captured_positions)
            VALUES(1,?,?,36,36)''',(V35,'v35-tx')).lastrowid
        self.conn.executemany('''INSERT INTO coach_benchmark_snapshots
            (run_id,position_id,explanation) VALUES(?,?,'stale copied explanation')''',
            [(snapshot,i) for i in range(1,37)])
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(result['state'],'created',result)
        run=current_evaluation_run(self.conn,1,V35)
        self.assertEqual(run['id'],result['run_id'])
        self.assertNotEqual(run['benchmark_run_id'],snapshot)
        self.assertEqual(self.conn.execute('''SELECT COUNT(*) FROM coach_benchmark_snapshots
            WHERE run_id=? AND explanation='v35 explanation' ''',
            (run['benchmark_run_id'],)).fetchone()[0],36)
        self.assertEqual(self.conn.execute('''SELECT COUNT(*) FROM evaluation_run_positions
            WHERE run_id=? AND status='solved' ''',(run['id'],)).fetchone()[0],0)
        self.assertEqual(self.conn.execute('''SELECT COUNT(*) FROM evaluation_run_positions
            WHERE run_id=? AND status='solved' ''',(self.old_run,)).fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT coaching_version FROM evaluation_runs WHERE id=?',(self.old_run,)).fetchone()[0],V34)
        self.assertTrue(featured_evaluation(self.conn,1,V35)['ready'])
        self.assertIn(f'run_id={run["id"]}',featured_evaluation(self.conn,1,V35)['href'])

    def test_matching_full_snapshot_reused(self):
        from coach_benchmark import snapshot_completed_refresh
        self.assertEqual(snapshot_completed_refresh(self.conn,1,V35,'v35-tx'),36)
        before=self.conn.execute('''SELECT id FROM coach_benchmark_runs
            WHERE job_id=1 AND coaching_version=?''',(V35,)).fetchone()[0]
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertTrue(result['ready'])
        self.assertEqual(self.conn.execute('''SELECT benchmark_run_id FROM evaluation_runs
            WHERE id=?''',(result['run_id'],)).fetchone()[0],before)
        self.assertEqual(activate_current_evaluation(self.conn,1,V35,'v35-tx')['run_id'],result['run_id'])

    def test_full_stale_taxonomy_rebuilt(self):
        self.conn.executemany("""INSERT INTO learning_concepts(key,name,family,description)
            VALUES(?,?,?,?)""", [
            ('double_attack','Double attack','Tactics','Attack two targets'),
            ('pin','Pin','Tactics','Pinned piece')])
        self.conn.execute("""INSERT INTO position_motif_taxonomy
            (position_id, context_key, move_type_key, motif_key, taxonomy_version)
            VALUES (1,'attack','tactical','double_attack','v35-tx')""")
        from coach_benchmark import snapshot_completed_refresh
        self.assertEqual(snapshot_completed_refresh(self.conn,1,V35,'v35-tx'),36)
        self.conn.execute('''UPDATE position_motif_taxonomy SET motif_key='pin'
            WHERE position_id=1''')
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertTrue(result['ready'])
        motif=self.conn.execute('''SELECT bs.motif_key FROM coach_benchmark_snapshots bs
            JOIN evaluation_runs er ON bs.run_id=er.benchmark_run_id
            WHERE er.id=? AND bs.position_id=1''',(result['run_id'],)).fetchone()[0]
        self.assertEqual(motif,'pin')

    def test_partial_refresh_reports_exact_problem_without_creating_run(self):
        self.conn.execute('''UPDATE training_positions SET coaching_version=?
            WHERE id=36''',(V34,))
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(result['state'],'positions_incomplete')
        self.assertIn('35/36',result['reason'])
        self.assertIsNone(current_evaluation_run(self.conn,1,V35))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM evaluation_runs WHERE id=?',(self.old_run,)).fetchone()[0],1)


if __name__=='__main__': unittest.main()
