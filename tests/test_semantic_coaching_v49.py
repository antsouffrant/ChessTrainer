"""Readable, causal coaching examples backed by legal saved continuations.

Run: python -m unittest discover -s tests -p 'test_semantic_coaching_v49.py'
Requires the application's python-chess dependency; no Stockfish required.
"""
import unittest
try:
    import chess
    from coaching.narrative_composition.coaching import generate_coaching_text
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching, evidence_findings
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'Install python-chess to run position-level tests')
class CausalCoachingTests(unittest.TestCase):
    def _say(self, board, best, played, good=None, bad=None, cp_good=50, cp_bad=-150, **options):
        return causal_coaching(board, board.parse_san(best), board.parse_san(played),
                               good, bad, best_cp=cp_good, played_cp=cp_bad, **options)

    def test_early_capture_beats_incidental_positional_concerns(self):
        board = chess.Board('6k1/8/8/6q1/8/5N2/8/K7 w - - 0 1')
        result = self._say(board, 'Nd4', 'Ng1', ['f3d4', 'g5e5'],
                           ['f3g1', 'g5g1'], cp_good=50, cp_bad=-310)
        self.assertIsNotNone(result)
        self.assertEqual(result['motif'], 'dont_hang_pieces')
        self.assertIn('Ng1', result['text'])
        self.assertIn('Qxg1', result['text'])
        self.assertIn('knight', result['text'])
        self.assertNotIn('Why ', result['text'])
        self.assertLess(len(result['text'].split()), 57)

    def test_retreating_knight_is_positional_when_no_tactic_proved(self):
        board = chess.Board('6k1/8/8/8/8/5N2/8/7K w - - 0 1')
        result = self._say(board, 'Nd4', 'Ng1', ['f3d4', 'g8f8'],
                           ['f3g1', 'g8f8'])
        self.assertEqual(result['finding'].key, 'passive_knight')
        self.assertIn('retreats', result['text'])
        self.assertIn('control', result['text'])
        self.assertNotIn('trapped', result['text'].lower())
        self.assertNotIn('loses initiative', result['text'].lower())

    def test_same_pawn_lost_in_both_branches_is_counterplay_not_defense(self):
        board = chess.Board('6k1/8/5n2/1p6/4P3/8/7P/1N4K1 w - - 0 1')
        result = self._say(board, 'Na3', 'h3', ['b1a3', 'f6e4'],
                           ['h2h3', 'f6e4'])
        self.assertEqual(result['motif'], 'counterattack')
        self.assertIn('rather than trying to save', result['text'])
        self.assertIn('counterattacks', result['text'])
        self.assertNotIn('saves', result['text'])
        self.assertLess(len(result['text'].split()), 57)

    def test_recapture_is_trade_not_winning_material(self):
        board = chess.Board('4r1k1/8/8/4n3/8/2B5/8/R5K1 w - - 0 1')
        result = self._say(board, 'Bxe5', 'Ra2', ['c3e5', 'e8e5'],
                           ['a1a2', 'e8f8'])
        self.assertIsNotNone(result)
        self.assertEqual(result['finding'].key, 'simplification')
        self.assertIn('exchanges', result['text'])
        self.assertNotIn('wins a free', result['text'])

    def test_ignored_mate_in_one_outweighs_any_piece_motif(self):
        board = chess.Board('r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3')
        result = self._say(board, 'g6', 'a6', ['g7g6', 'h5h3'],
                           ['a7a6', 'h5f7'], cp_good=-50, cp_bad=-1000)
        self.assertEqual(result['motif'], 'mate_defense')
        self.assertIn('Qxf7#', result['text'])

    def test_good_move_explains_preventing_mate_not_praising_it_generically(self):
        board = chess.Board('r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3')
        best = board.parse_san('g6')
        result = causal_coaching(board, best, best, ['g7g6', 'h5h3'],
              alternatives=[{'move_uci': board.parse_san('a6').uci(),
                             'pv_uci': ['a7a6', 'h5f7'], 'eval_cp': -1000}],
              best_cp=-50, played_cp=-50, category='excellent_move')
        self.assertIsNotNone(result)
        self.assertTrue(result['text'].startswith('g6 stops'))
        self.assertIn('a6', result['text'])

    def test_no_contrast_or_line_does_not_manufacture_a_tactic(self):
        board = chess.Board('6k1/8/8/8/8/5N2/8/7K w - - 0 1')
        best = board.parse_san('Nd4')
        result = causal_coaching(board, best, best, ['f3d4'], category='correct_move')
        self.assertIsNone(result)

    def test_integrated_caching_uses_new_short_text(self):
        board = chess.Board('6k1/8/8/6q1/8/5N2/8/K7 w - - 0 1')
        best, played = board.parse_san('Nd4'), board.parse_san('Ng1')
        _, text = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san='Ng1', best_move_uci=best.uci(),
            best_move_san='Nd4', category='major_blunder',
            best_pv_uci=['f3d4', 'g5e5'], played_pv_uci=['f3g1', 'g5g1'],
            eval_before_cp=50, eval_after_cp=-310)
        self.assertIn('Qxg1', text)
        self.assertLess(len(text.split()), 57)
        self.assertNotIn('The engine rates', text)


if __name__ == '__main__':
    unittest.main()
