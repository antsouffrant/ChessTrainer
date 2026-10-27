"""Post-solve session evidence must not slow the board or expose unsolved hints."""
import ast
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from coaching.narrative_composition.coach_session_recap import valid_session_key, cached_move, record_board_attempt, save_solved_recap

ROOT = Path(__file__).resolve().parents[1]


def get_schema():
    mod = ast.parse((ROOT / 'db.py').read_text())
    return next(n.value.value for n in mod.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets))


class CoachSessionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = Path(tmp.name) / 'test.db'
        self.conn = sqlite3.connect(self.db_path)
        self.addCleanup(self.conn.close)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(get_schema())
        self.conn.execute("INSERT INTO accounts(provider,username) VALUES('lichess','a')")
        self.conn.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES(1,'all','[]')")
        self.conn.execute('''INSERT INTO training_positions
            (job_id,game_id,category,fen,user_color,move_number,best_move_uci,
             best_move_san,played_move_uci,played_pv_uci,coach_explanation,
             coaching_version,learned) VALUES (1,'g','mistake',?,'white',2,
             'e2e4','e4','d2d4','d2d4 d7d5','e4 controls the center.','v77',0)''',
             ('8/8/8/8/8/8/8/8 w - - 0 1',))
        self.conn.commit()

    def row(self):
        return self.conn.execute('SELECT tp.*,j.account_id FROM training_positions tp JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=1').fetchone()

    def test_only_server_legal_attempt_log_and_cached_move(self):
        r=self.row()
        self.assertFalse(record_board_attempt(self.conn,r,session_key='bad',move_uci='d2d4',move_san='d4',correct=False))
        self.assertTrue(record_board_attempt(self.conn,r,session_key='session_123',move_uci='d2d4',move_san='d4',correct=False, quality={'eval_cp':-50,'best_reply_san':'d5'}))
        self.assertTrue(record_board_attempt(self.conn,r,session_key='session_123',move_uci='e2e4',move_san='e4',correct=True))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_board_attempts').fetchone()[0],2)
        self.assertTrue(cached_move(r,'d2d4'))
        self.assertFalse(cached_move(r,'a2a4'))
        attempt=self.conn.execute('SELECT * FROM coach_board_attempts WHERE move_uci="d2d4"').fetchone()
        self.assertEqual(attempt['from_saved_line'],1)
        self.assertEqual(attempt['best_reply_san'],'d5')

    def test_unsolved_never_receives_recap(self):
        record_board_attempt(self.conn,self.row(),session_key='session_124',move_uci='d2d4',move_san='d4',correct=False)
        with self.assertRaises(PermissionError):
            save_solved_recap(self.conn,self.row(),session_key='session_124')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],0)

    def test_idempotent_post_solve_recap_uses_saved_evidence(self):
        record_board_attempt(self.conn,self.row(),session_key='session_125',move_uci='d2d4',move_san='d4',correct=False,quality={'best_reply_san':'d5'})
        record_board_attempt(self.conn,self.row(),session_key='session_125',move_uci='e2e4',move_san='e4',correct=True)
        self.conn.execute('UPDATE training_positions SET learned=1 WHERE id=1')
        mock_adaptive=types.ModuleType('adaptive_coach')
        def thread(conn,position_id,account_id):
            cursor=conn.execute('INSERT OR IGNORE INTO coach_threads(account_id,position_id) VALUES (?,?)',(account_id,position_id))
            return conn.execute('SELECT id FROM coach_threads WHERE position_id=?',(position_id,)).fetchone()[0]
        mock_adaptive.get_or_create_thread=thread
        with patch.dict(sys.modules,{'coaching.narrative_composition.adaptive_coach':mock_adaptive}):
            first=save_solved_recap(self.conn,self.row(),session_key='session_125')
            again=save_solved_recap(self.conn,self.row(),session_key='session_125')
        self.assertTrue(first['created'])
        self.assertFalse(again['created'])
        self.assertEqual(first['id'],again['id'])
        self.assertNotIn('d5',first['content'])  # bare PV replies are not coaching
        self.assertIn('e4: e4 controls the center.',first['content'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],1)
        evidence=json.loads(first['structured_json'])
        self.assertEqual(evidence['attempt_count'],2)
        self.assertIn('e4 controls the center',evidence['model_explanation'])
        self.assertEqual(evidence['kind'],'solved_attempt_recap')
        comments = evidence['attempt_comments']
        self.assertEqual(len(comments), 2)
        self.assertEqual([c['move_san'] for c in comments], ['e4','d4'])
        self.assertEqual([c['correct'] for c in comments], [True, False])
        self.assertNotIn('d5', comments[1]['text'])
        self.assertEqual(comments[0]['text'], 'e4 controls the center.')

    def test_verified_pv_is_persisted_for_a_new_move(self):
        r=self.row()
        record_board_attempt(self.conn,r,session_key='session_126',move_uci='a2a3',
                             move_san='a3',correct=False,
                             quality={'eval_cp':-150,'best_reply_san':'e5',
                                      'pv_uci':['a2a3','e7e5','g1f3']})
        event=self.conn.execute('SELECT verified_pv_json FROM coach_board_attempts WHERE move_uci=?',
                                ('a2a3',)).fetchone()
        self.assertEqual(json.loads(event['verified_pv_json']), ['a2a3','e7e5','g1f3'])

    def test_prior_recap_upgrades_in_place_without_losing_message_id(self):
        from coaching.narrative_composition.coach_session_recap import refresh_saved_recaps
        r=self.row()
        record_board_attempt(self.conn,r,session_key='session_127',move_uci='d2d4',
                             move_san='d4',correct=False,quality={'best_reply_san':'d5'})
        record_board_attempt(self.conn,r,session_key='session_127',move_uci='e2e4',
                             move_san='e4',correct=True)
        self.conn.execute('UPDATE training_positions SET learned=1 WHERE id=1')
        mock_adaptive=types.ModuleType('adaptive_coach')
        def thread(conn, position_id, account_id):
            conn.execute('INSERT OR IGNORE INTO coach_threads(account_id,position_id) VALUES (?,?)',
                         (account_id,position_id))
            return conn.execute('SELECT id FROM coach_threads WHERE position_id=?',
                                (position_id,)).fetchone()[0]
        mock_adaptive.get_or_create_thread=thread
        with patch.dict(sys.modules,{'coaching.narrative_composition.adaptive_coach':mock_adaptive}):
            saved=save_solved_recap(self.conn,self.row(),session_key='session_127')
        old={'kind':'solved_attempt_recap','attempt_comments':[{'text':'d4 does not meet the solution threshold.'}]}
        self.conn.execute('UPDATE coach_messages SET structured_json=?, content=? WHERE id=?',
                          (json.dumps(old),'Legacy threshold note',saved['id']))
        self.assertEqual(refresh_saved_recaps(self.conn,self.row()),1)
        updated=self.conn.execute('SELECT * FROM coach_messages WHERE id=?',(saved['id'],)).fetchone()
        self.assertNotIn('solution threshold',updated['content'])
        self.assertEqual(json.loads(updated['structured_json'])['explanation_version'],7)
        self.assertEqual(refresh_saved_recaps(self.conn,self.row()),0)

    def test_v79_recap_is_regenerated_without_repeated_check(self):
        # Existing v79 (version 2) recap upgrades without changing its ID.
        self.conn.execute('''UPDATE training_positions SET
            best_move_uci='f2f1', best_move_san='Rf1+',
            coach_explanation='Rf1+ gives check, requiring an immediate reply.',
            explanatory_lines_json=? WHERE id=1''',
            (json.dumps({'lines':[{'root_uci':'f2f1','role':'recommended',
                'plies':[{'uci':'f2f1','san':'Rf1+',
                          'effects':[{'kind':'check','text':'Rf1+ gives check'}]},
                         {'uci':'g1g2','san':'Kg2', 'effects':[]}] }]}),))
        record_board_attempt(self.conn,self.row(),session_key='session_128',
                             move_uci='f2f1',move_san='Rf1+',correct=True)
        self.conn.execute('UPDATE training_positions SET learned=1 WHERE id=1')
        mock_adaptive=types.ModuleType('adaptive_coach')
        def thread(conn,position_id,account_id):
            conn.execute('INSERT OR IGNORE INTO coach_threads(account_id,position_id) VALUES (?,?)',
                         (account_id,position_id))
            return conn.execute('SELECT id FROM coach_threads WHERE position_id=?',
                                (position_id,)).fetchone()[0]
        mock_adaptive.get_or_create_thread=thread
        with patch.dict(sys.modules,{'coaching.narrative_composition.adaptive_coach':mock_adaptive}):
            original=save_solved_recap(self.conn,self.row(),session_key='session_128')
        legacy=json.loads(original['structured_json'])
        legacy['explanation_version']=2
        self.conn.execute('UPDATE coach_messages SET content=?,structured_json=? WHERE id=?',
                          ('Rf1+ gives check. Rf1+ gives check.',json.dumps(legacy),original['id']))
        from coaching.narrative_composition.coach_session_recap import refresh_saved_recaps
        self.assertEqual(refresh_saved_recaps(self.conn,self.row()),1)
        updated=self.conn.execute('SELECT * FROM coach_messages WHERE id=?',(original['id'],)).fetchone()
        self.assertEqual(updated['content'].count('Rf1+ gives check'),1)
        self.assertNotIn('Kg2',updated['content'])  # uninformative reply is omitted
        self.assertEqual(json.loads(updated['structured_json'])['explanation_version'],7)
        self.assertEqual(refresh_saved_recaps(self.conn,self.row()),0)

    def test_session_token_guard(self):
        self.assertFalse(valid_session_key('x' * 101))
        self.assertFalse(valid_session_key('../unsafe'))
        self.assertTrue(valid_session_key('abc_DEF012'))


if __name__=='__main__': unittest.main()
