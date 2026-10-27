"""Regression: evaluation completion and feedback are run-scoped, not version-scoped."""
import ast
from pathlib import Path
import sqlite3
import unittest

from coach_benchmark import (
    ensure_cohort, snapshot_completed_refresh, benchmark_comparison,
    evaluation_run_metrics,
)
from evaluation_runs import start_evaluation_run, record_evaluation_attempt
from feedback_history import append_feedback


def schema():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'db.py').read_text())
    return next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))


class EvaluationReportingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema())
        self.db.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        for i in range(1,37):
            self.db.execute('''INSERT INTO training_positions
                (id,job_id,game_id,category,learning_mode,fen,user_color,move_number,
                 learned,coaching_version,coach_explanation,best_move_uci)
                VALUES (?,1,?,'mistake','mistakes',?,'white',12,0,'v34',?,'e2e4')''',
                (i, f'game-{i}',f'8/8/8/8/8/8/8/8 w - - {i} 1',f'explanation {i}'))
        ensure_cohort(self.db,1,target=36)
        self.assertEqual(snapshot_completed_refresh(self.db,1,'v34','3.4'),36)
        self.one=start_evaluation_run(self.db,1,'v34')
        self.two=start_evaluation_run(self.db,1,'v34')
        self.positions=[r['position_id'] for r in self.db.execute(
            'SELECT position_id FROM coach_benchmark_positions WHERE job_id=1 ORDER BY ordinal')]

    def feedback(self,run,position,rating,kind='explanation'):
        append_feedback(self.db,position,kind,rating,
                        continuation='solving' if kind=='explanation' else None,
                        coaching_version='v34',evaluation_run_id=run)

    def test_second_run_replaces_first_as_authoritative_model_evaluation(self):
        p=self.positions[0]
        self.assertIsNone(self.db.execute("SELECT id FROM evaluation_runs WHERE id=? AND status!='superseded'",(self.one,)).fetchone())
        for position in self.positions:
            record_evaluation_attempt(self.db,self.two,position,True,'e2e4')
        self.feedback(self.one,p,-1)  # archival evidence is not a current vote
        self.feedback(self.two,p,1)
        self.feedback(self.two,self.positions[1],-1)
        metrics=evaluation_run_metrics(self.db,1)
        self.assertEqual(len(metrics),1)
        self.assertEqual(metrics[0]['id'],self.two)
        self.assertEqual((metrics[0]['solved'],metrics[0]['total']),(36,36))
        self.assertEqual(metrics[0]['feedback_positions'],2)
        self.assertEqual(metrics[0]['explanation_approval_pct'],50.0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM feedback_events').fetchone()[0],3)
        response=benchmark_comparison(self.db,1)
        self.assertEqual(len(response['evaluation_runs']),1)
        self.assertEqual(response['evaluation_runs'][0]['id'],self.two)
        self.assertEqual(response['comparisons'],[])

    def test_archived_run_not_accessible_and_not_counted(self):
        p=self.positions[0]
        with self.assertRaisesRegex(ValueError,'does not belong'):
            record_evaluation_attempt(self.db,self.one,p,True,'e2e4')
        self.feedback(self.one,p,1)
        self.assertEqual(evaluation_run_metrics(self.db,1)[0]['feedback_positions'],0)
        self.feedback(self.two,p,-1)
        self.feedback(self.two,p,0)
        self.assertEqual(evaluation_run_metrics(self.db,1)[0]['feedback_positions'],0)

    def test_same_model_cannot_be_compared_against_itself(self):
        with self.assertRaisesRegex(ValueError,'different coaching models'):
            benchmark_comparison(self.db,1,'v34','v34')

    def test_model_comparison_uses_only_current_run(self):
        p=self.positions[0]
        self.feedback(self.one,p,-1)
        record_evaluation_attempt(self.db,self.two,p,True,'e2e4')
        self.feedback(self.two,p,1)
        self.db.execute("UPDATE training_positions SET coaching_version='v35',coach_explanation='new prose' WHERE job_id=1")
        snapshot_completed_refresh(self.db,1,'v35','3.5')
        three=start_evaluation_run(self.db,1,'v35')
        record_evaluation_attempt(self.db,three,p,True,'e2e4')
        append_feedback(self.db,p,'explanation',-1,continuation='solving',
                        coaching_version='v35',evaluation_run_id=three)
        result=benchmark_comparison(self.db,1,'v34','v35')
        pair=result['comparisons'][0]
        self.assertEqual(pair['baseline_run_id'],self.two)
        self.assertEqual(pair['comparison_run_id'],three)
        self.assertEqual(pair['paired_ratings'],1)
        self.assertEqual(pair['baseline_approval_pct'],100.0)
        self.assertEqual(pair['comparison_approval_pct'],0.0)


if __name__=='__main__':unittest.main()
