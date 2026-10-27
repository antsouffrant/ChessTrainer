"""Persistent coaching thumbs, filtering, CSV and pre-existing chat integration."""
import ast
import csv
import io
import sqlite3
import unittest
import tempfile
import sys
import types
from pathlib import Path

import feedback_analytics as analytics

ROOT = Path(__file__).resolve().parents[1]

def schema():
    tree = ast.parse((ROOT / 'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets))


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider, username) VALUES ('lichess','alice')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,source_type) VALUES (1,'last year','[]','self')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,source_type) VALUES (1,'last month','[]','self')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES ('fork','Knight fork','Tactics','Forks')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES ('pin','Pin','Tactics','Pins')")
        self.conn.execute("""INSERT INTO training_positions(job_id,game_id,category,learning_mode,fen,user_color,move_number,
            best_move_uci,learned,opening_key,opening_name,coach_explanation,coaching_version)
            VALUES (1,'game1','major_blunder','mistakes','FEN1','white',12,'a2a4',1,'C20','King pawn','Learn pin!', 'v47')""")
        self.conn.execute("""INSERT INTO training_positions(job_id,game_id,category,learning_mode,fen,user_color,move_number,
            best_move_uci,learned,opening_key,opening_name) VALUES (2,'game2','excellent_move','excellent',
            'FEN2','black',8,'a7a5',0,'D00','Queen pawn')""")
        self.conn.execute("INSERT INTO position_concepts(position_id, concept_key, confidence, is_primary, classifier_version) VALUES (1,'pin',0.8,1,'v47')")
        self.conn.execute("INSERT INTO position_concepts(position_id, concept_key, confidence, is_primary, classifier_version) VALUES (2,'fork',0.8,1,'v47')")
        self.conn.execute('INSERT INTO coach_threads(account_id,position_id) VALUES (1,1)')
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES (1,'assistant','Try pressuring the rook.')")
        self.conn.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES (1,1,1,1)")
        self.conn.commit()
        from feedback_history import migrate_legacy_feedback
        migrate_legacy_feedback(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_repeat_rating_updates_not_appends(self):
        a = analytics.record_position_vote(self.conn, 1, 'position', 1)
        self.assertEqual(a, {'position': 1})
        a = analytics.record_position_vote(self.conn, 1, 'position', -1)
        self.assertEqual(a, {'position': -1})
        analytics.record_position_vote(self.conn, 1, 'explanation', 1, text='Counterattack instead of defend')
        analytics.record_position_vote(self.conn, 1, 'motif', -1, lesson_key='fork')
        rows = analytics.report_rows(self.conn)
        self.assertEqual(len(rows), 4)
        self.assertEqual(analytics.report_summary(rows)['overall'], {'total':4,'up':2,'down':2,'up_pct':50.0})
        self.assertEqual(analytics.report_summary(rows)['categories']['coaching']['total'],1)
        self.assertEqual(analytics.report_summary(rows)['categories']['position']['up_pct'],0)
        self.assertEqual(analytics.report_summary(rows)['categories']['explanation']['up_pct'],100)
        self.assertEqual(next(r for r in rows if r['feedback_type']=='explanation')['content_snapshot'], 'Counterattack instead of defend')
        self.assertEqual(next(r for r in rows if r['feedback_type']=='motif')['lesson_name'], 'Knight fork')
        self.assertEqual(next(r for r in rows if r['feedback_type']=='motif')['primary_motif_name'], 'Pin')
        self.assertEqual(analytics.report_summary(rows)['by_opening'][0]['name'],'King pawn')

    def test_restrict_rating_to_learned_positions(self):
        with self.assertRaises(PermissionError):
            analytics.record_position_vote(self.conn, 2, 'position', 1)
        with self.assertRaises(ValueError):
            analytics.record_position_vote(self.conn, 1, 'chat', 1)
        with self.assertRaises(ValueError):
            analytics.record_position_vote(self.conn, 1, 'position', 2)
        self.assertEqual(len(analytics.report_rows(self.conn)),1)

    def test_filtering_and_csv_export(self):
        analytics.record_position_vote(self.conn, 1, 'motif', -1, lesson_key='fork')
        analytics.record_position_vote(self.conn, 1, 'explanation', 1, text='=HYPERLINK("evil", "click")')
        for filt, count in [({'job_id':'1'},3), ({'job_id':'2'},0),
                            ({'primary_motif_key':'pin'},3), ({'lesson_key':'fork'},1),
                            ({'opening_key':'C20'},3), ({'learning_mode':'mistakes'},3),
                            ({'feedback_type':'coaching'},1), ({'rating':'-1'},1),
                            ({'rating':'1', 'feedback_type':'motif'},0)]:
            self.assertEqual(len(analytics.report_rows(self.conn,filt)),count,str(filt))
        saved = analytics.csv_bytes(analytics.report_rows(self.conn)).decode('utf-8-sig')
        records = list(csv.DictReader(io.StringIO(saved)))
        self.assertEqual(len(records),3)
        self.assertTrue(next(r for r in records if r['feedback_type']=='explanation')['content_snapshot'].startswith("'=HYPERLINK"))
        self.assertIn('message_id', records[0]);self.assertIn('primary_motif_key', records[0]);self.assertIn('lesson_name', records[0])
        facets = analytics.report_facets(self.conn)
        self.assertEqual(len(facets['game_lists']),2)
        self.assertEqual(len(facets['openings']),2)

    def test_chat_feedback_migration_preserves_legacy_vote(self):
        # Existing users have already voted in coach_message_feedback.
        original = schema()
        before, after = original.split('CREATE TABLE IF NOT EXISTS coach_message_feedback (', 1)
        chat_schema, remainder = after.split('CREATE INDEX IF NOT EXISTS idx_coach_feedback_account', 1)
        self.assertIn('    lesson_key TEXT,', chat_schema)
        legacy_schema = before + 'CREATE TABLE IF NOT EXISTS coach_message_feedback (' + chat_schema.replace('    lesson_key TEXT,\n', '') + 'CREATE INDEX IF NOT EXISTS idx_coach_feedback_account' + remainder
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'chess.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.executescript(legacy_schema)
                connection.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','original')")
                connection.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES (1,'month','[]')")
                connection.execute("INSERT INTO training_positions(job_id,category,fen,user_color,move_number,best_move_uci,learned) VALUES (1,'major_blunder','a','white',1,'e2e4',1)")
                connection.execute('INSERT INTO coach_threads(account_id,position_id) VALUES (1,1)')
                connection.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES (1,'assistant','Old rating')")
                connection.execute('INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES (1,1,1,-1)')
            sys.modules.setdefault('learning', types.SimpleNamespace(CLASSIFIER_VERSION='test', CONCEPT_CATALOG=[]))
            sys.path.insert(0,str(ROOT))
            import db
            previous = db.DB_PATH
            try:
                db.DB_PATH = path
                db.init_db()
                with db.connect() as connection:
                    row = connection.execute('SELECT rating,lesson_key FROM coach_message_feedback WHERE message_id=1').fetchone()
                    self.assertEqual(row['rating'], -1)
                    self.assertIsNone(row['lesson_key'])
                    self.assertEqual(len(analytics.report_rows(connection, {'feedback_type':'coaching'})),1)
            finally:
                db.DB_PATH = previous

    def test_empty_report_has_no_fabricated_percentage(self):
        summary = analytics.report_summary([])
        self.assertIsNone(summary['overall']['up_pct'])
        self.assertTrue(all(value['total'] == 0 for value in summary['categories'].values()))
        self.assertEqual(analytics.csv_bytes([]).decode('utf-8-sig').count('\n'),1)

if __name__ == '__main__':
    unittest.main()
