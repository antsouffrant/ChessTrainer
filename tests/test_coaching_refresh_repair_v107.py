"""Regression: old refresh falsely completed at 0/36 must be recoverable."""
import unittest
from tests.test_evaluation_activation_v105 import EvaluationActivation, V34, V35
from evaluation_runs import activate_current_evaluation, current_evaluation_run
from coaching.coaching_refresh.repair import repair_cohort_copy


class RepairMissingVersionedCopies(unittest.TestCase):
    def setUp(self):
        fixture=EvaluationActivation(methodName="test_complete_refresh_activates_new_model_at_zero_of_36")
        fixture.setUp()
        self.conn=fixture.conn
        self.old_run=fixture.old_run
        self.addCleanup(self.conn.close)
        self.conn.execute("""UPDATE training_positions SET coaching_version=NULL,
                          coach_explanation=NULL,coach_prompt=NULL WHERE job_id=1""")

    @staticmethod
    def rebuild(conn,pid):
        conn.execute("""UPDATE training_positions SET coaching_version=?,
            coach_explanation=?, coach_prompt=? WHERE id=?""",
            (V35,f'{pid}: distinct v35 explanation',f'{pid}: v35 prompt',pid))
        return True

    def test_all_missing_copies_recovered_and_new_run_created(self):
        result=repair_cohort_copy(self.conn,1,V35,reclassify=lambda *a: None,
                                  rebuild=self.rebuild,validate=lambda row:None)
        self.assertEqual(result['total'],36)
        self.assertEqual(result['ready'],36)
        self.assertEqual(result['repaired'],36)
        self.assertEqual(result['failures'],[])
        activation=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertTrue(activation['ready'],activation)
        self.assertEqual(activation['state'],'created')
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evaluation_run_positions WHERE run_id=? AND status='pending'",(activation['run_id'],)).fetchone()[0],36)
        self.assertEqual(self.conn.execute('SELECT status FROM evaluation_runs WHERE id=?',
                         (self.old_run,)).fetchone()[0], 'active')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_benchmark_snapshots bs JOIN evaluation_runs er ON er.benchmark_run_id=bs.run_id WHERE er.id=?',(self.old_run,)).fetchone()[0],36)

    def test_bad_position_is_rolled_back_and_run_not_created(self):
        def classify(conn,pid,row):
            conn.execute('UPDATE training_positions SET category=? WHERE id=?',('temporary',pid))
            if pid==10:
                raise ValueError('Cannot classify position')
        result=repair_cohort_copy(self.conn,1,V35,reclassify=classify,
                                  rebuild=self.rebuild,validate=lambda row:None)
        self.assertEqual(result['ready'],35)
        self.assertEqual(result['failures'][0]['id'],10)
        self.assertNotEqual(self.conn.execute('SELECT category FROM training_positions WHERE id=10').fetchone()[0],'temporary')
        self.assertEqual(activate_current_evaluation(self.conn,1,V35,'v35-tx')['state'],'positions_incomplete')
        self.assertIsNone(current_evaluation_run(self.conn,1,V35))

    def test_existing_v35_copy_not_regenerated(self):
        self.conn.execute('''UPDATE training_positions SET coaching_version=?,
            coach_explanation='keep v35 result' WHERE id=1''',(V35,))
        called=[]
        def rebuild(conn,pid):
            called.append(pid)
            return self.rebuild(conn,pid)
        result=repair_cohort_copy(self.conn,1,V35,reclassify=lambda *a: None,
                                  rebuild=rebuild,validate=lambda row:None)
        self.assertEqual(result['ready'],36)
        self.assertEqual(result['repaired'],35)
        self.assertNotIn(1,called)
        self.assertEqual(self.conn.execute('SELECT coach_explanation FROM training_positions WHERE id=1').fetchone()[0],'keep v35 result')

    def test_no_repair_changes_existing_frozen_v34_run_or_ledger(self):
        before=self.conn.execute('SELECT * FROM evaluation_runs WHERE id=?',(self.old_run,)).fetchone()
        repair_cohort_copy(self.conn,1,V35,reclassify=lambda *a: None,
                          rebuild=self.rebuild,validate=lambda row:None)
        after=self.conn.execute('SELECT * FROM evaluation_runs WHERE id=?',(self.old_run,)).fetchone()
        self.assertEqual(tuple(before),tuple(after))

if __name__=='__main__': unittest.main()
