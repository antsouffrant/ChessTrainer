"""Chess-only acceptance checks for the symmetric short-PV refutation scan."""
import unittest
try:
    import chess
    from coaching.conceptual_understanding.continuation_refutations import scan_branch
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'Install python-chess to validate legal chess positions')
class RefutationScanTests(unittest.TestCase):
    def test_checking_fork_with_captured_target(self):
        board = chess.Board('6k1/8/4r3/8/8/8/8/K2Q4 w - - 0 1')
        best = board.parse_san('Qg4+')
        line = [best.uci(), 'g8h7', 'g4e6']
        results = scan_branch(board, best, line, branch='best')
        self.assertTrue(any(r.motif == 'fork' and r.ply == 0 for r in results), results)
        self.assertIn('Qxe6', next(r.text for r in results if r.motif == 'fork'))

    def test_unrealized_fork_geometry_is_not_a_win(self):
        board = chess.Board('6k1/8/4r3/8/8/8/8/K2Q4 w - - 0 1')
        best = board.parse_san('Qg4+')
        results = scan_branch(board, best, [best.uci(), 'g8h7'], branch='best')
        self.assertEqual(results, [])

    def test_root_side_filter_disallows_opponent_reply_as_our_win(self):
        board = chess.Board('6k1/8/4r3/8/8/8/8/K2Q4 w - - 0 1')
        best = board.parse_san('Qg4+')
        results = scan_branch(board, best, [best.uci(), 'g8h7', 'g4e6'], branch='played')
        self.assertEqual(results, [])


if __name__ == '__main__':
    unittest.main()
