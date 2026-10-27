"""v114: exactly one active typed teaching-message store, historic feedback separate."""
import json
import sqlite3
import unittest

from coaching.coaching_refresh.message_cache import (
    cache_message, get_message, is_current_recap, visible_in_active_history,
)


class UnifiedMessageCacheTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE coaching_message_cache (
                position_id INTEGER NOT NULL, message_type TEXT NOT NULL
                CHECK(message_type IN ('best_move','attempted_move','game_move')),
                continuation_key TEXT NOT NULL, generation_version TEXT NOT NULL,
                content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                evidence_fingerprint TEXT NOT NULL DEFAULT '',
                coach_prompt TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(position_id,message_type,continuation_key));
            CREATE TABLE feedback_message_snapshots (
                id INTEGER PRIMARY KEY, position_id INTEGER, continuation_key TEXT,
                generation_version TEXT, content_snapshot TEXT);
            INSERT INTO feedback_message_snapshots
                VALUES (1,9,'e2e4','rules-v34','v34 original explanation');
        ''')

    def test_three_types_share_one_cache_and_generation_is_not_vote_time(self):
        cache_message(self.conn,9,'best_move','position','rules-v35','current solution')
        cache_message(self.conn,9,'attempted_move','e2e4','rules-v35','attempt reasoning')
        cache_message(self.conn,9,'game_move','d2d4','rules-v35','original game')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coaching_message_cache').fetchone()[0],3)
        self.assertEqual(get_message(self.conn,9,'attempted_move','e2e4',version='rules-v35')['content'],'attempt reasoning')
        self.assertIsNone(get_message(self.conn,9,'attempted_move','e2e4',version='rules-v34'))
        with self.assertRaises(ValueError):
            cache_message(self.conn,9,'old_style','e2e4','rules-v35','not allowed')

    def test_old_generation_replaced_without_damaging_historical_feedback(self):
        cache_message(self.conn,9,'attempted_move','e2e4','rules-v34','v34 original explanation')
        cache_message(self.conn,9,'attempted_move','e2e4','rules-v35','v35 revised explanation')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coaching_message_cache').fetchone()[0],1)
        self.assertEqual(get_message(self.conn,9,'attempted_move','e2e4')['generation_version'],'rules-v35')
        self.assertEqual(self.conn.execute('SELECT content_snapshot FROM feedback_message_snapshots').fetchone()[0],
                         'v34 original explanation')

    def test_historical_recap_cannot_reappear_after_refresh(self):
        cache_message(self.conn,9,'attempted_move','e2e4','rules-v35','new version')
        old={'kind':'solved_attempt_recap','coaching_version':'rules-v34',
             'attempt_comments':[{'origin':'attempt','move_uci':'e2e4','text':'old version'}]}
        new={'kind':'solved_attempt_recap','coaching_version':'rules-v35',
             'attempt_comments':[{'origin':'attempt','move_uci':'e2e4','text':'new version'}]}
        old_msg={'role':'assistant','generation_version':'rules-v34','structured_json':json.dumps(old)}
        new_msg={'role':'assistant','generation_version':'rules-v35','structured_json':json.dumps(new)}
        self.assertFalse(visible_in_active_history(self.conn,9,old_msg,'rules-v35'))
        self.assertTrue(visible_in_active_history(self.conn,9,new_msg,'rules-v35'))
        self.assertFalse(is_current_recap(self.conn,9,old,'rules-v35'))
        self.assertTrue(is_current_recap(self.conn,9,new,'rules-v35'))
        # A regenerated message in the same model has a distinct text identity.
        cache_message(self.conn,9,'attempted_move','e2e4','rules-v35','different current explanation')
        self.assertFalse(visible_in_active_history(self.conn,9,new_msg,'rules-v35'))

    def test_a_transcript_without_a_version_is_not_current(self):
        self.assertFalse(visible_in_active_history(self.conn,9,
            {'role':'assistant','content':'Legacy advice','structured_json':'{}'},'rules-v35'))
        self.assertTrue(visible_in_active_history(self.conn,9,
            {'role':'user','content':'Why?', 'structured_json':'{}'},'rules-v35'))


if __name__=='__main__': unittest.main()
