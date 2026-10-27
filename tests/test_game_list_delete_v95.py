"""SQLite-only regression: delete an empty or populated list without touching other lists.

No Flask or Stockfish required. The schema is extracted from db.py so this test
uses the real production foreign-key definitions.
"""
import ast
import sqlite3
import unittest
from pathlib import Path

from game_list_lifecycle import delete_list_records


def schema_text():
    parsed = ast.parse((Path(__file__).parents[1] / 'db.py').read_text())
    for stmt in parsed.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise AssertionError('Missing production schema')


class GameListDeleteTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema_text())
        self.db.execute("INSERT INTO accounts(id,provider,username) VALUES (1,'lichess','player')")
        for job in (1,2):
            self.db.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types,status) VALUES (?,1,'2026','[]','complete')",(job,))
        self.db.execute("INSERT INTO analyzed_games(account_id,game_id,source_job_id) VALUES (1,'game1',1)")
        self.db.commit()

    def tearDown(self):self.db.close()

    def test_empty_list_can_be_deleted_and_reusable_games_detached(self):
        delete_list_records(self.db,1)
        self.assertIsNone(self.db.execute('SELECT 1 FROM analysis_jobs WHERE id=1').fetchone())
        self.assertIsNotNone(self.db.execute('SELECT 1 FROM analysis_jobs WHERE id=2').fetchone())
        self.assertIsNone(self.db.execute('SELECT source_job_id FROM analyzed_games WHERE game_id="game1"').fetchone()[0])
        self.assertFalse(self.db.execute('PRAGMA foreign_key_check').fetchall())

    def test_populated_list_removes_evaluations_and_preserves_other_positions(self):
        for job in (1,2):
            self.db.execute('''INSERT INTO training_positions(id,job_id,category,fen,user_color,move_number,best_move_uci)
                  VALUES (?,?,?,?,?,?,?)''',(job,job,'mistake','8/8/8/8/8/8/8/8 w - - 0 1','white',1,'a2a3'))
        self.db.execute("INSERT INTO coach_benchmark_cohorts(job_id,source_count,sample_size) VALUES (1,1,1)")
        self.db.execute("INSERT INTO coach_benchmark_positions(job_id,position_id,ordinal,fen,category,learning_mode) VALUES (1,1,1,'fen','mistake','mistakes')")
        self.db.execute("INSERT INTO coach_benchmark_runs(id,job_id,coaching_version,taxonomy_version,expected_positions,captured_positions) VALUES (10,1,'v34','3.4',1,1)")
        self.db.execute("INSERT INTO evaluation_runs(id,job_id,benchmark_run_id,coaching_version) VALUES (20,1,10,'v34')")
        self.db.execute("INSERT INTO evaluation_run_positions(run_id,position_id) VALUES (20,1)")
        self.db.execute("INSERT INTO feedback_positions(position_key,account_id,provider,username,game_id,board_identity) VALUES ('key',1,'lichess','player','game1','board')")
        self.db.execute("INSERT INTO feedback_position_sources(position_id,position_key) VALUES (1,'key')")
        self.db.execute("INSERT INTO feedback_events(position_key,source_position_id,account_id,feedback_type,rating,coaching_version) VALUES ('key',1,1,'explanation',-1,'v34')")
        self.db.commit()
        delete_list_records(self.db,1)
        for table in ['coach_benchmark_cohorts','coach_benchmark_runs','evaluation_runs','evaluation_run_positions']:
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
        self.assertEqual(self.db.execute('SELECT job_id FROM training_positions').fetchall(),[(2,)])
        self.assertEqual(self.db.execute('SELECT rating FROM feedback_events').fetchone()[0],-1)
        self.assertFalse(self.db.execute('PRAGMA foreign_key_check').fetchall())


if __name__=='__main__':unittest.main()
