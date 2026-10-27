"""Board-level tests for multi-motif explanatory variations (python-chess)."""
import json
import unittest
import chess

from coaching.board_context.explanatory_evidence import board_events, explanation_variations, decode_variations
from coaching.conceptual_understanding.critical_moments import critical_decision_evidence, critical_explanation


class ExplanatoryEvidenceV43(unittest.TestCase):
    def test_material_realization_is_closer_than_later_tactics(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        good, bad = b.parse_san('Ra2'), b.parse_san('Bd4')
        lines = explanation_variations(b, good, bad, ['a1a2', 'd8f6'],
                ['c3d4', 'd8d4', 'a1a2', 'd4d6'], 100, -300)
        self.assertEqual([x['role'] for x in lines['lines']], ['recommended', 'played'])
        self.assertEqual(lines['assessment']['difference_cp'], 400)
        self.assertEqual(lines['lines'][1]['plies'][1]['san'], 'Qxd4')
        self.assertIn('capture', [x['kind'] for x in lines['lines'][1]['plies'][1]['effects']])
        explanation = critical_decision_evidence(b, good, bad,
            ['a1a2', 'd8f6'], ['c3d4', 'd8d4', 'a1a2', 'd4d6'], 100, -300,
            explanatory_lines=lines)
        self.assertEqual(explanation['kind'], 'material_loss')
        self.assertIn('Qxd4', critical_explanation(explanation))

    def test_discovered_check_from_stationary_rook(self):
        b = chess.Board('4k3/8/8/8/4N3/8/8/4R1K1 w - - 0 1')
        mv = b.parse_san('Ng3+')
        observations = board_events(b, mv)
        self.assertIn('discovered_check', [x['kind'] for x in observations])

    def test_discovered_attack_is_recorded_as_possible_realization(self):
        b = chess.Board('4r1k1/8/4n3/8/8/8/4Q2P/6K1 w - - 0 1')
        best, played = b.parse_san('Qd3'), b.parse_san('h3')
        good = ['e2d3', 'e6f4']
        bad = ['h2h3', 'e6f4', 'e2d1']
        evidence = critical_decision_evidence(b, best, played, good, bad, 100, -350)
        self.assertIn('discovered_attack', [x['kind'] for x in evidence['realizations']])

    def test_pin_created_by_rook(self):
        b = chess.Board('4k3/4b3/8/8/8/8/8/R5K1 w - - 0 1')
        observations = board_events(b, b.parse_san('Re1'))
        self.assertIn('pin', [x['kind'] for x in observations])

    def test_promotion_and_passed_pawn(self):
        b = chess.Board('7k/4P3/8/8/8/8/8/6K1 w - - 0 1')
        mv = b.parse_san('e8=Q+')
        effects = board_events(b, mv)
        self.assertIn('promotion', [x['kind'] for x in effects])
        earlier = chess.Board('6k1/p7/4P3/8/8/8/8/6K1 w - - 0 1')
        effects = board_events(earlier, earlier.parse_san('e7'))
        self.assertIn('passed_pawn', [x['kind'] for x in effects])

    def test_tested_reply_keeps_source_and_does_not_replace_root_score(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        good, bad = b.parse_san('Ra2'), b.parse_san('Bd4')
        evidence = explanation_variations(b, good, bad,
              ['a1a2', 'd8f6'], ['c3d4', 'd8d4', 'a1a2'], 100, -300,
              probe={'pv_uci': ['c3d4', 'd8b6'], 'eval_cp': -150, 'depth': 14})
        self.assertEqual(len(evidence['lines']), 3)
        tested = evidence['lines'][2]
        self.assertEqual(tested['role'], 'tested_reply')
        self.assertEqual(tested['source'], 'engine_reply_probe')
        self.assertEqual(tested['eval_cp'], -150)
        self.assertEqual(decode_variations(json.dumps(evidence)), evidence)

    def test_positive_move_uses_ranked_alternative(self):
        b = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        good, bad = b.parse_san('Ra2'), b.parse_san('Bd4')
        alt = [{'move_uci': bad.uci(), 'pv_uci': ['c3d4', 'd8d4', 'a1a2'],
                'eval_cp': -300}]
        e = critical_decision_evidence(b, good, good, ['a1a2', 'd8f6'],
                ['a1a2', 'd8f6'], 100, 100, alternatives=alt)
        self.assertEqual(e['comparison_role'], 'alternative')
        self.assertEqual(e['kind'], 'material_loss')
        self.assertIn('alternative', critical_explanation(e))

    def test_equal_exchange_does_not_become_material_loss(self):
        b = chess.Board('4r1k1/8/8/4n3/8/2B5/8/R5K1 w - - 0 1')
        good, bad = b.parse_san('Ra2'), b.parse_san('Bxe5')
        e = critical_decision_evidence(b, good, bad,
                ['a1a2', 'e8f8'], ['c3e5', 'e8e5'], 50, -200)
        self.assertNotEqual(e['kind'], 'material_loss')


if __name__ == '__main__':
    unittest.main()
