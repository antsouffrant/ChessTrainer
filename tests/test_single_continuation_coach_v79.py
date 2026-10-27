"""Branch-isolation and evidence-based narrative without a Stockfish dependency."""
import json
import unittest
from coaching.narrative_composition.continuation_coach import branch_evidence, explain_attempt

class SingleContinuationTests(unittest.TestCase):
    ROOT = {'best_move_uci':'e2e4','best_move_san':'e4','played_move_san':'d4',
        'fen':'', 'coach_explanation':'e4 increases central control.'}

    def data(self, lines):
        return dict(self.ROOT, explanatory_lines_json=json.dumps({'lines':lines}))

    def attempt(self, move='d2d4', san='d4', correct=False, reply=None, pv=None):
        return dict(move_uci=move, move_san=san, correct=int(correct),
                    best_reply_san=reply, from_saved_line=1 if move=='d2d4' else 0,
                    verified_pv_json=json.dumps(pv) if pv else None)

    def test_material_loss_is_explained_in_the_actual_branch(self):
        r = self.data([
            {'root_uci':'e2e4','role':'recommended','plies':[
                {'uci':'e2e4','san':'e4','effects':[{'kind':'fork','text':'e4 attacks rook and bishop'}]}]},
            {'root_uci':'d2d4','role':'played','plies':[
                {'uci':'d2d4','san':'d4','effects':[{'kind':'capture','text':'d4 captures a pawn'}]},
                {'uci':'c8g4','san':'Bg4','effects':[{'kind':'discovered_attack','text':'Bg4 reveals a bishop attack on your queen'}]},
                {'uci':'f1e2','san':'Be2','effects':[]}]}])
        c = explain_attempt(r,self.attempt(reply='Bg4'),'e4',saved_explanation='e4 attacks rook and bishop.')
        self.assertIn('d4 captures a pawn',c['text'])
        self.assertIn('opponent can respond with Bg4',c['text'])
        self.assertIn('queen',c['text'])
        self.assertNotIn('rook and bishop',c['text'])
        self.assertNotIn('solution threshold',c['text'])

    def test_capture_recapture_is_not_described_as_a_free_piece(self):
        r=self.data([{'root_uci':'d2d4','role':'played','plies':[
            {'uci':'d2d4','san':'d4','effects':[{'kind':'capture','text':'d4 captures the bishop on d4'}]},
            {'uci':'d8d4','san':'Qxd4','effects':[{'kind':'capture','text':'Qxd4 captures your rook on d4'}]}]}])
        text=explain_attempt(r,self.attempt(reply='Qxd4'),'e4')['text']
        self.assertIn('captures the bishop',text)
        self.assertIn('captures your rook',text)
        self.assertNotIn('free bishop',text)

    def test_reply_and_effect_always_come_from_same_saved_branch(self):
        r=self.data([{'root_uci':'d2d4','role':'played','plies':[
            {'uci':'d2d4','san':'d4','effects':[{'kind':'check','text':'d4 gives check'}]},
            {'uci':'d7d5','san':'d5','effects':[{'kind':'check','text':'d5 gives check'}]}]}])
        c=explain_attempt(r,self.attempt(reply='Qh4+'),'e4')
        self.assertIn('d5',c['text'])
        self.assertNotIn('Qh4+',c['text'])

    def test_followup_is_not_claimed_for_opponent(self):
        r=self.data([{'root_uci':'e2e4','role':'recommended','plies':[
            {'uci':'e2e4','san':'e4','effects':[{'kind':'mate_threat','text':'e4 threatens mate with Qh5#'}]},
            {'uci':'d7d5','san':'d5','effects':[]},
            {'uci':'e4d5','san':'exd5','effects':[{'kind':'capture','text':'exd5 captures the pawn on d5'}]}]}])
        c=explain_attempt(r,self.attempt('e2e4','e4',True),'e4')
        self.assertIn('threatens mate',c['text'])
        self.assertIn('you can then continue with exd5',c['text'].lower())

    def test_no_evidence_never_claims_unsupported_tactic(self):
        c=explain_attempt(self.data([]),self.attempt('a2a3','a3'),'e4',
                          saved_explanation='e4 wins a queen.')
        self.assertNotIn('wins a queen',c['text'])
        self.assertNotIn('solution threshold',c['text'])

    def test_new_pv_must_start_with_attempted_move(self):
        r=self.data([])
        bad=self.attempt(pv=['e2e4','e7e5'])
        self.assertIsNone(branch_evidence(r, 'd2d4', bad))

if __name__=='__main__': unittest.main()
