"""Post-solve teaching order and board-event chronology without Stockfish."""
import json
import sqlite3
import unittest

from coaching.narrative_composition.continuation_coach import explain_attempt
from coaching.narrative_composition.coach_session_recap import _build_recap
from feedback_history import register_continuation


def ply(san, uci, *effects):
    return {'san': san, 'uci': uci, 'effects': [
        {'kind': kind, 'text': txt} for kind, txt in effects]}


class Version32SequenceTests(unittest.TestCase):
    def test_sacrifice_capture_is_only_explained_after_correct_intermediate_move(self):
        line = [
            ply('Bxf7+', 'c4f7', ('check', 'Bxf7+ gives check'), ('capture','Bxf7+ captures pawn')),
            ply('Kxf7', 'e8f7', ('capture','Kxf7 captures bishop')),
            ply('Ng5+', 'f3g5', ('discovered_attack','Ng5+ reveals the queen attacking a bishop')),
            ply('Ke8', 'f7e8', ('check_evasion','Ke8 legally answers the check')),
            ply('Qxg4', 'd1g4', ('capture','Qxg4 captures the bishop')),
        ]
        row = {'best_move_uci':'c4f7','played_move_san':'Be3','fen':'',
               'explanatory_lines_json':json.dumps({'lines':[
                   {'root_uci':'c4f7','role':'recommended','plies':line}]})}
        note = explain_attempt(row,{'move_uci':'c4f7','move_san':'Bxf7+','correct':1},
            'Bxf7+', saved_explanation='Bxf7+ sacrifices a bishop for a pawn. After Kxf7, Qxg4 wins material.')
        t=note['text']
        self.assertEqual(note['purpose'],'explanation')
        self.assertEqual(t.count('Qxg4'),1)
        self.assertLess(t.index('Kxf7'),t.index('Ng5+'))
        self.assertLess(t.index('Ng5+'),t.index('Ke8'))
        self.assertLess(t.index('Ke8'),t.index('Qxg4'))
        self.assertIn('recaptures on f7',t)
        self.assertNotIn('legally answers',t)

    def test_failed_line_prioritizes_refutation_and_recapture(self):
        line = [
            ply('Qe7','d8e7'),
            ply('bxa4','b3a4',('capture','bxa4 captures the pawn on a4')),
            ply('bxa4','b5a4',('capture','bxa4 captures the pawn on a4')),
            ply('Nb1','c3b1',('attack_loose_piece','Nb1 attacks or exposes the opponent’s undefended pawn on c6')),
        ]
        row = {'best_move_uci':'a4b3','fen':'',
            'explanatory_lines_json':json.dumps({'lines':[{
                'root_uci':'d8e7','role':'played','plies':line}]})}
        note = explain_attempt(row,{'move_uci':'d8e7','move_san':'Qe7','correct':0},'axb3')
        self.assertEqual(note['purpose'],'learning')
        self.assertIn('After Qe7,',note['text'])
        self.assertIn('recaptures on a4', note['text'])
        self.assertLess(note['text'].index('bxa4'), note['text'].index('Nb1'))

    def test_attempted_message_supersedes_same_game_move(self):
        conn = sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        conn.execute('''CREATE TABLE coach_board_attempts(
          id INTEGER PRIMARY KEY, position_id INTEGER,session_key TEXT,
          move_uci TEXT,move_san TEXT,correct INTEGER,from_saved_line INTEGER,
          eval_cp INTEGER,mate INTEGER,best_reply_san TEXT,verified_pv_json TEXT)''')
        for i,uci,san,correct in ((1,'d2d4','d4',0),(2,'e2e4','e4',1)):
            conn.execute('''INSERT INTO coach_board_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                         (i,1,'example_12345',uci,san,correct,1,None,None,None,None))
        row = {'id':1,'best_move_uci':'e2e4','best_move_san':'e4',
               'played_move_uci':'d2d4','played_move_san':'d4',
               'coach_explanation':'e4 controls the center.',
               'coaching_version':'rules-v32-ordered-learning-recaptures',
               'fen':'', 'learning_mode':'mistakes','category':'major_blunder',
               'explanatory_lines_json': json.dumps({'lines':[
                   {'root_uci':'e2e4','role':'recommended','plies':[ply('e4','e2e4')]},
                   {'root_uci':'d2d4','role':'played','plies':[ply('d4','d2d4')]}]})}
        _, raw = _build_recap(conn,row,'example_12345')
        notes=json.loads(raw)['attempt_comments']
        self.assertEqual([n['origin'] for n in notes], ['solving','attempt'])
        self.assertEqual([n['purpose'] for n in notes], ['explanation','learning'])
        self.assertEqual([n['move_uci'] for n in notes], ['e2e4','d2d4'])

    def test_game_feedback_identity_is_separate_from_attempt(self):
        conn=sqlite3.connect(':memory:')
        conn.execute('''CREATE TABLE feedback_continuations(
            continuation_id TEXT PRIMARY KEY,position_key TEXT,move_key TEXT,
            UNIQUE(position_key,move_key))''')
        one=register_continuation(conn,'position_test','d2d4')
        other=register_continuation(conn,'position_test','game:d2d4')
        self.assertNotEqual(one,other)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM feedback_continuations').fetchone()[0],2)


if __name__ == '__main__': unittest.main()
