"""Data-informed, engine-free contracts for v84 calibration and UI sizing."""
import unittest
from pathlib import Path
from dataclasses import dataclass
from coaching.motif_selection.coaching_taxonomy import normalize_learning_labels, TAXONOMY_VERSION

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Label:
    key: str
    confidence: float
    evidence: str = 'Saved and verified variation'
    is_primary: bool = False

ROW = {'category':'blundered_into_loss', 'eval_before_cp':0, 'eval_after_cp':-450,
       'mate_before':None, 'mate_after':None}

class V84Calibration(unittest.TestCase):
    def test_verified_non_capture_king_evasion_precedes_other_line_geometry(self):
        # User corrections 3392, 3453: move is Kg8/Kh2, not a fork by the king.
        got = normalize_learning_labels([Label('fork', .98, is_primary=True)], ROW,
                         is_in_check=True, best_is_king_evasion=True)
        self.assertEqual(got[0].key, 'king_safety')
        self.assertEqual(len([x for x in got if x.is_primary]), 1)
        self.assertIn('evasion', got[0].evidence)

    def test_no_evasion_without_both_verified_conditions(self):
        for check, evasion in [(False,False),(False,True),(True,False)]:
            got = normalize_learning_labels([Label('fork', .98, is_primary=True)], ROW,
                                is_in_check=check, best_is_king_evasion=evasion)
            self.assertEqual(got[0].key, 'fork')

    def test_mate_defense_and_endgame_king_activity_remain_specific(self):
        for motif in ('mate_defense','king_activity'):
            got = normalize_learning_labels([Label(motif,.85,is_primary=True)], ROW,
                                     is_in_check=True, best_is_king_evasion=True)
            self.assertEqual(got[0].key,motif)

    def test_taxonomy_is_new_version_and_old_data_is_not_mutated(self):
        self.assertTrue(TAXONOMY_VERSION.startswith('3.2-'))
        source = (ROOT/'analysis.py').read_text()
        self.assertIn('is_in_check=board.is_check()',source)
        self.assertIn('best_is_king_evasion=king_evasion',source)
        self.assertIn("not board.is_capture(best)",source)

    def test_immediate_check_precedes_secondary_open_file(self):
        source = (ROOT/'coaching/conceptual_understanding/root_explanation.py').read_text()
        self.assertLess(source.index('    if mover and after.is_check():'),
                        source.index('    if mover and mover.piece_type == chess.ROOK:'))
        self.assertIn("'kind': 'check'",source)
        captures = (ROOT/'coaching/conceptual_understanding/semantic_coaching.py').read_text()
        self.assertIn('checking_capture = board.gives_check(best)',captures)
        self.assertIn('with check',captures)

    def test_solve_message_has_content_height_and_keeps_adaptive_width(self):
        css = (ROOT/'static/styles.css').read_text()
        tail = css[css.index('/* v84: solving explanation takes only the height'):]
        self.assertIn('display: block;',tail)
        self.assertIn('height: fit-content;',tail)
        self.assertIn('flex: 0 0 auto;',tail)
        self.assertIn('height: auto;',tail)
        self.assertIn('min-height: 0;',tail)
        self.assertIn('width: 88%; max-width: 88%',css)
        self.assertIn('background: none;',tail)

if __name__ == '__main__': unittest.main()

class RegressionReviewFixture(unittest.TestCase):
    def test_negative_feedback_fixture_remains_review_only(self):
        import json
        sample = json.loads((ROOT/'tests/fixtures/v30_feedback_review_v84.json').read_text())
        ids = [r['position_id'] for r in sample['cases']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertGreaterEqual(len(ids),25)
        self.assertEqual(sample['model'],'rules-v30-clean-taxonomy-outcomes')
        self.assertTrue(all(r['review_status']=='needs independent chess validation'
                            for r in sample['cases']))
        self.assertTrue(all(r['fen'] and r['best_pv'] and r['played_pv']
                            for r in sample['cases']))
        self.assertEqual(sum(len(r['explanation_feedback']) for r in sample['cases']),17)
        self.assertEqual(sum(r['suggested_motif'] is not None for r in sample['cases']),25)
