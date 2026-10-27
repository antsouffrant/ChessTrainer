"""Root evaluation vs earliest material realization. Requires python-chess."""
import json
import unittest
import chess
from coaching.conceptual_understanding.critical_moments import critical_decision_evidence, critical_explanation
from coaching.narrative_composition.coaching import generate_coaching_text


class CriticalMomentTests(unittest.TestCase):
    def test_early_capture_beats_later_fork(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        best, played = b.parse_san('Ra2'), b.parse_san('Bd4')
        good = ['a1a2', 'd8f6']
        bad = ['c3d4', 'd8d4', 'a1a2', 'd4d6']
        e = critical_decision_evidence(b, best, played, good, bad, 100, -300)
        self.assertEqual(e['kind'], 'material_loss')
        self.assertEqual(e['critical_move'], 'Qxd4')
        self.assertEqual(e['critical_ply'], 1)
        self.assertIn('Qxd4 wins your bishop on d4', critical_explanation(e))
        _, narration = generate_coaching_text(
            fen=b.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san='Bd4', best_move_uci=best.uci(),
            best_move_san='Ra2', category='major_blunder',
            best_pv_uci=good, played_pv_uci=bad,
            eval_before_cp=100, eval_after_cp=-300)
        self.assertIn('Qxd4', narration)
        self.assertNotIn('fork', narration.lower())

    def test_equal_exchange_is_not_a_lost_piece(self):
        b = chess.Board('4r1k1/8/8/4n3/8/2B5/8/R5K1 w - - 0 1')
        best, played = b.parse_san('Ra2'), b.parse_san('Bxe5')
        e = critical_decision_evidence(b, best, played,
                ['a1a2', 'e8f8'], ['c3e5', 'e8e5'], 50, -200)
        self.assertIsNone(e['kind'])

    def test_inconclusive_line_does_not_invent_material_loss(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        best, played = b.parse_san('Ra2'), b.parse_san('Bd4')
        e = critical_decision_evidence(b, best, played,
                ['a1a2'], ['c3d4', 'd8d4'], 100, -300)
        self.assertIsNone(e['kind'])

    def test_no_engine_gap_no_claim(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        e = critical_decision_evidence(b, b.parse_san('Ra2'), b.parse_san('Bd4'),
                ['a1a2', 'd8f6'], ['c3d4', 'd8d4'], 10, 0)
        self.assertIsNone(e['kind'])


if __name__ == '__main__':
    unittest.main()
