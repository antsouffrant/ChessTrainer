"""Run with python -m unittest discover -s tests -v (requires python-chess)."""
import unittest
import json
import chess
from learning import classify_learning_concepts
from coaching import generate_coaching_text
from pv_reasoning import fork_evidence, legal_pv, pv_san, comparative_insight


class PvMotifTests(unittest.TestCase):
    def test_checking_fork_has_priority_even_without_saved_pv(self):
        board = chess.Board('4k3/5q2/8/5N2/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('Nd6+')
        played = board.parse_san('Ng3')
        result = fork_evidence(board, best)
        self.assertTrue(result['check_fork'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 250)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'fork')

    def test_two_loose_pieces_are_enough_without_legacy_pv(self):
        board = chess.Board('1qpr2k1/8/8/4N3/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('Nc6')
        played = board.parse_san('Nf3')
        evidence = fork_evidence(board, best)
        self.assertTrue(evidence['loose_pair'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 300)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'fork')

    def test_engine_continuation_is_legal_and_does_not_overclaim(self):
        board = chess.Board('4k3/5q2/8/5N2/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('Nd6+')
        line = json.dumps(['f5d6', 'e8f8', 'd6f7'])
        self.assertEqual(len(legal_pv(board, line, best)), 3)
        self.assertIn('Nxf7', pv_san(board, line, best))
        played = board.parse_san('Ng3')
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 250,
                                            best_pv_uci=line)
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(), played_move_san='Ng3',
            best_move_uci=best.uci(), best_move_san='Nd6+',
            category='major_blunder', labels=labels, best_pv_uci=line,
        )
        self.assertIn('double attack', explanation)
        self.assertIn('queen', explanation.lower())
        self.assertNotIn('sampled engine continuation', explanation.lower())

    def test_pv_translation_explains_delayed_material_not_line_notation(self):
        board = chess.Board('4k3/5q2/8/5N2/8/8/8/4K3 w - - 0 1')
        best = board.parse_san('Nd6+')
        played = board.parse_san('Ng3')
        line = json.dumps(['f5d6', 'e8f8', 'd6f7'])
        insight = comparative_insight(board, best, played, line)
        self.assertIn('queen', insight['narrative'])
        self.assertNotIn('gain appears after the reply', insight['narrative'].lower())
        self.assertNotIn('1.Nd6+', insight['narrative'])

    def test_illegal_stale_pv_does_not_create_evidence(self):
        board = chess.Board()
        self.assertEqual(legal_pv(board, '["a7a5"]'), [])
        self.assertEqual(legal_pv(board, 'bad json'), [])

if __name__ == '__main__':
    unittest.main()
