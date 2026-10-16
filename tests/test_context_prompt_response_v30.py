"""Legality-aware context/prompt/response regressions (requires python-chess).

Run: python -m unittest discover -s tests -p 'test_context_prompt_response_v30.py' -v
"""
import unittest
import chess
from position_context import can_really_attack, pinned_capture_refutations, inspect_response
from learning import classify_learning_concepts
from coaching import generate_coaching_text


class ComprehensionStagesTests(unittest.TestCase):
    # White's rook pins the black rook on e7 to Ke8. After Bd7+, the black
    # rook APPEARS able to play ...Rxd7, but doing so exposes Ke8 to Re1.
    BOARD = '4k3/4r3/8/8/6B1/8/8/4R1K1 w - - 0 1'

    def setUp(self):
        self.board = chess.Board(self.BOARD)
        self.best = self.board.parse_san('Bd7+')
        self.played = self.board.parse_san('Bf3')

    def test_pinned_capture_is_pseudo_legal_but_illegal(self):
        after = self.board.copy(stack=False)
        after.push(self.best)
        attempted = chess.Move.from_uci('e7d7')
        self.assertIn(attempted, list(after.generate_pseudo_legal_moves()))
        self.assertNotIn(attempted, after.legal_moves)
        self.assertTrue(after.is_attacked_by(chess.BLACK, chess.D7))  # geometry
        self.assertFalse(can_really_attack(after, chess.BLACK, chess.D7))  # actionable
        facts = pinned_capture_refutations(after, chess.D7)
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['piece_square'], chess.E7)
        self.assertIn('pinned to the king', facts[0]['evidence'])

    def test_three_stage_evidence_and_relevant_primary_motif(self):
        # Black was in check on the e-file and blocked it with ...Re7.
        before = chess.Board('4k3/5r2/8/8/6B1/8/8/4R1K1 b - - 0 1')
        last = before.parse_san('Re7')
        current = before.copy(stack=False)
        current.push(last)
        self.assertEqual(current.board_fen(), self.board.board_fen())
        context = inspect_response(current, self.best, self.played, before.fen(), last.uci())
        self.assertIn(chess.E7, context['new_pins_on_them'])
        self.assertIn('pin', context['context_motifs'])
        self.assertIn('pin', context['response_motifs'])
        self.assertTrue(context['pin_capture_refutations'])
        self.assertTrue(context['context_facts'])
        self.assertTrue(context['response_facts'])
        labels = classify_learning_concepts(
            current, self.played, self.best, 'major_blunder', 200,
            previous_fen=before.fen(), opponent_move_uci=last.uci(),
        )
        self.assertEqual(next(label.key for label in labels if label.is_primary), 'pin')
        prompt, explanation = generate_coaching_text(
            fen=current.fen(), previous_fen=before.fen(), opponent_move_uci=last.uci(),
            opponent_move_san='Re7', played_move_uci=self.played.uci(),
            played_move_san='Bf3', best_move_uci=self.best.uci(),
            best_move_san='Bd7+', category='major_blunder', labels=labels,
        )
        self.assertNotIn('Bd7+', prompt)  # pre-solve message must not spoil solution
        self.assertIn('cannot capture', explanation)
        self.assertIn('king', explanation)
        self.assertIn('Bd7+', explanation)

    def test_incidental_pin_is_not_promoted(self):
        other = chess.Board('4k3/8/2n5/8/8/8/8/4KB2 w - - 0 1')
        best = other.parse_san('Bb5')
        played = other.parse_san('Bd3')
        context = inspect_response(other, best, played)
        self.assertFalse(context['pin_capture_refutations'])
        labels = classify_learning_concepts(other, played, best, 'major_blunder', 200)
        self.assertNotEqual(next(label.key for label in labels if label.is_primary), 'pin')


if __name__ == '__main__':
    unittest.main()
