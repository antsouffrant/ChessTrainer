"""Distinct-position denominators for the parameterized Coach rate chart."""
import unittest
import feedback_analytics as f
from test_taxonomy_feedback_v68 import TaxonomyFeedbackTests


class CoachComparisonTests(TaxonomyFeedbackTests):
    def setUp(self):
        super().setUp()
        self.db.execute("UPDATE training_positions SET opening_key='C20',opening_name='King Pawn',coaching_version='v73' WHERE id IN (1,2)")
        self.db.commit()

    def test_any_approval_and_any_change_count_positions_once(self):
        f.record_position_vote(self.db, 1, 'position', 1)
        f.record_position_vote(self.db, 1, 'explanation', -1)
        f.record_position_vote(self.db, 2, 'explanation', -1)
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'pin')
        # One position has TWO corrections, but it is still one changed puzzle.
        rows = f.coaching_comparison(self.db, group_by='opening')['rows']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['solved'], row['changed'], row['change_pct']), (2, 1, 50.))
        self.assertEqual((row['rated'], row['approved'], row['approval_pct']), (2, 1, 50.))
        self.assertEqual(f.coaching_comparison(self.db, group_by='opening', approval_area='explanation')['rows'][0]['approval_pct'], 0.)
        self.assertEqual(f.coaching_comparison(self.db, group_by='opening', approval_area='position')['rows'][0]['approval_pct'], 100.)
        self.assertEqual(f.coaching_comparison(self.db, group_by='opening', change_area='move_type')['rows'][0]['change_pct'], 0.)
        f.save_taxonomy_feedback(self.db, 1, 'context', 'attack')
        self.assertEqual(f.coaching_comparison(self.db, change_area='context')['rows'][0]['changed'], 0)
        self.assertEqual(f.coaching_comparison(self.db, change_area='any')['rows'][0]['changed'], 1)
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'fork')
        self.assertEqual(f.coaching_comparison(self.db)['rows'][0]['changed'], 0)

    def test_unrated_is_not_a_negative_approval(self):
        row = f.coaching_comparison(self.db)['rows'][0]
        self.assertEqual(row['solved'], 2)
        self.assertEqual(row['rated'], 0)
        self.assertIsNone(row['approval_pct'])
        self.assertEqual(row['change_pct'], 0.)
        f.record_position_vote(self.db, 1, 'position', -1)
        row = f.coaching_comparison(self.db)['rows'][0]
        self.assertEqual((row['rated'], row['approved'], row['approval_pct']), (1, 0, 0.))

    def test_historical_approval_version_does_not_fabricate_historical_changes(self):
        self.db.execute("UPDATE training_positions SET coaching_version='v-old' WHERE id=1")
        self.db.commit()
        f.record_position_vote(self.db, 1, 'explanation', 1)
        self.db.execute("UPDATE training_positions SET coaching_version='v-new' WHERE id=1")
        self.db.commit()
        rows = {r['key']: r for r in f.coaching_comparison(self.db, group_by='version')['rows']}
        self.assertEqual(rows['v-old']['approval_pct'], 100.)
        self.assertEqual(rows['v-old']['solved'], 0)
        self.assertIsNone(rows['v-old']['change_pct'])
        self.assertEqual(rows['v-new']['solved'], 1)
        self.assertIsNone(rows['v-new']['approval_pct'])
        selected = f.coaching_comparison(self.db, {'coaching_version': 'v-old'}, group_by='version')['rows']
        self.assertEqual({r['key'] for r in selected if r['rated']}, {'v-old'})

    def test_lesson_secondary_membership_and_game_list_scope(self):
        self.db.execute("INSERT INTO position_concepts(position_id,concept_key,is_primary,confidence,classifier_version) VALUES(1,'pin',0,0.6,'v73')")
        self.db.commit()
        f.record_position_vote(self.db, 1, 'position', 1)
        lesson = {r['key']: r for r in f.coaching_comparison(self.db, group_by='lesson')['rows']}
        self.assertEqual(lesson['pin']['solved'], 1)
        self.assertEqual(lesson['pin']['approval_pct'], 100.)
        self.assertEqual(lesson['fork']['solved'], 2)
        by_job = f.coaching_comparison(self.db, {'job_id':'2'}, group_by='game_list')['rows']
        self.assertEqual(len(by_job), 1)
        self.assertEqual(by_job[0]['solved'], 1)
        self.assertEqual(by_job[0]['rated'], 0)
        self.assertEqual(f.coaching_comparison(self.db, {'feedback_type':'explanation','rating':'-1'})['rows'][0]['solved'],2)

    def test_invalid_parameters_are_safely_normalized(self):
        data = f.coaching_comparison(self.db, group_by='bad', approval_area='bad', change_area='bad')
        self.assertEqual((data['group_by'], data['approval_area'], data['change_area']), ('opening','any','any'))


if __name__ == '__main__': unittest.main()
