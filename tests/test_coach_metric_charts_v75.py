"""Separated default Coach charts: one taxonomy change rate, one approval rate."""
import unittest
import feedback_analytics as f
from test_taxonomy_feedback_v68 import TaxonomyFeedbackTests


class CoachMetricChartsTests(TaxonomyFeedbackTests):
    def test_default_changes_grouped_by_primary_motif(self):
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'pin')
        rows = f.coaching_metric_chart(self.db, metric='changes')['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Double Attack')
        self.assertEqual((rows[0]['numerator'], rows[0]['denominator'], rows[0]['rate']), (1, 2, 50.0))
        f.save_taxonomy_feedback(self.db, 1, 'context', 'attack')
        self.assertEqual(f.coaching_metric_chart(self.db, metric='changes')['rows'][0]['numerator'], 1)
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'fork')
        self.assertEqual(f.coaching_metric_chart(self.db, metric='changes')['rows'][0]['rate'], 0)

    def test_approval_default_pivots_by_thumbs_area_even_with_no_votes(self):
        default = f.coaching_metric_chart(self.db, metric='approval')
        self.assertEqual(default['group_by'], 'feedback_area')
        self.assertEqual([r['key'] for r in default['rows']], ['position', 'explanation', 'coaching'])
        self.assertTrue(all(r['rate'] is None for r in default['rows']))
        f.record_position_vote(self.db, 1, 'position', 1)
        f.record_position_vote(self.db, 1, 'explanation', -1)
        f.record_position_vote(self.db, 2, 'explanation', 1)
        rows = {r['key']:r for r in f.coaching_metric_chart(self.db, metric='approval')['rows']}
        self.assertEqual((rows['position']['numerator'],rows['position']['denominator'],rows['position']['rate']), (1,1,100.0))
        self.assertEqual((rows['explanation']['numerator'],rows['explanation']['denominator'],rows['explanation']['rate']), (1,2,50.0))
        self.assertIsNone(rows['coaching']['rate'])

    def test_distinct_chat_ratings_and_historical_version(self):
        self.db.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,1)")
        self.db.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'assistant','First response')")
        self.db.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(1,'assistant','Second response')")
        self.db.execute("UPDATE training_positions SET coaching_version='coach-old' WHERE id=1")
        self.db.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating,coaching_version_at_vote) VALUES(1,1,1,-1,'coach-old')")
        self.db.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating,coaching_version_at_vote) VALUES(2,1,1,1,'coach-old')")
        self.db.commit()
        self.db.execute("UPDATE training_positions SET coaching_version='coach-new' WHERE id=1")
        self.db.commit()
        chart = f.coaching_metric_chart(self.db, {'coaching_version':'coach-old'}, metric='approval')
        chat = next(r for r in chart['rows'] if r['key']=='coaching')
        self.assertEqual((chat['numerator'],chat['denominator'],chat['rate']), (1,1,100.0))
        chart = f.coaching_metric_chart(self.db, {'coaching_version':'coach-new'}, metric='approval')
        chat = next(r for r in chart['rows'] if r['key']=='coaching')
        self.assertIsNone(chat['rate'])

    def test_changes_by_field_and_scoped_grouping(self):
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'pin')
        rows = {r['key']:r for r in f.coaching_metric_chart(self.db,metric='changes',group_by='taxonomy_field')['rows']}
        self.assertEqual((rows['context']['numerator'],rows['context']['denominator']), (1,2))
        self.assertEqual(rows['move_type']['numerator'],0)
        self.assertEqual(rows['motif']['rate'],50.)
        by_job=f.coaching_metric_chart(self.db,{'job_id': '2'},metric='changes',group_by='taxonomy_field')['rows']
        self.assertTrue(all(row['denominator']==1 and row['numerator']==0 for row in by_job))

    def test_grouped_rates_aggregate_any_without_third_measure_selector(self):
        f.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        f.save_taxonomy_feedback(self.db, 1, 'motif', 'pin')
        f.record_position_vote(self.db, 1, 'position', 1)
        f.record_position_vote(self.db, 1, 'explanation', -1)
        f.record_position_vote(self.db, 2, 'explanation', -1)
        for chart in ('changes','approval'):
            data=f.coaching_metric_chart(self.db,metric=chart,group_by='motif')
            self.assertEqual(data['group_by'],'motif')
            self.assertEqual(len(data['rows']),1)
            row=data['rows'][0]
            self.assertEqual((row['numerator'],row['denominator'],row['rate']), (1,2,50.0))
        self.assertEqual(f.coaching_metric_chart(self.db,metric='changes',group_by='bad')['group_by'],'motif')
        self.assertEqual(f.coaching_metric_chart(self.db,metric='approval',group_by='bad')['group_by'],'feedback_area')


if __name__=='__main__': unittest.main()
