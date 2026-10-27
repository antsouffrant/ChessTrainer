"""Historical feedback versions must remain visible after a coaching refresh."""
import csv
import io
import sqlite3
import unittest

from test_feedback_analytics_v48 import schema
import feedback_analytics as feedback


class CoachVersionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','test')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'month','[]')")
        self.conn.execute("""INSERT INTO learning_concepts(key,name,family,description,status,source)
                             VALUES('fork','Double Attack','Tactics','','seeded','built_in')""")
        self.conn.execute("""INSERT INTO training_positions
                             (job_id,game_id,category,learning_mode,fen,user_color,move_number,best_move_uci,
                              learned,coaching_version,coach_explanation)
                             VALUES(1,'game','mistake','mistakes','FEN','white',12,'a2a4',1,'coach-old','Old explanation')""")
        self.conn.execute("INSERT INTO position_concepts(position_id,concept_key,is_primary,confidence,classifier_version) VALUES(1,'fork',1,.85,'classifier-v1')")
        self.conn.execute("""INSERT INTO position_motif_taxonomy(position_id,context_key,move_type_key,motif_key,taxonomy_version)
                             VALUES(1,'attack','tactical','fork','taxonomy-v1')""")
        self.conn.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,1)")
        self.conn.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'assistant','old chat')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_snapshot_versions_survive_refresh_and_appear_in_dropdown(self):
        feedback.record_position_vote(self.conn,1,'explanation',-1,text='Old explanation')
        feedback.save_taxonomy_feedback(self.conn,1,'context','defend')
        self.conn.execute("""INSERT INTO coach_message_feedback
                 (message_id,account_id,position_id,rating,coaching_version_at_vote)
                 VALUES (1,1,1,1,'coach-old')""")
        # Historical chat thumbs were stored in the v85 latest-state table;
        # startup migrates them once before any cache/refresh operation.
        from feedback_history import migrate_legacy_feedback
        migrate_legacy_feedback(self.conn)
        self.conn.execute("UPDATE training_positions SET coaching_version='coach-new',coach_explanation='New explanation' WHERE id=1")
        self.conn.execute("UPDATE position_motif_taxonomy SET taxonomy_version='taxonomy-v2' WHERE position_id=1")
        self.conn.commit()
        versions = [v['value'] for v in feedback.report_facets(self.conn)['coaching_versions']]
        self.assertEqual(versions,['coach-old','coach-new'])
        older = feedback.report_rows(self.conn,{'coaching_version':'coach-old'})
        self.assertEqual({r['feedback_type'] for r in older}, {'explanation','taxonomy_context','coaching'})
        self.assertFalse(feedback.report_rows(self.conn,{'coaching_version':'coach-new'}))
        self.assertTrue(all(r['coaching_version']=='coach-old' for r in older))
        self.assertTrue(all(r['report_coaching_version']=='coach-old' for r in older))
        self.assertTrue(all(r['coaching_version_source']=='feedback_snapshot' for r in older))
        self.assertEqual(feedback.report_summary(older)['by_coaching_version'][0]['name'],'coach-old')
        csv_rows=list(csv.DictReader(io.StringIO(feedback.csv_bytes(older).decode('utf-8-sig'))))
        self.assertEqual(len(csv_rows),3)
        self.assertTrue(all(r['current_coaching_version']=='coach-new' for r in csv_rows))
        self.assertTrue(all(r['report_coaching_version']=='coach-old' for r in csv_rows))

    def test_new_taxonomy_selection_records_latest_version_independently(self):
        feedback.save_taxonomy_feedback(self.conn,1,'context','defend')
        self.conn.execute("UPDATE training_positions SET coaching_version='coach-new' WHERE id=1")
        self.conn.commit()
        feedback.save_taxonomy_feedback(self.conn,1,'move_type','strategic')
        rows = feedback.report_rows(self.conn)
        self.assertEqual({r['report_coaching_version'] for r in rows},{'coach-old','coach-new'})
        old_rows=feedback.report_rows(self.conn, {'coaching_version':'coach-old'})
        new_rows=feedback.report_rows(self.conn, {'coaching_version':'coach-new'})
        self.assertEqual([r['feedback_type'] for r in old_rows],['taxonomy_context'])
        self.assertEqual([r['feedback_type'] for r in new_rows],['taxonomy_move_type'])
        self.assertEqual(self.conn.execute("""SELECT coaching_version_at_vote FROM position_taxonomy_feedback
                                              WHERE position_id=1 AND field_key='context'""").fetchone()[0],'coach-old')

    def test_legacy_rows_without_snapshots_have_explicit_current_fallback(self):
        self.conn.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES(1,1,1,1)")
        self.conn.execute("""INSERT INTO position_taxonomy_feedback
                             (position_id,account_id,field_key,selected_key,model_key_at_vote)
                             VALUES(1,1,'motif','fork','fork')""")
        self.conn.execute("UPDATE training_positions SET coaching_version='coach-new' WHERE id=1")
        self.conn.commit()
        current=feedback.report_rows(self.conn, {'coaching_version':'coach-new'})
        self.assertEqual(len(current),2)
        self.assertTrue(all(r['coaching_version_source']=='current_position_fallback' for r in current))
        self.assertFalse(feedback.report_rows(self.conn, {'coaching_version':'coach-old'}))

    def test_updating_existing_selection_replaces_its_version_snapshot(self):
        feedback.save_taxonomy_feedback(self.conn,1,'context','defend')
        self.conn.execute("UPDATE training_positions SET coaching_version='coach-new' WHERE id=1")
        self.conn.commit()
        feedback.save_taxonomy_feedback(self.conn,1,'context','attack')
        result=self.conn.execute("SELECT coaching_version_at_vote FROM position_taxonomy_feedback WHERE position_id=1 AND field_key='context'").fetchone()
        self.assertEqual(result[0],'coach-new')
        self.assertEqual(len(feedback.report_rows(self.conn)),2)

if __name__=='__main__': unittest.main()
