"""Clean-slate restart without Flask, Stockfish or python-chess installed."""
import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app_settings import get_settings, serialize_settings
from process_policy import restart_analysis

ROOT = Path(__file__).resolve().parents[1]


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def standalone_route(name, env):
    tree = ast.parse((ROOT / 'app.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'app.py', 'exec'), env)
    return env[name]


class RestartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.batch = self.base / 'saved.pgn'
        self.batch.write_text('[Event "test"]\n\n1. e4 *\n')
        self.db = self.base / 'state.sqlite'

        def connect():
            conn = sqlite3.connect(self.db, factory=ClosingConnection)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn

        self.connect = connect
        with connect() as conn:
            conn.executescript('''
                CREATE TABLE accounts(id INTEGER PRIMARY KEY,username TEXT);
                CREATE TABLE analysis_jobs(
                    id INTEGER PRIMARY KEY,account_id INTEGER,source_username TEXT,
                    status TEXT,error TEXT,finished_at TEXT,
                    force_reanalysis INTEGER,current_pass INTEGER,max_passes INTEGER,passes_completed INTEGER,
                    checkpoint_pass INTEGER,checkpoint_game_index INTEGER,checkpoint_file_offset INTEGER,
                    games_processed INTEGER,games_screened INTEGER,positions_found INTEGER,
                    games_retrieved INTEGER,metadata_refreshed_at TEXT,screen_depth INTEGER,deep_depth INTEGER,
                    screen_seconds REAL,deep_seconds REAL,current_screen_depth INTEGER,current_deep_depth INTEGER,
                    settings_json TEXT
                );
                CREATE TABLE retrieval_processes(job_id INTEGER PRIMARY KEY,status TEXT);
                CREATE TABLE metadata_processes(job_id INTEGER PRIMARY KEY,status TEXT,
                    cursor INTEGER DEFAULT 0,processed INTEGER DEFAULT 0,total INTEGER DEFAULT 0,
                    updated INTEGER DEFAULT 0,failed INTEGER DEFAULT 0,without_pgn INTEGER DEFAULT 0,
                    error TEXT,updated_at TEXT);
                CREATE TABLE analyzed_games(account_id INTEGER,game_id TEXT,source_job_id INTEGER);
                CREATE TABLE analysis_candidates(job_id INTEGER,game_id TEXT,ply INTEGER);
                CREATE TABLE training_positions(id INTEGER PRIMARY KEY,job_id INTEGER,learned INTEGER,
                    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE);
                CREATE TABLE position_feedback(id INTEGER PRIMARY KEY,position_id INTEGER,rating INTEGER,
                    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE);
                CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);
                INSERT INTO accounts VALUES(1,'alice');
                INSERT INTO analysis_jobs VALUES(1,1,'alice','running','old error','yesterday',0,3,4,2,3,27,900,27,27,3,30,NULL,8,16,3.0,10.0,12,24,'{}');
                INSERT INTO retrieval_processes VALUES(1,'complete');
                INSERT INTO analysis_candidates VALUES(1,'abc',7);
                INSERT INTO training_positions VALUES(5,1,1);
                INSERT INTO position_feedback VALUES(1,5,1);
                INSERT INTO analyzed_games VALUES(1,'abc',1);
                INSERT INTO metadata_processes(job_id,status,cursor,processed,total) VALUES(1,'paused',99,12,99);
            ''')
        self.called = []
        self.env = {
            'connect': connect,
            'jsonify': lambda x: x,
            'batch_path_for_job': lambda *a: self.batch,
            'restart_analysis_after_current_worker': self.called.append,
        }
        self.restart = standalone_route('process_restart_analysis', self.env)

    def state(self):
        with self.connect() as conn:
            return dict(conn.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone())

    def test_pending_restart_waits_for_existing_worker(self):
        response, code = self.restart(1)
        self.assertEqual(code, 202)
        self.assertEqual(response['status'], 'restarting')
        self.assertEqual(self.called, [1])
        self.assertEqual(self.state()['checkpoint_game_index'], 27)
        # A duplicate request is rejected while the old worker winds down.
        response, code = self.restart(1)
        self.assertEqual(code, 409)
        self.assertEqual(self.called, [1])

    def test_fresh_run_invalidates_cache_and_clears_derived_history(self):
        self.restart(1)
        with self.connect() as conn:
            settings = get_settings(conn)
            settings.update({'analysis_engine_threads': 3, 'deep_seconds': 22,
                             'max_passes': 2, 'progressive_depths_enabled': True})
            restart_analysis(conn, 1, settings)
            conn.commit()
        st = self.state()
        self.assertEqual(st['status'], 'queued')
        self.assertEqual((st['checkpoint_pass'], st['checkpoint_game_index'], st['checkpoint_file_offset']), (1, 0, 0))
        self.assertEqual((st['current_pass'], st['max_passes'], st['passes_completed']), (1, 2, 0))
        self.assertEqual((st['games_processed'], st['games_screened'], st['games_retrieved']), (0, 0, 30))
        self.assertEqual(st['force_reanalysis'], 1)
        self.assertEqual(st['positions_found'], 0)
        self.assertEqual(st['deep_seconds'], 22)
        self.assertEqual(__import__('json').loads(st['settings_json'])['analysis_engine_threads'], 3)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM analysis_candidates').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM training_positions').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM position_feedback').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM analyzed_games').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT status FROM metadata_processes WHERE job_id=1').fetchone()[0], 'idle')
        self.assertEqual(self.batch.read_text(), '[Event "test"]\n\n1. e4 *\n')

    def test_missing_saved_game_rejects_restart(self):
        self.batch.unlink()
        response, code = self.restart(1)
        self.assertEqual(code, 409)
        self.assertEqual(self.state()['status'], 'running')
        self.assertFalse(self.called)

    def test_active_refresh_rejects_restart(self):
        with self.connect() as conn:
            conn.execute("UPDATE metadata_processes SET status='running' WHERE job_id=1")
        response, code = self.restart(1)
        self.assertEqual(code, 409)
        self.assertEqual(self.state()['status'], 'running')

    def test_retrieval_not_complete_rejects_restart(self):
        with self.connect() as conn:
            conn.execute("UPDATE retrieval_processes SET status='running' WHERE job_id=1")
        response, code = self.restart(1)
        self.assertEqual(code, 409)
        self.assertEqual(self.state()['status'], 'running')

    def test_interrupted_restart_boots_paused_at_start(self):
        # Restart may have been requested just before killing Flask.
        self.restart(1)
        env = {'connect': self.connect, 'restart_analysis': restart_analysis, 'get_settings': get_settings}
        startup = standalone_route('pause_interrupted_jobs_on_startup', env)
        # Only the tables touched by the startup migration are needed.
        with self.connect() as conn:
            conn.execute('ALTER TABLE retrieval_processes ADD COLUMN updated_at TEXT')
        startup()
        st = self.state()
        self.assertEqual((st['status'], st['checkpoint_game_index'], st['force_reanalysis']), ('paused', 0, 1))


if __name__ == '__main__':
    unittest.main()
