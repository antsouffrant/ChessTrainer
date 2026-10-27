"""Regression positions for check blocking, offered exchanges, and discovered checks.

Run in the application's environment after installing requirements.txt:
python -m unittest discover -s tests -p 'test_check_evasions_and_discoveries_v35.py'
"""
import unittest
import chess

from coaching.board_context.check_response import check_response
from coaching.board_context.discovered_counterfactuals import revealed_lines
from coaching.board_context.position_context import inspect_response
from coaching.narrative_composition.coaching import generate_coaching_text


class CheckDefenseNarrationTests(unittest.TestCase):
    def test_interposition_offers_real_equal_rook_exchange(self):
        board = chess.Board('4r2k/8/8/2R5/3P4/8/8/4K3 w - - 0 1')
        move = chess.Move.from_uci('c5e5')
        self.assertTrue(board.is_check())
        self.assertIn(move, board.legal_moves)
        answer = check_response(board, move)
        self.assertEqual(answer['kind'], 'interpose')
        self.assertEqual(answer['motif'], 'blocking')
        self.assertTrue(answer['trade']['equal_value'])
        self.assertIn('blocks the check', answer['evidence'])
        self.assertIn('exchange', answer['evidence'])
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci='e1d2',
            played_move_san='Kd2', best_move_uci='c5e5', best_move_san='Re5',
            category='major_blunder', labels=[], best_pv_uci=[], played_pv_uci=[])
        self.assertIn('blocks the check', explanation)
        self.assertNotIn('pressure', explanation.lower())
        self.assertNotIn('double attack', explanation.lower())

    def test_interposition_without_recapture_does_not_claim_equal_trade(self):
        board = chess.Board('4r2k/8/8/2B5/8/8/8/4K3 w - - 0 1')
        # Bc5-e3 blocks the e-file, but is it legal with a clear diagonal?
        move = chess.Move.from_uci('c5e3')
        self.assertIn(move, board.legal_moves)
        evidence = check_response(board, move)
        self.assertEqual(evidence['kind'], 'interpose')
        self.assertIsNone(evidence['trade'])
        self.assertNotIn('exchanges', evidence['evidence'])

    def test_plain_discovered_rook_check(self):
        board = chess.Board('4k3/8/8/8/4B2n/8/8/4R1K1 w - - 0 1')
        move = chess.Move.from_uci('e4f3')
        lines = revealed_lines(board, move)
        self.assertTrue(any(d['kind'] == 'discovered_check'
                            and d['attacker_square'] == chess.E1 for d in lines))
        context = inspect_response(board, move)
        self.assertTrue(context['discovered_unique_lines'])

    def test_en_passant_opens_diagonal_check_via_removed_pawn(self):
        # The discovered line opens on d5 (the captured pawn's square), NOT
        # on the moving pawn's original square e5.
        board = chess.Board('6k1/8/8/3pP3/8/8/B7/6K1 w - d6 0 1')
        move = chess.Move.from_uci('e5d6')
        self.assertTrue(board.is_en_passant(move))
        self.assertIn(move, board.legal_moves)
        lines = revealed_lines(board, move)
        self.assertTrue(any(d['kind'] == 'discovered_check' and
                            d['attacker_square'] == chess.A2 and
                            d['vacated_square'] == chess.D5 for d in lines))

    def test_non_discovered_direct_check_not_false_positive(self):
        board = chess.Board('4k3/8/8/8/8/8/5R2/6K1 w - - 0 1')
        # Check created by the rook itself, not a stationary sliding piece.
        move = chess.Move.from_uci('f2e2')
        self.assertIn(move, board.legal_moves)
        self.assertFalse(any(d['kind'] == 'discovered_check' for d in revealed_lines(board, move)))


if __name__ == '__main__':
    unittest.main()
