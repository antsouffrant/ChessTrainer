"""Perf metadata and safe replay-cache contracts; no engine dependency."""
import ast
import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_function(module, name, env):
    parsed = ast.parse((ROOT / module).read_text(encoding='utf-8'))
    fn = next(item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name == name)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), module, 'exec'), env)
    return env[name]


class PerformanceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {'json': json, 'hashlib': hashlib, 'PROACTIVE_VERSION': 1}
        cls.key = staticmethod(load_function('coaching/board_context/proactive_coaching.py', 'coaching_probe_cache_key', env))
        env['decode_probes'] = load_function('coaching/board_context/proactive_coaching.py', 'decode_probes', env)
        cls.cached = staticmethod(load_function('coaching/board_context/proactive_coaching.py', 'reusable_coaching_probe', env))

    def setUp(self):
        self.row = {'fen': 'root', 'best_move_uci': 'e2e4', 'played_move_uci': 'd2d4',
                    'eval_before_cp': 44, 'eval_after_cp': -106,
                    'alternative_pvs_json': '[]', 'proactive_coach_json': None}
        self.settings = {'coaching_probe_seconds': 1.2, 'coaching_probe_variations': 2,
                         'coaching_probe_depth': 14, 'analysis_engine_threads': 2,
                         'analysis_engine_hash_mb': 128}

    def test_reuses_exact_inputs_only(self):
        signature = self.key(self.row, self.settings, 'Stockfish 17')
        self.row['proactive_coach_json'] = json.dumps({'version': 1, 'branches': [],
                                                     'cache_key': signature})
        self.assertIsNotNone(self.cached(self.row, self.settings, 'Stockfish 17'))
        self.assertIsNone(self.cached(self.row, self.settings, 'Stockfish 18'))
        self.assertIsNone(self.cached(self.row, {**self.settings, 'coaching_probe_seconds': 2}, 'Stockfish 17'))
        self.assertIsNone(self.cached({**self.row, 'best_move_uci': 'g1f3'}, self.settings, 'Stockfish 17'))
        self.assertIsNone(self.cached({**self.row, 'eval_after_cp': -800}, self.settings, 'Stockfish 17'))
        self.assertIsNone(self.cached({**self.row, 'alternative_pvs_json': '[{}]'}, self.settings, 'Stockfish 17'))

    def test_unversioned_or_incomplete_legacy_probe_is_recomputed(self):
        self.row['proactive_coach_json'] = '{"version": 1, "branches": []}'
        self.assertIsNone(self.cached(self.row, self.settings, 'Stockfish 17'))
        self.row['proactive_coach_json'] = 'garbage'
        self.assertIsNone(self.cached(self.row, self.settings, 'Stockfish 17'))

    def test_both_stage_timing_columns_exist_for_new_database(self):
        parsed = ast.parse((ROOT / 'db.py').read_text(encoding='utf-8'))
        schema = ast.literal_eval(next(stmt.value for stmt in parsed.body
             if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in stmt.targets)))
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript(schema)
        for name in ('analysis_jobs', 'metadata_processes'):
            cols = {row[1] for row in conn.execute(f'PRAGMA table_info({name})')}
            self.assertIn('perf_json', cols)

    def test_refresh_caches_pgn_across_small_batches(self):
        source = (ROOT / 'coaching/coaching_refresh/metadata_refresh.py').read_text(encoding='utf-8')
        self.assertIn('game_cache=None', source)
        self.assertIn('cache.move_to_end(game_key)', source)
        self.assertIn('cache.popitem(last=False)', source)
        self.assertIn('classify_pgn(pgn, game=game)', source)


if __name__ == '__main__':
    unittest.main()
