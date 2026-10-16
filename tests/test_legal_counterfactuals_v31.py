"""Chess-specific regressions (require python-chess, no Stockfish needed)."""
import unittest
import chess
from legal_counterfactuals import verified_legal_reply_traps, missed_threat_counterfactual
from position_context import inspect_response


class LegalCounterfactualTests(unittest.TestCase):
    def test_no_unproven_capture_refutation(self):
        board = chess.Board()
        best = board.parse_san('e4')
        self.assertEqual(verified_legal_reply_traps(board, best), [])

    def test_every_reported_refutation_is_legal_mate(self):
        # The test is invariant-based: a returned tempting reply must always
        # be legal, and its claimed refutation must result in actual mate.
        board = chess.Board('6k1/5ppp/8/8/8/6Q1/5PPP/6K1 w - - 0 1')
        for best in list(board.legal_moves):
            for trap in verified_legal_reply_traps(board, best):
                b = board.copy(stack=False); b.push(best)
                reply = chess.Move.from_uci(trap['reply_uci'])
                self.assertIn(reply, b.legal_moves); b.push(reply)
                answer = chess.Move.from_uci(trap['refutation_uci'])
                self.assertIn(answer, b.legal_moves); b.push(answer)
                self.assertTrue(b.is_checkmate())

    def test_legal_played_move_is_not_assumed_bad_without_evidence(self):
        board = chess.Board()
        self.assertIsNone(missed_threat_counterfactual(
            board, board.parse_san('e4'), board.parse_san('d4'),
            {'best_neutralizes': [], 'played_ignores': []}))

    def test_previous_pin_context_remains_supported(self):
        board = chess.Board('4k3/4r3/8/8/6B1/8/8/4R1K1 w - - 0 1')
        context = inspect_response(board, board.parse_san('Bd7+'), board.parse_san('Bf3'))
        self.assertTrue(context['pin_capture_refutations'])
        self.assertIn('pin', context['response_motifs'])


if __name__ == '__main__':
    unittest.main()
