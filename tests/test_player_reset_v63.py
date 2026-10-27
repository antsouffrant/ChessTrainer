"""Player record deletion should mirror Coach reset while preserving unrelated data."""
import ast
import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from player_learning import record_attempt, reset_player_records, summary, export_rows, csv_data

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


class PlayerResetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'player.db'
        def connect():
            conn = sqlite3.connect(path, factory=ClosingConnection)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.connect = connect
        with connect() as db:
            db.executescript(schema())
            db.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
            for i in (1,2):
                db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,?,'[]')", (f'list{i}',))
                db.execute('''INSERT INTO training_positions(job_id,game_id,category,learning_mode,
                    fen,user_color,move_number,best_move_uci,attempts,learned)
                    VALUES(?,'game','mistake','mistakes',?,'white',5,'e2e4',4,1)''', (i, f'fen{i}'))
                db.execute("INSERT INTO position_feedback(position_id,account_id,category,rating) VALUES(?,1,'explanation',1)", (i,))
                row=db.execute('''SELECT tp.*, j.account_id FROM training_positions tp JOIN analysis_jobs j
                     ON j.id=tp.job_id WHERE tp.id=?''', (i,)).fetchone()
                record_attempt(db, row, move_uci='d2d4', correct=False, elapsed_seconds=8)
                record_attempt(db, row, move_uci='e2e4', correct=True, elapsed_seconds=10)
            db.commit()
        self.payload={}
        env={'connect':self.connect,'jsonify':lambda x:x,'reset_player_records':reset_player_records}
        env['request']=SimpleNamespace(get_json=lambda silent=False:self.payload)
        tree=ast.parse((ROOT/'app.py').read_text())
        func=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='player_reset_records')
        func.decorator_list=[]
        exec(compile(ast.Module(body=[func],type_ignores=[]),'app.py','exec'),env)
        self.endpoint=env['player_reset_records']

    def count(self,table,where='',params=()):
        with self.connect() as db:
            return db.execute(f'SELECT COUNT(*) FROM {table} {where}',params).fetchone()[0]

    def test_confirmation_required_and_no_mutation(self):
        self.payload={'job_id':1,'confirmation':'RESET FEEDBACK'}
        result,code=self.endpoint()
        self.assertEqual(code,400)
        self.assertEqual(self.count('player_solve_sessions'),2)

    def test_one_list_deletes_sessions_and_attempts_only(self):
        self.payload={'job_id':'1','confirmation':'RESET PLAYER'}
        result=self.endpoint()
        self.assertEqual(result['deleted'],{'sessions':1,'attempts':2})
        self.assertEqual(result['job_id'],1)
        self.assertEqual(self.count('player_solve_sessions'),1)
        self.assertEqual(self.count('player_solve_attempts'),2)
        self.assertEqual(self.count('player_solve_attempts','WHERE position_id=1'),0)
        self.assertEqual(self.count('training_positions'),2)
        self.assertEqual(self.count('analysis_jobs'),2)
        self.assertEqual(self.count('position_feedback'),2)
        with self.connect() as db:
            self.assertEqual(summary(db,{'job_id':1})['overview']['attempted_positions'],0)
            self.assertEqual(summary(db,{'job_id':1})['overview']['learned_positions'],1)
            self.assertEqual(summary(db,{'job_id':2})['overview']['attempted_positions'],1)
            self.assertEqual(db.execute('SELECT attempts FROM training_positions WHERE id=1').fetchone()[0],4)
            session_csv=list(csv.DictReader(io.StringIO(csv_data(export_rows(db,{'job_id':1})).decode('utf-8-sig'))))
            attempt_csv=list(csv.DictReader(io.StringIO(csv_data(export_rows(db,{'job_id':1},'attempts'), 'attempts').decode('utf-8-sig'))))
            self.assertEqual(session_csv,[])
            self.assertEqual(attempt_csv,[])

    def test_all_lists_delete_activity_only_and_idempotence(self):
        self.payload={'confirmation':'RESET PLAYER'}
        response=self.endpoint()
        self.assertEqual(response['deleted'],{'sessions':2,'attempts':4})
        self.assertEqual(self.count('player_solve_sessions'),0)
        self.assertEqual(self.count('player_solve_attempts'),0)
        self.assertEqual(self.count('position_feedback'),2)
        self.assertEqual(self.count('training_positions'),2)
        self.assertEqual(self.endpoint()['deleted'],{'sessions':0,'attempts':0})

    def test_unknown_or_invalid_list_is_rejected(self):
        for job_id,code in ((999,404),(-1,400),('oops',400)):
            self.payload={'job_id':job_id,'confirmation':'RESET PLAYER'}
            self.assertEqual(self.endpoint()[1],code)
        self.assertEqual(self.count('player_solve_sessions'),2)

if __name__=='__main__':
    unittest.main()
