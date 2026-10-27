"""Evaluation taxonomy corrections remain visible independently of global learned state."""
import unittest
from test_evaluation_reporting_v99 import EvaluationReportingTests
from evaluation_runs import record_evaluation_attempt
from feedback_history import append_feedback
from feedback_analytics import (taxonomy_change_rates, coaching_metric_chart,
    evaluation_taxonomy_rows, coach_change_population, report_rows, current_taxonomy_status)
from coach_benchmark import evaluation_run_metrics, benchmark_comparison

class EvaluationChangeRateTests(unittest.TestCase):
    def setUp(self):
        EvaluationReportingTests.setUp(self)
        self.db.execute("""UPDATE coach_benchmark_snapshots SET
            context_key='attack', move_type_key='tactical', motif_key='fork'
            WHERE run_id=(SELECT benchmark_run_id FROM evaluation_runs WHERE id=?)""",(self.two,))
        for pid in self.positions:
            record_evaluation_attempt(self.db,self.two,pid,True,'e2e4')

    def choice(self,pid,field,selection,rating=-1,run=None,version='v34'):
        append_feedback(self.db,pid,'taxonomy_'+field,rating,
            coaching_version=version,evaluation_run_id=run or self.two,
            model_key={'motif':'fork','context':'attack','move_type':'tactical'}[field],
            selected_key=selection)

    def test_36_solved_unlearned_have_real_denominator(self):
        self.assertEqual(self.db.execute('SELECT SUM(learned) FROM training_positions').fetchone()[0],0)
        self.choice(self.positions[0],'context','defend')
        self.choice(self.positions[0],'motif','pin')
        self.choice(self.positions[1],'motif','fork',1)  # explicit model agreement
        self.choice(self.positions[2],'motif','pin')
        self.choice(self.positions[2],'motif','',0)  # withdrawal wins
        counts=taxonomy_change_rates(self.db,{'coaching_version':'v34'})
        self.assertEqual((counts['context']['solved'],counts['context']['changed']),(36,1))
        self.assertEqual((counts['motif']['solved'],counts['motif']['changed']),(36,1))
        self.assertEqual(counts['move_type']['changed'],0)
        report=evaluation_run_metrics(self.db,1)[0]
        self.assertEqual((report['solved'],report['taxonomy_any_changed']),(36,1))
        self.assertEqual(report['taxonomy_any_change_pct'],2.8)
        self.assertEqual(report['taxonomy_context_change_pct'],2.8)
        self.assertEqual(report['taxonomy_motif_change_pct'],2.8)
        self.assertEqual(report['taxonomy_move_type_change_pct'],0.0)
        self.assertEqual(benchmark_comparison(self.db,1)['evaluation_runs'][0]['taxonomy_any_changed'],1)

    def test_general_coach_change_charts_include_evaluations(self):
        self.choice(self.positions[0],'motif','pin')
        by_version=coaching_metric_chart(self.db,{'coaching_version':'v34'},
                                         metric='changes',group_by='version')['rows']
        self.assertEqual(len(by_version),1)
        self.assertEqual((by_version[0]['numerator'],by_version[0]['denominator']),(1,36))
        fields=coaching_metric_chart(self.db,metric='changes',group_by='taxonomy_field')['rows']
        self.assertEqual({r['key']:(r['numerator'],r['denominator']) for r in fields},
                         {'context':(0,36),'move_type':(0,36),'motif':(1,36)})
        grouped=coaching_metric_chart(self.db,metric='changes',group_by='motif')['rows']
        self.assertEqual((grouped[0]['numerator'],grouped[0]['denominator']),(1,36))
        self.assertEqual(len(coach_change_population(self.db)),36)

    def test_archived_run_and_unscoped_votes_do_not_change_benchmark(self):
        p=self.positions[0]
        self.choice(p,'context','defend',run=self.one)
        append_feedback(self.db,p,'taxonomy_motif',-1,coaching_version='v34',selected_key='pin')
        self.assertEqual(evaluation_run_metrics(self.db,1)[0]['taxonomy_any_changed'],0)
        self.assertEqual(taxonomy_change_rates(self.db)['context']['changed'],0)
        self.assertEqual(taxonomy_change_rates(self.db)['motif']['changed'],0)

    def test_frozen_snapshot_attribution_across_versions(self):
        p=self.positions[0]
        self.choice(p,'motif','pin')
        self.db.execute("UPDATE training_positions SET coaching_version='v35' WHERE job_id=1")
        self.assertEqual(taxonomy_change_rates(self.db,{'coaching_version':'v34'})['motif']['changed'],1)
        self.assertEqual(evaluation_run_metrics(self.db,1)[0]['taxonomy_motif_changed'],1)
        self.assertEqual(evaluation_taxonomy_rows(self.db,{'coaching_version':'v35'}),[])

    def test_general_feedback_excludes_superseded_run_but_keeps_audit(self):
        p=self.positions[0]
        self.choice(p,'motif','pin',run=self.one)
        self.choice(p,'motif','pin')
        normal=report_rows(self.db,{'coaching_version':'v34'})
        voted=[r for r in normal if r['feedback_type']=='taxonomy_motif']
        self.assertEqual(len(voted),1)
        self.assertEqual(voted[0]['evaluation_run_id'],self.two)
        self.assertEqual(current_taxonomy_status(voted[0]),'changed')
        audit=report_rows(self.db,{'history':'all','coaching_version':'v34'})
        self.assertEqual(len([r for r in audit if r['feedback_type']=='taxonomy_motif']),2)

    def test_same_position_normal_learned_and_evaluation_count_once(self):
        p=self.positions[0]
        self.db.execute('UPDATE training_positions SET learned=1 WHERE id=?',(p,))
        self.choice(p,'context','defend')
        self.assertEqual(len(coach_change_population(self.db)),36)
        self.assertEqual(taxonomy_change_rates(self.db)['context']['changed'],1)

if __name__=='__main__':unittest.main()
