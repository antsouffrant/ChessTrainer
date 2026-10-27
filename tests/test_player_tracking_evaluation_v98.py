"""Player tracking is optional in every mode and scoped to evaluation runs."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
import types
try:
    import db
except ModuleNotFoundError as exc:
    if exc.name != 'chess':
        raise
    # db only needs the learning catalog during initialization; these tests
    # exercise Player persistence, not the chess engine or classifier.
    catalog_stub = types.ModuleType('learning')
    catalog_stub.CLASSIFIER_VERSION = 'test'
    catalog_stub.CONCEPT_CATALOG = []
    sys.modules['learning'] = catalog_stub
    try:
        import db
    finally:
        del sys.modules['learning']
from player_learning import record_attempt, abandon_session


class PlayerTrackingEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_path = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / 'player-v98.sqlite3'
        db.init_db()
        self.conn = db.connect()
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','v98-test')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'month','[]')")
        self.conn.execute("""INSERT INTO training_positions(job_id,game_id,category,learning_mode,fen,user_color,move_number,best_move_uci)
                             VALUES(1,'g','blunder','mistakes','fake fen','white',15,'e2e4')""")
        self.position = self.conn.execute('SELECT tp.*, j.account_id FROM training_positions tp '
                                          'JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=1').fetchone()

    def tearDown(self):
        self.conn.close()
        db.DB_PATH = self.previous_path
        self.tmp.cleanup()

    def test_regular_and_evaluation_sessions_are_independent(self):
        record_attempt(self.conn, self.position, move_uci='d2d4', correct=False, elapsed_seconds=7)
        record_attempt(self.conn, self.position, move_uci='g1f3', correct=False,
                       elapsed_seconds=3, evaluation_run_id=11)
        record_attempt(self.conn, self.position, move_uci='e2e4', correct=True,
                       elapsed_seconds=4, evaluation_run_id=22)
        record_attempt(self.conn, self.position, move_uci='e2e4', correct=True,
                       elapsed_seconds=6, evaluation_run_id=11)
        record_attempt(self.conn, self.position, move_uci='e2e4', correct=True, elapsed_seconds=5)
        sessions = self.conn.execute('SELECT evaluation_run_id, attempts, first_try_solved, active_seconds '
                                     'FROM player_solve_sessions ORDER BY id').fetchall()
        self.assertEqual([(s['evaluation_run_id'],s['attempts']) for s in sessions],
                         [(None,2),(11,2),(22,1)])
        self.assertEqual([s['first_try_solved'] for s in sessions],[0,0,1])
        self.assertEqual([s['active_seconds'] for s in sessions],[12,9,4])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM player_solve_attempts').fetchone()[0],5)

    def test_clock_out_targets_one_run_not_the_other(self):
        record_attempt(self.conn, self.position, move_uci='d2d4', correct=False)
        record_attempt(self.conn, self.position, move_uci='g1f3', correct=False, evaluation_run_id=11)
        abandon_session(self.conn, 1, evaluation_run_id=11)
        row = self.conn.execute('SELECT evaluation_run_id, abandoned_at FROM player_solve_sessions '
                                'ORDER BY id').fetchall()
        self.assertIsNone(row[0]['abandoned_at'])
        self.assertIsNotNone(row[1]['abandoned_at'])
        record_attempt(self.conn, self.position, move_uci='e2e4', correct=True, evaluation_run_id=11)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM player_solve_sessions').fetchone()[0],3)

    def test_schema_upgrade_from_pre_v98_sessions_is_additive(self):
        self.conn.close()
        legacy = sqlite3.connect(db.DB_PATH)
        legacy.execute('DROP INDEX IF EXISTS idx_player_open_regular_session')
        legacy.execute('DROP INDEX IF EXISTS idx_player_open_evaluation_session')
        # Simulate older database by restoring a historic session table definition.
        legacy.execute('ALTER TABLE player_solve_sessions RENAME TO player_solve_sessions_v98')
        legacy.execute('''CREATE TABLE player_solve_sessions (
            id INTEGER PRIMARY KEY, position_id INTEGER, account_id INTEGER,
            job_id INTEGER, game_id TEXT, opening_key TEXT, opening_name TEXT,
            primary_motif_key TEXT, learning_mode TEXT, lesson_key TEXT,
            attempts INTEGER DEFAULT 0, first_try_solved INTEGER DEFAULT 0,
            active_seconds REAL DEFAULT 0, solve_seconds REAL,
            timing_status TEXT DEFAULT 'pending',max_solve_seconds REAL DEFAULT 300,
            started_at TEXT DEFAULT CURRENT_TIMESTAMP,solved_at TEXT,abandoned_at TEXT)''')
        legacy.execute('DROP TABLE player_solve_sessions_v98')
        legacy.execute('''CREATE UNIQUE INDEX idx_player_open_session
                 ON player_solve_sessions(position_id)
                 WHERE solved_at IS NULL AND abandoned_at IS NULL''')
        legacy.execute('INSERT INTO player_solve_sessions(position_id,account_id,job_id) VALUES(1,1,1)')
        legacy.commit()
        legacy.close()
        db.init_db()
        with db.connect() as migrated:
            self.assertIn('evaluation_run_id', [r['name'] for r in migrated.execute('PRAGMA table_info(player_solve_sessions)')])
            self.assertEqual(migrated.execute('SELECT COUNT(*) FROM player_solve_sessions').fetchone()[0],1)
            indexes = {row['name'] for row in migrated.execute('PRAGMA index_list(player_solve_sessions)')}
            self.assertIn('idx_player_open_regular_session',indexes)
            self.assertIn('idx_player_open_evaluation_session',indexes)
        self.conn = db.connect()


if __name__ == '__main__': unittest.main()
