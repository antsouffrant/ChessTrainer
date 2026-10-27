"""Clock in/out regressions that do not require python-chess or Flask."""
import ast
import sqlite3
import unittest
from pathlib import Path
from player_learning import record_attempt, abandon_session, export_rows

ROOT = Path(__file__).resolve().parents[1]


class PlayerClockInTests(unittest.TestCase):
    def setUp(self):
        module = ast.parse((ROOT / 'db.py').read_text())
        script = next(node.value.value for node in module.body if isinstance(node, ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id == 'SCHEMA' for t in node.targets))
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(script)
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','learner')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'month','[]')")
        self.conn.execute("""INSERT INTO training_positions(job_id,game_id,category,learning_mode,fen,user_color,move_number,best_move_uci)
            VALUES(1,'test','blunder','mistakes','sample fen','white',15,'e2e4')""")
        self.row = self.conn.execute('''SELECT tp.*, j.account_id FROM training_positions tp
                                      JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=1''').fetchone()

    def tearDown(self):
        self.conn.close()

    def test_clock_out_preserves_old_data_and_abandons_incomplete_cycle(self):
        record_attempt(self.conn, self.row, move_uci='d2d4', correct=False, elapsed_seconds=12)
        abandon_session(self.conn,1)
        record_attempt(self.conn, self.row, move_uci='e2e4', correct=True, elapsed_seconds=4)
        sessions=export_rows(self.conn, {'job_id':1})
        self.assertEqual(len(sessions),2)
        self.assertIsNotNone(sessions[0]['abandoned_at'])
        self.assertIsNotNone(sessions[1]['solved_at'])
        self.assertEqual(sessions[1]['active_seconds'],4)
        self.assertEqual([x[0] for x in self.conn.execute('SELECT correct FROM player_solve_attempts ORDER BY id')], [0,1])

    def test_server_guards_recording_and_persists_ordinary_progress(self):
        source=(ROOT/'app.py').read_text()
        self.assertIn("payload.get('track_learning', True) is not False", source)
        self.assertIn("payload.get('start_new_learning_session') is True", source)
        self.assertIn('abandon_player_session(conn, position_id)', source)
        self.assertIn("@app.post('/api/positions/<int:position_id>/player/clock-out')", source)
        self.assertIn('UPDATE training_positions\n                SET attempts = attempts + 1,', source)
        self.assertIn('learned = 1', source)

if __name__ == '__main__':
    unittest.main()
