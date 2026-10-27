"""Position-level acceptance tests of the v50 semantic planner.

These are *simplified independent positions* expressing the user's coaching
examples, not attempts to recreate absent PGN/FEN from the original games.
Requires python-chess; no Stockfish or network access.
"""
import unittest
try:
    import chess
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
    from coaching.narrative_composition.coaching import generate_coaching_text
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'Install python-chess to run semantic chess acceptance tests')
class ChessIdeaExamples(unittest.TestCase):
    def explain(self, fen, best, played, good, bad, cp_good=180, cp_bad=-250, **kwargs):
        board = chess.Board(fen)
        best_move = board.parse_san(best)
        bad_move = board.parse_san(played)
        good_uci = self._variation(board, good)
        bad_uci = self._variation(board, bad)
        output = causal_coaching(board, best_move, bad_move, good_uci, bad_uci,
                                 best_cp=cp_good, played_cp=cp_bad, **kwargs)
        self.assertIsNotNone(output)
        self.assertLessEqual(len(output['text'].split()), 42)
        for forbidden in ('Why ', 'Stockfish evaluates the difference',
                          'the saved line reaches', 'not necessarily a free piece'):
            self.assertNotIn(forbidden, output['text'])
        return output

    @staticmethod
    def _variation(board, sans):
        tmp = board.copy(stack=False)
        out = []
        for san in sans:
            move = tmp.parse_san(san)
            out.append(move.uci())
            tmp.push(move)
        return out

    def test_1_free_pawn_beats_quiet_rook_move(self):
        result = self.explain('7k/8/8/2p5/8/4B3/3R4/R3K3 w - - 0 1',
                              'Bxc5', 'Rad1', ['Bxc5', 'Kg8'], ['Rad1', 'Kg8'])
        self.assertIn('free pawn', result['text'])
        self.assertIn('Rad1', result['text'])
        self.assertEqual(result['finding'].key, 'clean_capture')

    def test_2_castling_claim_requires_king_to_recapture_queen(self):
        result = self.explain('3qk3/8/8/1p6/2B1P3/8/8/3QK2R w K - 0 1',
                              'Bxb5+', 'e5', ['Bxb5+', 'Kf8'],
                              ['e5', 'Qxd1+', 'Kxd1'])
        self.assertIn('castling', result['text'])
        self.assertIn('Bxb5+', result['text'])
        self.assertNotIn('not guaranteed', result['text'])

    def test_3_missed_free_knight_outweighs_remote_line(self):
        result = self.explain('7k/8/8/8/4n3/8/4Q3/2R4K w - - 0 1',
                              'Qxe4', 'Rc7', ['Qxe4', 'Kg8'], ['Rc7', 'Kg8'])
        self.assertIn('free knight', result['text'])
        self.assertNotIn('bishop', result['text'])

    def test_4_capture_not_called_free_if_legally_recapturable(self):
        # A guarded capture that exchanges a bishop for a bishop.
        result = self.explain('4k3/8/2b5/3n4/2B5/8/8/4K3 w - - 0 1',
                              'Bxd5', 'Bb3', ['Bxd5', 'Bxd5'], ['Bb3', 'Ba8'])
        self.assertNotIn('free knight', result['text'])
        self.assertNotIn('free bishop', result['text'])

    def test_5_exchange_loss_is_not_random_pin_commentary(self):
        result = self.explain('7k/8/3br3/8/8/4Q3/8/3R2K1 w - - 0 1',
                              'Qe2', 'Rxd6', ['Qe2', 'Kg8', 'Qxe6'],
                              ['Rxd6', 'Rxd6'])
        self.assertEqual(result['finding'].key, 'exchange_loss')
        self.assertIn('loses the exchange', result['text'])

    def test_6_checking_double_attack_with_material_payoff(self):
        result = self.explain('6k1/8/4r3/8/8/8/8/K2Q4 w - - 0 1',
                              'Qg4+', 'Qh5', ['Qg4+', 'Kh7', 'Qxe6'],
                              ['Qh5', 'Rh6'])
        self.assertEqual(result['finding'].key, 'double_attack')
        self.assertIn('wins material', result['text'])

    def test_7_checking_fork_with_longer_material_win(self):
        result = self.explain('6k1/8/4r3/8/8/8/8/K2Q4 w - - 0 1',
                              'Qg4+', 'Qh5', ['Qg4+', 'Kh7', 'Qxe6'],
                              ['Qh5', 'Rh6'], cp_good=650, cp_bad=-10)
        self.assertEqual(result['finding'].key, 'double_attack')
        self.assertNotIn('exchange R', result['text'])

    def test_8_queen_captures_loose_pawn_and_stays_active(self):
        result = self.explain('7k/8/8/8/8/3p4/8/3QK3 w - - 0 1',
                              'Qxd3', 'Qh5', ['Qxd3', 'Kg8'], ['Qh5', 'Kg8'])
        self.assertIn('pawn', result['text'])
        self.assertIn('queen active', result['text'])

    def test_9_pawn_offer_unlocks_bishop_path_to_pawn(self):
        result = self.explain('k7/6p1/8/8/1p6/8/1BP5/7K w - - 0 1',
                              'c3', 'Kh2', ['c3', 'bxc3', 'Bxc3', 'Ka7', 'Bxg7'],
                              ['Kh2', 'Ka7'])
        self.assertEqual(result['finding'].key, 'pawn_sacrifice_plan')
        self.assertIn('bishop', result['text'])
        self.assertIn('g7', result['text'])

    def test_10_blunder_root_rook_taken_immediately(self):
        result = self.explain('7k/1p6/Q7/4q3/8/8/8/2R3K1 w - - 0 1',
                              'Qxb7', 'Re1', ['Qxb7', 'Qe8'], ['Re1', 'Qxe1+'])
        self.assertEqual(result['finding'].key, 'material_loss')
        self.assertIn('Re1 fails tactically', result['text'])
        self.assertIn('Qxe1+', result['text'])
        self.assertNotIn('avoids that loss', result['text'])

    def test_integrated_generator_does_not_use_legacy_two_heading_template(self):
        board = chess.Board('7k/8/8/2p5/8/4B3/3R4/R3K3 w - - 0 1')
        good = self._variation(board, ['Bxc5', 'Kg8'])
        bad = self._variation(board, ['Rad1', 'Kg8'])
        _, prose = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=board.parse_san('Rad1').uci(),
            played_move_san='Rad1', best_move_uci=board.parse_san('Bxc5').uci(),
            best_move_san='Bxc5', category='mistake', best_pv_uci=good,
            played_pv_uci=bad, eval_before_cp=180, eval_after_cp=-250)
        self.assertIn('free pawn', prose)
        self.assertNotIn('Why Bxc5 is better', prose)
        self.assertNotIn('Why Rad1 falls short', prose)


if __name__ == '__main__':
    unittest.main()
