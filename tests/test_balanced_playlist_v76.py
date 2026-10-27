"""Regression tests for a diverse but complete All Positions playlist."""
import ast
from collections import Counter
from pathlib import Path
import random
import sqlite3
from types import SimpleNamespace

from balanced_playlist import balanced_playlist_order
from opening_playlist import board_identity

root = Path(__file__).resolve().parents[1]

# A balanced source should interleave openings and primary motifs instead of
# producing long uniform stretches. Random seeds make expectations repeatable.
items = [dict(id=i + 1, opening_key=f'opening-{i % 5}',
              motif_key=f'motif-{i % 7}', learning_mode=f'mode-{i % 3}')
         for i in range(210)]
a = balanced_playlist_order(items, rng=random.Random(19))
b = balanced_playlist_order(items, rng=random.Random(20))
assert len(a) == len(items) == len(set(row['id'] for row in a))
assert {row['id'] for row in a} == {row['id'] for row in items}
assert [row['id'] for row in a] != [row['id'] for row in b], 'fresh sessions should reshuffle'
assert sum(x['opening_key'] == y['opening_key'] for x, y in zip(a, a[1:])) < 5
assert sum(x['motif_key'] == y['motif_key'] for x, y in zip(a, a[1:])) < 5
assert len({row['opening_key'] for row in a[:15]}) == 5
assert len({row['motif_key'] for row in a[:15]}) == 7

# When the catalog is skewed, spread categories over the session instead of
# exhausting rare motifs or openings in the first few positions.
skewed = [dict(id=i + 1,
               opening_key='major' if i < 140 else 'minor' if i < 175 else 'other',
               motif_key='common' if i % 10 < 7 else 'uncommon',
               learning_mode='mistakes') for i in range(210)]
out = balanced_playlist_order(skewed, rng=random.Random(8))
assert len(out) == len(skewed) == len({row['id'] for row in out})
for prefix in (35, 70, 105):
    observed = Counter(row['opening_key'] for row in out[:prefix])
    for key, n in Counter(row['opening_key'] for row in skewed).items():
        assert abs(observed[key] - prefix * n / len(skewed)) <= 10, (prefix, key, observed)
assert [row['id'] for row in balanced_playlist_order(items, rng=random.Random(19))] == [row['id'] for row in a]
assert balanced_playlist_order([], rng=random.Random(1)) == []
assert balanced_playlist_order([items[0]], rng=random.Random(1)) == [items[0]]
assert len(balanced_playlist_order([{'id':1}, {'id':2}], rng=random.Random(2))) == 2

# Exercise the live Flask route logic as standalone AST functions, without
# requiring Flask, python-chess, a Stockfish process, or a user's database.
source = root / 'app.py'
tree = ast.parse(source.read_text())
def extract(name):
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    return compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec')

env = dict(
    request=SimpleNamespace(args={}),
    list_has_positions=lambda _id: True,
    render_template=lambda _name, **kw: kw,
    get_settings=lambda: {},
    balanced_playlist_order=balanced_playlist_order,
    board_identity=board_identity,
    ensure_opening_metadata=lambda *a: None,
    jsonify=lambda x: x,
)
exec(extract('trainer'), env)
def train(params):
    env['request'] = SimpleNamespace(args=params)
    return env['trainer'](12)
assert train({})['sort_key'] == 'balanced', 'general training should default to balanced'
assert train({'listing': '1'})['sort_key'] == 'balanced'
assert train({'new_playlist': '1'})['sort_key'] == 'balanced'
assert train({'sort':'rating-asc'})['sort_key'] == 'rating-asc'
assert train({'sort':'date-desc'})['sort_key'] == 'date-desc'
assert train({'learning_mode':'brilliant'})['sort_key'] == 'rating-asc'
assert train({'position':'42'})['sort_key'] == 'rating-asc'
assert train({'context':'defend'})['sort_key'] == 'rating-asc'
assert train({'position':'42','sort':'balanced'})['sort_key'] == 'rating-asc'

conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
conn.executescript('''
    CREATE TABLE analysis_jobs(id INTEGER PRIMARY KEY);
    CREATE TABLE training_positions(id INTEGER PRIMARY KEY, job_id INTEGER,
        game_id INTEGER, learned INTEGER, fen TEXT, opening_key TEXT,
        opening_variation TEXT, learning_mode TEXT, estimated_rating INTEGER,
        game_date TEXT, move_number INTEGER, opening_history TEXT);
    CREATE TABLE position_concepts(position_id INTEGER, concept_key TEXT, is_primary INTEGER);
    CREATE TABLE position_motif_taxonomy(position_id INTEGER PRIMARY KEY, motif_key TEXT,
        context_key TEXT, move_type_key TEXT);
    INSERT INTO analysis_jobs VALUES (12);
''')
for i in range(90):
    conn.execute('''INSERT INTO training_positions VALUES(?,12,?,?,?,?,?,?,?,?,?,?)''',
                 (i+1,i+1,int(i == 7),f'fen-{i}',f'opening-{i%5}','',
                  ('mistakes','blunders','brilliant')[i%3],800+i*10,'2026-01-01',i,'x'))
    conn.execute('INSERT INTO position_motif_taxonomy VALUES(?,?,?,?)',
                 (i+1, f'motif-{i%9}', 'attack', 'tactical'))
conn.commit()
env.update(connect=lambda:conn)
exec(extract('training_playlist_manifest'), env)

def manifest(params):
    env['request'] = SimpleNamespace(method='GET', args=params)
    return env['training_playlist_manifest'](12)

def resume(ids):
    env['request'] = SimpleNamespace(method='POST', get_json=lambda silent=True: {'position_ids':ids})
    return env['training_playlist_manifest'](12)

fresh = manifest({'sort':'balanced'})
assert len(fresh) == 89
assert {row['id'] for row in fresh} == set(range(1, 91)) - {8}
assert [row['id'] for row in fresh] != sorted(row['id'] for row in fresh)
assert len({(i-1)%5 for i in [row['id'] for row in fresh[:16]]}) == 5
assert len({(i-1)%9 for i in [row['id'] for row in fresh[:24]]}) == 9
assert resume([8, fresh[5]['id'], fresh[0]['id']]) == [
    {'id':8,'learned':1}, {'id':fresh[5]['id'],'learned':0},
    {'id':fresh[0]['id'],'learned':0}], 'resumed sessions preserve pinned order'
assert [row['id'] for row in manifest({'sort':'rating-asc'})][:6] == [1,2,3,4,5,6]
assert [row['id'] for row in manifest({'sort':'balanced','learning_mode':'blunders'})][:3] == [2,5,11], 'filtered playlists remain difficulty-sorted'
print('PASS: balanced shuffle, proportional coverage, route default, optional sorting, pinned resume')
