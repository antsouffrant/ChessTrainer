"""Architectural compatibility checks: no engine or Flask required."""
import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
STAGES={
 'board_context': ['pv_outcomes','pv_reasoning','check_repetition','check_response',
      'position_context','explanatory_evidence','discovered_counterfactuals',
      'legal_counterfactuals','loose_piece_provenance','endgame_evidence',
      'proactive_coaching','decision_evidence','presolve_prompt'],
 'conceptual_understanding':['decision_context','branch_diagnostics','critical_moments',
      'continuation_refutations','causal_consequences','semantic_coaching',
      'immediate_decision','root_explanation','decision_comparator'],
 'motif_selection':['motif_relevance','motif_hierarchy','coaching_taxonomy',
      'causal_selection','explanation_selector'],
 'narrative_composition':['narrative_editor','coaching_language','coaching',
      'continuation_coach','coach_session_recap','adaptive_coach',
      'coach_reasoner','coach_learning','pedagogical_narrative','decision_pipeline'],
 'coaching_validation':['narrative_validator'],
 'coaching_refresh':['coaching_cache','coaching_copy_refresh','metadata_refresh','version'],
}

class SixStageArchitecture(unittest.TestCase):
    def test_single_canonical_implementation_and_no_legacy_alias(self):
        for stage, names in STAGES.items():
            package=ROOT/'coaching'/stage
            self.assertTrue((package/'__init__.py').exists(),stage)
            for name in names:
                src=package/(name+'.py')
                compat=ROOT/(name+'.py')
                self.assertTrue(src.exists(),str(src))
                self.assertFalse(compat.exists(),str(compat))
                ast.parse(src.read_text(encoding='utf8'))

    def test_public_interfaces_and_identity_validator(self):
        from coaching import STAGES as stages
        self.assertEqual(tuple(STAGES),stages)
        from coaching.coaching_validation import validate_evidence,validate_message_identity
        ev=SimpleNamespace(legal=True,root_uci='e2e4',continuation_uci=('e2e4','e7e5'),truncated=False)
        self.assertTrue(validate_evidence(ev,expected_root_uci='e2e4').valid)
        self.assertIn('wrong_root',validate_evidence(ev,expected_root_uci='d2d4').problems)
        ev.truncated=True
        self.assertIn('truncated_pv',validate_evidence(ev).problems)
        good=validate_message_identity(expected_position_id=12,actual_position_id=12,
                 expected_root_uci='e2e4',actual_root_uci='e2e4',
                 expected_version='v34',actual_version='v34')
        self.assertTrue(good.valid)
        bad=validate_message_identity(expected_position_id=12,actual_position_id=7,
                 expected_root_uci='e2e4',actual_root_uci='d2d4',
                 expected_version='v34',actual_version='v33')
        self.assertEqual(set(bad.problems),{'wrong_position','wrong_root','wrong_model_version'})

    def test_all_python_imports_use_canonical_packages(self):
        legacy = {n for names in STAGES.values() for n in names} - {'coaching'}
        # 'coaching' is now the public package, not an obsolete root-level module.
        for source in ROOT.rglob('*.py'):
            tree = ast.parse(source.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        self.assertNotIn(item.name, legacy, (source,node.lineno))
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn(node.module, legacy, (source,node.lineno))

    def test_v35_public_version_and_app_uses_stage_boundaries(self):
        coaching=(ROOT/'coaching/narrative_composition/coaching.py').read_text()
        version=(ROOT/'coaching/coaching_refresh/version.py').read_text()
        self.assertIn("COACHING_VERSION = 'rules-v35-decision-findings'",version)
        self.assertIn('from coaching.coaching_refresh.version import COACHING_VERSION',coaching)
        app=(ROOT/'app.py').read_text()
        self.assertIn('from coaching.narrative_composition import explain_position',app)
        self.assertIn('from coaching.coaching_refresh import refresh_batch',app)
        self.assertIn('from coaching.coaching_refresh import clear_cache',app)

if __name__=='__main__':unittest.main()
