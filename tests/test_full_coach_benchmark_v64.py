"""Protect positive references as well as negative correction cases (no engine needed)."""
import json
import unittest
from collections import Counter
from pathlib import Path

from tools.build_full_coach_fixture import ALLOW, transform

ROOT = Path(__file__).resolve().parents[1]
ROWS = ROOT / 'tests' / 'fixtures' / 'coach_feedback_full_v64.jsonl'


class FullHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in ROWS.read_text(encoding='utf-8').splitlines()]

    def test_all_281_ratings_retained_without_chat(self):
        self.assertEqual(len(self.rows), 281)
        self.assertEqual(Counter((r['feedback_type'], r['rating']) for r in self.rows), {
            ('position', '1'): 86, ('position', '-1'): 1,
            ('motif', '1'): 71, ('motif', '-1'): 21,
            ('explanation', '1'): 58, ('explanation', '-1'): 44,
        })

    def test_approved_and_rejected_cases_share_position_groups(self):
        self.assertEqual(len({r['position_group'] for r in self.rows}), 103)
        self.assertEqual(len({(r['case_id'], r['feedback_type']) for r in self.rows}), 281)

    def test_no_personal_or_game_metadata(self):
        allowed = set(ALLOW) | {'position_group', 'case_id'}
        forbidden = {'username', 'opponent', 'game_id', 'job_id', 'position_url',
                     'source_username', 'game_date', 'provider'}
        for r in self.rows:
            self.assertEqual(set(r), allowed)
            self.assertFalse(forbidden & set(r))
            self.assertTrue(r['fen'] and r['best_move_uci'] and r['played_move_uci'])

    def test_builder_excludes_chat_and_maintains_grouping(self):
        raw = [dict(feedback_type='motif', rating='1', fen='fen-test',
                    best_move_uci='e2e4', played_move_uci='d2d4', username='private'),
               dict(feedback_type='explanation', rating='-1', fen='fen-test',
                    best_move_uci='e2e4', played_move_uci='d2d4', suggested_text='proposal'),
               dict(feedback_type='chat', rating='-1', fen='fen-test')]
        result = list(transform(raw))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['position_group'], result[1]['position_group'])
        self.assertNotIn('username', result[0])
        self.assertEqual(result[1]['suggested_text'], 'proposal')

    def test_navigation_keeps_player_before_coach(self):
        html = (ROOT / 'templates' / 'base.html').read_text()
        self.assertLess(html.index('>Player</span>'), html.index('>Coach</span>'))
        self.assertLess(html.index('>Coach</span>'), html.index('>Process</span>'))


if __name__ == '__main__':
    unittest.main()
