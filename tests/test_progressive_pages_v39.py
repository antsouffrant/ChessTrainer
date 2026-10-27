"""Regressions for bounded first-page and exact async totals (no Flask/Stockfish required)."""
import ast
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def load_server_function(name, env):
    tree = ast.parse((PROJECT / 'app.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(PROJECT / 'app.py'), 'exec'), env)
    return env[name]


class ProgressivePageTests(unittest.TestCase):
    def test_first_page_matches_legacy_pagination_and_opening_counts(self):
        old_learning = sys.modules.get('learning')
        stub = types.ModuleType('learning')
        stub.CLASSIFIER_VERSION = 'test'
        stub.CONCEPT_CATALOG = []
        sys.modules['learning'] = stub
        try:
            spec = importlib.util.spec_from_file_location('db_v39_fixture', PROJECT / 'db.py')
            db = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(db)
            with tempfile.TemporaryDirectory() as dirname:
                db.DB_PATH = Path(dirname) / 'fixture.sqlite3'
                db.init_db()
                with db.connect() as conn:
                    conn.execute("INSERT INTO accounts (id,provider,username) VALUES (1,'test','player')")
                    conn.execute("INSERT INTO analysis_jobs (id,account_id,date_range,game_types) VALUES (1,1,'all','all')")
                    conn.execute("INSERT INTO learning_concepts (key,name,family,description,priority) VALUES ('fork','Fork','Tactics','Fork',2)")
                    for i in range(144):
                        # Every three games share a board: opening playlist
                        # should count only one trained position per board.
                        board_index = i // 3
                        # Tests SQL board identity regardless of counters; use
                        # distinct mock board strings for subsequent groups.
                        fen = f'{board_index} w KQ - {i} 1'
                        conn.execute('''INSERT INTO training_positions
                            (job_id,game_id,category,fen,user_color,move_number,best_move_uci,
                             opening_key,opening_name,learned,learning_mode,estimated_rating)
                            VALUES(1,?,'mistake',?,'white',?,'a2a3','sicilian','Sicilian Defense',?,?,?)''',
                            (f'game-{i}',fen,5+i%22,int(i%7==0),'mistakes' if i%2==0 else 'blunders',850+i*10))
                        pid = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
                        conn.execute('''INSERT INTO position_concepts
                            (position_id,concept_key,confidence,is_primary,classifier_version)
                            VALUES (?,'fork',0.9,1,'test')''', (pid,))
                    conn.commit()
                args={}
                request=types.SimpleNamespace(args=args)
                env={'connect':db.connect,'request':request,'jsonify':lambda value:value,
                     'get_settings':lambda:{'lesson_page_size':16},
                     'ensure_opening_metadata':lambda conn,job_id:0,
                     '_position_concepts':lambda conn,ids:{},
                     'board_identity':db._fen_board_identity,
                     'famous_for_opening':lambda name:[]}
                route=load_server_function('position_library', env)
                args.update(concept='fork',sort='rating-asc',page='1',phase='page')
                first=route(1)
                self.assertEqual(len(first['items']),16)
                self.assertTrue(first['pagination']['has_next'])
                self.assertEqual(first['items'][0]['estimated_rating'],850)
                args['page']='2'
                second=route(1)
                self.assertNotIn(second['items'][0]['id'],[item['id'] for item in first['items']])
                self.assertEqual(second['items'][0]['estimated_rating'],1010)
                args['page']='1';args['phase']='summary'
                summary=route(1)
                self.assertEqual(summary['summary']['total'],144)
                self.assertEqual(summary['pagination']['pages'],9)
                self.assertEqual(summary['pagination']['filtered_total'],144)
                self.assertEqual(summary['trainable_total'],144-21)
                args['phase']=''; full=route(1)
                self.assertEqual([r['id'] for r in full['items']],[r['id'] for r in first['items']])
                args.clear();args.update(opening='sicilian',sort='move-asc',phase='summary',page='1')
                summary=route(1)
                self.assertEqual(summary['trainable_total'],48) # each board has at least one unlearned member
                tiles=load_server_function('opening_plans',env)(1)
                self.assertEqual(tiles[0]['position_count'],48)
                self.assertEqual(tiles[0]['learned_positions'],0)  # none of each 3-member group all learned
        finally:
            if old_learning is None:sys.modules.pop('learning',None)
            else:sys.modules['learning']=old_learning


if __name__=='__main__': unittest.main()
