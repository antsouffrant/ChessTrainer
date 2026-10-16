"""Run with python -m unittest tests/test_exchange_and_startup_v29.py (python-chess required)."""
import unittest
import chess

from pv_reasoning import fork_evidence, comparative_insight
from learning import classify_learning_concepts


class ExchangeAwareLearningTests(unittest.TestCase):
    def test_checking_equal_exchange_is_not_sacrifice(self):
        # Bxf7+ Rxf7 trades bishop for knight. The fact that the move checks
        # does not turn an ordinary equal trade into a material sacrifice.
        board = chess.Board('5rk1/5n2/8/8/2B5/8/8/6K1 w - - 0 1')
        best = board.parse_san('Bxf7+')
        played = board.parse_san('Kf2')
        insight = comparative_insight(board, best, played,
            [best.uci(), 'f8f7'], [played.uci()])
        self.assertNotIn('sacrifice', insight['narrative'].lower())
        self.assertNotEqual(insight['motif'], 'tactical_combination')

    def test_double_attack_not_tagged_if_knight_recaptured(self):
        # Nxe5 momentarily attacks Qd7 and Rf7; ...dxe5 removes that
        # knight immediately, so the geometry is not an actionable fork.
        board = chess.Board('6k1/3q1r2/3p4/4p3/8/5N2/8/6K1 w - - 0 1')
        best = board.parse_san('Nxe5')
        played = board.parse_san('Kf2')
        result = fork_evidence(board, best, [best.uci(), 'd6e5'])
        self.assertIsNone(result)
        labels = classify_learning_concepts(board, played, best,
            category='major_blunder', centipawn_loss=180,
            best_pv_uci=[best.uci(), 'd6e5'], played_pv_uci=[played.uci()])
        self.assertNotIn('fork', [row.key for row in labels])
        self.assertNotIn('missed_capture', [row.key for row in labels])


if __name__ == '__main__':
    unittest.main()
