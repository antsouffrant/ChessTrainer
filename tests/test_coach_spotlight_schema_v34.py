"""Schema and query fixture that can run without the chess or Flask dependencies."""
import ast
import pathlib
import re
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_spotlight_schema_and_selection():
    module = ast.parse((ROOT / 'db.py').read_text())
    raw = next(item.value for item in module.body if isinstance(item, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in item.targets))
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript(ast.literal_eval(raw))
    db.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','example')")
    db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,status) VALUES (1,'all','rapid','done')")
    for game, mode, move in [('A','mistakes','e4'),('B','brilliant','Nf3'),('C','brilliant','Nc3')]:
        db.execute('''INSERT INTO training_positions(job_id,game_id,category,learning_mode,fen,user_color,
            move_number,best_move_uci,played_move_uci,played_move_san,centipawn_loss,learned)
            VALUES (1,?,?,?,?,?,1,'g1f3','g1f3',?,15,1)''',
            (game, 'brilliant_move' if mode=='brilliant' else 'major_blunder', mode,
             'example-fen', 'white', move))
    app_source = (ROOT / 'app.py').read_text()
    query = re.search(r"row = conn\.execute\('''(\s*SELECT tp\.id, tp\.played_move_san.+?)'''",
                      app_source, re.S).group(1)
    result = db.execute(query, (1,1,1,'A')).fetchone()
    assert result is not None and result['played_move_san'] == 'Nf3'
    assert 'coach_proactive_spotlights' in [r['name'] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
