"""Route-level tests against a real SQLite transaction, without Flask/Stockfish."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path
from process_policy import queue_analysis

ROOT=Path(__file__).resolve().parents[1]

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

def route(name, env):
    tree=ast.parse((ROOT/'app.py').read_text())
    f=next(f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name==name)
    f.decorator_list=[]
    exec(compile(ast.Module(body=[f],type_ignores=[]),'app.py','exec'),env)
    return env[name]

class ProcessRouteTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.db=Path(t.name)/'state.db'
        self.batch=Path(t.name)/'one.pgn'
        self.batch.write_text('[Event "test"]\n\n1. e4 *\n')
        def connect():
            c=sqlite3.connect(self.db,factory=ClosingConnection)
            c.row_factory=sqlite3.Row
            return c
        self.connect=connect
        with connect() as conn:
            conn.executescript('''
            CREATE TABLE accounts (id INTEGER PRIMARY KEY,username TEXT);
            CREATE TABLE analysis_jobs (id INTEGER PRIMARY KEY,account_id INTEGER,source_username TEXT,
              status TEXT,passes_completed INTEGER,max_passes INTEGER,current_pass INTEGER,force_reanalysis INTEGER,
              checkpoint_pass INTEGER,checkpoint_game_index INTEGER,checkpoint_file_offset INTEGER,
              games_processed INTEGER,positions_found INTEGER,finished_at TEXT,error TEXT);
            CREATE TABLE retrieval_processes (job_id INTEGER PRIMARY KEY,status TEXT,updated_at TEXT);
            CREATE TABLE metadata_processes (job_id INTEGER PRIMARY KEY,status TEXT);
            INSERT INTO accounts VALUES(1,'Alice');
            INSERT INTO analysis_jobs VALUES(1,1,'Alice','stopped',1,3,2,0,2,7,123,7,2,NULL,NULL);
            INSERT INTO retrieval_processes VALUES(1,'complete',NULL);
            ''')
        self.launched=[]
        self.env={'connect':connect,'jsonify':lambda obj:obj,'batch_path_for_job':lambda *args:self.batch,
            'queue_analysis':queue_analysis,'resume_analysis_thread':self.launched.append}
        self.analyze=route('process_analyze',self.env)
        self.pause_retrieval=route('process_pause_retrieval',self.env)
        self.stop_retrieval=route('process_stop_retrieval',self.env)
    def state(self):
        with self.connect() as conn:
            return dict(conn.execute('SELECT * FROM analysis_jobs').fetchone())
    def test_analyze_after_stop_resumes_existing_checkpoint(self):
        payload,code=self.analyze(1)
        self.assertEqual((code,payload['action']), (202,'resuming'))
        self.assertEqual(self.launched,[1])
        s=self.state()
        self.assertEqual((s['checkpoint_pass'],s['checkpoint_game_index'],s['checkpoint_file_offset']),(2,7,123))
        self.assertEqual(s['positions_found'],2)
    def test_complete_list_enqueues_new_pass(self):
        with self.connect() as conn:
            conn.execute("UPDATE analysis_jobs SET status='complete',current_pass=3,passes_completed=3 WHERE id=1")
        payload,code=self.analyze(1)
        self.assertEqual((code,payload['action']),(202,'refining'))
        s=self.state()
        self.assertEqual((s['max_passes'],s['checkpoint_pass']),(4,4))
        self.assertEqual(s['positions_found'],2)
    def test_retrieval_prevents_analysis_even_with_batch(self):
        with self.connect() as conn:
            conn.execute("UPDATE retrieval_processes SET status='running' WHERE job_id=1")
        payload,status=self.analyze(1)
        self.assertEqual(status,409)
        self.assertFalse(self.launched)
    def test_refresh_prevents_analysis(self):
        with self.connect() as conn:
            conn.execute("INSERT INTO metadata_processes VALUES(1,'running')")
        payload,status=self.analyze(1)
        self.assertEqual(status,409)
    def test_pause_and_stop_retrieval_are_isolated(self):
        with self.connect() as conn:
            conn.execute("UPDATE retrieval_processes SET status='running' WHERE job_id=1")
            conn.execute("UPDATE analysis_jobs SET status='waiting_for_games' WHERE id=1")
        payload=self.pause_retrieval(1)
        self.assertEqual(payload['status'],'paused')
        self.assertEqual(self.state()['status'],'paused')
        payload=self.stop_retrieval(1)
        self.assertEqual(payload['status'],'stopped')
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM retrieval_processes').fetchone()[0],'stopped')
if __name__=='__main__':unittest.main()
