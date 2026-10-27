"""No Flask/Stockfish dependency: exercise coaching-only purge transaction."""
import ast
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from coaching.coaching_refresh.coaching_cache import clear_coaching_cache

ROOT = Path(__file__).resolve().parents[1]


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class CacheResetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'database.sqlite'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE analysis_jobs(id INTEGER PRIMARY KEY, status TEXT, metadata_refreshed_at TEXT);
                CREATE TABLE metadata_processes(job_id INTEGER PRIMARY KEY, status TEXT, cursor INTEGER,
                    processed INTEGER, total INTEGER, updated INTEGER, failed INTEGER,
                    without_pgn INTEGER, perf_json TEXT, error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE retrieval_processes(job_id INTEGER PRIMARY KEY, status TEXT);
                CREATE TABLE training_positions(id INTEGER PRIMARY KEY, job_id INTEGER, learned INTEGER, attempts INTEGER,
                    eval_before_cp INTEGER, best_pv_uci TEXT, alternative_pvs_json TEXT,
                    coach_prompt TEXT, coach_explanation TEXT, coaching_version TEXT,
                    proactive_coach_json TEXT, explanatory_lines_json TEXT, critical_events_json TEXT);
                CREATE TABLE position_concepts(position_id INTEGER, concept_key TEXT);
                CREATE TABLE position_motif_taxonomy(position_id INTEGER, motif_key TEXT);
                CREATE TABLE coach_threads(id INTEGER PRIMARY KEY, position_id INTEGER, account_id INTEGER);
                CREATE TABLE coach_messages(id INTEGER PRIMARY KEY, thread_id INTEGER,
                    content TEXT, FOREIGN KEY(thread_id) REFERENCES coach_threads(id) ON DELETE CASCADE);
                CREATE TABLE coach_message_feedback(message_id INTEGER, position_id INTEGER,
                    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE);
                CREATE TABLE coach_solve_recaps(position_id INTEGER, message_id INTEGER,
                    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE);
                CREATE TABLE coach_proactive_history(job_id INTEGER, message_id INTEGER,
                    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE);
                CREATE TABLE coach_proactive_spotlights(job_id INTEGER, message_id INTEGER,
                    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE);
                CREATE TABLE concept_evidence(position_id INTEGER);
                CREATE TABLE coach_claims(position_id INTEGER);
                CREATE TABLE coach_board_attempts(position_id INTEGER, move_uci TEXT);
                CREATE TABLE continuation_explanation_feedback(position_id INTEGER, coaching_version TEXT);
                CREATE TABLE position_feedback(position_id INTEGER, coaching_version TEXT);
                CREATE TABLE position_taxonomy_feedback(position_id INTEGER, coaching_version_at_vote TEXT);
                INSERT INTO analysis_jobs VALUES(1,'complete','yesterday');
                INSERT INTO analysis_jobs VALUES(2,'complete','yesterday');
                INSERT INTO retrieval_processes VALUES(1,'complete');
                INSERT INTO retrieval_processes VALUES(2,'complete');
                INSERT INTO training_positions VALUES(10,1,1,3,220,'e2e4 e7e5','[]',
                    'old prompt','old explanation','v30','probes','lines','critical');
                INSERT INTO training_positions VALUES(20,2,1,4,190,'d2d4 d7d5','[]',
                    'untouched','untouched','v30','probes','lines','critical');
                INSERT INTO position_concepts VALUES(10,'skewer');
                INSERT INTO position_concepts VALUES(20,'pin');
                INSERT INTO position_motif_taxonomy VALUES(10,'skewer');
                INSERT INTO position_motif_taxonomy VALUES(20,'pin');
                INSERT INTO coach_threads VALUES(1,10,7);
                INSERT INTO coach_threads VALUES(2,20,7);
                INSERT INTO coach_messages VALUES(1,1,'stale recap');
                INSERT INTO coach_messages VALUES(2,2,'other list');
                INSERT INTO coach_message_feedback VALUES(1,10);
                INSERT INTO coach_message_feedback VALUES(2,20);
                INSERT INTO coach_solve_recaps VALUES(10,1);
                INSERT INTO coach_proactive_history VALUES(1,1);
                INSERT INTO coach_proactive_spotlights VALUES(1,1);
                INSERT INTO concept_evidence VALUES(10);
                INSERT INTO coach_claims VALUES(10);
                INSERT INTO coach_board_attempts VALUES(10,'e2e4');
                INSERT INTO continuation_explanation_feedback VALUES(10,'rules-v30');
                INSERT INTO position_feedback VALUES(10,'rules-v30');
                INSERT INTO position_taxonomy_feedback VALUES(10,'rules-v30');
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def test_cache_reset_is_list_scoped_and_preserves_evidence_and_votes(self):
        with self.connect() as db:
            counts = clear_coaching_cache(db, 1)
            self.assertEqual((counts['positions'], counts['chat_messages'], counts['chat_feedback']), (1,1,1))
            db.commit()
        with self.connect() as db:
            p = db.execute('SELECT * FROM training_positions WHERE id=10').fetchone()
            self.assertEqual((p['learned'],p['attempts'],p['eval_before_cp'],p['best_pv_uci']),
                             (1,3,220,'e2e4 e7e5'))
            for name in ('coach_prompt','coach_explanation','coaching_version',
                         'proactive_coach_json','explanatory_lines_json','critical_events_json'):
                self.assertIsNone(p[name], name)
            self.assertEqual(db.execute('SELECT coach_explanation FROM training_positions WHERE id=20').fetchone()[0], 'untouched')
            self.assertEqual(db.execute('SELECT status FROM metadata_processes WHERE job_id=1').fetchone()[0],'needs_refresh')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coach_message_feedback').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coach_solve_recaps').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM position_concepts WHERE position_id=10').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM position_motif_taxonomy WHERE position_id=10').fetchone()[0],0)
            for table in ('coach_board_attempts','position_feedback','continuation_explanation_feedback','position_taxonomy_feedback'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table + ' WHERE position_id=10').fetchone()[0],1)

    def test_clear_is_idempotent_without_reclaiming_other_lists(self):
        with self.connect() as db:
            clear_coaching_cache(db,1)
            clear_coaching_cache(db,1)
            db.commit()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],1)

    def test_version_mismatch_hides_old_votes_without_erasing_history(self):
        tree = ast.parse((ROOT/'feedback_analytics.py').read_text())
        names = {'position_votes','position_feedback_details','continuation_votes',
                 'continuation_feedback_details','taxonomy_feedback_choices'}
        funcs = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        from feedback_history import current_feedback, migrate_legacy_feedback
        env = {'CONTEXTS':{'attack':'Attacking Plans'},
               'MOVE_TYPES':{'tactical':'Tactical Calculation'},
               'current_feedback':current_feedback,
               'POSITION_KINDS':('position','explanation','motif'),
               'taxonomy_feedback_options':lambda db: []}
        exec(compile(ast.Module(body=funcs, type_ignores=[]),'feedback_analytics.py','exec'), env)
        # Use the actual production schema (retrieved from the source AST) to
        # verify historical rows are queryable after regeneration.
        db_tree = ast.parse((ROOT/'db.py').read_text())
        schema = next(n.value.value for n in db_tree.body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.executescript(schema)
        db.execute("INSERT INTO accounts(id,provider,username) VALUES(1,'lichess','test')")
        db.execute("INSERT INTO analysis_jobs(id,account_id,date_range,game_types) VALUES(1,1,'all','[]')")
        db.execute("""INSERT INTO training_positions(id,job_id,category,fen,user_color,move_number,
                best_move_uci,coaching_version) VALUES(1,1,'blunder','empty','white',1,'e2e4','v30')""")
        db.execute("""INSERT INTO position_feedback(position_id,account_id,category,rating,
                coaching_version,suggested_text) VALUES(1,1,'explanation',-1,'v30','old issue')""")
        db.execute("""INSERT INTO continuation_explanation_feedback(position_id,account_id,
                continuation_key,rating,coaching_version,suggested_text)
                VALUES(1,1,'d2d4',1,'v30',NULL)""")
        db.execute("""INSERT INTO position_taxonomy_feedback(position_id,account_id,
                field_key,selected_key,model_key_at_vote,coaching_version_at_vote)
                VALUES(1,1,'context','attack','attack','v30')""")
        migrate_legacy_feedback(db)
        self.assertEqual(env['position_votes'](db,1),{'explanation':-1})
        self.assertEqual(env['continuation_votes'](db,1),{'d2d4':1})
        self.assertEqual(env['taxonomy_feedback_choices'](db,1)['selected'], {'context':'attack'})
        db.execute("UPDATE training_positions SET coaching_version='v31' WHERE id=1")
        self.assertEqual(env['position_votes'](db,1),{})
        self.assertEqual(env['position_feedback_details'](db,1),{})
        self.assertEqual(env['continuation_votes'](db,1),{})
        self.assertEqual(env['continuation_feedback_details'](db,1),{})
        self.assertEqual(env['taxonomy_feedback_choices'](db,1)['selected'],{})
        self.assertEqual(db.execute('SELECT COUNT(*) FROM continuation_explanation_feedback').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM position_feedback').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM position_taxonomy_feedback').fetchone()[0],1)

    def test_cannot_clear_nonexistent_job(self):
        with self.connect() as db:
            with self.assertRaises(LookupError):
                clear_coaching_cache(db,999)

    def test_route_requires_confirmation_and_blocks_active_work(self):
        tree = ast.parse((ROOT / 'app.py').read_text())
        func = next(f for f in tree.body if isinstance(f,ast.FunctionDef) and f.name == 'process_clear_coaching_cache')
        func.decorator_list = []
        class FakeRequest:
            payload = {}
            def get_json(self, silent=True):
                return self.payload
        request = FakeRequest()
        env = {'request':request,'jsonify':lambda value:value,
               'PROCESS_LOCK':threading.Lock(),'connect':self.connect,
               'clear_coaching_cache':clear_coaching_cache}
        exec(compile(ast.Module(body=[func], type_ignores=[]), 'app.py', 'exec'),env)
        route = env['process_clear_coaching_cache']
        self.assertEqual(route(1)[1],400)
        request.payload = {'confirmation':'CLEAR COACHING CACHE'}
        with self.connect() as db:
            db.execute("UPDATE analysis_jobs SET status='running' WHERE id=1")
        self.assertEqual(route(1)[1],409)
        with self.connect() as db:
            db.execute("UPDATE analysis_jobs SET status='complete' WHERE id=1")
            db.execute("UPDATE retrieval_processes SET status='running' WHERE job_id=1")
        self.assertEqual(route(1)[1],409)
        with self.connect() as db:
            db.execute("UPDATE retrieval_processes SET status='complete' WHERE job_id=1")
        env['PROCESS_LOCK'].acquire()
        try:
            self.assertEqual(route(1)[1],409)
        finally:
            env['PROCESS_LOCK'].release()
        result = route(1)
        self.assertEqual(result['status'],'needs_refresh')
        self.assertEqual(result['cleared']['chat_feedback'],1)


if __name__ == '__main__':
    unittest.main()
