"""Semantic ownership and causal priority across proactive / reactive coaching.

These run without python-chess to cover the persisted evidence contract.
"""
import json
import unittest
from coaching.narrative_composition.continuation_coach import explain_attempt


class NarrativeOwnershipTests(unittest.TestCase):
    @staticmethod
    def row(move, san, reply=None, reply_effects=None, root_effects=None, followup=None):
        plies = [{'uci': move, 'san': san, 'effects': root_effects or []}]
        if reply:
            plies.append({'uci': 'h7h8', 'san': reply, 'effects': reply_effects or []})
        if followup:
            plies.append(followup)
        return dict(best_move_uci=move, best_move_san=san, played_move_san='Nf3',
                    explanatory_lines_json=json.dumps({'lines': [
                        {'role': 'recommended', 'root_uci': move, 'plies': plies}]}),
                    fen='')

    @staticmethod
    def attempt(move, san, correct=True):
        return {'move_uci': move, 'move_san': san, 'correct': correct}

    def test_reported_kh1_check_evasion_is_described_once(self):
        row = self.row('g1h1', 'Kh1', reply='Kh8', root_effects=[
            {'kind': 'check_evasion', 'text': 'Kh1 legally answers the check'}])
        comment = explain_attempt(row, self.attempt('g1h1', 'Kh1'), 'Kh1',
                                  saved_explanation='Kh1 moves the king out of check.')
        self.assertEqual(comment['text'], 'Kh1 moves the king out of check.')
        self.assertNotIn('Kh8', comment['text'])
        self.assertNotIn('legally answers', comment['text'])

    def test_an_inert_reply_does_not_create_an_empty_chess_lesson(self):
        row = self.row('g1h1', 'Kh1', reply='Kh8', root_effects=[
            {'kind': 'check_evasion', 'text': 'Kh1 legally answers the check'}],
            reply_effects=[{'kind': 'check_evasion', 'text': 'Kh8 legally answers a check'}])
        comment = explain_attempt(row, self.attempt('g1h1', 'Kh1'), 'Kh1',
                                  saved_explanation='Kh1 moves the king out of check.')
        self.assertEqual(comment['text'], 'Kh1 moves the king out of check.')

    def test_rf1_check_and_causal_kg2_reply_not_repeated(self):
        row = self.row('f2f1', 'Rf1+', reply='Kg2', root_effects=[
            {'kind': 'check', 'text': 'Rf1+ gives check'}], reply_effects=[
            {'kind': 'attack_loose_piece', 'text':
             'Kg2 attacks or exposes the opponent’s undefended rook on f1'}])
        comment = explain_attempt(row, self.attempt('f2f1', 'Rf1+'), 'Rf1+',
                                  saved_explanation='Rf1+ gives check, requiring an immediate reply.')
        self.assertEqual(comment['text'].count('Rf1+ gives check'), 1)
        self.assertIn('Kg2', comment['text'])
        self.assertIn('your undefended rook on f1', comment['text'])

    def test_root_is_owned_by_proactive_even_if_wording_differs(self):
        row = self.row('g1h1', 'Kh1', root_effects=[
            {'kind': 'check_evasion', 'text': 'Kh1 legally answers the check'},
            {'kind': 'check', 'text': 'Kh1 checks the opponent king'}])
        comment = explain_attempt(row, self.attempt('g1h1', 'Kh1'), 'Kh1',
                                  saved_explanation='Kh1 moves the king out of check.')
        self.assertEqual(comment['text'], 'Kh1 moves the king out of check.')

    def test_material_capture_outweighs_incidental_check_in_reply(self):
        row = self.row('a2a3', 'a3', reply='Qxd4+', root_effects=[], reply_effects=[
            {'kind': 'check', 'text': 'Qxd4+ gives check'},
            {'kind': 'capture', 'text': 'Qxd4+ captures your rook on d4'}])
        comment = explain_attempt(row, self.attempt('a2a3', 'a3'), 'a3',
                                  saved_explanation='a3 improves king safety.')
        self.assertIn('captures your rook', comment['text'])
        self.assertNotIn('gives check', comment['text'])

    def test_saved_reply_is_not_repeated_if_proactive_already_discusses_it(self):
        row = self.row('f2f1', 'Rf1+', reply='Kg2', root_effects=[
            {'kind': 'check', 'text': 'Rf1+ gives check'}], reply_effects=[
            {'kind': 'attack_loose_piece', 'text':
             'Kg2 attacks or exposes the opponent’s undefended rook on f1'}])
        explanation = 'Rf1+ forces Kg2, after which the rook is vulnerable.'
        comment = explain_attempt(row, self.attempt('f2f1', 'Rf1+'), 'Rf1+',
                                  saved_explanation=explanation)
        self.assertEqual(comment['text'], explanation)

    def test_wrong_branch_never_inherits_proactive_solution(self):
        row = self.row('g1h1', 'Kh1', reply='Kh8', root_effects=[
            {'kind': 'check_evasion', 'text': 'Kh1 legally answers the check'}])
        comment = explain_attempt(row, self.attempt('g1f1', 'Kf1', correct=False), 'Kh1',
                                  saved_explanation='Kh1 wins a rook.')
        self.assertNotIn('wins a rook', comment['text'])
        self.assertNotIn('Kh8', comment['text'])

    def test_no_saved_solution_avoids_literal_legally_answers_tautology(self):
        row = self.row('g1h1', 'Kh1', reply='Kh8', root_effects=[
            {'kind': 'check_evasion', 'text': 'Kh1 legally answers the check'}])
        comment = explain_attempt(row, self.attempt('g1h1', 'Kh1'), 'Kh1')
        self.assertEqual(comment['text'], 'Kh1 resolves the check.')


if __name__ == '__main__':
    unittest.main()
