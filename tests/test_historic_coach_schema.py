"""Standalone SQLite and endpoint regression fixture (requires no Flask/python-chess)."""
import ast
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
db_tree = ast.parse((ROOT / 'db.py').read_text())
schema = next(node.value.value for node in db_tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in node.targets))
conn = sqlite3.connect(':memory:')
conn.row_factory = sqlite3.Row
conn.executescript(schema)
conn.execute('PRAGMA foreign_keys=ON')
conn.execute("INSERT INTO accounts (id, provider, username) VALUES (1, 'lichess', 'a')")
conn.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types) VALUES (1,1,'all','rapid')")
for pid, learned in ((10, 1),(11,1),(12,0),(13,1)):
    match = json.dumps({'key':'opera-game','match_type':'exact_position'}) if pid == 10 else None
    conn.execute('''INSERT INTO training_positions(id, job_id, category, fen, user_color,
      move_number, best_move_uci, learned, opening_name, historical_match)
      VALUES (?,?, 'correct','fen','white',1,'e2e4',?,'Philidor Defense',?)''',
      (pid,1,learned,match))
conn.commit()
class App:
    def post(self, path):
        return lambda fn: fn
class Request:
    data = {'opening_playlist':True}
    def get_json(self, silent=False):
        return self.data
request = Request()
classic = {'key':'opera-game','title':'The Opera Game','year':1858,'players':'Paul Morphy',
           'opening':'Philidor Defense','lesson':'Coordinated attack.',
           'source_url':'https://example.org/verified-game'}

def thread_lookup(c, position_id, account_id):
    row = c.execute('SELECT id FROM coach_threads WHERE account_id=? AND position_id=?',
                    (account_id,position_id)).fetchone()
    if row: return row['id']
    return c.execute('INSERT INTO coach_threads(account_id,position_id) VALUES (?,?)',
                     (account_id,position_id)).lastrowid

def related(name):
    return [classic] if name == 'Philidor Defense' else []

tree = ast.parse((ROOT/'app.py').read_text())
node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='position_historical_coach')
node.decorator_list = []
code=compile(ast.Module(body=[node],type_ignores=[]),'<historic-endpoint>','exec')
ns={'app':App(),'connect':lambda:conn,'request':request,'jsonify':lambda x:x,
    'famous_for_opening':related,'CLASSICS':[classic], 'sqlite3':sqlite3,
    'json':json,'get_or_create_thread':thread_lookup}
exec(code,ns)
endpoint=ns['position_historical_coach']
first=endpoint(10)
assert first['shown'] and first['reference']['match_type']=='exact_position'
assert endpoint(10)['reason']=='already-shared'
assert endpoint(11)['reason']=='already-shared'
assert endpoint(12)['reason']=='unsolved'
request.data={'opening_playlist':False}
assert endpoint(13)['reason']=='no-reference'
assert conn.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0] == 1
assert conn.execute('SELECT COUNT(*) FROM coach_proactive_history').fetchone()[0] == 1
row=conn.execute('SELECT content, structured_json FROM coach_messages').fetchone()
assert 'Opera Game' in row['content']
assert json.loads(row['structured_json'])['kind']=='historical_reference'
print('Historical coach schema/endpoint: exact, dedupe, unsolved, missing, persisted tests passed')
