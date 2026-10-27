"""Regression: /api/processes must not use SQLite after exiting `with connect()`.

The production db._ClosingConnection closes on context exit (unlike vanilla
sqlite3.Connection). Run the actual route body against that behavior without
requiring Flask, Stockfish, or python-chess in isolated environments.
"""
import ast
from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _named_node(module_path, name):
    tree = ast.parse(module_path.read_text(encoding='utf-8'), filename=str(module_path))
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                and n.name == name)


def _schema():
    tree = ast.parse((ROOT / 'db.py').read_text(encoding='utf-8'))
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets))


class BenchmarkProcessConnectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'test.sqlite3'
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executescript(_schema())
            conn.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','tester')")
            conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,status) VALUES (1,'2026','rapid','complete')")
            conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,status) VALUES (1,'2025','blitz','complete')")
            conn.execute("INSERT INTO coach_benchmark_cohorts(job_id,source_count,sample_size) VALUES (1,10,0)")
            conn.commit()

        # Load the *actual* connection-closing class used by the app.
        cls = _named_node(ROOT / 'db.py', '_ClosingConnection')
        namespace = {'sqlite3': sqlite3}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(ROOT / 'db.py'), 'exec'), namespace)
        closing_class = namespace['_ClosingConnection']
        self.opens = []

        def connect(timeout=0.5):
            con = sqlite3.connect(self.path, factory=closing_class, timeout=timeout)
            con.row_factory = sqlite3.Row
            self.opens.append(con)
            return con

        # Extract and execute the original decorated Flask handler, stripping
        # only its route decorator. This catches accidental indentation drift.
        fn = _named_node(ROOT / 'app.py', 'process_listing')
        fn.decorator_list = []
        from coach_benchmark import benchmark_status
        ns = {'connect': connect, 'benchmark_status': benchmark_status,
              'jsonify': lambda payload: payload, 'sqlite3': sqlite3}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / 'app.py'), 'exec'), ns)
        self.handler = ns['process_listing']

    def test_process_listing_reads_benchmark_while_connection_is_open(self):
        result = self.handler()
        self.assertEqual(len(self.opens), 1)
        rows = result['processes']
        self.assertEqual([r['id'] for r in rows], [2, 1])
        self.assertIsNone(rows[0]['benchmark'])
        self.assertEqual(rows[1]['benchmark']['source_count'], 10)
        self.assertEqual(rows[1]['benchmark']['size'], 0)
        # The connection must still close after all benchmark work finishes.
        with self.assertRaises(sqlite3.ProgrammingError):
            self.opens[0].execute('SELECT 1')

    def test_empty_process_list_is_safe(self):
        with closing(sqlite3.connect(self.path)) as con:
            con.execute('DELETE FROM coach_benchmark_cohorts')
            con.execute('DELETE FROM analysis_jobs')
            con.commit()
        self.assertEqual(self.handler()['processes'], [])


if __name__ == '__main__':
    unittest.main()

# Note: Tests added after the __main__ guard also run under unittest discovery.
class SolvedPositionConnectionTests(BenchmarkProcessConnectionTests):
    def setUp(self):
        super().setUp()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("""INSERT INTO training_positions
              (job_id,category,fen,user_color,move_number,best_move_uci,learned)
              VALUES (1,'correct','4k3/8/8/8/8/8/8/4K3 w - - 0 1', 'white',12,'e1f1',1)""")
            con.commit()
        fn = _named_node(ROOT / 'app.py', 'position_solution')
        fn.decorator_list = []
        actual_connect = self.handler.__globals__['connect']

        def assert_open_then_read(conn, ids):
            # If the route leaves the connection context before building
            # taxonomy, this query raises the production ProgrammingError.
            conn.execute('SELECT COUNT(*) FROM position_motif_taxonomy').fetchone()
            return {1: {'motif_key':'king_safety'}}

        scope = {'connect': actual_connect,
                 'jsonify': lambda payload: payload,
                 '_enrich_saved_variations': lambda position_id: None,
                 '_position_concepts': lambda conn, ids: {},
                 '_position_taxonomies': assert_open_then_read}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / 'app.py'), 'exec'), scope)
        self.solution_handler = scope['position_solution']

    def test_solved_position_taxonomy_reads_before_connection_closes(self):
        response = self.solution_handler(1)
        self.assertEqual(response['taxonomy']['motif_key'], 'king_safety')
        self.assertEqual(response['best_move_uci'], 'e1f1')
        self.assertEqual(len(self.opens), 2)
        for conn in self.opens:
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute('SELECT 1')
