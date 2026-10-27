"""Board tests require python-chess; no Stockfish execution is necessary."""
import unittest

try:
    import chess
    from coaching.conceptual_understanding.decision_context import trace_variation
    from coaching.conceptual_understanding.causal_consequences import sacrifice_compensation, structural_exchange_gain
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'python-chess needed for legal-board regressions')
class CausalConsequencesTests(unittest.TestCase):
    def test_sacrifice_requires_realized_material_compensation(self):
        good = {'exchanges': [{'first': {'ply': 0, 'by_solver': True, 'value': 3},
                               'recapture': {'ply': 1, 'by_solver': False, 'value': 5}}],
                'captures': [{'ply': 0, 'by_solver': True, 'value': 3},
                             {'ply': 1, 'by_solver': False, 'value': 5},
                             {'ply': 2, 'by_solver': True, 'value': 5,
                              'square': 'b7', 'piece': 'rook'}],
                'steps': [{'san': 'Rxb7', 'material_delta': 3},
                          {'san': 'Rxb7', 'material_delta': -2},
                          {'san': 'Qxb7', 'material_delta': 3}],
                'material_delta': 3}
        evidence = sacrifice_compensation(good)
        self.assertEqual(evidence['payoff'], 'Qxb7')
        self.assertEqual(evidence['reply'], 'Rxb7')
        self.assertEqual(evidence['piece'], 'rook')
        uncompensated = dict(good, material_delta=-2)
        self.assertIsNone(sacrifice_compensation(uncompensated))
        empty = dict(good, captures=good['captures'][:2])
        self.assertIsNone(sacrifice_compensation(empty))

    def test_trade_creates_doubled_opponent_pawns(self):
        board = chess.Board('7k/8/4pp2/5n2/8/3B4/8/4K3 w - - 0 1')
        best, played = board.parse_san('Bxf5'), board.parse_san('Be4')
        good = trace_variation(board, [best.uci(), 'e6f5'], best)
        bad = trace_variation(board, [played.uci(), 'e6e5'], played)
        structural = structural_exchange_gain(board, best, played, good, bad)
        self.assertEqual(structural, {'file': 'f', 'reply': 'exf5'})
        result = causal_coaching(board, best, played,
                                 [best.uci(), 'e6f5'], [played.uci(), 'e6e5'],
                                 best_cp=110, played_cp=-90)
        self.assertEqual(result['motif'], 'pawn_structure')
        self.assertIn('doubled f-pawns', result['text'])

    def test_unequal_trade_explains_legal_compensation_not_generic_investment(self):
        board = chess.Board('1r5k/1n6/Q7/8/8/8/8/1R5K w - - 0 1')
        best, played = board.parse_san('Rxb7'), board.parse_san('Ra1')
        good = [best.uci(), 'b8b7', 'a6b7']
        bad = [played.uci(), 'b8b7']
        result = causal_coaching(board, best, played, good, bad,
                                 best_cp=500, played_cp=-100)
        self.assertIsNotNone(result)
        self.assertEqual(result['motif'], 'exchange_sacrifice')
        self.assertIn('Qxb7', result['text'])
        self.assertNotIn('deliberate material investment', result['text'])


if __name__ == '__main__':
    unittest.main()
