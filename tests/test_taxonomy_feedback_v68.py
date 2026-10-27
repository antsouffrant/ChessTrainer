"""Canonical three-part dropdown responses: editable snapshots, exports, and regression."""
import csv
import io
import sqlite3
import unittest
from test_feedback_analytics_v48 import schema
import feedback_analytics as f


class TaxonomyFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema())
        self.db.execute("INSERT INTO accounts(provider,username) VALUES('lichess','chess_user')")
        for month in ('May','June'):
            self.db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,?,'[]')",(month,))
        for key,name in [('fork','Double Attack'),('king_activity','King Activity'),('pin','Pin')]:
            self.db.execute("INSERT INTO learning_concepts(key,name,family,description,status,source) VALUES(?,?, 'Tactical Calculation','', 'seeded','built_in')",(key,name))
        for job_id in (1,2):
            self.db.execute("""INSERT INTO training_positions(job_id,game_id,category,fen,user_color,move_number,best_move_uci,learned)
                VALUES(?,'abc','major_blunder','4k3/8/8/8/8/8/8/4K3 w - - 0 1','white',14,'e1d1',1)""",(job_id,))
            self.db.execute("INSERT INTO position_concepts(position_id,concept_key,is_primary,confidence,classifier_version) VALUES(?,'fork',1,.86,'v67')",(job_id,))
            self.db.execute("""INSERT INTO position_motif_taxonomy(position_id,context_key,move_type_key,motif_key,taxonomy_version)
                               VALUES(?,'attack','tactical','fork','v67')""",(job_id,))
        self.db.commit()
    def tearDown(self): self.db.close()

    def test_dropdown_overwrites_and_clear_isolated(self):
        with self.assertRaises(ValueError): f.save_taxonomy_feedback(self.db,1,'motif','retired')
        self.assertEqual(f.save_taxonomy_feedback(self.db,1,'context','defend')['selected']['context'],'defend')
        f.save_taxonomy_feedback(self.db,1,'move_type','none')
        f.save_taxonomy_feedback(self.db,1,'motif','king_activity')
        f.save_taxonomy_feedback(self.db,1,'motif','pin')
        rows=f.report_rows(self.db,{'job_id':1})
        self.assertEqual(len(rows),3)
        self.assertEqual(next(r for r in rows if r['feedback_type']=='taxonomy_motif')['selected_taxonomy_key'],'pin')
        self.assertEqual(len(f.regression_candidate_rows(rows)),3)
        f.save_taxonomy_feedback(self.db,1,'context','')
        self.assertEqual(len(f.report_rows(self.db,{'job_id':1})),2)
        self.assertEqual(f.taxonomy_feedback_choices(self.db,1)['selected']['move_type'],'none')
        self.assertEqual(len(f.report_rows(self.db,{'job_id':2})),0)

    def test_feedback_snapshot_survives_metadata_refresh(self):
        f.save_taxonomy_feedback(self.db,1,'motif','king_activity')
        f.save_taxonomy_feedback(self.db,1,'context','attack')
        self.db.execute("UPDATE position_motif_taxonomy SET motif_key='pin',context_key='defend',taxonomy_version='v68' WHERE position_id=1")
        self.db.commit()
        choices=f.taxonomy_feedback_choices(self.db,1)
        self.assertEqual(choices['predicted']['motif'],'pin')
        self.assertEqual(choices['selected']['motif'],'king_activity')
        rows=f.report_rows(self.db)
        motif=next(r for r in rows if r['feedback_type']=='taxonomy_motif')
        self.assertEqual(motif['content_snapshot'],'fork')
        self.assertEqual(motif['current_taxonomy_motif_key'],'pin')
        self.assertEqual(motif['classifier_version_at_vote'],'v67')
        self.assertEqual(motif['rating'],-1)
        self.assertEqual(next(r for r in rows if r['feedback_type']=='taxonomy_context')['rating'],1)
        exported=list(csv.DictReader(io.StringIO(f.csv_bytes(rows).decode('utf-8-sig'))))
        motif_csv=next(r for r in exported if r['feedback_type']=='taxonomy_motif')
        self.assertEqual(motif_csv['taxonomy_model_at_feedback_name'],'Double Attack')
        self.assertEqual(motif_csv['selected_taxonomy_name'],'King Activity')
        self.assertEqual(motif_csv['current_context_key'],'defend')
        self.assertEqual(motif_csv['regression_candidate'],'1')
        self.assertEqual(motif_csv['rating_label'],'corrected_prediction')
        self.assertEqual(len(f.regression_candidate_rows(rows)),1)

    def test_agreement_selection_is_positive_and_doesnt_become_regression(self):
        f.save_taxonomy_feedback(self.db,1,'motif','fork')
        f.save_taxonomy_feedback(self.db,1,'context','attack')
        f.save_taxonomy_feedback(self.db,1,'move_type','tactical')
        rows=f.report_rows(self.db)
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r['rating']==1 for r in rows))
        self.assertEqual(f.report_summary(rows)['taxonomy']['up_pct'],100.)
        self.assertFalse(f.regression_candidate_rows(rows))

    def test_reset_boundary_and_legacy_votes_preserved(self):
        f.save_taxonomy_feedback(self.db,1,'motif','pin')
        f.save_taxonomy_feedback(self.db,2,'context','defend')
        f.record_position_vote(self.db,1,'explanation',1)
        self.db.execute('DELETE FROM position_taxonomy_feedback WHERE position_id IN (SELECT id FROM training_positions WHERE job_id=1)')
        self.db.commit()
        # Deleting the old live projection must not erase the durable ledger.
        self.assertEqual(len(f.report_rows(self.db,{'job_id':1})),2)
        self.assertEqual(len(f.report_rows(self.db,{'job_id':2})),1)
        self.assertEqual(len(f.report_rows(self.db,{'feedback_type':'taxonomy_context'})),1)

if __name__ == '__main__': unittest.main()
