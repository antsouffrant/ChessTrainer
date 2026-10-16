"""Board-level regressions for concrete-first explanatory text.

Run with: python -m unittest discover -s tests -p 'test_root_explanation_v40.py'
Requires python-chess from requirements.txt.
"""
import unittest

try:
    import chess
    from root_explanation import root_move_impact
    from coaching import generate_coaching_text
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'python-chess is not installed')
class RootExplanationTests(unittest.TestCase):
    def test_unrecapturable_capture_precedes_remote_pressure(self):
        board = chess.Board('7k/8/8/4p3/3Q4/8/8/4K3 w - - 0 1')
        best = board.parse_san('Qxe5+')
        played = board.parse_san('Qd6')
        fact = root_move_impact(board, best, played)
        self.assertEqual(fact['kind'], 'capture')
        self.assertIn('pawn on e5', fact['text'])
        self.assertNotIn('pressure', fact['text'])
        prompt, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(), played_move_san=board.san(played),
            best_move_uci=best.uci(), best_move_san=board.san(best),
            category='squandered_advantage', labels=[],
            best_pv_uci=[best.uci()], played_pv_uci=[played.uci()],
        )
        self.assertIn('pawn on e5', explanation)
        self.assertNotIn('increases pressure', explanation)

    def test_equal_exchange_is_not_free_capture(self):
        board = chess.Board('4k3/8/8/3n4/2B5/8/8/4K3 w - - 0 1')
        best = board.parse_san('Bxd5')
        # A hypothetical opponent bishop on c6 would defend d5; this first
        # board instead has no legal recapture, so no exchange is claimed.
        self.assertEqual(root_move_impact(board, best)['kind'], 'capture')
        board = chess.Board('4k3/8/2b5/3n4/2B5/8/8/4K3 w - - 0 1')
        best = board.parse_san('Bxd5')
        after = board.copy()
        after.push(best)
        reply = after.parse_san('Bxd5')
        fact = root_move_impact(board, best, best_pv=[best.uci(), reply.uci()])
        self.assertEqual(fact['kind'], 'exchange')
        self.assertIn('exchanges', fact['text'])
        self.assertNotIn('wins', fact['text'])

    def test_pawn_push_has_non_tautological_consequence(self):
        board = chess.Board('7k/3p1p2/8/4P3/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('e6')
        fact = root_move_impact(board, best)
        self.assertIsNotNone(fact)
        self.assertIn('space', fact['text'])
        self.assertNotIn('places your pawn', fact['text'])
        prompt, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=None, played_move_san=None,
            best_move_uci=best.uci(), best_move_san='e6',
            category='correct_move', labels=[])
        self.assertIn('space', explanation)

    def test_shared_capture_does_not_claim_distinct_win(self):
        board = chess.Board('4k3/8/8/4p3/3QR3/8/8/4K3 w - - 0 1')
        best = board.parse_san('Qxe5+')
        played = board.parse_san('Rxe5+')
        self.assertIsNone(root_move_impact(board, best, played))


if __name__ == '__main__':
    unittest.main()
