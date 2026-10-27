"""Chess-specific regression tests; run after installing requirements.txt."""
import unittest
import chess
from coaching.board_context.pv_outcomes import positional_outcome
from coaching.board_context.pv_reasoning import legal_pv
from coaching.narrative_composition.coaching import generate_coaching_text


class BranchContrastV28Tests(unittest.TestCase):
    def test_rooted_lines_stay_rooted_and_missing_root_can_be_recovered(self):
        board = chess.Board()
        best = chess.Move.from_uci('e2e4')
        rooted = ['e2e4', 'e7e5', 'g1f3']
        reply_only = ['e7e5', 'g1f3']
        self.assertEqual([m.uci() for m in legal_pv(board, rooted, best)], rooted)
        self.assertEqual([m.uci() for m in legal_pv(board, reply_only, best)], rooted)
        self.assertEqual(legal_pv(board, ['a7a5'], best), [])

    def test_same_capture_preserves_other_pawn(self):
        board = chess.Board('4r1k1/8/8/1p2R3/8/4P3/4B3/6K1 w - - 0 1')
        bishop = board.parse_san('Bxb5')
        rook = board.parse_san('Rxb5')
        outcome = positional_outcome(board, [bishop], [rook])
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome['motif'], 'defensive_resource')
        self.assertIn('both capture', outcome['narrative'])
        self.assertIn('e3', outcome['narrative'])
        self.assertIn('hanging', outcome['narrative'])

    def test_coaching_mentions_both_moves_and_not_generic_line(self):
        board = chess.Board('4r1k1/8/8/1p2R3/8/4P3/4B3/6K1 w - - 0 1')
        bishop = board.parse_san('Bxb5')
        rook = board.parse_san('Rxb5')
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=rook.uci(), played_move_san='Rxb5',
            best_move_uci=bishop.uci(), best_move_san='Bxb5',
            category='major_blunder', labels=[],
            best_pv_uci=[bishop.uci()], played_pv_uci=[rook.uci()],
        )
        self.assertIn('Bxb5', explanation)
        self.assertIn('Rxb5', explanation)
        self.assertIn('pawn on e3', explanation)
        self.assertNotIn('the gain appears after the reply', explanation)
        self.assertNotIn('In the saved evaluation', explanation)


if __name__ == '__main__':
    unittest.main()
