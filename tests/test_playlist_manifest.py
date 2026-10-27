"""Standalone playlist manifest regression without Flask or python-chess."""
import ast
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from opening_playlist import board_identity

source = Path(__file__).resolve().parents[1] / 'app.py'
tree = ast.parse(source.read_text())
function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == 'training_playlist_manifest')
function.decorator_list = []
compiled = compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec')
conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
conn.executescript('''
 CREATE TABLE analysis_jobs(id INT PRIMARY KEY);
 CREATE TABLE training_positions(
 id INT PRIMARY KEY, job_id INT, game_id INT, learned INT DEFAULT 0, fen TEXT,
 category TEXT, opening_key TEXT, opening_variation TEXT, learning_mode TEXT,
 estimated_rating INT, game_date TEXT, move_number INT, opening_history TEXT
 );
 CREATE TABLE position_concepts(position_id INT, concept_key TEXT, is_primary INT);
 INSERT INTO analysis_jobs VALUES (5);
 INSERT INTO training_positions VALUES
 (1,5,11,0,'7k/8/8/8/8/8/8/7K w - - 0 1','c','sicilian','Najdorf','mistakes',1250,'2026-01-01',12,'a'),
 (2,5,12,0,'7k/8/8/8/8/8/8/7K w - - 2 99','c','sicilian','Najdorf','mistakes',1600,'2026-01-02',13,'a'),
 (3,5,11,0,'6rk/8/8/8/8/8/8/7K w - - 0 1','c','sicilian','Dragon','mistakes',1350,'2026-01-03',15,'b'),
 (4,5,14,1,'7k/8/8/8/8/8/8/7K b - - 0 1','c','sicilian','Najdorf','mistakes',1700,'2026-01-04',18,'c');
 INSERT INTO position_concepts VALUES (1,'fork',1),(2,'fork',1),(3,'fork',1);
''')

env = {
 'connect': lambda: conn, 'jsonify': lambda x: x,
 'board_identity': board_identity,
 'ensure_opening_metadata': lambda *args: None,
}
exec(compiled, env)
api = env['training_playlist_manifest']

def get(params):
 env['request'] = SimpleNamespace(method='GET', args=params)
 return api(5)

def post(ids):
 env['request'] = SimpleNamespace(method='POST', get_json=lambda silent=True: {'position_ids':ids})
 return api(5)

# Stable sort and same one-per-game lesson deduplication as original.
assert [row['id'] for row in get({'concept':'fork','sort':'rating-asc'})] == [1, 2]
assert [row['id'] for row in get({'concept':'fork','sort':'rating-asc','listing':'1'})] == [1, 3, 2]
# Board identity excludes move counters; opening duplicates disappear.
assert [row['id'] for row in get({'opening':'sicilian','sort':'move-asc'})] == [1, 3]
assert [row['id'] for row in get({'opening':'sicilian','variation':'Najdorf','sort':'move-asc'})] == [1]
# Explicit position link can still show a learned card.
assert [row['id'] for row in get({'position_id':'4','sort':'rating-asc'})] == [1,3,2,4]
# Resume keeps original order, learned cards, and never mixes jobs.
assert post([4,2,1]) == [{'id':4,'learned':1},{'id':2,'learned':0},{'id':1,'learned':0}]
assert post([2,2])[1] == 400
print('PASS: manifest filtering, ordering, opening dedup, resume and learned status')
