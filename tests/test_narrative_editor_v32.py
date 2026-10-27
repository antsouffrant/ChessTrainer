"""Pure language tests, no chess engine or python-chess dependency."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coaching.narrative_composition.narrative_editor import mate_explanation, polish_comparison, concise


class NaturalChessNarrationTests(unittest.TestCase):
    def test_mate_mentioned_once_no_engine_or_motif_meta(self):
        text = mate_explanation('Bb8', 'Nf6', mate_in=6, final_move='Rh8#', verified=True)
        self.assertIn('Bb8', text)
        self.assertIn('Rh8#', text)
        self.assertIn('Nf6', text)
        self.assertEqual(text.lower().count('mate'), 1)
        for forbidden in ('decisive lesson', 'secondary', 'at the saved analysis depth',
                          'best analyzed continuation', 'along the way'):
            self.assertNotIn(forbidden, text.lower())

    def test_unverified_line_is_not_called_forced(self):
        text = mate_explanation('Bb8', 'Nf6', final_move='Rh8#')
        self.assertNotIn('force', text)
        self.assertIn('analyzed line', text)

    def test_mate_defense(self):
        text = mate_explanation('Kg1', 'Kh2', threatened_mate=True)
        self.assertIn('stops the mating attack', text)
        self.assertIn('In the game, Kh2', text)
        self.assertNotIn('motif', text)

    def test_two_captures_one_target_has_specific_contrast(self):
        original = ('Bxb5 and Rxb5 both capture the opponent’s pawn on b5, but '
                    'Bxb5 keeps your pawn on e3 protected. '
                    'In the game, Rxb5 leaves that pawn hanging.')
        result = polish_comparison(original, best='Bxb5', played='Rxb5')
        self.assertIn('both bxb5', result.lower())
        self.assertIn('e3', result)
        self.assertIn('hanging', result)
        self.assertNotIn('game continuation', result)

    def test_edit_removes_analysis_provenance(self):
        result = polish_comparison(
            'The key payoff comes later: Nxf7 creates a double attack in the analyzed continuation.',
            best='Nd6+', played='Ng3')
        self.assertIn('Nxf7', result)
        self.assertNotIn('analyzed continuation', result)
        self.assertNotIn('key payoff comes later', result)

    def test_no_duplicate_mate_claims_from_separate_sources(self):
        result = concise(['Bb8 forces mate in 6, finishing with Rh8#.',
                          'The best analyzed continuation ends in checkmate with Rh8#.',
                          'The rook on e7 cannot capture the bishop because it is pinned.'])
        self.assertNotIn('best analyzed', result)
        self.assertIn('pinned', result)

if __name__ == '__main__':
    unittest.main()
