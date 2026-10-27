"""v51: conservative motif labeling, exchanges vs sacrifices, compact coaching.

No Stockfish required. Board tests are skipped if python-chess is absent;
feedback export and UI structure tests run independently.
"""
import unittest

try:
    import chess
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
    from learning import classify_learning_concepts
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'Install python-chess to run v51 position-level tests')
class ExplanationTests(unittest.TestCase):
    def analysis(self, fen, best_san, worse_san, good_sans, bad_sans):
        board = chess.Board(fen)
        def encode(moves):
            child = board.copy(stack=False)
            out = []
            for san in moves:
                move = child.parse_san(san)
                out.append(move.uci())
                child.push(move)
            return out
        best, played = board.parse_san(best_san), board.parse_san(worse_san)
        good, bad = encode(good_sans), encode(bad_sans)
        return board, best, played, good, bad

    def assert_mechanism(self, example, expected_key, expected_motif):
        board, best, played, good, bad = example
        result = causal_coaching(board, best, played, good, bad,
                                 best_cp=250, played_cp=-100)
        self.assertIsNotNone(result)
        self.assertEqual(result['finding'].key, expected_key)
        self.assertEqual(result['motif'], expected_motif)
        self.assertNotIn('Why ', result['text'])
        return result

    def test_rook_for_bishop_is_exchange_sacrifice_not_trade(self):
        example = self.analysis('7k/8/8/8/8/2n5/8/Rb5K w - - 0 1',
                                'Rxb1', 'Ra2', ['Rxb1', 'Nxb1'], ['Ra2', 'Ne4'])
        r = self.assert_mechanism(example, 'exchange_sacrifice', 'exchange_sacrifice')
        self.assertIn('sacrifices the exchange', r['text'])
        labels = classify_learning_concepts(example[0], example[2], example[1],
                    'mistake', 350, best_pv_uci=example[3], played_pv_uci=example[4])
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'exchange_sacrifice')

    def test_bishop_for_pawn_is_material_sacrifice(self):
        example = self.analysis('7k/8/5n2/3p4/2B5/8/8/7K w - - 0 1',
                                'Bxd5', 'Bd3', ['Bxd5', 'Nxd5'], ['Bd3', 'Kg8'])
        result = self.assert_mechanism(example, 'material_sacrifice', 'material_sacrifice')
        self.assertIn('bishop', result['text'])
        self.assertIn('pawn', result['text'])

    def test_queen_for_knight_is_material_sacrifice(self):
        example = self.analysis('7k/8/2p5/3n4/8/8/8/3Q3K w - - 0 1',
                                'Qxd5', 'Qh5', ['Qxd5', 'cxd5'], ['Qh5', 'Kg8'])
        result = self.assert_mechanism(example, 'material_sacrifice', 'material_sacrifice')
        self.assertIn('queen', result['text'])
        self.assertIn('knight', result['text'])

    def test_even_trade_is_simplification_not_sacrifice(self):
        example = self.analysis('4r1k1/8/8/4n3/8/2B5/8/R5K1 w - - 0 1',
                                'Bxe5', 'Ra2', ['Bxe5', 'Rxe5'], ['Ra2', 'Rf8'])
        result = self.assert_mechanism(example, 'simplification', 'simplification')
        self.assertIn('simplifying', result['text'])
        self.assertNotIn('sacrifice', result['text'])

    def test_no_unsupported_loose_piece_label_for_geometry_alone(self):
        # A rook looks attacked after Ra3, but absent a line showing a
        # differential capture this is not a proven hanging-piece lesson.
        board = chess.Board('7k/8/8/8/1p6/8/R7/6K1 w - - 0 1')
        labels = classify_learning_concepts(board, board.parse_san('Ra3'),
                    board.parse_san('Ra1'), 'mistake', 150,
                    best_pv_uci=['a2a1', 'h8g8'],
                    played_pv_uci=['a2a3', 'h8g8'])
        self.assertNotIn('loose_piece_awareness', [l.key for l in labels])

    def test_forcing_scan_is_not_generic_quiet_fallback(self):
        board = chess.Board('7k/8/8/8/8/3N4/8/7K w - - 0 1')
        labels = classify_learning_concepts(board, board.parse_san('Nb4'),
                    board.parse_san('Ne5'), 'mistake', 50,
                    best_pv_uci=['d3e5', 'h8g8'],
                    played_pv_uci=['d3b4', 'h8g8'])
        self.assertNotEqual(next(l.key for l in labels if l.is_primary), 'calculation')

if __name__ == '__main__':
    unittest.main()
