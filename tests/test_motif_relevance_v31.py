"""Pure relevance tests; do not require Stockfish or python-chess."""
import unittest
from types import SimpleNamespace
from motif_relevance import select_relevant_primary


def label(key, confidence=0.85):
    return SimpleNamespace(key=key, confidence=confidence)


class RelevanceTests(unittest.TestCase):
    def test_context_only_pin_cannot_own_lesson(self):
        context = {'context_motifs': ['pin'], 'prompt_motifs': ['pin'],
                   'response_motifs': [], 'pin_capture_refutations': []}
        chosen, scores = select_relevant_primary(
            [label('pin'), label('calculation')], context, original_choice='pin')
        self.assertEqual(chosen, 'calculation')
        self.assertNotIn('pin', scores)

    def test_verified_pin_in_context_and_response_beats_incidental_activity(self):
        context = {'context_motifs': ['pin'], 'prompt_motifs': ['pin'],
                   'response_motifs': ['pin', 'piece_activity'],
                   'pin_capture_refutations': [{'attempted_move': 'e7d7'}]}
        chosen, scores = select_relevant_primary(
            [label('pin'), label('piece_activity')], context,
            original_choice='piece_activity', immediate_choice='piece_activity')
        self.assertEqual(chosen, 'pin')
        self.assertGreater(scores['pin'], scores['piece_activity'])

    def test_distant_pv_motif_does_not_own_current_lesson(self):
        context = {'context_motifs': [], 'prompt_motifs': ['threat_awareness'],
                   'response_motifs': ['defensive_resource'],
                   'best_neutralizes': [1], 'played_ignores': [1]}
        chosen, scores = select_relevant_primary(
            [label('defensive_resource'), label('fork')], context,
            original_choice='fork', pv_choice='fork', pv_ply=9)
        self.assertEqual(chosen, 'defensive_resource')
        self.assertNotIn('fork', scores)

    def test_near_root_fork_can_be_primary(self):
        chosen, _ = select_relevant_primary(
            [label('fork'), label('calculation')],
            {'response_motifs': ['fork']}, immediate_choice='fork',
            pv_choice='fork', pv_ply=3)
        self.assertEqual(chosen, 'fork')

    def test_unrelated_geometry_does_not_beat_legal_missed_defense(self):
        context = {'prompt_motifs': ['loose_piece_awareness'],
                   'response_motifs': ['loose_piece_awareness'],
                   'played_ignores': [10], 'best_neutralizes': [10]}
        chosen, _ = select_relevant_primary(
            [label('loose_piece_awareness'), label('piece_activity')], context,
            original_choice='piece_activity', immediate_choice='piece_activity')
        self.assertEqual(chosen, 'loose_piece_awareness')

    def test_verified_forced_mate_takes_priority(self):
        chosen, _ = select_relevant_primary(
            [label('mating_net'), label('pin')],
            {'response_motifs': ['pin']}, forced_choice='mating_net',
            immediate_choice='pin')
        self.assertEqual(chosen, 'mating_net')


if __name__ == '__main__':
    unittest.main()
