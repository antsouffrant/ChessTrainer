"""Board-specific coaching regression. Run with python-chess installed."""
import unittest
try:
    import chess
except ImportError:
    chess = None

@unittest.skipUnless(chess is not None, 'python-chess required for board verification')
class BoardRefinementTests(unittest.TestCase):
    def test_check_interposition_is_blocking(self):
        from coaching.board_context.check_response import check_response, blocking_response
        board = chess.Board('4r2k/8/8/2R5/3P4/8/8/4K3 w - - 0 1')
        move = chess.Move.from_uci('c5e5')
        self.assertIn(move, board.legal_moves)
        self.assertEqual(check_response(board, move)['motif'], 'blocking')
        self.assertEqual(blocking_response(board, move)['kind'], 'check')

    def test_legal_interposition_cuts_rook_attack_on_queen(self):
        from coaching.board_context.check_response import blocking_response
        board = chess.Board('4r2k/8/8/6B1/8/8/4QP2/6K1 w - - 0 1')
        move = chess.Move.from_uci('g5e3')
        self.assertIn(move, board.legal_moves)
        evidence = blocking_response(board, move)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence['kind'], 'material')
        self.assertIn('queen on e2', evidence['evidence'])

    def test_nonblocking_quiet_move_not_blocking(self):
        from coaching.board_context.check_response import blocking_response
        board = chess.Board('4r2k/8/8/6B1/8/8/4QP2/6K1 w - - 0 1')
        move = chess.Move.from_uci('g5h4')
        self.assertIn(move, board.legal_moves)
        self.assertIsNone(blocking_response(board, move))

    def test_discovery_requires_uncovered_slider(self):
        from coaching.board_context.discovered_counterfactuals import revealed_lines
        from coaching.board_context.pv_reasoning import fork_evidence
        board = chess.Board('4k3/8/8/8/4B2n/8/8/4R1K1 w - - 0 1')
        best = chess.Move.from_uci('e4f3')
        self.assertIn(best, board.legal_moves)
        self.assertTrue(any(d['kind'] == 'discovered_check' for d in revealed_lines(board, best)))
        self.assertIsNone(fork_evidence(board, best))

    def test_three_kinds_of_material_loss_are_distinct(self):
        from coaching.board_context.loose_piece_provenance import differential_loss_motif
        loose_board = chess.Board('3r3k/8/8/8/3B4/8/8/6K1 w - - 0 1')
        played = chess.Move.from_uci('g1h1')
        self.assertEqual(differential_loss_motif(loose_board, played, {'root_square': 'd4'}),
                         'loose_piece_awareness')
        hung_board = chess.Board('2r4k/8/8/8/8/8/2Q5/6K1 w - - 0 1')
        hung = chess.Move.from_uci('c2c6')
        self.assertEqual(differential_loss_motif(hung_board, hung, {'root_square': 'c2'}),
                         'dont_hang_pieces')
        other = chess.Board('6rk/8/8/8/8/2N5/8/6K1 w - - 0 1')
        self.assertEqual(differential_loss_motif(other, chess.Move.from_uci('g1h1'),
                                                  {'root_square': 'c3'}), 'lost_material')


if __name__ == '__main__':
    unittest.main()
