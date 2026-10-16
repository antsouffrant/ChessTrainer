"""Regression examples for causal lesson selection; run with python-chess installed.

python -m unittest discover -s tests -v
"""
import unittest
import chess
from learning import classify_learning_concepts
from coaching import generate_coaching_text
from position_context import inspect_response


class CausalConceptTests(unittest.TestCase):
    def test_incidental_pin_is_not_primary_without_a_proven_consequence(self):
        board = chess.Board('4k3/8/2n5/8/8/8/8/4KB2 w - - 0 1')
        best = board.parse_san('Bb5')  # pins the knight on c6 to e8
        played = board.parse_san('Bd3')
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 350)
        self.assertNotEqual(next(x.key for x in labels if x.is_primary), 'pin')
        prompt, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san='Bd3', best_move_uci=best.uci(),
            best_move_san='Bb5', category='major_blunder', labels=labels,
        )
        self.assertNotIn('pin', explanation.lower())

    def test_new_opponent_threat_overrides_background_motifs(self):
        previous = chess.Board('r5k1/p7/8/1B6/8/8/8/R5K1 b - - 0 1')
        last = previous.parse_san('a6')
        board = previous.copy(stack=False)
        board.push(last)
        best = board.parse_san('Ba4')
        played = board.parse_san('Ra2')
        c = inspect_response(board, best, played, previous.fen(), last.uci())
        self.assertEqual(c['primary_key'], 'loose_piece_awareness')
        self.assertIn(chess.B5, c['new_loose'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 250,
                                            previous_fen=previous.fen(), opponent_move_uci=last.uci())
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'loose_piece_awareness')
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=previous.fen(), opponent_move_uci=last.uci(),
            opponent_move_san='a6', played_move_uci=played.uci(),
            played_move_san='Ra2', best_move_uci=best.uci(),
            best_move_san='Ba4', category='major_blunder', labels=labels,
        )
        self.assertIn('bishop on b5', explanation)
        self.assertIn('Ra2 leaves', explanation)

    def test_undefended_capture_is_more_concrete_than_incidental_pin(self):
        board = chess.Board('4k3/8/8/8/4q3/8/4R3/4K3 w - - 0 1')
        best = board.parse_san('Rxe4')
        played = board.parse_san('Re3')
        c = inspect_response(board, best, played)
        self.assertEqual(c['primary_key'], 'hanging_piece')
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 900)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'hanging_piece')

if __name__ == '__main__':
    unittest.main()
