"""v56 feedback proposals: vote reversal, catalog validation, export and migrations."""
import csv
import io
import re
import sqlite3
import unittest
from pathlib import Path

from test_feedback_analytics_v48 import schema
import feedback_analytics as fa

ROOT = Path(__file__).resolve().parents[1]


class FeedbackCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','tester')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'past','[]')")
        self.conn.execute("""INSERT INTO training_positions(job_id, game_id, category, fen, user_color,
            move_number, learned, played_move_uci, best_move_uci, coach_explanation, coaching_version)
            VALUES(1, 'g1', 'mistake', '4k3/8/8/8/8/8/8/4K3 w - - 0 1', 'white', 17, 1,
                   'e1f1', 'e1d1', 'Avoid the trade.', 'v55')""")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('pin','Pin','Tactics','Pin')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('sacrifice','Sacrifice Material','Strategy','Give material')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description,status) VALUES('old','Retired','Other','Old','retired')")
        self.conn.execute("INSERT INTO position_concepts(position_id,concept_key,confidence,is_primary,classifier_version) VALUES(1,'pin',.8,1,'v54')")
        self.conn.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,1)")
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'user','Why?')")
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'assistant','Avoid the pin.')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_explanation_down_correction_up_erase_down_again(self):
        fa.record_position_vote(self.conn, 1, 'explanation', -1, text='Avoid the pin.',
                                suggested_text='This loses a rook to Qxe1+ instead.')
        self.assertEqual(fa.position_feedback_details(self.conn, 1)['explanation']['suggested_text'],
                         'This loses a rook to Qxe1+ instead.')
        fa.record_position_vote(self.conn, 1, 'explanation', -1)  # reopen selected thumbs down
        self.assertIn('Qxe1+', fa.position_feedback_details(self.conn, 1)['explanation']['suggested_text'])
        fa.record_position_vote(self.conn, 1, 'explanation', 1)
        self.assertEqual(fa.position_feedback_details(self.conn, 1)['explanation']['suggested_text'], '')
        self.assertEqual(fa.regression_candidate_rows(fa.report_rows(self.conn)), [])
        fa.record_position_vote(self.conn, 1, 'explanation', -1)
        self.assertEqual(fa.position_feedback_details(self.conn, 1)['explanation']['suggested_text'], '')
        self.assertEqual(len(fa.report_rows(self.conn)), 1)

    def test_motif_select_validation_and_erasure(self):
        options = fa.motif_feedback_options(self.conn)
        self.assertEqual({o['key'] for o in options}, {'pin','sacrifice'})
        with self.assertRaises(ValueError):
            fa.record_position_vote(self.conn, 1, 'motif', -1, suggested_motif_key='old')
        with self.assertRaises(ValueError):
            fa.record_position_vote(self.conn, 1, 'explanation', -1, suggested_motif_key='sacrifice')
        fa.record_position_vote(self.conn, 1, 'motif', -1, suggested_motif_key='sacrifice')
        self.assertEqual(fa.position_feedback_details(self.conn, 1)['motif']['suggested_motif_key'],'sacrifice')
        row = fa.regression_candidate_rows(fa.report_rows(self.conn))[0]
        self.assertEqual(row['suggested_motif_name'],'Sacrifice Material')
        fa.record_position_vote(self.conn, 1, 'motif', 1)
        self.assertEqual(fa.position_feedback_details(self.conn, 1)['motif']['suggested_motif_key'],'')

    def test_position_note_and_all_csv_context(self):
        fa.record_position_vote(self.conn, 1, 'position', -1,
                                suggested_text='Not a meaningful decision; both moves are equal.')
        rows = fa.regression_candidate_rows(fa.report_rows(self.conn))
        self.assertEqual(len(rows),1)
        record = list(csv.DictReader(io.StringIO(fa.csv_bytes(rows).decode('utf-8-sig'))))[0]
        self.assertEqual(record['suggested_text'], 'Not a meaningful decision; both moves are equal.')
        self.assertEqual(record['review_status'], 'proposed')
        self.assertEqual(record['regression_candidate'], '1')
        self.assertEqual(len(record['regression_case_id']),20)
        self.assertEqual(record['fen'],'4k3/8/8/8/8/8/8/4K3 w - - 0 1')
        self.assertIn('coaching_version',record)
        with self.assertRaises(ValueError):
            fa.record_position_vote(self.conn,1,'position',-1,suggested_text='x'*6001)

    def test_chat_sql_from_actual_endpoint_upvote_erases_text(self):
        # Extract the actual SQL in app.py without importing Flask or python-chess.
        app = (ROOT / 'app.py').read_text()
        match = re.search(r"conn\.execute\('''\s*(INSERT INTO coach_message_feedback.+?)\s*'''", app, re.S)
        self.assertIsNotNone(match)
        sql = match.group(1)
        def vote(rating, correction=None):
            self.conn.execute(sql, (2,1,1,rating,'',correction,'coach-v56'))
            self.conn.commit()
            return self.conn.execute('SELECT rating,suggested_text FROM coach_message_feedback WHERE message_id=2').fetchone()
        self.assertEqual(vote(-1,'This is a fork, not a pin.')['suggested_text'], 'This is a fork, not a pin.')
        self.assertEqual(vote(-1)['suggested_text'], 'This is a fork, not a pin.')
        self.assertIsNone(vote(1)['suggested_text'])
        self.assertIsNone(vote(-1)['suggested_text'])
        self.assertEqual(len(fa.regression_candidate_rows(fa.report_rows(self.conn))),0)
        vote(-1, 'The move threatens mate instead.')
        rows = fa.regression_candidate_rows(fa.report_rows(self.conn))
        self.assertEqual(rows[0]['chat_user_message'],'Why?')
        self.assertEqual(rows[0]['content_snapshot'],'Avoid the pin.')
        self.assertEqual(rows[0]['suggested_text'],'The move threatens mate instead.')


if __name__ == '__main__':
    unittest.main()

class LegacyCorrectionMigrationTests(unittest.TestCase):
    def test_upgrade_existing_votes_without_dropping_any(self):
        import sys
        import tempfile
        import types
        old_schema = schema().replace('    suggested_text TEXT,\n    suggested_motif_key TEXT,\n', '')
        old_schema = old_schema.replace('    lesson_key TEXT,\n    suggested_text TEXT,\n', '    lesson_key TEXT,\n')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pre_v56.db'
            with sqlite3.connect(path) as conn:
                conn.executescript(old_schema)
                conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','alice')")
                conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'past','[]')")
                conn.execute("INSERT INTO training_positions(job_id,category,fen,user_color,move_number,best_move_uci,learned) VALUES(1,'mistake','fen','white',3,'e2e4',1)")
                conn.execute("INSERT INTO position_feedback(position_id,account_id,category,rating) VALUES(1,1,'explanation',-1)")
                conn.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,1)")
                conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'assistant','Old text')")
                conn.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES(1,1,1,-1)")
            sys.modules.setdefault('learning', types.SimpleNamespace(CLASSIFIER_VERSION='test', CONCEPT_CATALOG=[]))
            import db
            previous = db.DB_PATH
            try:
                db.DB_PATH = path
                db.init_db()
                with db.connect() as conn:
                    self.assertEqual(conn.execute("SELECT rating FROM position_feedback WHERE position_id=1 AND category='explanation'").fetchone()['rating'], -1)
                    self.assertEqual(conn.execute('SELECT rating FROM coach_message_feedback WHERE message_id=1').fetchone()['rating'], -1)
                    self.assertIsNone(conn.execute("SELECT suggested_text FROM position_feedback WHERE position_id=1").fetchone()['suggested_text'])
                    self.assertIsNone(conn.execute("SELECT suggested_text FROM coach_message_feedback WHERE message_id=1").fetchone()['suggested_text'])
            finally:
                db.DB_PATH = previous
