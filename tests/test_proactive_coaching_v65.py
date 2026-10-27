"""Proactive coach contracts and fake-engine regression tests (v65)."""
import ast
import json
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extract_function(filename, name, env):
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    node = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), env)
    return env[name]


class SafeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.decode = staticmethod(extract_function('coaching/board_context/proactive_coaching.py', 'decode_probes', {'json': json, 'PROACTIVE_VERSION': 1}))
        cls.explain = staticmethod(extract_function('coaching/board_context/proactive_coaching.py', 'trusted_probe_explanation',
                                       {'decode_probes': cls.decode}))

    def test_versioned_probe_rejects_stale_or_malformed(self):
        self.assertIsNone(self.decode('{bad'))
        self.assertIsNone(self.decode({'version': 0, 'branches': []}))
        self.assertIsNone(self.decode({'version': 1, 'branches': None}))
        self.assertEqual(self.decode('{"version":1,"branches":[]}')['version'], 1)

    def test_probed_tactic_only_displaces_a_generic_description(self):
        class Board:
            def fen(self):
                return 'board-1'
        class Move:
            def __init__(self, uci):
                self._uci = uci
            def uci(self):
                return self._uci
        best, played = Move('e2e4'), Move('d2d4')
        data = {'version': 1, 'root_fen': 'board-1',
                'selection': {'kind': 'demonstrated_refutation',
                              'role': 'played', 'motif': 'fork',
                              'text': 'A response exposes a double attack.'},
                'branches': [{'role': 'best', 'root_uci': best.uci()},
                             {'role': 'played', 'root_uci': played.uci()}]}
        self.assertEqual(self.explain(Board(), best, played, data, 'e4 simplifies the position.'),
                         'A response exposes a double attack.')
        self.assertIsNone(self.explain(Board(), best, played, data,
                                        'e4 wins a free rook on a8.'))
        self.assertIsNone(self.explain(Board(), best, played,
                                       {**data, 'root_fen': 'other'}, 'e4 simplifies.'))
        self.assertIsNone(self.explain(Board(), best, played,
                                       {**data, 'branches': data['branches'][:1]},
                                       'e4 simplifies.'))

    def test_engine_evidence_only_changes_broad_primary_motifs(self):
        from types import ModuleType, SimpleNamespace
        from unittest.mock import patch
        import sys
        learning = ModuleType('learning')
        learning.CONCEPTS = {'fork': {}, 'simplification': {}, 'capture_loose_piece': {}}
        learning.LearningLabel = lambda key, conf, evidence: SimpleNamespace(
            key=key, confidence=conf, evidence=evidence, is_primary=False)
        hierarchy = ModuleType('motif_hierarchy')
        hierarchy.BROAD_FALLBACKS = frozenset({'simplification'})
        hierarchy.ancestors = lambda key: frozenset({'simplification'}) if key == 'fork' else frozenset()
        refine = extract_function('coaching/board_context/proactive_coaching.py', 'prefer_evidenced_primary',
                                  {'decode_probes': self.decode})
        class Board:
            def fen(self):
                return 'board'
        finding = {'version': 1, 'root_fen': 'board', 'branches': [],
                   'selection': {'kind':'demonstrated_refutation', 'motif':'fork',
                                 'text':'A verified fork in a short line.'}}
        with patch.dict(sys.modules, {'learning':learning, 'coaching.motif_selection.motif_hierarchy':hierarchy}):
            broad = [SimpleNamespace(key='simplification', is_primary=True)]
            result = refine(Board(), broad, finding)
            self.assertEqual(next(x.key for x in result if x.is_primary), 'fork')
            specific = [SimpleNamespace(key='capture_loose_piece', is_primary=True)]
            self.assertEqual(refine(Board(), specific, finding)[0].key, 'capture_loose_piece')
            self.assertTrue(specific[0].is_primary)
            self.assertEqual(len(refine(Board(), specific, {**finding,'root_fen':'elsewhere'})), 1)

    def test_coach_export_includes_stored_independent_stockfish_probes(self):
        import feedback_analytics as feedback
        tree = ast.parse((ROOT / 'db.py').read_text(encoding='utf-8'))
        schema = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets)))
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.executescript(schema)
        conn.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','test')")
        conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES (1,'today','[]')")
        snapshot = json.dumps({'version':1,'branches':[{'role':'best','lines':[]}]})
        conn.execute("""INSERT INTO training_positions(job_id,category,fen,user_color,move_number,
            best_move_uci,played_move_uci,learned,proactive_coach_json)
            VALUES (1,'mistake','fen','white',4,'e2e4','d2d4',1,?)""", (snapshot,))
        conn.execute("""INSERT INTO position_feedback(position_id,account_id,category,rating)
            VALUES (1,1,'explanation',-1)""")
        results = feedback.report_rows(conn)
        self.assertEqual(len(results),1)
        self.assertEqual(results[0]['proactive_coach_json'], snapshot)
        exported = feedback.csv_bytes(results).decode('utf-8-sig')
        self.assertIn('proactive_coach_json', exported.splitlines()[0])
        self.assertIn('version', exported)

    def test_database_new_column_and_existing_history_unchanged(self):
        tree = ast.parse((ROOT / 'db.py').read_text(encoding='utf-8'))
        schema = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets)))
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.executescript(schema)
        columns = {r[1] for r in conn.execute('PRAGMA table_info(training_positions)')}
        self.assertIn('proactive_coach_json', columns)
        self.assertIn('learned', columns)
        self.assertIn('coach_explanation', columns)
        self.assertIn('eval_before_cp', columns)

    def test_insert_and_copy_queries_match_values(self):
        import re
        source = (ROOT / 'analysis.py').read_text(encoding='utf-8')
        for pattern in (r'INSERT INTO training_positions \((.*?)\) VALUES \((.*?)\)',
                        r'INSERT OR IGNORE INTO training_positions \((.*?)\) VALUES \((.*?)\)'):
            for match in re.finditer(pattern, source, re.S):
                self.assertEqual(len(match.group(1).split(',')), match.group(2).count('?'))
        self.assertIn("candidate['proactive_probe']", source)
        self.assertIn('proactive_coach_json = ?', source)
        self.assertIn('coaching_probes=probes.get(position_id)',
                      (ROOT / 'coaching/coaching_refresh/metadata_refresh.py').read_text())

    def test_refresh_uses_stockfish_and_separate_transaction(self):
        source = (ROOT / 'app.py').read_text()
        fn = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                  and node.name == '_run_refresh_worker')
        body = ast.get_source_segment(source, fn)
        self.assertIn('find_stockfish(settings)', body)
        self.assertIn('probe_training_position(engine, row, settings)', body)
        self.assertLess(body.index('probe_training_position(engine, row, settings)'),
                        body.index('refresh_metadata_batch(conn, job_id'))
        self.assertIn('status', body)
        self.assertNotIn('run_analysis_job(', body)
        nav = (ROOT / 'templates/base.html').read_text()
        self.assertLess(nav.index('>Player</span>'), nav.index('>Coach</span>'))


try:
    import chess
    import chess.engine
    from coaching.board_context.proactive_coaching import probe_training_position
except ImportError:
    chess = None


@unittest.skipUnless(chess, 'python-chess required for engine-backed board tests')
class BoardProbeTests(unittest.TestCase):
    def test_engine_tests_actual_opponent_replies_without_changing_root_scores(self):
        class StubEngine:
            def __init__(self):
                self.fens = []
            def analyse(self, board, limit, multipv=2):
                self.fens.append(board.fen())
                # Current board is AFTER a white root move; legal black replies.
                first = chess.Move.from_uci('e7e5') if board.piece_at(chess.E4) else chess.Move.from_uci('d7d5')
                assert first in board.legal_moves
                return [{'pv':[first], 'score':chess.engine.PovScore(chess.engine.Cp(-30), chess.BLACK),
                         'depth':12}]
        engine = StubEngine()
        row = {'fen': chess.Board().fen(), 'best_move_uci':'e2e4',
               'played_move_uci':'d2d4', 'eval_before_cp':60,
               'eval_after_cp':-80, 'alternative_pvs_json':'[]'}
        data = probe_training_position(engine, row, {'coaching_probe_seconds':0.4,
                 'coaching_probe_variations':2,'coaching_probe_depth':12,'mate_score_cp':100000})
        self.assertEqual(data['version'], 1)
        self.assertEqual([b['role'] for b in data['branches']], ['best','played'])
        self.assertEqual(len(engine.fens), 2)
        self.assertTrue(all(fen != row['fen'] for fen in engine.fens))
        self.assertEqual(data['branches'][0]['lines'][0]['pv_uci'][:2], ['e2e4','e7e5'])
        self.assertEqual(data['branches'][1]['lines'][0]['pv_uci'][:2], ['d2d4','d7d5'])
        self.assertEqual(data['root_loss_cp'], 140)
        self.assertEqual(row['eval_before_cp'], 60)
        self.assertIsNone(data['selection'])


if __name__ == '__main__':
    unittest.main()
