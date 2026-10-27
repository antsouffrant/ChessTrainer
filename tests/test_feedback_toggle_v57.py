"""v57: unchecking a thumb deletes its rating and every associated proposal."""
import re
import sqlite3
import unittest
from pathlib import Path
from test_feedback_corrections_v56 import FeedbackCorrectionsTests
import feedback_analytics as feedback

ROOT = Path(__file__).resolve().parents[1]


class ToggleFeedbackTests(FeedbackCorrectionsTests):
    # Reuse the exact database fixture containing a training position and chat.
    def test_toggle_explanation_removes_rating_and_proposed_gold_standard(self):
        feedback.record_position_vote(self.conn, 1, 'explanation', -1,
            suggested_text='The bishop is trapped after the pawn advances.')
        self.assertEqual(len(feedback.regression_candidate_rows(feedback.report_rows(self.conn))), 1)
        self.assertEqual(feedback.record_position_vote(self.conn, 1, 'explanation', 0), {})
        self.assertEqual(feedback.position_feedback_details(self.conn, 1), {})
        self.assertEqual(feedback.report_rows(self.conn), [])
        feedback.record_position_vote(self.conn, 1, 'explanation', -1)
        self.assertEqual(feedback.position_feedback_details(self.conn, 1)['explanation']['suggested_text'], '')
        self.assertEqual(feedback.regression_candidate_rows(feedback.report_rows(self.conn)), [])

    def test_all_three_position_categories_can_be_unchecked_independently(self):
        feedback.record_position_vote(self.conn, 1, 'position', 1)
        feedback.record_position_vote(self.conn, 1, 'explanation', -1, suggested_text='Correction')
        feedback.record_position_vote(self.conn, 1, 'motif', -1, suggested_motif_key='sacrifice')
        self.assertEqual(len(feedback.report_rows(self.conn)), 3)
        self.assertEqual(feedback.record_position_vote(self.conn, 1, 'motif', 0),
                         {'position': 1, 'explanation': -1})
        self.assertNotIn('motif', feedback.position_feedback_details(self.conn, 1))
        feedback.record_position_vote(self.conn, 1, 'position', 0)
        self.assertEqual(len(feedback.report_rows(self.conn)), 1)
        feedback.record_position_vote(self.conn, 1, 'explanation', 0)
        self.assertEqual(feedback.report_summary(feedback.report_rows(self.conn))['overall']['total'], 0)

    def test_motif_options_alphabetical_not_grouped_by_family(self):
        # A strategy item alphabetically precedes a tactics item.
        self.conn.execute("UPDATE learning_concepts SET name = 'Zebra Fork', family = 'Tactics' WHERE key='pin'")
        names = [item['name'] for item in feedback.motif_feedback_options(self.conn, 1)]
        self.assertEqual(names, ['Sacrifice Material', 'Zebra Fork'])

    def test_chat_endpoint_uncheck_branch_deletes_correction_without_touching_message(self):
        source = (ROOT / 'app.py').read_text()
        self.assertIn("if rating == 0:\n            # Remove the whole record", source)
        self.conn.execute('''INSERT INTO coach_message_feedback
            (message_id, account_id, position_id, rating, suggested_text)
            VALUES(2, 1, 1, -1, 'A better explanation')''')
        # Execute the same SQL as the uncheck route against its fixture database.
        match = re.search(r"if rating == 0:\s*# Remove the whole record.+?conn\.execute\('([^']+)'", source, re.S)
        self.assertIsNotNone(match)
        self.conn.execute(match.group(1), (2,))
        self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_message_feedback').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0], 2)
        self.assertEqual(feedback.regression_candidate_rows(feedback.report_rows(self.conn)), [])


if __name__ == '__main__':
    unittest.main()
