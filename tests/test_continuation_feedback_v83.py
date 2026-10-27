"""v83: continuation ownership, feedback identities, legacy support, and analytics."""
import csv
import io
import json
import sqlite3
import unittest
from test_feedback_analytics_v48 import schema
from coaching.narrative_composition.continuation_coach import explain_attempt
from feedback_analytics import (record_position_vote, record_continuation_vote,
    continuation_votes, continuation_feedback_details, report_rows, csv_bytes,
    coaching_metric_chart, regression_candidate_rows)
from coaching.narrative_composition.coach_session_recap import _build_recap


class ContinuationFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript(schema())
        self.db.execute("INSERT INTO accounts(provider,username) VALUES ('lichess','player')")
        self.db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types) VALUES (1,'Oct','[]')")
        self.db.execute("""INSERT INTO training_positions
            (job_id,category,fen,user_color,move_number,best_move_uci,best_move_san,
             played_move_uci,played_move_san,learned,coaching_version,coach_explanation)
            VALUES (1,'mistake','4k3/8/8/8/8/8/8/4K3 w - - 0 1','white',1,
                'e1d1','Kd1','e1f1','Kf1',1,'coach-v83','Kd1 is safer than Kf1.')""")
        for uci, san, correct in [('e1f1','Kf1',0), ('e1e2','Ke2',0), ('e1d1','Kd1',1)]:
            self.db.execute('''INSERT INTO coach_board_attempts
                (position_id,session_key,move_uci,move_san,correct,from_saved_line)
                VALUES (1,'session_abc',?,?,?,1)''', (uci,san,correct))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_independent_votes_and_legacy_solution_mapping(self):
        record_position_vote(self.db,1,'explanation',1,text='Original winning line')
        self.assertEqual(record_continuation_vote(self.db,1,'e1f1',-1,
            text='Kf1 lets a piece hang',suggested_text='Specific threat needed'),{'e1f1':-1})
        record_continuation_vote(self.db,1,'e1e2',1,text='Ke2 explains the check')
        self.assertEqual(continuation_votes(self.db,1),{'e1f1':-1,'e1e2':1})
        self.assertEqual(continuation_feedback_details(self.db,1)['e1f1']['suggested_text'],'Specific threat needed')
        rows = [r for r in report_rows(self.db) if r['feedback_type']=='explanation']
        self.assertEqual({r['continuation_key']:r['rating'] for r in rows},
                         {'solving':1,'e1f1':-1,'e1e2':1})
        self.assertEqual(len(report_rows(self.db,{'continuation_scope':'attempted'})),2)
        self.assertEqual(len(report_rows(self.db,{'continuation_scope':'solving'})),1)
        self.assertEqual(len(report_rows(self.db,{'continuation_key':'e1f1'})),1)
        csv_rows = list(csv.DictReader(io.StringIO(csv_bytes(rows).decode('utf-8-sig'))))
        self.assertEqual({r['continuation_key'] for r in csv_rows}, {'solving','e1f1','e1e2'})
        self.assertEqual(len({r['regression_case_id'] for r in csv_rows}),3)
        self.assertEqual([r['continuation_key'] for r in regression_candidate_rows(rows)],['e1f1'])
        record_continuation_vote(self.db,1,'e1f1',1,text='Fixed explanation')
        self.assertEqual(continuation_feedback_details(self.db,1)['e1f1']['suggested_text'],'')
        record_continuation_vote(self.db,1,'e1f1',0)
        self.assertNotIn('e1f1',continuation_votes(self.db,1))
        self.assertEqual(self.db.execute("SELECT rating FROM position_feedback WHERE category='explanation'").fetchone()[0],1)

    def test_individually_counted_approval_chart(self):
        record_position_vote(self.db,1,'explanation',1)
        record_continuation_vote(self.db,1,'e1f1',-1,text='Bad')
        record_continuation_vote(self.db,1,'e1e2',1,text='Good')
        chart = coaching_metric_chart(self.db,metric='approval',group_by='continuation_kind')
        got = {r['key']:(r['numerator'],r['denominator']) for r in chart['rows']}
        self.assertEqual(got['solving'], (1,1))
        self.assertEqual(got['attempted'], (1,2))
        self.assertEqual(got['chat'], (0,0))

    def test_verification_blocks_unseen_lines_and_unsolved_puzzles(self):
        with self.assertRaisesRegex(ValueError,'verified'):
            record_continuation_vote(self.db,1,'g2g4',1)
        with self.assertRaises(ValueError):
            record_continuation_vote(self.db,1,'not_move',1)
        with self.assertRaisesRegex(ValueError,'verified'):
            record_continuation_vote(self.db,1,'e1d1',1)
        self.db.execute('UPDATE training_positions SET learned=0 WHERE id=1')
        with self.assertRaises(PermissionError):
            record_continuation_vote(self.db,1,'e1f1',1)

    def test_original_game_move_and_previous_attempt_get_independent_cards(self):
        evidence = {'lines': [
            {'role':'recommended', 'root_uci':'e1d1', 'plies': [
                {'uci':'e1d1','san':'Kd1','effects':[{'kind':'check_evasion','text':'Kd1 resolves check'}]}]},
            {'role':'played', 'root_uci':'e1f1', 'plies': [
                {'uci':'e1f1','san':'Kf1','effects':[{'kind':'capture','text':'Kf1 sacrifices a piece'}]}]}
        ]}
        self.db.execute('UPDATE training_positions SET explanatory_lines_json=? WHERE id=1',
                        (json.dumps(evidence),))
        # The user's game move is distinct from an earlier training attempt.
        self.db.execute('DELETE FROM coach_board_attempts WHERE move_uci=?',('e1f1',))
        self.db.execute("INSERT INTO coach_board_attempts (position_id,session_key,move_uci,move_san,correct,from_saved_line) VALUES (1,'session_new','e1d1','Kd1',1,1)")
        row = self.db.execute('SELECT * FROM training_positions WHERE id=1').fetchone()
        content, structured = _build_recap(self.db,row,'session_new')
        notes = json.loads(structured)['attempt_comments']
        self.assertEqual([n['move_uci'] for n in notes], ['e1f1','e1e2','e1d1'])
        self.assertEqual([n.get('origin') for n in notes], ['game','previous_session',None])
        self.assertFalse(notes[0]['correct'])
        self.assertTrue(notes[-1]['correct'])
        self.assertNotIn('Kf1 sacrifices', notes[-1]['text'])
        self.assertIn('Kf1', content)

    def test_previous_attempts_do_not_duplicate_game_move(self):
        evidence = {'lines': [{'role':'played', 'root_uci':'e1f1', 'plies': [
            {'uci':'e1f1','san':'Kf1','effects':[{'kind':'capture','text':'Kf1 loses material'}]}]}]}
        self.db.execute('UPDATE training_positions SET explanatory_lines_json=? WHERE id=1',
                        (json.dumps(evidence),))
        self.db.execute("INSERT INTO coach_board_attempts (position_id,session_key,move_uci,move_san,correct,from_saved_line) VALUES (1,'session_new','e1d1','Kd1',1,1)")
        row = self.db.execute('SELECT * FROM training_positions WHERE id=1').fetchone()
        _, structured = _build_recap(self.db,row,'session_new')
        notes = json.loads(structured)['attempt_comments']
        self.assertEqual(len([n for n in notes if n['move_uci']=='e1f1']),1)
        self.assertEqual(len([n for n in notes if n['move_uci']=='e1e2']),1)

    def test_version_snapshots_survive_updates(self):
        record_continuation_vote(self.db,1,'e1f1',-1,text='Old message')
        self.db.execute("UPDATE training_positions SET coaching_version='coach-v84' WHERE id=1")
        record_continuation_vote(self.db,1,'e1e2',1,text='New message')
        self.assertEqual({r['continuation_key'] for r in report_rows(self.db, {'coaching_version':'coach-v83'})}, {'e1f1'})
        self.assertEqual({r['continuation_key'] for r in report_rows(self.db, {'coaching_version':'coach-v84'})}, {'e1e2'})


class OneRootNarrativeTests(unittest.TestCase):
    def test_solution_never_inherits_the_other_root_before_its_reply(self):
        lines = {'lines':[
            {'role':'recommended','root_uci':'f6d7','plies':[
                {'uci':'f6d7','san':'Nxd7','effects':[{'kind':'capture','text':'Nxd7 takes a free rook'}]},
                {'uci':'c8c7','san':'Bc7','effects':[{'kind':'attack_loose_piece',
                    'text':'Bc7 attacks your undefended rook on h2'}]}]},
            {'role':'played','root_uci':'h2h4','plies':[
                {'uci':'h2h4','san':'Rxh4','effects':[{'kind':'capture','text':'Rxh4 captures a pawn'}]}]}]}
        row = {'best_move_uci':'f6d7','played_move_san':'Rxh4','fen':'',
               'explanatory_lines_json':json.dumps(lines)}
        original = ('Nxd7 takes a free rook. Rxh4 misses that opportunity. '
                    'After Ra7, that capture is no longer available.')
        solution = explain_attempt(row,{'move_uci':'f6d7','move_san':'Nxd7','correct':1},
                                   'Nxd7', saved_explanation=original)['text']
        failed = explain_attempt(row,{'move_uci':'h2h4','move_san':'Rxh4','correct':0},
                                 'Nxd7',saved_explanation=original)['text']
        self.assertEqual(solution, 'Nxd7 takes a free rook. Your opponent can respond with Bc7, '
                                   'which attacks your undefended rook on h2.')
        self.assertEqual(failed,'Rxh4 captures a pawn.')
        self.assertNotIn('Ra7', solution)
        self.assertNotIn('Bc7', failed)


if __name__ == '__main__': unittest.main()
