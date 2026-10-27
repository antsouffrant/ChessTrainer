"""Dependency-free database contract for Player learning sessions."""
import ast
import csv
import io
import sqlite3
import unittest
from pathlib import Path

from player_learning import record_attempt, abandon_session, summary, export_rows, csv_data

ROOT = Path(__file__).resolve().parents[1]

def schema():
    tree = ast.parse((ROOT / 'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets))


class PlayerLearningTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'month','[]')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'year','[]')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('fork','Double Attack','Tactics','A fork')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('pin','Pin','Tactics','Pin')")
        for job, fen, opening in [(1, 'example one', 'C20'),(1,'example two','C21'),(2,'unrelated','D00')]:
            self.conn.execute('''INSERT INTO training_positions(job_id, game_id, category, learning_mode,
                fen, user_color, move_number, best_move_uci, opening_key, opening_name)
                VALUES(?, ?, 'blunder','mistakes', ?, 'white',10,'e2e4', ?, ?)''',
                (job, f'game{fen}', fen, opening, opening))
        for p, motif in [(1,'fork'),(2,'pin'),(3,'fork')]:
            self.conn.execute('''INSERT INTO position_concepts(position_id,concept_key,confidence,is_primary,classifier_version)
                VALUES(?,?,0.9,1,'v61')''', (p,motif))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def attempt(self, position=1, good=False, seconds=10):
        row = self.conn.execute('SELECT tp.*, j.account_id FROM training_positions tp JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=?',(position,)).fetchone()
        result = record_attempt(self.conn,row,move_uci='e2e4' if good else 'd2d4',
            correct=good, elapsed_seconds=seconds, max_solve_seconds=300, lesson_key='fork')
        if good: self.conn.execute('UPDATE training_positions SET learned=1 WHERE id=?',(position,))
        return result

    def test_unattempted_position_never_creates_session(self):
        self.assertEqual(summary(self.conn, {})['overview']['attempted_positions'],0)
        self.assertEqual(summary(self.conn, {})['overview']['total_positions'],3)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM player_solve_sessions').fetchone()[0],0)

    def test_first_try_solve_and_time(self):
        event = self.attempt(good=True,seconds=38.4)
        self.assertTrue(event['first_try_solved'])
        r = summary(self.conn, {'job_id':'1'})['overview']
        self.assertEqual((r['total_positions'],r['learned_positions'],r['attempted_positions']), (2,1,1))
        self.assertEqual((r['total_attempts'],r['solved_sessions'],r['first_try_rate']), (1,1,100.0))
        self.assertEqual((r['avg_attempts_per_solve'],r['avg_solve_seconds']),(1.0,38.4))
        self.assertEqual(summary(self.conn, {'job_id':'2'})['overview']['total_attempts'],0)

    def test_failed_then_successful_attempts_with_correct_average(self):
        self.attempt(seconds=8)
        self.attempt(seconds=14)
        self.attempt(good=True,seconds=16)
        result=summary(self.conn,{})
        self.assertEqual(result['overview']['first_try_rate'],0)
        self.assertEqual(result['overview']['avg_attempts_per_solve'],3.0)
        self.assertEqual(result['overview']['avg_solve_seconds'],38)
        self.assertEqual(result['histogram'][2]['count'],1)
        rows=export_rows(self.conn, {},'attempts')
        self.assertEqual([x['attempt_number'] for x in rows],[1,2,3])
        self.assertEqual([x['correct'] for x in rows],[0,0,1])

    def test_long_and_missing_times_excluded_but_attempts_kept(self):
        self.attempt(good=True,seconds=410)
        self.attempt(position=2,good=True,seconds=None)
        r=summary(self.conn,{})['overview']
        self.assertEqual((r['solved_sessions'],r['excluded_solve_times']), (2,2))
        self.assertIsNone(r['avg_solve_seconds'])
        self.assertEqual(r['first_try_rate'],100.0)

    def test_combined_duration_over_limit_excludes_only_timing(self):
        self.attempt(seconds=230)
        self.attempt(good=True, seconds=100)
        overview = summary(self.conn, {})['overview']
        self.assertEqual(overview['solved_sessions'], 1)
        self.assertEqual(overview['avg_attempts_per_solve'], 2.0)
        self.assertEqual(overview['excluded_solve_times'], 1)
        self.assertIsNone(overview['avg_solve_seconds'])

    def test_first_time_rate_not_inflated_by_repetitions(self):
        self.attempt(seconds=3)
        self.attempt(good=True, seconds=5)
        self.conn.execute('UPDATE training_positions SET learned=0 WHERE id=1')
        self.attempt(good=True, seconds=4)
        overview = summary(self.conn, {})['overview']
        self.assertEqual(overview['first_try_rate'], 0.0)
        self.assertEqual(overview['first_try_rate_sessions'], 50.0)
        self.assertEqual(overview['attempted_positions'], 1)

    def test_repeat_after_reset_preserves_previous_session(self):
        self.attempt(good=True,seconds=11)
        self.conn.execute('UPDATE training_positions SET learned=0 WHERE id=1')
        self.attempt(good=True,seconds=25)
        r=summary(self.conn,{})['overview']
        self.assertEqual(r['solved_sessions'],2)
        self.assertEqual(r['attempted_positions'],1)
        self.assertEqual(r['avg_solve_seconds'],18.0)

    def test_abandon_open_session_and_replay(self):
        self.attempt(seconds=12)
        abandon_session(self.conn, 1)
        self.attempt(good=True,seconds=19)
        sessions=export_rows(self.conn, {'job_id':1})
        self.assertEqual(len(sessions),2)
        self.assertIsNotNone(sessions[0]['abandoned_at'])
        self.assertEqual(sessions[1]['first_try_solved'],1)
        self.assertEqual(summary(self.conn,{})['overview']['first_try_rate'],0)
        self.assertEqual(summary(self.conn,{})['overview']['first_try_rate_sessions'],50)

    def test_csv_and_motif_filters(self):
        self.attempt(good=True,seconds=9)
        self.attempt(position=2,good=True,seconds=12)
        self.assertEqual(summary(self.conn,{'primary_motif_key':'fork'})['overview']['total_positions'],2)
        self.assertEqual(summary(self.conn,{'opening_key':'C21'})['overview']['solved_sessions'],1)
        csvtext=csv_data(export_rows(self.conn, {'job_id':1})).decode('utf-8-sig')
        data=list(csv.DictReader(io.StringIO(csvtext)))
        self.assertEqual(len(data),2)
        self.assertIn('lesson_key',data[0]);self.assertIn('first_try_solved',data[0])

if __name__=='__main__': unittest.main()
