"""Migration test for pre-checkpoint game lists, even without python-chess."""
import ast
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

class CheckpointSchemaTests(unittest.TestCase):
    def test_migration_preserves_analysis_state(self):
        with tempfile.TemporaryDirectory() as work:
            module = ast.parse((ROOT / 'db.py').read_text())
            schema = next(n.value.value for n in module.body if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets))
            legacy_schema = '\n'.join(line for line in schema.splitlines()
                 if not any(k in line for k in ('checkpoint_pass INTEGER','checkpoint_game_index INTEGER','checkpoint_file_offset INTEGER')))
            path = Path(work) / 'legacy.sqlite3'
            with sqlite3.connect(path) as c:
                c.executescript(legacy_schema)
                c.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','alice')")
                c.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,status, games_processed, current_pass) VALUES (1,'month','[]','paused',12,2)")
                c.commit()
            # Import actual migration with a minimal taxonomy stub; chess parser is unnecessary.
            sys.modules.setdefault('learning', types.SimpleNamespace(CLASSIFIER_VERSION='test', CONCEPT_CATALOG=[]))
            sys.path.insert(0,str(ROOT))
            import db
            old = db.DB_PATH
            try:
                db.DB_PATH = path
                db.init_db()
                with db.connect() as c:
                    row = c.execute('SELECT * FROM analysis_jobs').fetchone()
                    self.assertEqual((row['status'],row['current_pass'],row['games_processed']),('paused',2,12))
                    self.assertEqual((row['checkpoint_pass'],row['checkpoint_game_index'],row['checkpoint_file_offset']),(0,0,0))
                    c.execute("UPDATE analysis_jobs SET checkpoint_pass=2, checkpoint_game_index=11, checkpoint_file_offset=312, status='queued'")
                    c.commit()
                db.init_db()
                with db.connect() as c:
                    row = c.execute('SELECT * FROM analysis_jobs').fetchone()
                    self.assertEqual((row['checkpoint_pass'],row['checkpoint_game_index'],row['checkpoint_file_offset']),(2,11,312))
            finally:
                db.DB_PATH = old

if __name__=='__main__': unittest.main()
