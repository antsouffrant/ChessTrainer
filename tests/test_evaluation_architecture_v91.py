"""SQLite-only migration, run isolation and matched model comparisons."""
import ast
from pathlib import Path
import sqlite3
import unittest

from coach_benchmark import ensure_cohort, snapshot_completed_refresh, benchmark_comparison
from evaluation_runs import (start_evaluation_run,resolve_run,run_position,
                             record_evaluation_attempt,evaluation_manifest,run_history)


def original_schema():
    tree=ast.parse((Path(__file__).parent.parent/'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in node.targets))


class EvaluationArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(original_schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','example')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'2026','blitz')")
        for id_ in range(1,5):
            self.conn.execute('''INSERT INTO training_positions
               (id,job_id,category,learning_mode,fen,user_color,move_number,best_move_uci,
                learned,coaching_version,coach_prompt,coach_explanation)
               VALUES(?,1,'mistake','mistakes',?,'white',12,'e2e4',?,?,?,?)''',
               (id_,f'fake-fen-{id_}',int(id_%2==0),'v34',f'prompt-{id_}',f'v34 explanation {id_}'))
        ensure_cohort(self.conn,1,target=4)
        self.assertEqual(snapshot_completed_refresh(self.conn,1,'v34','3.4'),4)

    def test_replacement_run_ignores_global_learning_and_archives_prior(self):
        one=start_evaluation_run(self.conn,1,'v34')
        self.assertEqual([r['learned'] for r in evaluation_manifest(self.conn,1,one)],[0]*4)
        first=evaluation_manifest(self.conn,1,one)[0]['id']
        record_evaluation_attempt(self.conn,one,first,False,'d2d4')
        record_evaluation_attempt(self.conn,one,first,True,'e2e4')
        self.assertEqual(run_position(self.conn,one,first)['status'],'solved')
        self.assertEqual(run_position(self.conn,one,first)['attempts'],2)
        with self.assertRaises(ValueError):record_evaluation_attempt(self.conn,one,first,True,'e2e4')
        self.assertEqual(self.conn.execute('SELECT learned FROM training_positions WHERE id=?',(first,)).fetchone()[0],int(first%2==0))
        two=start_evaluation_run(self.conn,1,'v34')
        self.assertNotEqual(one,two)
        self.assertEqual(run_position(self.conn,two,first)['status'],'pending')
        self.assertIsNone(run_position(self.conn,one,first))
        self.assertIsNone(resolve_run(self.conn,1,one))
        self.assertEqual(self.conn.execute('SELECT status FROM evaluation_runs WHERE id=?',(one,)).fetchone()[0],'superseded')
        self.assertEqual(len(run_history(self.conn,1)),1)
        self.assertEqual(len(evaluation_manifest(self.conn,1,two)),4)
        self.assertEqual(run_history(self.conn,1)[0]['id'],two)

    def test_version_change_rejects_old_scoring_but_keeps_past_runs(self):
        old=start_evaluation_run(self.conn,1)
        self.conn.execute("UPDATE training_positions SET coaching_version='v35', coach_explanation='updated' WHERE job_id=1")
        with self.assertRaisesRegex(ValueError,'version'):
            start_evaluation_run(self.conn,1,'v34')
        snapshot_completed_refresh(self.conn,1,'v35','3.5')
        new=start_evaluation_run(self.conn,1,'v35')
        self.assertEqual(resolve_run(self.conn,1,new)['coaching_version'],'v35')
        self.assertEqual(run_position(self.conn,old,1)['coaching_version'],'v34')

    def test_comparison_snapshots_changes_and_paired_votes(self):
        self.conn.execute("UPDATE training_positions SET coaching_version='v35', coach_explanation='updated' WHERE job_id=1")
        snapshot_completed_refresh(self.conn,1,'v35','3.5')
        self.conn.execute("INSERT INTO feedback_positions(position_key,account_id,provider,username,game_id,board_identity) VALUES('pos',1,'lichess','example','game','board')")
        def vote(version,rating,move='solving'):
            # Stable position identity is independent of the disposable cache.
            self.conn.execute('''INSERT INTO feedback_events(position_key,source_position_id,account_id,
               feedback_type,rating,coaching_version,continuation_id)
               VALUES('pos',1,1,'explanation',?,?,NULL)''',(rating,version))
        # Two votes on the first version collapse to the latest. No other
        # position is counted as rated by implication.
        vote('v34',-1);vote('v34',1);vote('v35',-1)
        result=benchmark_comparison(self.conn,1,'v34','v35')
        row=result['comparisons'][0]
        self.assertEqual(row['shared_snapshots'],4)
        self.assertEqual(row['explanation_change_count'],4)
        self.assertEqual(row['explanation_change_pct'],100.0)
        self.assertEqual(row['paired_ratings'],0)  # No evaluations: old unscoped votes aren't benchmark ratings.
        self.assertIsNone(row['baseline_approval_pct'])
        self.assertIsNone(row['comparison_approval_pct'])
        self.assertEqual(len(benchmark_comparison(self.conn,1,'v34','all')['comparisons']),1)

    def test_feedback_is_scoped_to_evaluation_run(self):
        from feedback_history import append_feedback,current_feedback
        first=start_evaluation_run(self.conn,1)
        second=start_evaluation_run(self.conn,1)
        # No ratings are invented for the second evaluation.
        append_feedback(self.conn,1,'explanation',1,continuation='solving',
                        coaching_version='v34',evaluation_run_id=first)
        self.assertEqual(len(current_feedback(self.conn,1,version='v34',evaluation_run_id=first)),1)
        self.assertEqual(len(current_feedback(self.conn,1,version='v34',evaluation_run_id=second)),0)
        append_feedback(self.conn,1,'explanation',-1,continuation='solving',
                        coaching_version='v34',evaluation_run_id=second)
        self.assertEqual(current_feedback(self.conn,1,version='v34',evaluation_run_id=first)[0]['rating'],1)
        self.assertEqual(current_feedback(self.conn,1,version='v34',evaluation_run_id=second)[0]['rating'],-1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM feedback_events').fetchone()[0],2)

    def test_cache_deletion_does_not_delete_run_or_feedback(self):
        run_id=start_evaluation_run(self.conn,1)
        self.conn.execute("UPDATE training_positions SET coach_explanation=NULL WHERE job_id=1")
        self.assertEqual(resolve_run(self.conn,1,run_id)['coaching_version'],'v34')
        self.assertEqual(len(evaluation_manifest(self.conn,1,run_id)),4)
        self.assertEqual(len(benchmark_comparison(self.conn,1)['versions']),1)


if __name__=='__main__':unittest.main()
