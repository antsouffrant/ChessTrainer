"""Evaluation ratings must work without the global learned flag."""
import ast
from pathlib import Path
import sqlite3
import unittest

from coach_benchmark import ensure_cohort, snapshot_completed_refresh
from evaluation_runs import start_evaluation_run,record_evaluation_attempt
from feedback_analytics import record_position_vote, position_votes
from feedback_history import current_feedback


def schema():
    tree = ast.parse((Path(__file__).parent.parent / 'db.py').read_text())
    return next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))


class EvaluationExplanationFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        self.conn.execute("""INSERT INTO training_positions(id,job_id,category,learning_mode,
            fen,user_color,move_number,learned,coaching_version,coach_explanation,best_move_uci)
            VALUES(1,1,'mistake','mistakes','8/8/8/8/8/8/8/8 w - - 0 1',
            'white',12,0,'rules-v34-version-scoped-cache','New solution','e2e4')""")
        ensure_cohort(self.conn,1,target=1)
        snapshot_completed_refresh(self.conn,1,'rules-v34-version-scoped-cache','3.4')
        self.run_id = start_evaluation_run(self.conn,1,'rules-v34-version-scoped-cache')

    def test_ratings_after_evaluation_solve_even_if_globally_unlearned(self):
        record_evaluation_attempt(self.conn,self.run_id,1,True,'e2e4')
        self.assertEqual(self.conn.execute('SELECT learned FROM training_positions WHERE id=1').fetchone()[0],0)
        for rating in (1,-1,0,1):
            record_position_vote(self.conn,1,'explanation',rating,
                text='Current solution',evaluation_run_id=self.run_id)
            expected = {} if rating == 0 else {'explanation':rating}
            self.assertEqual(position_votes(self.conn,1,self.run_id),expected)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM feedback_events WHERE feedback_type='explanation'").fetchone()[0],4)

    def test_new_run_has_no_inherited_thumbs(self):
        record_evaluation_attempt(self.conn,self.run_id,1,True,'e2e4')
        record_position_vote(self.conn,1,'explanation',-1,evaluation_run_id=self.run_id,text='Run A')
        run_b=start_evaluation_run(self.conn,1,'rules-v34-version-scoped-cache')
        self.assertEqual(position_votes(self.conn,1,run_b),{})
        self.assertEqual(position_votes(self.conn,1,self.run_id),{'explanation':-1})
        self.assertEqual(len(current_feedback(self.conn,1,version='rules-v34-version-scoped-cache',evaluation_run_id=self.run_id)),1)

if __name__=='__main__': unittest.main()
