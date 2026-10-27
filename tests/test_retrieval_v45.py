"""Independent creation/retrieval/analysis handoff tests (no chess engine needed)."""
import importlib.util
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class RetrievalLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.db_path = self.base / 'test.sqlite'
        self.dest = self.base / 'job_1_Alice.pgn'
        with self.connection() as conn:
            conn.executescript('''
            CREATE TABLE accounts(id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE analysis_jobs(id INTEGER PRIMARY KEY,account_id INTEGER,
                source_username TEXT,game_types TEXT,date_range TEXT,status TEXT,
                games_retrieved INTEGER NOT NULL DEFAULT 0,error TEXT);
            CREATE TABLE retrieval_processes(job_id INTEGER PRIMARY KEY,status TEXT,
                bytes_downloaded INTEGER DEFAULT 0,bytes_total INTEGER DEFAULT 0,
                error TEXT,started_at TEXT,finished_at TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO accounts VALUES(1,'Alice');
            INSERT INTO analysis_jobs(id,account_id,source_username,game_types,date_range,status)
                VALUES(1,1,'Alice','["blitz"]','month','waiting_for_games');
            INSERT INTO retrieval_processes(job_id,status) VALUES(1,'queued');
            ''')
        self.analysis_stub = types.ModuleType('analysis')
        self.analysis_stub.batch_path_for_job = lambda user, jid: self.dest
        self.analysis_stub.count_games_in_batch = lambda path: path.read_text().count('[Event ')
        self.analysis_stub.date_range_to_ms = lambda r: 12345
        self.db_stub = types.ModuleType('db')
        self.db_stub.connect = self.connection
        with patch.dict(sys.modules, {'analysis': self.analysis_stub, 'db': self.db_stub}):
            spec = importlib.util.spec_from_file_location('test_retrieval_impl', ROOT / 'retrieval.py')
            self.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.mod)

    def connection(self):
        conn = sqlite3.connect(self.db_path, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        return conn

    def state(self):
        with self.connection() as conn:
            r = conn.execute('SELECT * FROM retrieval_processes WHERE job_id=1').fetchone()
            j = conn.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone()
            return dict(r), dict(j)

    def response(self, chunks, *, status=200):
        test = self
        class Result:
            status_code = status
            headers = {'Content-Length': str(sum(map(len,chunks)))}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self):
                if status >= 400: raise RuntimeError(f'HTTP {status}')
            def iter_content(self, chunk_size):
                for part in chunks:
                    yield part
        return Result()

    def test_retrieval_commits_and_automatically_starts_analysis(self):
        launches = []
        pgndata = b'[Event "1"]\n\n1. e4 e5 *\n[Event "2"]\n\n1. d4 d5 *\n'
        self.mod.retrieve_game_list(1, on_complete=launches.append,
                                    request_get=lambda *a, **kw: self.response([pgndata]))
        r, j = self.state()
        self.assertEqual((r['status'], j['status'], j['games_retrieved']), ('complete', 'queued', 2))
        self.assertEqual(launches, [1])
        self.assertEqual(self.dest.read_bytes(), pgndata)
        self.assertFalse(self.dest.with_suffix('.pgn.part').exists())
        self.assertEqual(r['bytes_downloaded'], len(pgndata))
        # No retriever can be launched again after success.
        self.mod.retrieve_game_list(1, on_complete=launches.append,request_get=lambda *a,**kw: self.fail('Redownload'))
        self.assertEqual(launches, [1])

    def test_stopped_download_keeps_batch_hidden(self):
        def interrupted():
            yield b'[Event "part"]\n'
            with self.connection() as conn:
                conn.execute("UPDATE retrieval_processes SET status='stopped' WHERE job_id=1")
                conn.execute("UPDATE analysis_jobs SET status='stopped' WHERE id=1")
                conn.commit()
            yield b'no more'
        response = self.response([b'1', b'2'])
        response.iter_content = lambda **kwargs: interrupted()
        started = []
        self.mod.retrieve_game_list(1, on_complete=started.append,request_get=lambda *a,**kw: response)
        r,j=self.state()
        self.assertEqual(r['status'],'stopped')
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_suffix('.pgn.part').exists())
        self.assertFalse(started)

    def test_failed_or_empty_download_never_triggers_analysis(self):
        called = []
        self.mod.retrieve_game_list(1, on_complete=called.append,
                                    request_get=lambda *a,**kw:self.response([b'not a PGN']))
        r,j=self.state()
        self.assertEqual(r['status'],'error')
        self.assertEqual(j['status'],'error')
        self.assertIn('no PGN games', r['error'])
        self.assertEqual(called, [])
        self.assertFalse(self.dest.exists())

    def test_legacy_job_without_retrieval_record_is_not_fetched(self):
        with self.connection() as conn:
            conn.execute('DELETE FROM retrieval_processes')
            conn.commit()
        self.mod.retrieve_game_list(1, request_get=lambda *a,**kw:self.fail('Unwanted download'))
        self.assertFalse(self.dest.exists())


class ReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('list_readiness_test',ROOT/'list_readiness.py')
        cls.lib = importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.lib)
    def test_workflow_states(self):
        state = self.lib.list_state
        self.assertEqual(state('running','waiting_for_games',0),'retrieving')
        self.assertEqual(state('complete','queued',0),'analyzing')
        self.assertEqual(state('complete','running',0),'analyzing')
        self.assertEqual(state('complete','running',1),'ready')
        self.assertEqual(state(None,'complete',42),'ready')
        self.assertEqual(state('complete','complete',0),'empty')
        self.assertEqual(state('error','error',0),'retrieval_error')
        self.assertEqual(state('stopped','stopped',0),'retrieval_stopped')


if __name__ == '__main__': unittest.main()
