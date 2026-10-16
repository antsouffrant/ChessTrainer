"""Persistent schema and opening playlist SQL tests (no Stockfish required)."""
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

class OpeningSchemaTests(unittest.TestCase):
    def test_schema_and_grouped_playlist(self):
        stub = types.ModuleType('learning')
        stub.CLASSIFIER_VERSION = 'test'
        stub.CONCEPT_CATALOG = []
        previous = sys.modules.get('learning')
        sys.modules['learning'] = stub
        try:
            spec = importlib.util.spec_from_file_location('test_db_v19', PROJECT / 'db.py')
            db = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(db)
            with tempfile.TemporaryDirectory() as folder:
                db.DB_PATH = Path(folder) / 'trainer.sqlite3'
                db.init_db()
                with db.connect() as c:
                    columns={row['name'] for row in c.execute('PRAGMA table_info(training_positions)')}
                    self.assertTrue({'opening_key','opening_name','opening_variation','opening_history','historical_match'}.issubset(columns))
                    c.execute("INSERT INTO accounts(id,provider,username) VALUES(1,'test','me')")
                    c.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types) VALUES(1,1,'all','classical')")
                    data=[('sicilian-defense','Sicilian Defense','Najdorf Variation',15,0),('sicilian-defense','Sicilian Defense','Open Sicilian',12,1),('philidor-defense','Philidor Defense','',10,0)]
                    for i,(key,name,var,move,learned) in enumerate(data,1):
                        c.execute('''INSERT INTO training_positions(job_id,game_id,category,fen,user_color,move_number,best_move_uci,opening_key,opening_name,opening_variation,learned)
                        VALUES(1,?,'mistake','testfen','white',?, 'a2a3',?,?,?,?)''',(str(i),move,key,name,var,learned))
                    rows=c.execute('''SELECT opening_key AS key, MAX(opening_name) AS name, COUNT(*) AS position_count, SUM(learned) AS learned_positions FROM training_positions WHERE job_id=1 GROUP BY opening_key ORDER BY position_count DESC''').fetchall()
                    self.assertEqual(rows[0]['name'],'Sicilian Defense')
                    self.assertEqual(rows[0]['position_count'],2)
                    results=c.execute('''SELECT opening_variation FROM training_positions WHERE job_id=1 AND opening_key=? ORDER BY move_number ASC''',('sicilian-defense',)).fetchall()
                    self.assertEqual([r['opening_variation'] for r in results],['Open Sicilian','Najdorf Variation'])
                db.init_db() # migration can run twice
        finally:
            if previous is None: sys.modules.pop('learning',None)
            else: sys.modules['learning']=previous

if __name__ == '__main__': unittest.main()
