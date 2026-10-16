"""Source-level startup regression; does not require Flask or python-chess."""
from pathlib import Path
import ast
import unittest

APP = Path(__file__).resolve().parents[1] / 'app.py'

class StartupTests(unittest.TestCase):
    def test_main_startup_does_not_launch_background_jobs(self):
        module = ast.parse(APP.read_text())
        mains = [n for n in module.body if isinstance(n, ast.If)
                 and isinstance(n.test, ast.Compare) and
                 any(isinstance(c, ast.Constant) and c.value == '__main__'
                     for c in n.test.comparators)]
        self.assertEqual(len(mains), 1)
        calls = [n.func.id for n in ast.walk(mains[0]) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        self.assertIn('pause_interrupted_jobs_on_startup', calls)
        self.assertNotIn('start_analysis_thread', calls)
        self.assertNotIn('start_refresh_thread', calls)
        source = APP.read_text()
        self.assertIn("WHERE status IN ('queued','retrieving','running')", source)
        self.assertIn("WHERE status IN ('queued','running')", source)

if __name__ == '__main__':
    unittest.main()
