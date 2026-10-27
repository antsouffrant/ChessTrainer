"""Integration-style checkpoint regression, no Flask/python-chess/Stockfish required.

Executes the application's real analysis loop with a tiny fake PGN reader and a
SQLite job. Stockfish screening is mocked, not the resume/checkpoint algorithm.
"""
import ast
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
analysis_tree = ast.parse((ROOT / 'analysis.py').read_text())
analysis_fn = next(n for n in analysis_tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run_analysis_job')
analysis_fn.decorator_list = []
compiled_loop = compile(ast.Module(body=[analysis_fn], type_ignores=[]), 'analysis.py', 'exec')


class FakeEngine:
    options = {}
    def ping(self): pass
    def quit(self): pass
    def close(self): pass


class ResumeTests(unittest.TestCase):
    def test_resume_keeps_completed_game_checkpoint_and_next_pass(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            database = root / 'test.sqlite'
            batch = root / 'batch.pgn'
            batch.write_text('g1\ng2\ng3\n', encoding='utf-8')

            def connect():
                c = sqlite3.connect(database)
                c.row_factory = sqlite3.Row
                return c

            with connect() as conn:
                conn.executescript('''
                CREATE TABLE accounts(id INTEGER PRIMARY KEY, username TEXT);
                INSERT INTO accounts VALUES(1,'alice');
                CREATE TABLE analysis_jobs (
                  id INTEGER PRIMARY KEY, account_id INTEGER, status TEXT,
                  learning_modes TEXT, settings_json TEXT, game_types TEXT,
                  date_range TEXT, screen_depth INTEGER, deep_depth INTEGER,
                  screen_seconds REAL, deep_seconds REAL, max_passes INTEGER,
                  current_pass INTEGER, passes_completed INTEGER,
                  current_screen_depth INTEGER, current_deep_depth INTEGER,
                  games_retrieved INTEGER DEFAULT 0, games_processed INTEGER DEFAULT 0,
                  games_screened INTEGER DEFAULT 0, checkpoint_pass INTEGER DEFAULT 0,
                  checkpoint_game_index INTEGER DEFAULT 0, checkpoint_file_offset INTEGER DEFAULT 0,
                  positions_found INTEGER DEFAULT 0, force_reanalysis INTEGER DEFAULT 1,
                  source_type TEXT, source_username TEXT, error TEXT, finished_at TEXT
                );
                INSERT INTO analysis_jobs(id,account_id,status,learning_modes,settings_json,
                  game_types,date_range,screen_depth,deep_depth,screen_seconds,deep_seconds,
                  max_passes,current_pass,passes_completed,source_type,source_username)
                  VALUES(1,1,'queued','["mistakes"]','{}','["blitz"]','month',8,16,1,1,2,1,0,'self','alice');
                CREATE TABLE retrieval_processes(job_id INTEGER PRIMARY KEY, status TEXT);
                INSERT INTO retrieval_processes VALUES(1,'complete');
                CREATE TABLE training_positions(job_id INTEGER);
                CREATE TABLE analyzed_games (
                  account_id INTEGER, game_id TEXT, source_job_id INTEGER,
                  analysis_version TEXT, settings_signature TEXT, max_screen_depth INTEGER,
                  max_deep_depth INTEGER, analysis_pass INTEGER, source_type TEXT,
                  source_username TEXT, PRIMARY KEY(account_id,game_id)
                );
                ''')

            fake_engine_module = SimpleNamespace(SimpleEngine=SimpleNamespace(popen_uci=lambda *_a, **_k: FakeEngine()),
                 EngineTerminatedError=type('EngineTerminatedError', (Exception,), {}),
                 EngineError=type('EngineError', (Exception,), {}))
            sf = SimpleNamespace(engine=fake_engine_module, pgn=SimpleNamespace(
                 read_game=lambda handle: handle.readline().strip() or None))
            settings = dict(progressive_depths_enabled=True, max_passes=2,
                engine_start_timeout_seconds=1, engine_restart_retries=0,
                analysis_engine_threads=1, analysis_engine_hash_mb=16)
            screens = []
            pause_once = [True]
            def screen_game(_engine, game, *_args):
                screens.append(game)
                if game == 'g2' and pause_once[0]:
                    pause_once[0] = False
                    with connect() as c:
                        c.execute("UPDATE analysis_jobs SET status='paused' WHERE id=1")
                return []
            def save_cache(conn, account_id, game_id, _game, _pgn, job_id,
                           sd, dd, pass_number, signature, **kwargs):
                conn.execute('''INSERT INTO analyzed_games VALUES(?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(account_id,game_id) DO UPDATE SET source_job_id=excluded.source_job_id,
                  max_screen_depth=excluded.max_screen_depth,
                  max_deep_depth=excluded.max_deep_depth,
                  analysis_pass=excluded.analysis_pass''',
                  (account_id,game_id,job_id,'current',signature,sd,dd,pass_number,'self','alice'))

            env = dict(
                connect=connect, json=json, os=SimpleNamespace(cpu_count=lambda:1),
                chess=sf, settings_from_snapshot=lambda *_args: settings.copy(),
                date_range_to_ms=lambda _: 0, analysis_signature=lambda _: 'signature',
                pass_depths=lambda a,b,p,_s: (a+p,b+p),
                batch_path_for_job=lambda *_args: batch,
                count_games_in_batch=lambda _: 3,
                find_stockfish=lambda *_args: Path('stockfish'),
                screen_game=screen_game,
                choose_deep_candidates=lambda *_args: [],
                cache_analyzed_game=save_cache,
                export_game_pgn=lambda game: game,
                stable_game_id=lambda game,pgn: game,
                copy_cached_positions=lambda *_args: 0,
                repoint_cache_to_job=lambda *_args: None,
                ANALYSIS_VERSION='current',
            )
            exec(compiled_loop, env)
            worker = env['_run_analysis_job']
            worker(1)
            with connect() as conn:
                j = conn.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone()
                self.assertEqual(j['status'], 'paused')
                self.assertEqual((j['checkpoint_pass'],j['checkpoint_game_index'],j['games_processed']), (1,1,1))
                saved_offset = j['checkpoint_file_offset']
                self.assertGreater(saved_offset,0)
                conn.execute("UPDATE analysis_jobs SET status='queued' WHERE id=1")
                conn.commit()
            worker(1)
            with connect() as conn:
                j = conn.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone()
                self.assertEqual(j['status'],'complete')
                self.assertEqual(j['passes_completed'], 2)
                self.assertEqual(j['checkpoint_game_index'],3)
                self.assertEqual(j['games_processed'],3)
            self.assertEqual(screens,['g1','g2','g2','g3','g1','g2','g3'])

if __name__=='__main__': unittest.main()
