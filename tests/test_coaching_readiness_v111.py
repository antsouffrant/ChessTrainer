"""v111: per-position readiness guards may not infer readiness from evaluations."""
import sqlite3
import unittest
from pathlib import Path
from coaching.coaching_refresh.readiness import coaching_ready, coaching_refresh_error

ACTIVE = 'rules-v34-version-scoped-cache'


class CoachingReadinessTests(unittest.TestCase):
    def test_current_nonempty_copy_is_ready(self):
        self.assertTrue(coaching_ready({'coaching_version': ACTIVE, 'coach_explanation': 'Nxd7 wins material'}, ACTIVE))

    def test_stale_or_blank_copy_is_not_ready_even_if_evaluation_complete(self):
        for version, copy in [(None,None), ('rules-v33', 'Old version'), (ACTIVE,None), (ACTIVE,'  ')]:
            row={'coaching_version':version,'coach_explanation':copy,'job_id':7}
            self.assertFalse(coaching_ready(row, ACTIVE))
            error=coaching_refresh_error(row,ACTIVE)
            self.assertEqual(error['code'],'coaching_refresh_required')
            self.assertEqual(error['job_id'],7)
            self.assertIn('remain saved',error['error'])

    def test_sqlite_rows_and_missing_rows(self):
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.row_factory=sqlite3.Row
        row=conn.execute("SELECT 'rules-v33' AS coaching_version, 'old' AS coach_explanation, 42 AS job_id").fetchone()
        self.assertFalse(coaching_ready(row, ACTIVE))
        self.assertEqual(coaching_refresh_error(row, ACTIVE)['position_coaching_version'],'rules-v33')
        self.assertFalse(coaching_ready(None,ACTIVE))

    def test_routes_keep_historical_feedback_but_suppress_old_active_coaching(self):
        app=(Path(__file__).parents[1]/'app.py').read_text()
        js=(Path(__file__).parents[1]/'static/trainer.js').read_text()
        self.assertIn("card['coaching_ready'] = coaching_ready(card, COACHING_VERSION)",app)
        self.assertIn("active = get_message(conn,card['id'],'best_move','position',version=COACHING_VERSION)",app)
        self.assertIn("card['coach_explanation'] = ''",app)
        self.assertIn('if version and not coaching_ready(version, COACHING_VERSION):',app)
        self.assertIn("if category in ('explanation', 'continuation') and payload.get('message_snapshot_id'):",app)
        self.assertIn('if (not coaching_ready(row, COACHING_VERSION) or not current',app)
        self.assertIn('showCoachRecapIssue(positionId',js)
        self.assertNotIn('if (!response.ok) return;\n    const result = await response.json();\n    const message = result.message;',js)


if __name__=='__main__': unittest.main()
