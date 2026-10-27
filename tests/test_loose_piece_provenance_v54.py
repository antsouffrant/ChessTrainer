"""Regression positions for material opportunities and their *origin*.

Run with python-chess: python -m unittest tests.test_loose_piece_provenance_v54
No Stockfish installation or new evaluations required.
"""
import unittest

try:
    import chess
    from learning import classify_learning_concepts
    from coaching.conceptual_understanding.immediate_decision import immediate_decision
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
    from coaching.board_context.loose_piece_provenance import differential_loss_motif, confirmed_differential_loss
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'Install python-chess to test position-level motif provenance')
class LoosePieceOriginTests(unittest.TestCase):
    def classify(self, fen, best, played, best_line, played_line):
        board = chess.Board(fen)
        best_move = board.parse_san(best)
        played_move = board.parse_san(played)
        good = self._uci(board, best_line)
        bad = self._uci(board, played_line)
        labels = classify_learning_concepts(board, played_move, best_move,
                                            'major_blunder', 300,
                                            best_pv_uci=good, played_pv_uci=bad)
        return board, best_move, played_move, good, bad, labels

    @staticmethod
    def _uci(board, sans):
        child = board.copy(stack=False)
        result = []
        for san in sans:
            move = child.parse_san(san)
            result.append(move.uci())
            child.push(move)
        return result

    @staticmethod
    def primary(labels):
        return next(x.key for x in labels if x.is_primary)

    def test_moving_rook_onto_attacked_square_is_dont_hang(self):
        case = self.classify('7k/8/8/8/1p6/8/R7/6K1 w - - 0 1',
                             'Ra1', 'Ra3', ['Ra1', 'Kg8'], ['Ra3', 'bxa3'])
        board, best, played, good, bad, labels = case
        self.assertEqual(self.primary(labels), 'dont_hang_pieces')
        coach = causal_coaching(board, best, played, good, bad,
                                best_cp=100, played_cp=-400)
        self.assertEqual(coach['motif'], 'dont_hang_pieces')
        self.assertNotEqual(coach['motif'], 'loose_piece_awareness')

    def test_root_loose_rook_saved_by_better_move_is_protect(self):
        case = self.classify('7k/8/8/8/1p6/R7/8/6K1 w - - 0 1',
                             'Ra2', 'Kg2', ['Ra2', 'b3'], ['Kg2', 'bxa3'])
        self.assertEqual(self.primary(case[-1]), 'loose_piece_awareness')

    def test_releasing_a_defended_piece_is_lost_material_not_protect(self):
        case = self.classify('7k/8/8/8/1p6/B7/R7/6K1 w - - 0 1',
                             'Bb2', 'Rh2', ['Bb2', 'b3'], ['Rh2', 'bxa3'])
        self.assertEqual(self.primary(case[-1]), 'lost_material')
        self.assertNotIn('loose_piece_awareness', [x.key for x in case[-1]])

    def test_free_capture_is_capture_not_new_attack(self):
        case = self.classify('4k3/8/8/8/4q3/8/4R3/6K1 w - - 0 1',
                             'Rxe4+', 'Re3', ['Rxe4+', 'Kd7'], ['Re3', 'Kd7'])
        self.assertEqual(immediate_decision(case[0], case[1], case[2])['motif'],
                         'capture_loose_piece')
        self.assertEqual(self.primary(case[-1]), 'capture_loose_piece')
        self.assertNotEqual(self.primary(case[-1]), 'hanging_piece')

    def test_new_threat_later_wins_bishop_is_attack_loose(self):
        case = self.classify('7k/1b6/8/8/8/8/8/R5K1 w - - 0 1',
                             'Ra7', 'Ra2', ['Ra7', 'Ba8', 'Rxa8+'], ['Ra2', 'Ba8'])
        self.assertEqual(self.primary(case[-1]), 'hanging_piece')
        self.assertNotEqual(self.primary(case[-1]), 'capture_loose_piece')

    def test_no_proven_loss_does_not_claim_material_was_lost(self):
        case = self.classify('7k/8/8/8/1p6/8/R7/6K1 w - - 0 1',
                             'Ra1', 'Ra3', ['Ra1', 'Kg8'], ['Ra3', 'Kg8'])
        self.assertNotIn('lost_material', [x.key for x in case[-1]])
        self.assertNotIn('loose_piece_awareness', [x.key for x in case[-1]])


if __name__ == '__main__':
    unittest.main()
