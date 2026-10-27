"""v78: one comment per attempt, one overall explanation feedback record."""
import unittest
from coaching.narrative_composition.coach_session_recap import _comment_for_attempt, _saved_continuation

class CommentTests(unittest.TestCase):
    def test_solution_reuses_only_its_own_cached_explanation(self):
        solution = _comment_for_attempt({'move_san':'Nxe5','move_uci':'f3e5','correct':1,
            'best_reply_san':None,'from_saved_line':1},'Nxe5',model_explanation='Nxe5 opens a discovered attack.')
        self.assertEqual(solution['text'],'Nxe5 opens a discovered attack.')
        self.assertEqual(solution['source'],'saved_solution')

    def test_wrong_attempt_does_not_inherit_solution_claim(self):
        wrong = _comment_for_attempt({'move_san':'Nf3','move_uci':'g1f3','correct':0,
            'best_reply_san':'d5','from_saved_line':1},'Nxe5',model_explanation='Nxe5 wins a piece.')
        self.assertIn('Nf3',wrong['text'])
        self.assertNotIn('d5',wrong['text'])  # uninformative reply is not narrated
        self.assertNotIn('wins a piece',wrong['text'])
        self.assertEqual(wrong['source'],'saved_analysis')

    def test_uncached_attempt_is_honest(self):
        unknown = _comment_for_attempt({'move_san':'a3','move_uci':'a2a3','correct':0,
            'best_reply_san':None,'from_saved_line':0},'Nxe5',model_explanation='Nxe5 wins material.')
        self.assertIn('does not establish a specific',unknown['text'])
        self.assertNotIn('wins material',unknown['text'])

    def test_saved_explanation_uses_matching_root_only(self):
        import json
        class Row(dict):
            pass
        evidence = {'lines':[
            {'root_uci':'e2e4','role':'recommended','plies':[
                {'san':'e4','effects':[{'kind':'capture','text':'e4 wins a rook'}]},
                {'san':'e5','effects':[]}]},
            {'root_uci':'d2d4','role':'played','plies':[
                {'san':'d4','effects':[{'kind':'check','text':'d4 gives check'}]},
                {'san':'d5','effects':[]}]}
        ]}
        row = Row(explanatory_lines_json=json.dumps(evidence))
        self.assertEqual(_saved_continuation(row,'d2d4')['fact'],'d4 gives check')
        self.assertEqual(_saved_continuation(row,'d2d4')['reply_san'],'d5')
        self.assertIsNone(_saved_continuation(row,'a2a4'))
        comment = _comment_for_attempt({'move_san':'d4','move_uci':'d2d4','correct':0,
            'best_reply_san':None,'from_saved_line':1}, 'e4',
            model_explanation='e4 wins a rook',saved_line=_saved_continuation(row,'d2d4'))
        self.assertIn('d4 gives check',comment['text'])
        self.assertNotIn('wins a rook',comment['text'])

    def test_accepted_alternative_not_mislabeled_as_best(self):
        alternative = _comment_for_attempt({'move_san':'Be2','move_uci':'f1e2','correct':1,
            'best_reply_san':None,'from_saved_line':0},'Nf3',model_explanation='Nf3 forks the rook.')
        self.assertNotIn('solution threshold',alternative['text'])
        self.assertTrue(alternative['correct'])
        self.assertNotIn('forks', alternative['text'])

if __name__ == '__main__': unittest.main()
