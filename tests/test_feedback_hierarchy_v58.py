"""Feedback benchmark consistency + evidence hierarchy tests (no engine needed)."""
from __future__ import annotations
import ast
import json
import unittest
from collections import Counter
from pathlib import Path

from coaching.motif_selection.motif_hierarchy import ancestors, choose_specific, validate_ontology
from coaching.narrative_composition.coaching_language import game_continuation

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'fixtures' / 'coach_feedback_v58.jsonl'


class HierarchyTests(unittest.TestCase):
    def test_catalog_is_complete_and_acyclic(self):
        tree = ast.parse((ROOT / 'learning.py').read_text())
        node = next(item for item in tree.body if isinstance(item, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'CONCEPT_CATALOG'
                            for target in item.targets))
        names = {item['key'] for item in ast.literal_eval(node.value)}
        self.assertTrue(validate_ontology(names))
        self.assertIn('threat_awareness', ancestors('fork'))
        self.assertIn('piece_activity', ancestors('attack_building'))
        self.assertIn('tactical_combination', ancestors('skewer'))

    def test_verified_fork_outranks_see_threat(self):
        self.assertEqual(choose_specific('threat_awareness', {'fork': (0.98, 1)}), 'fork')

    def test_verified_skewer_outranks_defensive_resource(self):
        self.assertEqual(choose_specific('defensive_resource', {'skewer': (0.93, 0)}), 'skewer')

    def test_geometry_or_remote_pattern_cannot_outrank_nearby_reason(self):
        self.assertEqual(choose_specific('threat_awareness', {'fork': (0.4, 0)}), 'threat_awareness')
        self.assertEqual(choose_specific('threat_awareness', {'fork': (0.99, 5)}), 'threat_awareness')
        self.assertEqual(choose_specific('mate_defense', {'fork': (0.99, 0)},
                                         protected={'mate_defense'}), 'mate_defense')

    def test_dont_hang_beats_generic_lost_material_when_confirmed(self):
        self.assertEqual(choose_specific('lost_material', {'dont_hang_pieces': (0.99, 1)}),
                         'dont_hang_pieces')


class FeedbackFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(x) for x in FIXTURE.read_text(encoding='utf-8').splitlines()]

    def test_fixture_matches_uploaded_coach_feedback_counts(self):
        self.assertEqual(len(self.rows), 109)
        counts = Counter((r['feedback_type'], r['rating']) for r in self.rows)
        self.assertEqual(counts['position', '1'], 32)
        self.assertEqual(counts['position', '-1'], 1)
        self.assertEqual(counts['explanation', '1'], 29)
        self.assertEqual(counts['explanation', '-1'], 12)
        self.assertEqual(counts['motif', '1'], 18)
        self.assertEqual(counts['motif', '-1'], 17)
        self.assertEqual(sum(bool(r['suggested_motif_key'] or r['suggested_text']) for r in self.rows), 24)

    def test_anonymized_fixture_retains_exact_board_and_variations(self):
        self.assertTrue(all(r.get('fen') and r.get('best_move_uci') and r.get('played_move_uci')
                            for r in self.rows))
        self.assertTrue(all(r['case_id'].startswith('cb-') for r in self.rows))
        self.assertEqual(len({(r['case_id'], r['feedback_type']) for r in self.rows}), len(self.rows))
        self.assertTrue(all('username' not in r and 'opponent' not in r and 'game_id' not in r
                            for r in self.rows))

    def test_delayed_response_names_opponent_not_engine(self):
        sentence = game_continuation('Kc7', 'bxg4', 'win your queen', ply=3, preceding=['Qf6'])
        self.assertIn('In the game you played Kc7', sentence)
        self.assertIn('After Qf6', sentence)
        self.assertIn('your opponent can win your queen with bxg4', sentence)
        self.assertNotIn('analyzed continuation', sentence)


if __name__ == '__main__':
    unittest.main()
