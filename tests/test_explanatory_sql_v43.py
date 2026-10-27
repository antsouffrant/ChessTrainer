"""Database/SQL compatibility checks without optional chess dependencies."""
import pathlib
import re
import sqlite3
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class ExplanatorySchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'db.py').read_text()
        cls.schema = re.search(r"SCHEMA = '''(.*?)'''", source, re.S).group(1)
        cls.analysis = (ROOT / 'analysis.py').read_text()

    def test_v43_initial_schema_contains_structured_variations(self):
        db = sqlite3.connect(':memory:')
        db.executescript(self.schema)
        names = [row[1] for row in db.execute('PRAGMA table_info(training_positions)')]
        self.assertIn('explanatory_lines_json', names)
        db.close()

    def test_existing_database_can_add_column(self):
        db = sqlite3.connect(':memory:')
        db.executescript(self.schema.replace('    explanatory_lines_json TEXT,\n', ''))
        db.execute('ALTER TABLE training_positions ADD COLUMN explanatory_lines_json TEXT')
        names = [row[1] for row in db.execute('PRAGMA table_info(training_positions)')]
        self.assertIn('explanatory_lines_json', names)
        db.close()

    def test_copy_and_insert_field_counts_match_placeholders(self):
        for m in re.finditer(r'INSERT (?:OR IGNORE )?INTO training_positions', self.analysis):
            statement = self.analysis[m.start():].split('"""', 1)[0]
            fields = re.search(r'\((.*?)\) VALUES', statement, re.S).group(1)
            self.assertEqual(statement.count('?'), len(fields.split(',')))
            self.assertIn('explanatory_lines_json', fields)
            conn = sqlite3.connect(':memory:')
            conn.executescript(self.schema)
            conn.execute('EXPLAIN ' + statement, [''] * statement.count('?'))
            conn.close()

    def test_checkpoints_not_changed(self):
        self.assertIn('checkpoint_game_index', self.analysis)
        self.assertIn('checkpoint_file_offset', self.analysis)
        self.assertIn('probe_explanatory_replies', self.analysis)


if __name__ == '__main__':
    unittest.main()
