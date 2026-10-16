"""Regression fixtures for explaining the move the player *chose*, not only
what the engine recommends. Run with python-chess installed."""
import json
import unittest

import chess
from branch_diagnostics import decisive_contrast
from coaching import generate_coaching_text


class DecisionContrastTests(unittest.TestCase):
    # A natural king move permits a checking knight fork; moving the rook to
    # the eighth rank makes the knight trick irrelevant.
    FEN = '7k/8/8/8/2n5/8/8/1R4K1 w - - 0 1'
    BEST = ['b1b8', 'h8h7']
    PLAYED = ['g1f1', 'c4d2']

    def setUp(self):
        self.board = chess.Board(self.FEN)
        self.best = chess.Move.from_uci(self.BEST[0])
        self.played = chess.Move.from_uci(self.PLAYED[0])

    def test_blunder_contrast_identifies_nearby_fork(self):
        finding = decisive_contrast(self.board, self.best, self.played,
                                    self.BEST, self.PLAYED, category='major_blunder')
        self.assertIsNotNone(finding)
        self.assertEqual(finding['kind'], 'fork')
        self.assertIn('Nd2+', finding['text'])
        self.assertIn('Kf1', finding['text'])
        self.assertIn('Rb8+', finding['text'])
        self.assertNotIn('forced', finding['text'].lower())

    def test_excellent_move_compares_second_best(self):
        alternatives = [{'move_uci': 'g1f1', 'pv_uci': self.PLAYED,
                         'eval_cp': 0}]
        finding = decisive_contrast(self.board, self.best, self.best,
                                    self.BEST, self.BEST,
                                    alternatives=alternatives,
                                    category='excellent_move', best_eval_cp=150)
        self.assertIsNotNone(finding)
        self.assertEqual(finding['kind'], 'fork')
        self.assertIn('alternative Kf1', finding['text'])

    def test_nearly_equal_alternative_is_not_described_as_refuted(self):
        alternatives = [{'move_uci': 'g1f1', 'pv_uci': self.PLAYED,
                         'eval_cp': 150}]
        finding = decisive_contrast(self.board, self.best, self.best,
                                    self.BEST, self.BEST,
                                    alternatives=json.dumps(alternatives),
                                    category='excellent_move', best_eval_cp=160)
        self.assertIsNone(finding)

    def test_coaching_calls_decision_comparison(self):
        _, text = generate_coaching_text(
            fen=self.FEN, previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=self.PLAYED[0],
            played_move_san='Kf1', best_move_uci=self.BEST[0],
            best_move_san='Rb8+', category='major_blunder',
            best_pv_uci=self.BEST, played_pv_uci=self.PLAYED,
        )
        self.assertIn('fork', text.lower())
        self.assertIn('Kf1', text)


if __name__ == '__main__':
    unittest.main()
