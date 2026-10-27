"""v110 categorical analytics filters use OR within one facet and AND between facets."""
import unittest
class MultiDict(dict):
    """Test stand-in for Flask's request MultiDict, including repeated keys."""
    def __init__(self, pairs):
        super().__init__()
        for key, value in pairs:
            self.setdefault(key, []).append(value)

    def getlist(self, key):
        return self.get(key, [])

import feedback_analytics as analytics
from player_learning import summary as player_summary
from test_taxonomy_feedback_v68 import TaxonomyFeedbackTests
from test_player_learning_v61 import PlayerLearningTests


class CoachMultiselectV110(TaxonomyFeedbackTests):
    def test_two_game_lists_or_combined_and_with_motif(self):
        analytics.save_taxonomy_feedback(self.db, 1, 'context', 'defend')
        analytics.save_taxonomy_feedback(self.db, 2, 'context', 'defend')
        both = MultiDict([('job_id','1'),('job_id','2'),('primary_motif_key','fork')])
        self.assertEqual({r['job_id'] for r in analytics.report_rows(self.db, both)}, {1,2})
        self.assertEqual(len(analytics.coach_change_population(self.db,both)), 2)
        self.assertEqual(analytics.taxonomy_change_rates(self.db,both)['context']['changed'], 2)
        one = MultiDict([('job_id','2'),('primary_motif_key','fork')])
        self.assertEqual(len(analytics.report_rows(self.db, one)),1)
        mismatch = MultiDict([('job_id','1'),('job_id','2'),('primary_motif_key','pin')])
        self.assertEqual(analytics.report_rows(self.db, mismatch), [])

    def test_rating_and_feedback_type_or(self):
        analytics.record_position_vote(self.db,1,'position',1)
        analytics.record_position_vote(self.db,2,'explanation',-1)
        all_ratings = MultiDict([('rating','1'),('rating','-1'),('feedback_type','position'),('feedback_type','explanation')])
        rows=analytics.report_rows(self.db,all_ratings)
        self.assertEqual({(x['feedback_type'],x['rating']) for x in rows},{('position',1),('explanation',-1)})
        narrowed = MultiDict([('rating','1'),('feedback_type','position'),('feedback_type','explanation')])
        self.assertEqual([(r['feedback_type'],r['rating']) for r in analytics.report_rows(self.db,narrowed)], [('position',1)])


class PlayerMultiselectV110(PlayerLearningTests):
    def test_multiple_job_and_opening_values(self):
        all_jobs=MultiDict([('job_id','1'),('job_id','2')])
        self.assertEqual(player_summary(self.conn,all_jobs)['overview']['total_positions'],3)
        job_one=MultiDict([('job_id','1')])
        self.assertEqual(player_summary(self.conn,job_one)['overview']['total_positions'],2)
        openings=MultiDict([('opening_key','C20'),('opening_key','D00')])
        self.assertEqual(player_summary(self.conn,openings)['overview']['total_positions'],2)
        intersection=MultiDict([('job_id','1'),('opening_key','C20'),('opening_key','D00')])
        self.assertEqual(player_summary(self.conn,intersection)['overview']['total_positions'],1)


if __name__=='__main__': unittest.main()
