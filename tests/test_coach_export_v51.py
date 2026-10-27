"""Version-aware feedback CSV regression; requires only stdlib SQLite."""
import csv
import io
import sqlite3
import unittest
from test_feedback_analytics_v48 import schema
import feedback_analytics as reports


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider, username) VALUES ('lichess', 'reviewer')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES (1,'May','[]')")
        self.conn.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES ('simplification','Simplify','Strategy','Trades')")
        self.conn.execute("""INSERT INTO training_positions(job_id,game_id,category,fen,user_color,move_number,
            best_move_uci, played_move_uci, learned, coach_prompt, coach_explanation,
            coaching_version, best_pv_uci, played_pv_uci, eval_before_cp, eval_after_cp,
            centipawn_loss) VALUES (1,'g1','mistake','4k3/8/8/8/8/8/8/4K3 w - - 0 1',
            'white',14,'e1d1','e1f1',1,'Find a better move','Simplify with the trade.',
            'coach-v51','[\"e1d1\"]','[\"e1f1\"]',75,-30,105)""")
        self.conn.execute("INSERT INTO position_concepts(position_id,concept_key,confidence,is_primary,evidence,classifier_version) VALUES (1,'simplification',0.92,1,'Even trade','classifier-v51')")
        self.conn.execute("INSERT INTO coach_threads(account_id,position_id) VALUES (1,1)")
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES (1,'user','Why trade?')")
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES (1,'assistant','To simplify.')")
        self.conn.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES (2,1,1,-1)")
        self.conn.commit()
        from feedback_history import migrate_legacy_feedback
        migrate_legacy_feedback(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_at_vote_vs_current_labels_and_evidence_exported(self):
        reports.record_position_vote(self.conn,1,'explanation',-1,text='Too vague')
        reports.record_position_vote(self.conn,1,'motif',1)
        self.conn.execute("UPDATE training_positions SET coach_explanation='New short explanation',coaching_version='coach-v52' WHERE id=1")
        records=list(csv.DictReader(io.StringIO(reports.csv_bytes(reports.report_rows(self.conn)).decode('utf-8-sig'))))
        self.assertEqual(len(records),3)
        explanation=next(row for row in records if row['feedback_type']=='explanation')
        self.assertEqual(explanation['content_snapshot'],'Too vague')
        self.assertEqual(explanation['current_explanation'],'New short explanation')
        self.assertEqual(explanation['coaching_version'],'coach-v51')
        self.assertEqual(explanation['current_coaching_version'],'coach-v52')
        self.assertEqual(explanation['classifier_version_at_vote'],'classifier-v51')
        self.assertEqual(explanation['fen'],'4k3/8/8/8/8/8/8/4K3 w - - 0 1')
        self.assertEqual(explanation['best_move_uci'],'e1d1')
        self.assertEqual(explanation['rating_label'],'thumbs_down')
        self.assertEqual(explanation['position_url'],'/trainer/1?position=1')
        self.assertIn('best_pv_uci', explanation)
        self.assertEqual(explanation['current_primary_motif_evidence'],'Even trade')
        coach=next(row for row in records if row['feedback_type']=='coaching')
        self.assertEqual(coach['chat_user_message'],'Why trade?')
        self.assertEqual(coach['content_snapshot'],'To simplify.')
        self.assertEqual(coach['rating'] ,'-1')

    def test_version_and_category_filter(self):
        reports.record_position_vote(self.conn,1,'explanation',1)
        self.assertEqual(len(reports.report_rows(self.conn,{'coaching_version':'coach-v51'})),2)  # Includes legacy chat's current-position fallback
        self.assertEqual(len(reports.report_rows(self.conn,{'position_category':'mistake'})),2)
        self.assertEqual(len(reports.report_rows(self.conn,{'position_category':'excellent_move'})),0)
        self.assertEqual(reports.report_summary(reports.report_rows(self.conn))['by_coaching_version'][0]['name'],'coach-v51')
        self.assertTrue(any(c['value']=='mistake' for c in reports.report_facets(self.conn)['position_categories']))

if __name__ == '__main__':
    unittest.main()
