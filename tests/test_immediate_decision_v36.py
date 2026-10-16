"""Immediate position relevance regressions (requires python-chess)."""
import unittest
import chess
from immediate_decision import immediate_decision
from learning import classify_learning_concepts
from coaching import generate_coaching_text


class ImmediateDecisionTests(unittest.TestCase):
    def test_free_queen_capture_outranks_future_ideas(self):
        board = chess.Board('4k3/8/8/8/4q3/8/4R3/6K1 w - - 0 1')
        best = board.parse_san('Rxe4+')
        played = board.parse_san('Rd2')
        reason = immediate_decision(board, best, played)
        self.assertEqual(reason['kind'], 'free_capture')
        self.assertEqual(reason['motif'], 'hanging_piece')
        self.assertIn('queen on e4', reason['explanation'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 800)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'hanging_piece')
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san=board.san(played), best_move_uci=best.uci(),
            best_move_san=board.san(best), category='major_blunder', labels=labels,
        )
        self.assertIn('queen on e4', explanation)
        self.assertNotIn('pressure', explanation.lower())

    def test_legal_immediate_capture_exposes_hanging_rook(self):
        board = chess.Board('7k/8/8/8/1p6/8/R7/6K1 w - - 0 1')
        best, played = board.parse_san('Ra1'), board.parse_san('Ra3')
        reason = immediate_decision(board, best, played)
        self.assertEqual(reason['kind'], 'played_hangs_piece')
        self.assertIn('rook on a3 hanging', reason['explanation'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 500)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'loose_piece_awareness')

    def test_immediately_recapturable_pawn_not_called_free(self):
        board = chess.Board('3r3k/8/8/8/3p4/2P5/8/4K3 w - - 0 1')
        best, played = board.parse_san('cxd4'), board.parse_san('c4')
        self.assertIsNone(immediate_decision(board, best, played))

    def test_same_target_capture_does_not_claim_missed_capture(self):
        board = chess.Board('4r1k1/8/8/1p2R3/8/4P3/4B3/6K1 w - - 0 1')
        bishop, rook = board.parse_san('Bxb5'), board.parse_san('Rxb5')
        self.assertIsNone(immediate_decision(board, bishop, rook))


if __name__ == '__main__':
    unittest.main()
