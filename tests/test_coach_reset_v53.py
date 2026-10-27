"""Coach ratings reset independent of analysis and per-game-list boundaries."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def schema():
    tree = ast.parse((ROOT / 'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                if any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets))


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class ResetFeedbackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'ratings.db'
        def connect():
            conn = sqlite3.connect(self.path, factory=ClosingConnection)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.connect = connect
        with connect() as db:
            db.executescript(schema())
            db.execute("INSERT INTO accounts(provider,username) VALUES('lichess','alex')")
            for i in (1, 2):
                db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
                db.execute("""INSERT INTO training_positions(job_id,game_id,category,fen,user_color,
                    move_number,best_move_uci,coach_explanation,learned)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (i, f'g{i}', 'mistake',f'fen{i}', 'white', 1,'a2a4',f'Coach {i}',1))
                db.execute("INSERT INTO position_feedback(position_id,account_id,category,rating) VALUES(?,1,'explanation',1)",(i,))
                db.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,?)",(i,))
                db.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(?,'assistant','Hi')",(i,))
                db.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES(?,1,?,1)",(i,i))
                db.execute("INSERT INTO position_taxonomy_feedback(position_id,account_id,field_key,selected_key,model_key_at_vote) VALUES(?,1,'context','defend','attack')",(i,))
        env = {'connect':self.connect, 'jsonify': lambda x:x}
        self.payload = {}
        env['request'] = SimpleNamespace(get_json=lambda silent=False: self.payload)
        tree = ast.parse((ROOT/'app.py').read_text())
        func = next(f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name=='coach_reset_feedback')
        func.decorator_list=[]
        exec(compile(ast.Module(body=[func],type_ignores=[]),'app.py','exec'),env)
        self.reset = env['coach_reset_feedback']

    def count(self, table, where=''):
        with self.connect() as db:
            return db.execute(f'SELECT COUNT(*) FROM {table} {where}').fetchone()[0]

    def test_confirmation_required(self):
        result, code = self.reset()
        self.assertEqual(code,400)
        self.assertEqual(self.count('position_feedback'),2)

    def test_reset_one_list_preserves_other_and_positions(self):
        self.payload = {'job_id':1,'confirmation':'RESET FEEDBACK'}
        answer = self.reset()
        self.assertEqual(answer['deleted'],{'feedback_history_events':0,'position_explanation_motif':1,'chat_coaching':1,'taxonomy_selections':1,'continuation_explanations':0})
        self.assertEqual(self.count('position_feedback'),1)
        self.assertEqual(self.count('position_taxonomy_feedback'),1)
        self.assertEqual(self.count('coach_message_feedback'),1)
        self.assertEqual(self.count('training_positions'),2)
        self.assertEqual(self.count('coach_messages'),2)
        self.assertEqual(self.count('analysis_jobs'),2)

    def test_global_reset_removes_only_votes(self):
        self.payload = {'confirmation':'RESET FEEDBACK'}
        self.assertTrue(self.reset()['ok'])
        self.assertEqual(self.count('position_feedback'),0)
        self.assertEqual(self.count('position_taxonomy_feedback'),0)
        self.assertEqual(self.count('coach_message_feedback'),0)
        self.assertEqual(self.count('training_positions'),2)
        self.assertEqual(self.count('coach_messages'),2)

    def test_bad_list_rejected(self):
        self.payload = {'job_id':999,'confirmation':'RESET FEEDBACK'}
        _, code = self.reset()
        self.assertEqual(code,404)
        self.assertEqual(self.count('position_feedback'),2)

if __name__=='__main__': unittest.main()
