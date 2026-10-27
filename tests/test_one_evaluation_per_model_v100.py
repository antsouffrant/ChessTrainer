"""Source-of-truth evaluation semantics and migration from v99 databases."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path

from coach_benchmark import (ensure_cohort, snapshot_completed_refresh,
                             evaluation_run_metrics, benchmark_comparison)
from evaluation_runs import (start_evaluation_run, ensure_evaluation_run,
                             current_evaluation_run, resolve_run, run_position,
                             record_evaluation_attempt, run_history)
from feedback_history import append_feedback


def schema():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'db.py').read_text())
    return next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))


class OneEvaluationPerModel(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        for i in (1,2):
            self.conn.execute('''INSERT INTO training_positions(id,job_id,category,learning_mode,
                fen,user_color,move_number,learned,coaching_version,coach_explanation,best_move_uci)
                VALUES(?,1,'mistake','mistakes',?,'white',12,0,'v34','Current explanation','e2e4')''',
                (i,f'8/8/8/8/8/8/8/8 w - - {i} 1'))
        ensure_cohort(self.conn,1,target=2)
        snapshot_completed_refresh(self.conn,1,'v34','taxonomy-1')

    def test_explicit_replacement_preserves_history_but_removes_old_authority(self):
        first=start_evaluation_run(self.conn,1,'v34')
        record_evaluation_attempt(self.conn,first,1,True,'e2e4')
        append_feedback(self.conn,1,'explanation',-1,continuation='solving',
                        coaching_version='v34',evaluation_run_id=first)
        second=start_evaluation_run(self.conn,1,'v34')
        self.assertNotEqual(first,second)
        self.assertIsNone(resolve_run(self.conn,1,first))
        self.assertIsNone(run_position(self.conn,first,1))
        self.assertEqual(resolve_run(self.conn,1)['id'],second)
        self.assertEqual(len(run_history(self.conn,1)),1)
        self.assertEqual(self.conn.execute('SELECT status FROM evaluation_runs WHERE id=?',(first,)).fetchone()[0],'superseded')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM feedback_events WHERE evaluation_run_id=?',(first,)).fetchone()[0],1)
        self.assertEqual(evaluation_run_metrics(self.conn,1)[0]['feedback_positions'],0)
        with self.assertRaises(ValueError):
            record_evaluation_attempt(self.conn,first,2,True,'e2e4')
        for position in (1,2):
            record_evaluation_attempt(self.conn,second,position,True,'e2e4')
        self.assertEqual(evaluation_run_metrics(self.conn,1)[0]['solved'],2)

    def test_refresh_does_not_reset_existing_model(self):
        current=start_evaluation_run(self.conn,1,'v34')
        record_evaluation_attempt(self.conn,current,1,True,'e2e4')
        self.assertEqual(ensure_evaluation_run(self.conn,1,'v34'),current)
        self.assertEqual(run_position(self.conn,current,1)['status'],'solved')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM evaluation_runs').fetchone()[0],1)

    def test_new_model_has_its_own_evaluation_and_can_be_compared(self):
        a=start_evaluation_run(self.conn,1,'v34')
        self.conn.execute("UPDATE training_positions SET coaching_version='v35',coach_explanation='Other explanation'")
        snapshot_completed_refresh(self.conn,1,'v35','taxonomy-2')
        b=ensure_evaluation_run(self.conn,1,'v35')
        self.assertNotEqual(a,b)
        self.assertEqual(len(run_history(self.conn,1)),2)
        self.assertEqual(len(benchmark_comparison(self.conn,1,'v34','v35')['comparisons']),1)
        self.assertIsNone(benchmark_comparison(self.conn,1,'v34','v35')['comparisons'][0]['baseline_approval_pct'])


class ExistingDatabaseMigration(unittest.TestCase):
    def test_existing_run_two_becomes_authoritative_without_losing_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trainer.sqlite3'
            conn=sqlite3.connect(path)
            conn.row_factory=sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            try:
                conn.executescript(schema())
                conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
                conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
                conn.execute("INSERT INTO coach_benchmark_cohorts(job_id,source_count,sample_size) VALUES(1,2,2)")
                conn.execute("INSERT INTO coach_benchmark_runs(job_id,coaching_version,taxonomy_version,expected_positions,captured_positions) VALUES(1,'v34','t',2,2)")
                for i in (1,2):
                    conn.execute("INSERT INTO training_positions(id,job_id,category,learning_mode,fen,user_color,move_number,coaching_version,best_move_uci) VALUES(?,1,'mistake','mistakes',?,'white',12,'v34','e2e4')",(i,f'FEN-{i}'))
                for run,status in ((1,'active'),(2,'completed')):
                    conn.execute("INSERT INTO evaluation_runs(id,job_id,benchmark_run_id,coaching_version,status) VALUES(?,1,1,'v34',?)",(run,status))
                    for pos in (1,2):
                        conn.execute("INSERT INTO evaluation_run_positions(run_id,position_id,status) VALUES(?,?,?)",(run,pos,'solved' if run==2 or pos==1 else 'pending'))
                conn.execute("INSERT INTO feedback_positions(position_key,account_id,provider,username,game_id,board_identity) VALUES('p1',1,'lichess','tester','g1','board')")
                for run,rating in ((1,1),(2,-1)):
                    conn.execute("INSERT INTO feedback_events(position_key,source_position_id,account_id,feedback_type,rating,coaching_version,evaluation_run_id) VALUES('p1',1,1,'explanation',?,'v34',?)",(rating,run))
                conn.commit()
                # Read and execute the actual v100 migration statements from
                # db.init_db, without importing python-chess-dependent runtime.
                tree=ast.parse((Path(__file__).resolve().parents[1]/'db.py').read_text())
                init=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='init_db')
                statements=sorted((n.lineno,n.args[0].value) for n in ast.walk(init)
                    if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                    and n.func.attr=='execute' and n.args
                    and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str)
                    and ('UPDATE evaluation_runs SET status' in n.args[0].value or 'idx_evaluation_one_current_model' in n.args[0].value))
                self.assertEqual(len(statements),2)
                for _ in range(2):
                    for _,sql in statements: conn.execute(sql)
                    conn.commit()
                self.assertEqual([tuple(x) for x in conn.execute('SELECT id,status FROM evaluation_runs ORDER BY id')],[(1,'superseded'),(2,'completed')])
                self.assertEqual(len(run_history(conn,1)),1)
                self.assertEqual(run_history(conn,1)[0]['solved'],2)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM feedback_events').fetchone()[0],2)
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute("INSERT INTO evaluation_runs(job_id,benchmark_run_id,coaching_version) VALUES(1,1,'v34')")
            finally:
                conn.close()

if __name__=='__main__': unittest.main()
