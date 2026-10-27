"""No repeated immediate chess facts when cached solution and PV agree."""
import json
import unittest

from coaching.narrative_composition.continuation_coach import explain_attempt


class DeduplicatedContinuationTests(unittest.TestCase):
    def row(self, plies, *, best='f2f1', game='g2g3'):
        return {
            'best_move_uci': best,
            'played_move_san': 'g3',
            'fen': '',
            'explanatory_lines_json': json.dumps({'lines': [
                {'root_uci': best, 'role': 'recommended', 'plies': plies}
            ]}),
        }

    def attempt(self, *, move='f2f1', san='Rf1+', correct=True):
        return {'move_uci': move, 'move_san': san, 'correct': int(correct)}

    def check_plies(self):
        return [
            {'uci': 'f2f1', 'san': 'Rf1+', 'effects': [
                {'kind': 'check', 'text': 'Rf1+ gives check'}]},
            {'uci': 'g1g2', 'san': 'Kg2', 'effects': [
                {'kind': 'attack_loose_piece',
                 'text': 'Kg2 attacks or exposes the opponent’s undefended rook on f1'}]},
        ]

    def test_reported_rf1_repetition_is_removed_but_kg2_remains(self):
        explanation = 'Rf1+ gives check, requiring an immediate reply.'
        result = explain_attempt(self.row(self.check_plies()),
                                 self.attempt(), 'Rf1+', saved_explanation=explanation)
        text = result['text']
        self.assertEqual(text.count('Rf1+ gives check'), 1, text)
        self.assertIn('requiring an immediate reply', text)
        self.assertIn('opponent can respond with Kg2', text)
        self.assertIn('rook on f1', text)

    def test_check_synonym_is_not_repeated(self):
        explanation = 'Rf1+ checks the king, forcing a response.'
        text = explain_attempt(self.row(self.check_plies()), self.attempt(),
                               'Rf1+', saved_explanation=explanation)['text']
        self.assertEqual(text.count('Rf1+'), 1, text)
        self.assertIn('checks the king', text)
        self.assertIn('Kg2', text)

    def test_identical_capture_is_not_repeated(self):
        plies = [
            {'uci': 'f2f1', 'san': 'Bxf1', 'effects': [
                {'kind': 'capture', 'text': 'Bxf1 captures the rook on f1'}]},
            {'uci': 'g1f1', 'san': 'Rxf1', 'effects': [
                {'kind': 'capture', 'text': 'Rxf1 recaptures the bishop'}]},
        ]
        text = explain_attempt(self.row(plies), self.attempt(san='Bxf1'), 'Bxf1',
                               saved_explanation='Bxf1 captures the rook on f1, but allows a recapture.')['text']
        self.assertEqual(text.count('Bxf1 captures the rook on f1'), 1, text)
        self.assertIn('Rxf1', text)

    def test_reply_already_explained_is_not_repeated(self):
        explanation = ('Rf1+ gives check. In the line Kg2 attacks or exposes '
                       'the opponent’s undefended rook on f1.')
        text = explain_attempt(self.row(self.check_plies()), self.attempt(),
                               'Rf1+', saved_explanation=explanation)['text']
        self.assertEqual(text.count('attacks or exposes'), 1, text)
        self.assertEqual(text.count('Rf1+ gives check'), 1, text)

    def test_new_root_fact_is_not_suppressed(self):
        explanation = 'Rf1+ creates pressure on the back rank.'
        text = explain_attempt(self.row(self.check_plies()), self.attempt(),
                               'Rf1+', saved_explanation=explanation)['text']
        self.assertIn(explanation, text)
        self.assertNotIn('Rf1+ gives check.', text)  # proactive root claim owns the decision

    def test_different_candidate_does_not_inherit_best_move_explanation(self):
        plies = [{'uci': 'g2g3', 'san': 'g3', 'effects': [
            {'kind': 'check', 'text': 'g3 gives check'}]}]
        text = explain_attempt(self.row(plies, best='g2g3'),
                               self.attempt(move='g2g3', san='g3', correct=False), 'Rf1+',
                               saved_explanation='Rf1+ gives check, requiring an immediate reply.')['text']
        self.assertEqual(text, 'g3 gives check.')
        self.assertNotIn('Rf1+', text)


if __name__ == '__main__':
    unittest.main()
