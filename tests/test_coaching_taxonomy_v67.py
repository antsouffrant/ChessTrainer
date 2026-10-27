"""Regression checks for canonical taxonomy, flexible evidence, WDL fallback."""
from __future__ import annotations

import ast
import sqlite3
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coaching.motif_selection.coaching_taxonomy import (
    canonical_motif_key, normalize_learning_labels, evaluation_outcome_key,
    assign_taxonomy, save_taxonomy, EVALUATION_OUTCOMES, CANONICAL_KEYS,
    RETIRED_KEYS, TAXONOMY_VERSION,
)

@dataclass
class Label:
    key: str
    confidence: float
    evidence: str = 'Legal, saved and evaluated continuation'
    is_primary: bool = False

ROW = {'category': 'mistake', 'eval_before_cp': 520, 'eval_after_cp': -420,
       'mate_before': None, 'mate_after': None}

class CanonicalTaxonomyTests(unittest.TestCase):
    def test_all_legacy_keys_map_to_canonical_or_evaluation_fallback(self):
        for key in RETIRED_KEYS:
            mapped = canonical_motif_key(key)
            self.assertTrue(mapped is None or mapped in CANONICAL_KEYS, key)
        self.assertEqual(canonical_motif_key('exchange_sacrifice'), 'material_sacrifice')
        self.assertEqual(canonical_motif_key('piece_development'), 'piece_activity')
        self.assertEqual(canonical_motif_key('back_rank_mate'), 'mating_net')

    def test_context_never_repeats_as_motif(self):
        for key in CANONICAL_KEYS:
            path = assign_taxonomy(key).serialize()
            self.assertNotEqual(path['levels'][0]['name'].lower(), path['levels'][-1]['name'].lower())
            self.assertIn(len(path['levels']), (2, 3))
        self.assertIsNone(canonical_motif_key('defensive_resource'))

    def test_evaluation_fallback_when_retired_generic_only(self):
        result = normalize_learning_labels([Label('defensive_resource', .97, is_primary=True)], ROW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].key, 'evaluation_win_to_loss')
        self.assertEqual(result[0].confidence, .55)
        path = assign_taxonomy(result[0].key).serialize()
        self.assertEqual([x['name'] for x in path['levels']],
                         ['Defensive Resources', 'Winning to Losing Position'])

    def test_flexible_global_tactical_search_escapes_wrong_context(self):
        result = normalize_learning_labels([
            Label('defensive_resource', .92, is_primary=True),
            Label('skewer', .84), Label('pawn_structure', .79),
        ], ROW)
        self.assertEqual(result[0].key, 'skewer')
        self.assertTrue(result[0].is_primary)
        self.assertEqual(assign_taxonomy(result[0].key).move_type_key, 'tactical')

    def test_global_general_search_can_choose_attack_under_defensive_fallback(self):
        result = normalize_learning_labels([
            Label('defensive_resource', .98, is_primary=True),
            Label('capture_loose_piece', .83),
        ], ROW)
        self.assertEqual(result[0].key, 'capture_loose_piece')
        self.assertEqual(assign_taxonomy(result[0].key).context_key, 'attack')

    def test_preserves_specific_primary_even_if_other_feature_is_confident(self):
        result = normalize_learning_labels([
            Label('capture_loose_piece', .84, is_primary=True),
            Label('skewer', .92),
        ], ROW)
        self.assertEqual(result[0].key, 'capture_loose_piece')
        self.assertEqual(sum(bool(i.is_primary) for i in result), 1)

    def test_retired_references_merge_with_canonical_without_duplicates(self):
        result = normalize_learning_labels([
            Label('exchange_sacrifice', .89, is_primary=True),
            Label('material_sacrifice', .86), Label('exchange', .78),
        ], ROW)
        self.assertEqual([x.key for x in result], ['material_sacrifice','simplification'])
        self.assertEqual(sum(bool(i.is_primary) for i in result), 1)

    def test_evaluation_fallback_does_not_invent_winning_opportunity(self):
        row = dict(ROW, eval_before_cp=30, eval_after_cp=-45)
        self.assertEqual(evaluation_outcome_key(row), 'evaluation_change')
        self.assertEqual(evaluation_outcome_key(ROW), 'evaluation_win_to_loss')
        self.assertEqual(evaluation_outcome_key(dict(ROW, eval_after_cp=0)), 'evaluation_win_to_draw')

    def test_schema_can_store_legacy_and_new_without_data_loss(self):
        tree = ast.parse((ROOT/'db.py').read_text())
        schema = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(x, ast.Name) and x.id == 'SCHEMA' for x in node.targets))
        conn = sqlite3.connect(':memory:'); conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.create_function('board_identity',1,lambda fen: ' '.join(fen.split()[:4]),deterministic=True)
        conn.executescript(schema)
        conn.execute("INSERT INTO accounts(id,provider,username) VALUES (1,'lichess','tester')")
        conn.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types) VALUES (1,1,'all','rapid')")
        for key in ('defensive_resource', 'evaluation_win_to_loss', 'skewer'):
            conn.execute('INSERT INTO learning_concepts(key,name,family,description) VALUES(?,?,?,?)',
                         (key, EVALUATION_OUTCOMES.get(key,key),'General','Test'))
        conn.execute("INSERT INTO training_positions(id,job_id,category,fen,user_color,move_number,best_move_uci) VALUES (4,1,'mistake','test fen','white',8,'a2a3')")
        conn.execute("INSERT INTO position_concepts(position_id,concept_key,confidence,is_primary,classifier_version) VALUES (4,'defensive_resource',.9,1,'legacy')")
        new = save_taxonomy(conn,4,ROW,'evaluation_win_to_loss')
        self.assertEqual(new.motif_key,'evaluation_win_to_loss')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM position_concepts').fetchone()[0],1)
        self.assertEqual(conn.execute('SELECT taxonomy_version FROM position_motif_taxonomy').fetchone()[0],TAXONOMY_VERSION)
        conn.close()

if __name__ == '__main__': unittest.main()
