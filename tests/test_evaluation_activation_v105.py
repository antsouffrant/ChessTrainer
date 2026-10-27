"""Evaluation creation and v104 partial-snapshot recovery, without Stockfish/Flask."""
import ast
import sqlite3
import unittest
from pathlib import Path

from coach_benchmark import ensure_cohort, snapshot_completed_refresh
from evaluation_runs import (activate_current_evaluation, current_evaluation_run,
                             featured_evaluation, start_evaluation_run,
                             record_evaluation_attempt)


ROOT = Path(__file__).resolve().parents[1]
V34 = 'rules-v34-version-scoped-cache'
V35 = 'rules-v35-decision-findings'


def schema():
    tree=ast.parse((ROOT/'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(n,ast.Name) and n.id=='SCHEMA' for n in node.targets))


class EvaluationActivation(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        self.conn.executemany('''INSERT INTO training_positions
            (id,job_id,category,learning_mode,fen,user_color,move_number,
             coaching_version,coach_explanation,best_move_uci)
            VALUES (?,1,'mistake','mistakes',?,'white',12,?,?, 'e2e4')''',
            [(i,f'FEN-{i}',V34,f'v34 explanation {i}') for i in range(1,37)])
        ensure_cohort(self.conn,1)
        self.assertEqual(snapshot_completed_refresh(self.conn,1,V34,'v34-tx'),36)
        self.old_run=start_evaluation_run(self.conn,1,V34)
        record_evaluation_attempt(self.conn,self.old_run,1,True,'e2e4')
        self.conn.execute("UPDATE training_positions SET coaching_version=?,coach_explanation='v35 explanation'",(V35,))
        self.conn.execute("INSERT INTO metadata_processes(job_id,status,processed,total) VALUES(1,'complete',36,36)")
        self.addCleanup(self.conn.close)

    def test_complete_refresh_activates_new_model_at_zero_of_36(self):
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(result['state'],'created')
        self.assertTrue(result['ready'])
        featured=featured_evaluation(self.conn,1,V35)
        self.assertEqual((featured['solved'],featured['total']),(0,36))
        self.assertIn(f'run_id={result["run_id"]}',featured['href'])
        self.assertEqual(activate_current_evaluation(self.conn,1,V35,'v35-tx')['run_id'],result['run_id'])
        self.assertEqual(self.conn.execute('SELECT status FROM evaluation_runs WHERE id=?',(self.old_run,)).fetchone()[0],'active')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM evaluation_run_positions WHERE run_id=?',(result['run_id'],)).fetchone()[0],36)

    def test_repair_partial_v104_snapshot_only_when_unused(self):
        old=self.conn.execute('''INSERT INTO coach_benchmark_runs
          (job_id,coaching_version,taxonomy_version,expected_positions,captured_positions)
          VALUES(1,?,?,36,12)''',(V35,'v35-tx')).lastrowid
        self.conn.execute('''INSERT INTO coach_benchmark_snapshots
          (run_id,position_id,explanation) VALUES(?,?,?)''',(old,1,'partial'))
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertTrue(result['ready'])
        row=self.conn.execute('SELECT expected_positions,captured_positions FROM coach_benchmark_runs WHERE job_id=1 AND coaching_version=?',(V35,)).fetchone()
        self.assertEqual(tuple(row),(36,36))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_benchmark_snapshots WHERE run_id=?',(old,)).fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT captured_positions FROM coach_benchmark_runs WHERE id=(SELECT benchmark_run_id FROM evaluation_runs WHERE id=?)',(self.old_run,)).fetchone()[0],36)

    def test_partial_position_refresh_is_not_silently_snapshot_or_activated(self):
        self.conn.execute('UPDATE training_positions SET coaching_version=NULL WHERE id=36')
        self.assertEqual(snapshot_completed_refresh(self.conn,1,V35,'v35-tx'),0)
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertFalse(result['ready'])
        self.assertEqual(result['state'],'positions_incomplete')
        self.assertIn('35/36',result['reason'])
        self.assertEqual(featured_evaluation(self.conn,1,V35)['total'],36)
        self.assertFalse(featured_evaluation(self.conn,1,V35)['ready'])
        self.assertIsNone(current_evaluation_run(self.conn,1,V35))

    def test_running_refresh_does_not_activate(self):
        self.conn.execute("UPDATE metadata_processes SET status='running' WHERE job_id=1")
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(result['state'],'refresh_needed')
        self.assertIsNone(current_evaluation_run(self.conn,1,V35))

    def test_completed_run_not_reset_by_page_reconciliation(self):
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        run=result['run_id']
        self.conn.execute("UPDATE evaluation_runs SET status='completed' WHERE id=?",(run,))
        self.conn.execute("UPDATE evaluation_run_positions SET status='solved' WHERE run_id=?",(run,))
        current=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(current['run_id'],run)
        self.assertEqual(current['state'],'existing')
        self.assertIsNone(featured_evaluation(self.conn,1,V35))

    def test_old_evaluated_partial_snapshot_is_not_rewritten(self):
        snap=self.conn.execute('''INSERT INTO coach_benchmark_runs
          (job_id,coaching_version,taxonomy_version,expected_positions,captured_positions)
          VALUES(1,?,?,36,12)''',(V35,'v35-tx')).lastrowid
        self.conn.execute('''INSERT INTO evaluation_runs(job_id,benchmark_run_id,coaching_version,status)
          VALUES(1,?,?,'superseded')''',(snap,V35))
        result=activate_current_evaluation(self.conn,1,V35,'v35-tx')
        self.assertEqual(result['state'],'snapshot_frozen')
        self.assertEqual(self.conn.execute('SELECT captured_positions FROM coach_benchmark_runs WHERE id=?',(snap,)).fetchone()[0],12)


if __name__=='__main__':
    unittest.main()
