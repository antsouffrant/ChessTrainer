"""Generated messages, not the active model, own ordinary feedback."""
import ast
import sqlite3
import unittest
from pathlib import Path

from feedback_messages import ensure_message, message_feedback, record_message_feedback, hydrate_recap, snapshot, backfill_legacy_message_attribution
from feedback_analytics import report_rows


def schema():
    tree=ast.parse((Path(__file__).parent.parent/'db.py').read_text())
    return next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and
                any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))

class MessageSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema())
        self.db.execute("INSERT INTO accounts(id,provider,username) VALUES(1,'lichess','tester')")
        self.db.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types,status) VALUES(1,1,'all','[]','complete')")
        self.db.execute('''INSERT INTO training_positions
            (id,job_id,game_id,category,fen,user_color,move_number,learned,
             best_move_uci,played_move_uci,coaching_version,coach_explanation)
            VALUES (11,1,'g','mistake','8/8/8/8/8/8/8/8 w - - 0 1','white',15,1,
                    'd1d8','a1a8','v33','First generated message')''')
        self.db.execute("INSERT INTO coach_board_attempts(position_id,session_key,move_uci,correct) VALUES(11,'solved_session','a1a8',0)")

    def test_old_message_remains_rateable_after_current_model_changes(self):
        old=ensure_message(self.db,11,'solving','v33','First generated message')
        self.assertEqual(old,ensure_message(self.db,11,'solving','v33','First generated message'))
        self.db.execute("UPDATE training_positions SET coaching_version='v34',coach_explanation='Second generated message' WHERE id=11")
        current=ensure_message(self.db,11,'solving','v34','Second generated message')
        self.assertNotEqual(old,current)
        record_message_feedback(self.db,11,'solving',old,-1,suggested_text='Make it more specific')
        record_message_feedback(self.db,11,'solving',current,1)
        votes,corr=message_feedback(self.db,11)
        self.assertEqual(votes,{str(old):-1,str(current):1})
        self.assertEqual(corr[str(old)]['suggested_text'],'Make it more specific')
        # Later editing a stale message retains generation-time version.
        record_message_feedback(self.db,11,'solving',old,-1,suggested_text='Explain the pin')
        self.assertEqual(self.db.execute('''SELECT coaching_version,content_snapshot,suggested_text
            FROM feedback_events WHERE message_snapshot_id=? ORDER BY id DESC LIMIT 1''',(old,)).fetchone()[:],
            ('v33','First generated message','Explain the pin'))
        record_message_feedback(self.db,11,'solving',old,0)
        self.assertNotIn(str(old),message_feedback(self.db,11)[0])
        self.assertEqual(message_feedback(self.db,11)[0][str(current)],1)

    def test_two_messages_on_same_move_are_independent_even_same_model(self):
        a=ensure_message(self.db,11,'a1a8','v33','First reason')
        b=ensure_message(self.db,11,'a1a8','v33','Revised reason')
        self.assertNotEqual(a,b)
        record_message_feedback(self.db,11,'a1a8',a,1)
        record_message_feedback(self.db,11,'a1a8',b,-1)
        self.assertEqual(message_feedback(self.db,11)[0],{str(a):1,str(b):-1})
        rows=report_rows(self.db,{'feedback_type':'explanation'})
        self.assertEqual(len(rows),2)
        self.assertEqual({r['coaching_version'] for r in rows},{'v33'})
        self.assertEqual({r['message_snapshot_id'] for r in rows},{a,b})
        with self.assertRaises(LookupError):
            record_message_feedback(self.db,11,'solving',a,1)

    def test_feedback_snapshot_persists_after_position_cache_is_cleared(self):
        msg=ensure_message(self.db,11,'solving','v33','Original')
        record_message_feedback(self.db,11,'solving',msg,1)
        self.db.execute("UPDATE training_positions SET coaching_version=NULL,coach_explanation=NULL WHERE id=11")
        self.assertEqual(snapshot(self.db,msg,11,'solving')['generation_version'],'v33')
        record_message_feedback(self.db,11,'solving',msg,-1)
        self.assertEqual(message_feedback(self.db,11)[0][str(msg)],-1)

    def test_message_with_missing_version_can_be_rated_without_guessing(self):
        msg=ensure_message(self.db,11,'solving',None,'Pre-versioned coaching')
        self.assertEqual(snapshot(self.db,msg,11,'solving')['generation_version'],'legacy-unknown')
        record_message_feedback(self.db,11,'solving',msg,1)
        self.assertEqual(message_feedback(self.db,11)[0][str(msg)],1)
        self.assertEqual(self.db.execute('SELECT coaching_version FROM feedback_events ORDER BY id DESC LIMIT 1').fetchone()[0],
                         'legacy-unknown')

    def test_old_event_backfill_never_fabricates_generation_version(self):
        from feedback_history import append_feedback
        append_feedback(self.db,11,'explanation',-1,continuation='solving',
                        content_snapshot='Earlier saved text',coaching_version='v33')
        append_feedback(self.db,11,'explanation',1,continuation='a1a8',
                        content_snapshot='No generation tag',coaching_version=None)
        self.db.execute("UPDATE training_positions SET coaching_version='v34',coach_explanation='New' WHERE id=11")
        self.assertEqual(backfill_legacy_message_attribution(self.db),1)
        self.assertEqual(backfill_legacy_message_attribution(self.db),0)
        row=self.db.execute("SELECT coaching_version,message_snapshot_id FROM feedback_events WHERE content_snapshot='Earlier saved text'").fetchone()
        self.assertEqual(row['coaching_version'],'v33')
        self.assertEqual(snapshot(self.db,row['message_snapshot_id'],11,'solving')['generation_version'],'v33')
        self.assertIsNone(self.db.execute("SELECT message_snapshot_id FROM feedback_events WHERE coaching_version IS NULL").fetchone()[0])

    def test_evaluation_is_isolated_from_ordinary_feedback(self):
        msg=ensure_message(self.db,11,'solving','v33','Original')
        record_message_feedback(self.db,11,'solving',msg,1)
        self.db.execute('''INSERT INTO coach_benchmark_cohorts(job_id,source_count,sample_size) VALUES(1,1,1)''')
        self.db.execute('''INSERT INTO coach_benchmark_runs(id,job_id,coaching_version,taxonomy_version,expected_positions,captured_positions)
            VALUES(1,1,'v33','v33',1,1)''')
        self.db.execute("INSERT INTO evaluation_runs(id,job_id,benchmark_run_id,coaching_version,status) VALUES(2,1,1,'v33','active')")
        self.db.execute("INSERT INTO evaluation_run_positions(run_id,position_id,status) VALUES(2,11,'solved')")
        record_message_feedback(self.db,11,'solving',msg,-1,evaluation_run_id=2)
        self.assertEqual(message_feedback(self.db,11)[0][str(msg)],1)
        self.assertEqual(message_feedback(self.db,11,2)[0][str(msg)],-1)
        other=ensure_message(self.db,11,'solving','v34','Another model')
        with self.assertRaises(PermissionError):
            record_message_feedback(self.db,11,'solving',other,1,evaluation_run_id=2)

    def test_older_saved_recaps_are_hydrated_without_changing_model(self):
        meta={'kind':'solved_attempt_recap','coaching_version':'v33','attempt_comments':[
            {'origin':'solving','move_uci':'d1d8','text':'Solution'},
            {'origin':'attempt','move_uci':'a1a8','text':'Missed a tactic'}]}
        first=hydrate_recap(self.db,11,meta)
        ids=[note['feedback_message_id'] for note in first['attempt_comments']]
        self.assertTrue(all(ids))
        self.assertEqual([note['feedback_message_id'] for note in hydrate_recap(self.db,11,meta)['attempt_comments']],ids)
        self.assertEqual(snapshot(self.db,ids[1],11,'a1a8')['generation_version'],'v33')

if __name__=='__main__':unittest.main()
