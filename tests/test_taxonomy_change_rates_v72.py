"""Change rate measures disagreement among ALL solved positions, not only feedback rows."""
import csv
import io
import unittest
from test_taxonomy_feedback_v68 import TaxonomyFeedbackTests
import feedback_analytics as f


class ChangeRateTests(TaxonomyFeedbackTests):
    def test_implicit_matches_edit_and_reselection(self):
        # Two solved positions; neither has a dropdown judgment yet.
        self.assertEqual(f.taxonomy_change_rates(self.db)['context'], {
            'solved': 2, 'total': 2, 'changed': 0, 'unchanged': 2,
            'change_pct': 0.0, 'unchanged_pct': 100.0})
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        self.assertEqual(f.taxonomy_change_rates(self.db)['context']['change_pct'], 50.0)
        self.assertEqual(f.taxonomy_change_rates(self.db)['move_type']['change_pct'], 0.0)
        f.save_taxonomy_feedback(self.db, 1, 'context', 'attack')
        self.assertEqual(f.taxonomy_change_rates(self.db)['context']['changed'], 0)
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        f.save_taxonomy_feedback(self.db, 1, 'context', '')
        self.assertEqual(f.taxonomy_change_rates(self.db)['context']['changed'], 0)

    def test_each_field_separately_and_only_solved_denominator(self):
        f.save_taxonomy_feedback(self.db,1,'context','defend')
        f.save_taxonomy_feedback(self.db,1,'move_type','strategic')
        f.save_taxonomy_feedback(self.db,1,'motif','pin')
        self.assertEqual([f.taxonomy_change_rates(self.db)[k]['changed'] for k in ('context','move_type','motif')],[1,1,1])
        self.assertEqual(f.taxonomy_change_rates(self.db,{'job_id':'1'})['motif']['change_pct'],100.)
        self.assertEqual(f.taxonomy_change_rates(self.db,{'job_id':'2'})['motif']['change_pct'],0.)
        # These record-level filters must not silently change the position denominator.
        self.assertEqual(f.taxonomy_change_rates(self.db,{'feedback_type':'explanation','rating':'-1'})['motif']['solved'],2)
        self.db.execute('UPDATE training_positions SET learned=0 WHERE id=2')
        self.db.commit()
        self.assertEqual(f.taxonomy_change_rates(self.db)['motif']['solved'],1)
        self.assertEqual(f.taxonomy_change_rates(self.db,{'job_id':'2'})['motif']['change_pct'],None)
        self.assertEqual(f.taxonomy_change_rates(self.db,{'current_context_key':'defend'})['motif']['solved'],0)

    def test_solved_position_csv_includes_untouched_matches(self):
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'pin')
        rows = f.solved_taxonomy_rows(self.db)
        self.assertEqual(len(rows),2)
        data = list(csv.DictReader(io.StringIO(f.solved_taxonomy_csv(rows).decode('utf-8-sig'))))
        first, second = data
        self.assertEqual(first['position_id'], '1')
        self.assertEqual(first['motif_changed'],'1')
        self.assertEqual(first['original_motif_at_selection'],'fork')
        self.assertEqual(second['position_id'],'2')
        self.assertEqual(second['context_changed'],'0')
        self.assertEqual(second['motif_changed'],'0')
        self.assertEqual(second['chosen_motif'],'')
        self.assertEqual(len(f.solved_taxonomy_rows(self.db,{'job_id':'2'})),1)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(f.solved_taxonomy_csv([]).decode('utf-8-sig'))))),0)

    def test_current_assignment_vs_original_prediction_preserves_snapshot(self):
        f.save_taxonomy_feedback(self.db,1,'motif','pin')
        row = next(r for r in f.report_rows(self.db) if r['feedback_type']=='taxonomy_motif')
        self.assertEqual(row['rating'],-1)  # historical at-selection status, retained
        self.assertEqual(f.current_taxonomy_status(row),'changed')
        self.db.execute("UPDATE position_motif_taxonomy SET motif_key='pin' WHERE position_id=1")
        self.db.commit()
        row = next(r for r in f.report_rows(self.db) if r['feedback_type']=='taxonomy_motif')
        self.assertEqual(row['content_snapshot'],'fork')
        self.assertEqual(row['rating'],-1)
        self.assertEqual(f.current_taxonomy_status(row),'unchanged')
        self.assertEqual(f.taxonomy_change_rates(self.db)['motif']['changed'],0)
        exported = list(csv.DictReader(io.StringIO(f.csv_bytes([row]).decode('utf-8-sig'))))[0]
        self.assertEqual(exported['current_taxonomy_change_status'],'unchanged')
        self.assertEqual(exported['current_taxonomy_model_key'],'pin')
        self.assertEqual(exported['taxonomy_motif_at_feedback'],'fork')
        # Legacy regression correction stays available despite model updates.
        self.assertTrue(f.is_regression_candidate(row))

if __name__=='__main__': unittest.main()
