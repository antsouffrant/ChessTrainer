"""v70 taxonomy regression: defend vs attack and supported strategic investment."""
import unittest
from coaching.motif_selection.coaching_taxonomy import TACTICAL, CANONICAL_KEYS, RETIRED_KEYS, assign_taxonomy, validate_taxonomy


class RefinedTaxonomyTests(unittest.TestCase):
    def test_blocking_is_active_tactical_primary(self):
        self.assertIn('blocking', TACTICAL)
        self.assertIn('blocking', CANONICAL_KEYS)
        self.assertTrue(validate_taxonomy(CANONICAL_KEYS | RETIRED_KEYS))
        path = assign_taxonomy('blocking', is_in_check=True)
        self.assertEqual(path.context_key, 'defend')
        self.assertEqual(path.move_type_key, 'tactical')
        self.assertEqual([node['key'] for node in path.serialize()['levels']],
                         ['defend', 'tactical', 'blocking'])

    def test_defensive_material_sacrifice_is_a_valid_strategy(self):
        normal = assign_taxonomy('material_sacrifice')
        self.assertEqual((normal.context_key, normal.move_type_key), ('attack', 'tactical'))
        defensive = assign_taxonomy('material_sacrifice', strategic_sacrifice=True)
        self.assertEqual((defensive.context_key, defensive.move_type_key), ('defend', 'strategic'))
        self.assertEqual(defensive.serialize()['levels'][-1]['key'], 'material_sacrifice')

    def test_defense_without_verified_investment_does_not_invent_strategy(self):
        defense = assign_taxonomy('material_sacrifice', is_in_check=True)
        self.assertEqual(defense.move_type_key, 'tactical')


if __name__ == '__main__':
    unittest.main()
