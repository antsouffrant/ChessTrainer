"""Pure evidence ranking tests, runnable without python-chess."""
from dataclasses import dataclass
import unittest
from coaching.motif_selection.motif_relevance import select_relevant_primary


@dataclass
class Label:
    key: str
    confidence: float = .9


class RelevanceTests(unittest.TestCase):
    def test_shared_discovery_not_primary(self):
        context = {'response_motifs': ['discovered_attack'],
                   'discovered_unique_lines': [], 'discovered_reply_checks': []}
        primary, _ = select_relevant_primary([Label('discovered_attack')], context,
                                             original_choice='discovered_attack')
        self.assertEqual(primary, 'calculation')

    def test_forcing_discovered_check_is_relevant(self):
        context = {'response_motifs': ['discovered_attack'],
                   'discovered_unique_lines': [{'kind': 'discovered_check'}],
                   'discovered_reply_checks': []}
        primary, _ = select_relevant_primary([Label('discovered_attack')], context)
        self.assertEqual(primary, 'discovered_attack')

    def test_quiet_discovery_without_counterfactual_is_only_background(self):
        context = {'response_motifs': ['discovered_attack'],
                   'discovered_unique_lines': [{'kind': 'discovered_attack'}],
                   'discovered_reply_checks': []}
        primary, _ = select_relevant_primary([Label('discovered_attack')], context)
        self.assertEqual(primary, 'calculation')

    def test_verified_legal_reply_supports_quiet_discovery(self):
        context = {'response_motifs': ['discovered_attack'],
                   'discovered_unique_lines': [{'kind': 'discovered_attack'}],
                   'discovered_reply_checks': [{'kind': 'legal_capture_allows_followup'}]}
        primary, _ = select_relevant_primary([Label('discovered_attack')], context)
        self.assertEqual(primary, 'discovered_attack')


if __name__ == '__main__':
    unittest.main()
