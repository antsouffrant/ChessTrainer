"""An evaluation run must have actual, active feedback before allowing Next."""
import sqlite3
import unittest
import ast
from pathlib import Path

def schema():
    tree=ast.parse((Path(__file__).resolve().parents[1]/"db.py").read_text())
    return next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=="SCHEMA" for t in n.targets))
from feedback_analytics import evaluation_feedback_saved
from feedback_history import append_feedback
from coach_benchmark import ensure_cohort, snapshot_completed_refresh
from evaluation_runs import start_evaluation_run, record_evaluation_attempt

VERSION = 'rules-v34-version-scoped-cache'


class EvaluationFeedbackGateTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        for i in (1, 2):
            self.conn.execute('''INSERT INTO training_positions(id,job_id,category,learning_mode,
                fen,user_color,move_number,learned,coaching_version,coach_explanation,best_move_uci)
                VALUES(?,1,'mistake','mistakes',?,'white',12,0,?,'Explanation','e2e4')''',
                (i, f'8/8/8/8/8/8/8/8 w - - {i-1} 1', VERSION))
        ensure_cohort(self.conn,1,target=2)
        snapshot_completed_refresh(self.conn,1,VERSION,'3.4')
        self.run_a=start_evaluation_run(self.conn,1,VERSION)
        self.run_b=None

    def event(self, rating, *,run=None,position=1,kind='explanation',continuation='solving',version=VERSION,message_id=None):
        append_feedback(self.conn,position,kind,rating,continuation=continuation,
                        coaching_version=version,evaluation_run_id=run or self.run_a,message_id=message_id)

    def test_solving_is_not_feedback_and_other_runs_are_isolated(self):
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))
        record_evaluation_attempt(self.conn,self.run_a,1,True,'e2e4')
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(1)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.assertFalse(evaluation_feedback_saved(self.conn,2,self.run_a))
        self.assertIsNone(self.run_b)
        self.assertFalse(evaluation_feedback_saved(self.conn,1,None))

    def test_withdrawing_last_vote_locks_again(self):
        record_evaluation_attempt(self.conn,self.run_a,1,True,'e2e4')
        self.event(-1)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(0)
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(1,kind='position',continuation=None)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(0,kind='position',continuation=None)
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))

    def test_two_independent_votes_and_taxonomy_suggestions(self):
        record_evaluation_attempt(self.conn,self.run_a,1,True,'e2e4')
        self.event(1,kind='taxonomy_motif',continuation=None)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(-1,kind='coaching',continuation=None,message_id=50)
        self.event(0,kind='taxonomy_motif',continuation=None)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(0,kind='coaching',continuation=None,message_id=50)
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))

    def test_older_version_not_counted(self):
        record_evaluation_attempt(self.conn,self.run_a,1,True,'e2e4')
        self.event(1,version='rules-v33')
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))
        self.event(1)
        self.assertTrue(evaluation_feedback_saved(self.conn,1,self.run_a))

    def test_unsolved_position_cannot_be_unlocked_by_forged_feedback(self):
        self.event(1)
        self.assertFalse(evaluation_feedback_saved(self.conn,1,self.run_a))


if __name__ == '__main__':
    unittest.main()
