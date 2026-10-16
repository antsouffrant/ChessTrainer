"""Run after pip install -r requirements.txt: python -m unittest discover -s tests -v"""
import unittest
import chess
from pv_outcomes import positional_outcome
from pv_reasoning import comparative_insight
from learning import classify_learning_concepts
from coaching import generate_coaching_text


class AdvantageOutcomesTests(unittest.TestCase):
    def test_added_attack_on_queen_compared_with_played_move(self):
        board = chess.Board('4k3/8/8/3q4/1P6/8/8/2R1K3 w - - 0 1')
        best = board.parse_san('Rc5')
        played = board.parse_san('Rc2')
        result = positional_outcome(board, [best], [played])
        self.assertIsNotNone(result)
        self.assertEqual(result['motif'], 'attack_building')
        self.assertIn('queen', result['narrative'])
        self.assertIn('d5', result['narrative'])

    def test_passed_pawn_advancement_detected_in_both_branches(self):
        board = chess.Board('4k3/8/8/4P3/8/8/8/4K3 w - - 0 1')
        best = [chess.Move.from_uci(x) for x in ('e5e6', 'e8d8', 'e6e7')]
        played = [chess.Move.from_uci(x) for x in ('e1d2', 'e8d8', 'd2e3')]
        result = positional_outcome(board, best, played)
        self.assertEqual(result['motif'], 'passed_pawn')
        self.assertIn('e7', result['narrative'])
        self.assertNotIn('forced', result['narrative'].lower())

    def test_delayed_queen_capture_is_primary_tactical_evidence(self):
        board = chess.Board('4k3/5q2/8/5N2/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('Nd6+')
        played = board.parse_san('Ng3')
        line = ['f5d6', 'e8f8', 'd6f7']
        insight = comparative_insight(board, best, played, line)
        self.assertTrue(insight['narrative'])
        self.assertIn('queen', insight['narrative'].lower())
        self.assertNotIn('tactical balance', insight['narrative'].lower())

    def test_new_motif_is_primary_when_pv_shows_passed_pawn_payoff(self):
        board = chess.Board('4k3/8/8/4P3/8/8/8/4K3 w - - 0 1')
        best = chess.Move.from_uci('e5e6')
        played = chess.Move.from_uci('e1d2')
        best_line = ['e5e6', 'e8d8', 'e6e7']
        played_line = ['e1d2', 'e8d8', 'd2e3']
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 250,
                                             best_pv_uci=best_line, played_pv_uci=played_line)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'passed_pawn')


if __name__ == '__main__':
    unittest.main()
