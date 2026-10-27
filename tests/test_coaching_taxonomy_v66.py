"""Regression contracts for the context -> optional qualifier -> primary path.

No python-chess or Flask dependency: validates semantic placement, model scope,
SQL persistence and backward-compatible primary lesson identity.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coaching.motif_selection.coaching_taxonomy import (
    ATTACK_GENERAL, DEFEND_GENERAL, TACTICAL, STRATEGIC,
    CONTEXTS, MOVE_TYPES, TAXONOMY_VERSION, assign_taxonomy, save_taxonomy,
    validate_taxonomy, CANONICAL_KEYS, RETIRED_KEYS, evaluation_outcome_key, canonical_motif_key,
)


class TaxonomyTests(unittest.TestCase):
    def test_all_context_and_move_type_keys_valid(self):
        self.assertEqual(set(CONTEXTS), {'attack', 'defend'})
        self.assertEqual(set(MOVE_TYPES), {'tactical', 'strategic'})
        self.assertTrue(validate_taxonomy(CANONICAL_KEYS | RETIRED_KEYS))
        with self.assertRaises(ValueError):
            validate_taxonomy({'fork'})

    def test_general_attack_has_exactly_two_levels(self):
        path = assign_taxonomy('capture_loose_piece', confidence=.93)
        self.assertEqual(path.context_key, 'attack')
        self.assertIsNone(path.move_type_key)
        self.assertEqual([n['level'] for n in path.serialize()['levels']], ['context', 'motif'])

    def test_general_defense_has_exactly_two_levels(self):
        path = assign_taxonomy('loose_piece_awareness', confidence=.91)
        self.assertEqual([n['name'] for n in path.serialize()['levels']],
                         ['Defensive Resources', 'Loose Piece Awareness'])
        self.assertIsNone(path.move_type_key)

    def test_forcing_move_scan_does_not_invent_specific_tactic(self):
        self.assertIsNone(canonical_motif_key('calculation'))
        self.assertEqual(canonical_motif_key('exchange'), 'simplification')
        self.assertEqual(assign_taxonomy('exchange').move_type_key, 'strategic')

    def test_specific_tactical_motif_in_attack_and_defense(self):
        attack = assign_taxonomy('fork', root_best_is_check=True)
        defense = assign_taxonomy('fork', is_in_check=True)
        self.assertEqual(attack.context_key, 'attack')
        self.assertEqual(defense.context_key, 'defend')
        for item in (attack, defense):
            self.assertEqual(item.move_type_key, 'tactical')
            self.assertEqual(len(item.serialize()['levels']), 3)
            self.assertEqual(item.serialize()['levels'][-1]['key'], 'fork')

    def test_verified_material_save_can_qualify_strategic_exchange(self):
        attack = assign_taxonomy('simplification')
        defense = assign_taxonomy('simplification', best_move_saves_material=True)
        self.assertEqual(attack.context_key, 'attack')
        self.assertEqual(defense.context_key, 'defend')
        self.assertEqual(defense.move_type_key, 'strategic')

    def test_existing_specific_concepts_never_replaced_by_taxonomy(self):
        for key in ('material_sacrifice', 'removal_of_defender',
                    'mating_net', 'passed_pawn', 'king_activity',
                    'opposition_zugzwang', 'pawn_structure'):
            self.assertEqual(assign_taxonomy(key).motif_key, key)

    def test_context_and_subtype_stay_independent_of_learning_mode(self):
        for mode in ('mistakes','blunders','excellent','brilliant','opposition'):
            path = assign_taxonomy('deflection', learning_mode=mode)
            self.assertEqual(path.motif_key, 'deflection')
            self.assertEqual(path.move_type_key, 'tactical')
            self.assertEqual(len(path.serialize()['levels']), 3)

    def test_database_schema_and_upsert_are_compatible(self):
        tree = ast.parse((ROOT/'db.py').read_text())
        schema = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == 'SCHEMA'
                              for target in node.targets))
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.create_function('board_identity', 1, lambda fen: ' '.join(fen.split()[:4]), deterministic=True)
        conn.executescript(schema)
        # Keep the actual schema and foreign keys: deleting a training position
        # must also delete its context path without touching another game list.
        conn.execute("INSERT INTO accounts(id, provider, username) VALUES(1, 'lichess', 'tester')")
        conn.execute("INSERT INTO analysis_jobs(id, account_id, date_range, game_types) VALUES(1, 1, 'all', 'rapid')")
        conn.execute("INSERT INTO learning_concepts(key, name, family, description, priority) VALUES('fork','Double Attack','Tactics','Two threats',95)")
        conn.execute("""INSERT INTO training_positions
            (id, job_id, category, fen, user_color, move_number, best_move_uci)
            VALUES(3,1,'missed_checkmate','test FEN','white',12,'f3f7')""")
        row = {'category':'missed_checkmate', 'learning_mode':'mistakes'}
        path = save_taxonomy(conn, 3, row, 'fork', confidence=.9)
        self.assertEqual(path.context_key, 'attack')
        self.assertEqual(conn.execute('SELECT motif_key FROM position_motif_taxonomy WHERE position_id=3').fetchone()[0], 'fork')
        # Replacing an assignment does not erase the position, lesson identity,
        # previous learning activity, or any other position's taxonomy.
        row['category'] = 'allowed_checkmate'
        path = save_taxonomy(conn, 3, row, 'fork', confidence=.81)
        self.assertEqual(path.context_key, 'defend')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM position_motif_taxonomy').fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            save_taxonomy(conn, 555, row, 'fork')
        conn.execute('DELETE FROM training_positions WHERE id=3')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM position_motif_taxonomy').fetchone()[0], 0)
        conn.close()


if __name__ == '__main__':
    unittest.main()
