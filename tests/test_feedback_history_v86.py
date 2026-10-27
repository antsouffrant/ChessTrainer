"""v86 regression: independent append-only feedback history and cache reset."""
import ast
import sqlite3
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import feedback_history as history
import feedback_analytics as feedback
from coaching.coaching_refresh.coaching_cache import clear_coaching_cache


def schema():
    tree=ast.parse((ROOT/'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in node.targets))


class FeedbackHistoryTest(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema())
        self.db.execute("INSERT INTO accounts(id,provider,username) VALUES(1,'lichess','tester')")
        self.db.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types,status) VALUES(1,1,'all','[]','complete')")
        self.db.execute("INSERT INTO retrieval_processes(job_id,status) VALUES(1,'complete')")
        self.db.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('skewer','Skewer','tactical','')")
        self.db.execute("""INSERT INTO training_positions
           (id,job_id,game_id,category,fen,user_color,move_number,mistake_ply,learned,
            best_move_uci,played_move_uci,coaching_version,coach_explanation,best_pv_uci)
           VALUES (11,1,'game-1','blunder','8/8/8/8/8/8/8/8 w - - 0 1','white',15,29,1,
                   'd1d8','a1a8','rules-v30','Old coach','d1d8 a8d8')""")
        self.db.execute("INSERT INTO coach_board_attempts(position_id,session_key,move_uci,correct) VALUES(11,'s','a1a8',0)")
        self.db.execute("INSERT INTO coach_threads(id,account_id,position_id) VALUES(22,1,11)")
        self.db.execute("INSERT INTO coach_messages(id,thread_id,role,content) VALUES(31,22,'assistant','The pinned rook')")
        self.db.execute("INSERT INTO position_feedback(position_id,account_id,category,rating,coaching_version,content_snapshot) VALUES(11,1,'explanation',-1,'rules-v30','Old coach')")
        self.db.execute("INSERT INTO coach_message_feedback(message_id,position_id,account_id,rating,coaching_version_at_vote) VALUES(31,11,1,1,'rules-v30')")
        self.db.commit()

    def test_import_votes_is_idempotent_and_retains_chat_after_cache_clear(self):
        history.migrate_legacy_feedback(self.db)
        history.migrate_legacy_feedback(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM feedback_events').fetchone()[0],2)
        self.assertEqual(self.db.execute("SELECT content_snapshot FROM feedback_events WHERE feedback_type='coaching'").fetchone()[0],'The pinned rook')
        clear_coaching_cache(self.db,1)
        self.db.commit()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coach_message_feedback').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM feedback_events').fetchone()[0],2)
        self.assertEqual(len(feedback.report_rows(self.db,{'feedback_type':'coaching'})),1)
        self.assertEqual(len(feedback.report_rows(self.db,{'feedback_type':'explanation'})),1)

    def test_repeated_votes_per_version_and_continuation_and_undo(self):
        history.migrate_legacy_feedback(self.db)
        feedback.record_continuation_vote(self.db,11,'a1a8',-1,text='The first mistake',suggested_text='Misses the win')
        feedback.record_continuation_vote(self.db,11,'a1a8',1,text='The first mistake')
        feedback.record_position_vote(self.db,11,'explanation',1,text='Old coach')
        self.assertEqual(feedback.continuation_votes(self.db,11),{'a1a8':1})
        self.assertEqual(feedback.position_votes(self.db,11)['explanation'],1)
        self.assertEqual(len(feedback.report_rows(self.db,{'history':'all'})),5)
        self.assertEqual(len(feedback.report_rows(self.db)),3)
        self.db.execute("UPDATE training_positions SET coaching_version='rules-v31',coach_explanation='New explanation' WHERE id=11")
        self.assertNotIn('explanation', feedback.position_votes(self.db,11))
        self.assertEqual(feedback.continuation_votes(self.db,11),{})
        feedback.record_position_vote(self.db,11,'explanation',-1,text='New explanation',suggested_text='Misleading')
        self.assertEqual(feedback.position_votes(self.db,11)['explanation'],-1)
        self.assertEqual(len(feedback.report_rows(self.db,{'feedback_type':'explanation','coaching_version':'rules-v30'})),2)
        self.assertEqual(len(feedback.report_rows(self.db,{'feedback_type':'explanation','coaching_version':'rules-v31'})),1)
        feedback.record_position_vote(self.db,11,'explanation',0)
        self.assertNotIn('explanation',feedback.position_votes(self.db,11))
        self.assertEqual(len(feedback.report_rows(self.db,{'feedback_type':'explanation','coaching_version':'rules-v31'})),0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM feedback_events WHERE feedback_type='explanation'").fetchone()[0],6)

    def test_taxonomy_correction_and_reversion_keep_versioned_history(self):
        history.migrate_legacy_feedback(self.db)
        self.db.execute("INSERT INTO position_motif_taxonomy(position_id,context_key,move_type_key,motif_key,taxonomy_version) VALUES(11,'attack','tactical','skewer','v30')")
        feedback.save_taxonomy_feedback(self.db,11,'context','defend')
        self.assertEqual(feedback.taxonomy_feedback_choices(self.db,11)['selected']['context'],'defend')
        feedback.save_taxonomy_feedback(self.db,11,'context','')
        self.assertEqual(feedback.taxonomy_feedback_choices(self.db,11)['selected'],{})
        records=self.db.execute("SELECT rating,selected_key FROM feedback_events WHERE feedback_type='taxonomy_context' ORDER BY id").fetchall()
        self.assertEqual([(r[0],r[1]) for r in records],[(-1,'defend'),(0,None)])

    def test_analytics_does_not_inflate_repeat_rating_denominators(self):
        history.migrate_legacy_feedback(self.db)
        feedback.record_position_vote(self.db,11,'explanation',-1,text='Once')
        feedback.record_position_vote(self.db,11,'explanation',1,text='Again')
        r=feedback.coaching_metric_chart(self.db,metric='approval',group_by='feedback_area')
        exp=next(x for x in r['rows'] if x['key']=='explanation')
        self.assertEqual((exp['numerator'],exp['denominator']),(1,1))


# Attach additional lifecycle checks without relying on flask/python-chess.
def test_orphaned_feedback_can_still_be_exported(self):
    history.migrate_legacy_feedback(self.db)
    self.db.execute('DELETE FROM training_positions WHERE id=11')
    self.db.commit()
    rows=feedback.report_rows(self.db)
    self.assertEqual(len(rows),2)
    self.assertEqual({r['content_snapshot'] for r in rows}, {'Old coach','The pinned rook'})
    self.assertTrue(all(r['game_id']=='game-1' for r in rows))
    self.assertTrue(all(r['username']=='tester' for r in rows))
    self.assertTrue(all(r['fen'] for r in rows))

FeedbackHistoryTest.test_orphaned_feedback_can_still_be_exported = test_orphaned_feedback_can_still_be_exported


def test_latest_global_approval_does_not_treat_old_approval_as_current(self):
    history.migrate_legacy_feedback(self.db)
    feedback.record_position_vote(self.db,11,'explanation',1,text='Old positive')
    self.db.execute("UPDATE training_positions SET coaching_version='rules-v31' WHERE id=11")
    feedback.record_position_vote(self.db,11,'explanation',-1,text='New negative')
    unfiltered=feedback.coaching_metric_chart(self.db,metric='approval',group_by='feedback_area')
    approved=next(r for r in unfiltered['rows'] if r['key']=='explanation')
    self.assertEqual((approved['numerator'],approved['denominator']),(0,1))
    historic=feedback.coaching_metric_chart(self.db,metric='approval',group_by='feedback_area',
                                            filters={'coaching_version':'rules-v30'})
    old=next(r for r in historic['rows'] if r['key']=='explanation')
    self.assertEqual((old['numerator'],old['denominator']),(1,1))

FeedbackHistoryTest.test_latest_global_approval_does_not_treat_old_approval_as_current = test_latest_global_approval_does_not_treat_old_approval_as_current

if __name__ == '__main__':
    unittest.main()
