"""Pure SQLite / narrative regressions: no Flask or Stockfish required."""
import sqlite3
import unittest

from coach_benchmark import ensure_cohort, snapshot_completed_refresh, benchmark_status, benchmark_manifest
from coaching.narrative_composition.continuation_coach import _checking_cycle, explain_attempt


def ply(san,uci,fen,effects=()):
    return {'san':san,'uci':uci,'fen_after':fen,'effects':[
        {'kind':e,'text':f'{san} gives check'} for e in effects]}


class FrozenBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE training_positions(id INTEGER PRIMARY KEY,job_id INTEGER,
              fen TEXT,category TEXT,learning_mode TEXT,estimated_rating INTEGER,
              learned INTEGER,coaching_version TEXT,coach_explanation TEXT,coach_prompt TEXT);
            CREATE TABLE position_motif_taxonomy(position_id INTEGER PRIMARY KEY,
              motif_key TEXT,context_key TEXT,move_type_key TEXT);
            CREATE TABLE coach_benchmark_cohorts(job_id INTEGER PRIMARY KEY,
              selection_version TEXT DEFAULT 'v1-stratified-hash',source_count INTEGER,sample_size INTEGER);
            CREATE TABLE coach_benchmark_positions(job_id INTEGER,position_id INTEGER,ordinal INTEGER,
              fen TEXT,category TEXT,learning_mode TEXT,
              PRIMARY KEY(job_id,position_id),UNIQUE(job_id,ordinal));
            CREATE TABLE coach_benchmark_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id INTEGER,
              coaching_version TEXT,taxonomy_version TEXT,expected_positions INTEGER,
              captured_positions INTEGER,completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(job_id,coaching_version));
            CREATE TABLE coach_benchmark_snapshots(run_id INTEGER,position_id INTEGER,
              explanation TEXT,coach_prompt TEXT,motif_key TEXT,context_key TEXT,
              move_type_key TEXT,PRIMARY KEY(run_id,position_id));
            CREATE TABLE feedback_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_position_id INTEGER,continuation_id TEXT,feedback_type TEXT,
              coaching_version TEXT,rating INTEGER);
        ''')
        for i in range(1,81):
            self.db.execute('''INSERT INTO training_positions VALUES(?,1,?,?,?,?,?,?,?,?)''',
                (i,f'test-FEN-{i}', 'major_blunder' if i%3 else 'correct',
                 'blunders' if i%3 else 'excellent',850 if i%2 else 2100,
                 i%2,'v31',f'v31-{i}',f'prompt-{i}'))

    def test_frozen_cohort_and_versioned_immutable_snapshots(self):
        self.assertEqual(ensure_cohort(self.db,1),36)
        original=[r['id'] for r in benchmark_manifest(self.db,1)]
        self.assertEqual(len(set(original)),36)
        self.assertEqual(ensure_cohort(self.db,1),36)
        self.db.execute("INSERT INTO training_positions VALUES(99,1,'later','correct','excellent',1000,0,'v31','later','later')")
        self.assertEqual([r['id'] for r in benchmark_manifest(self.db,1)],original)
        self.assertEqual(snapshot_completed_refresh(self.db,1,'v31','3.3'),36)
        self.db.execute("UPDATE training_positions SET coach_explanation='changed' WHERE job_id=1")
        self.assertEqual(snapshot_completed_refresh(self.db,1,'v31','3.3'),0)
        first=self.db.execute('''SELECT explanation FROM coach_benchmark_snapshots
           WHERE run_id=1 AND position_id=?''',(original[0],)).fetchone()[0]
        self.assertEqual(first,f'v31-{original[0]}')
        self.db.execute("UPDATE training_positions SET coaching_version='v33' WHERE job_id=1")
        self.assertEqual(snapshot_completed_refresh(self.db,1,'v33','3.3'),36)
        status=benchmark_status(self.db,1)
        self.assertEqual([v['coaching_version'] for v in status['versions']],['v31','v33'])
        self.assertEqual((status['size'],status['available']), (36,36))

    def test_matched_ratings_use_identical_position_continuation_pairs(self):
        ensure_cohort(self.db,1)
        ids=[r['id'] for r in benchmark_manifest(self.db,1)]
        snapshot_completed_refresh(self.db,1,'v31','3.3')
        self.db.execute("UPDATE training_positions SET coaching_version='v33' WHERE job_id=1")
        snapshot_completed_refresh(self.db,1,'v33','3.4')
        a,b=ids[:2]
        for version,rating,position,move in [
                ('v31',-1,a,'solving'),('v31',1,b,'solving'),
                ('v33',1,a,'solving'),('v33',1,b,'other'),
                ('v33',-1,b,'solving')]:
            self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(?,?,'explanation',?,?)",
                (position,move,version,rating))
        comparison=benchmark_status(self.db,1)['comparisons'][0]
        self.assertEqual(comparison['paired_messages'],2)
        self.assertEqual(comparison['before_approval_pct'],50)
        self.assertEqual(comparison['after_approval_pct'],50)
        self.assertEqual(comparison['paired_positions_with_snapshots'],36)

    def test_only_actual_votes_enter_approval_denominator_and_repeat_votes_collapse(self):
        ensure_cohort(self.db,1)
        snapshot_completed_refresh(self.db,1,'v31','3.3')
        original=benchmark_manifest(self.db,1)
        a,b=original[0]['id'],original[1]['id']
        self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(?,'solving','explanation','v31',-1)",(a,))
        self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(?,'solving','explanation','v31',1)",(a,))
        self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(?,'solving','explanation','v31',-1)",(b,))
        self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(99,'solving','explanation','v31',1)")
        s=benchmark_status(self.db,1)['versions'][0]
        self.assertEqual((s['rated_messages'],s['positive'],s['approval_pct']),(2,1,50.0))
        self.assertEqual(s['expected'],36)
        self.db.execute("INSERT INTO feedback_events(source_position_id,continuation_id,feedback_type,coaching_version,rating) VALUES(?,'solving','explanation','v31',0)",(a,))
        s=benchmark_status(self.db,1)['versions'][0]
        self.assertEqual((s['rated_messages'],s['positive'],s['approval_pct']),(1,0,0.0))


class CycleTests(unittest.TestCase):
    def test_series_of_checks_alone_is_not_perpetual(self):
        line={'start_fen':'K  w - - 0 1','plies':[
            ply('Qh5+','d1h5',f'p{i} w - - 0 1',('check',) if i%2==0 else ())
            for i in range(7)]}
        text=_checking_cycle(line)
        self.assertIn('not established',text)
        self.assertNotIn('a draw by',text)

    def test_repeated_position_suggests_pattern_then_confirmed_threefold(self):
        head='start w - - 0 1'
        positions=['p1 b - - 0 1','p2 w - - 0 1',head,'p3 w - - 0 1',
                   'p1 b - - 0 1','p2 w - - 0 1',head]
        line={'start_fen':head,'plies':[ply('Qh5+','d1h5',fen,('check',) if i%2==0 else ())
            for i,fen in enumerate(positions)]}
        self.assertIn('threefold repetition can be claimed',_checking_cycle(line))
        line['plies']=line['plies'][:5]
        # Still 3 checks but no position appears three times.
        self.assertIn('possibility',_checking_cycle(line))


if __name__=='__main__': unittest.main()

# Additional verification of the real startup SCHEMA without importing
# python-chess (unavailable in isolated CI environments).
class SqliteSchemaUpgradeTests(unittest.TestCase):
    def test_benchmark_tables_exist_in_full_production_schema(self):
        import ast
        from pathlib import Path
        tree=ast.parse((Path(__file__).resolve().parents[1]/'db.py').read_text())
        schema=next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(schema)
        for table in ('coach_benchmark_cohorts','coach_benchmark_positions',
                      'coach_benchmark_runs','coach_benchmark_snapshots'):
            self.assertIsNotNone(db.execute('SELECT name FROM sqlite_master WHERE name=?',(table,)).fetchone())
