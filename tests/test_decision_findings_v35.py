"""v35 evidence-grounded explanation/learning contracts, no Stockfish needed."""
import json
import unittest
from coaching.narrative_composition.decision_pipeline import coach_decision
from coaching.coaching_refresh.version import COACHING_VERSION
from coaching.coaching_validation.narrative_validator import validate_narrative
from coaching.narrative_composition.pedagogical_narrative import compose_finding
from coaching.conceptual_understanding.decision_comparator import DecisionFinding


def line(root, san, effects=(), reply=None, reply_effects=(), later=None, later_effects=()):
    plies=[{'uci':root,'san':san,'effects':[{'kind':k,'text':t} for k,t in effects]}]
    if reply:
        plies.append({'uci':reply[0],'san':reply[1],
                      'effects':[{'kind':k,'text':t} for k,t in reply_effects]})
    if later:
        plies.append({'uci':later[0],'san':later[1],
                      'effects':[{'kind':k,'text':t} for k,t in later_effects]})
    return {'root_uci':root,'role':'recommended','plies':plies}


def row(lines, best='g1f3', best_san='Nf3', motif='fork', **more):
    data=dict(fen='8/8/8/8/8/8/8/8 w - - 0 1',best_move_uci=best,
       best_move_san=best_san,explanatory_lines_json=json.dumps({'lines':lines}),
       motif_key=motif,mate_before=None)
    data.update(more)
    return data


def speak(record,uci,san,correct):
    return coach_decision(record,{'move_uci':uci,'move_san':san,'correct':int(correct)},
                          correct=correct,motif_key=record.get('motif_key'))

class PedagogicalCoachingV35(unittest.TestCase):
    def test_one_finding_not_four_ply_transcription(self):
        r=row([line('g1f3','Nf3',[('fork','Nf3 attacks the queen on d4 and rook on h8 together')],
                 reply=('d4c5','Qc5'),reply_effects=[('check_evasion','Qc5 gets out of check')],
                 later=('f3e5','Ne5'),later_effects=[('capture','Ne5 captures a pawn on e5')])])
        out=speak(r,'g1f3','Nf3',True)
        self.assertEqual(out['purpose'],'explanation')
        self.assertIn('queen on d4 and rook on h8',out['text'])
        self.assertNotIn('Qc5',out['text'])
        self.assertNotIn('Ne5',out['text'])
        self.assertLessEqual(len(out['text'].split()),55)
        self.assertEqual(out['motif_alignment'],'motif_grounded')
        self.assertEqual(out['coaching_version'],COACHING_VERSION)

    def test_failed_attempt_learns_from_refutation(self):
        r=row([line('e2e4','e4',reply=('g8f6','Nf6+'),
                 reply_effects=[('fork','Nf6+ attacks the king on e4 and rook on h1 together')])])
        out=speak(r,'e2e4','e4',False)
        self.assertEqual(out['purpose'],'learning')
        self.assertIn('e4 allows Nf6+',out['text'])
        self.assertIn('king on e4 and rook',out['text'])
        self.assertNotIn('you can then play',out['text'].lower())
        self.assertLessEqual(len(out['text'].split()),55)

    def test_no_refutation_teaches_missed_best_move(self):
        best=line('g1f3','Nf3',[('fork','Nf3 attacks the queen on d4 and rook on h8 together')])
        inferior=line('e2e4','e4',reply=('d7d5','d5'))
        out=speak(row([best,inferior]),'e2e4','e4',False)
        self.assertIn('e4 misses Nf3',out['text'])
        self.assertIn('queen on d4 and rook',out['text'])
        self.assertNotIn('allows d5',out['text'])

    def test_specific_motif_requires_matching_evidence(self):
        r=row([line('g1f3','Nf3',[('capture','Nf3 captures a pawn on f3')])],motif='fork')
        out=speak(r,'g1f3','Nf3',True)
        self.assertNotIn('fork',out['text'].lower())
        self.assertEqual(out['motif_alignment'],'motif_unverified')

    def test_wrong_branch_root_is_not_blended(self):
        wrong=line('e2e4','e4',[('fork','e4 forks the opponent king and rook')])
        r=row([wrong],best='g1f3')
        out=speak(r,'g1f3','Nf3',True)
        self.assertNotIn('forks',out['text'])
        self.assertEqual(out['finding_kind'],'insufficient')

    def test_verified_mate_score_is_coherent(self):
        r=row([line('g1f3','Nf3',[('check','Nf3 gives check')])],
               motif='mating_net',mate_before=3)
        out=speak(r,'g1f3','Nf3',True)
        self.assertIn('forces mate in 3',out['text'])
        self.assertNotIn('can then',out['text'])

    def test_pawn_san_keeps_lowercase(self):
        r=row([line('e2e4','e4',[('capture','e4 captures the pawn on e4')])],
              best='e2e4',best_san='e4')
        out=speak(r,'e2e4','e4',True)
        self.assertTrue(out['text'].startswith('e4 '),out['text'])
        self.assertFalse(out['validation_problems'])

    def test_prose_limit_and_empty_finding(self):
        f=DecisionFinding('e2e4','e4','learning',None,None,None,'Nf3',False,'fork')
        text=compose_finding(f)
        self.assertFalse(validate_narrative(f,text))
        self.assertLessEqual(len(text.split()),55)

    def test_presolve_hint_is_not_the_postsolve_reason(self):
        from coaching.narrative_composition.coaching import generate_coaching_text
        branch=line('g1f3','Nf3',[('fork','Nf3 attacks queen and rook together')])
        prompt, explanation=generate_coaching_text(
            fen='8/8/8/8/8/8/8/8 w - - 0 1',best_move_uci='g1f3',
            best_move_san='Nf3',category='excellent_move',
            explanatory_lines_json=json.dumps({'lines':[branch]}))
        self.assertIn('strong choice',prompt)
        self.assertIn('queen and rook',explanation)
        self.assertNotIn('queen and rook',prompt)

    def test_no_rewrite_of_frozen_previous_model_recaps(self):
        from coaching.narrative_composition.coach_session_recap import refresh_saved_recaps
        class UntouchableDB:
            def execute(self,*a,**kw):
                raise AssertionError('The archived recap must never be rewritten')
        self.assertEqual(refresh_saved_recaps(UntouchableDB(),
            {'coaching_version':'rules-v34-version-scoped-cache'}),0)

    def test_incidental_recapture_is_not_a_refutation(self):
        # A pawn capture followed by a normal recapture does not prove a
        # wrong move was a blunder; prefer the verified missed opportunity.
        best=line('g1f3','Nf3',[('fork','Nf3 attacks the rook and king together')])
        traded=line('e2e4','e4',[('capture','e4 captures a pawn')],
                    reply=('d5e4','dxe4'),
                    reply_effects=[('recapture','dxe4 recaptures the pawn')])
        text=speak(row([best,traded]),'e2e4','e4',False)['text']
        self.assertIn('misses Nf3',text)
        self.assertNotIn('allows dxe4',text)

if __name__=='__main__':unittest.main()
