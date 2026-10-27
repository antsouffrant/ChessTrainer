"""Version migration and stale-probe checks without Flask or python-chess."""
import importlib.util
import json
import sqlite3
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def isolated_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class CacheVersions(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE training_positions(id INTEGER PRIMARY KEY,fen TEXT,
                previous_fen TEXT,opponent_move_uci TEXT,opponent_move_san TEXT,
                played_move_uci TEXT,played_move_san TEXT,best_move_uci TEXT,
                best_move_san TEXT,category TEXT,mate_before INTEGER,
                best_pv_uci TEXT,played_pv_uci TEXT,alternative_pvs_json TEXT,
                eval_before_cp INTEGER,eval_after_cp INTEGER,
                critical_events_json TEXT,explanatory_lines_json TEXT,
                proactive_coach_json TEXT,coaching_version TEXT,
                coach_prompt TEXT,coach_explanation TEXT);
            CREATE TABLE position_concepts(position_id INTEGER,concept_key TEXT,
                confidence REAL,is_primary INTEGER,evidence TEXT);
            CREATE TABLE position_motif_taxonomy(position_id INTEGER,
                context_key TEXT,move_type_key TEXT,motif_key TEXT,
                confidence REAL,evidence TEXT);
            CREATE TABLE coaching_message_cache(position_id INTEGER,
                message_type TEXT, continuation_key TEXT,generation_version TEXT,
                content TEXT,content_sha256 TEXT,evidence_fingerprint TEXT,
                coach_prompt TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(position_id,message_type,continuation_key));
            INSERT INTO training_positions(id,fen,coaching_version,coach_prompt,
               coach_explanation,best_pv_uci) VALUES
               (1,'initial','v33','old prompt','old text','["e2e4"]');
            INSERT INTO position_concepts VALUES(1,'check',.9,1,'old rules');
        ''')
        self.calls=[]
        self.coaching=types.ModuleType('coaching.narrative_composition.coaching')
        self.coaching.COACHING_VERSION='v34'
        def generate(**kwargs):
            self.calls.append(kwargs)
            return 'prompt-'+str(len(self.calls)), 'new-'+str(len(self.calls))
        self.coaching.generate_coaching_text=generate
        self.taxonomy=types.ModuleType('coaching.motif_selection.coaching_taxonomy')
        self.taxonomy.TAXONOMY_VERSION='3.4'
        self.taxonomy.MotifPath=lambda *args:args
        self.mods={'coaching.narrative_composition.coaching':self.coaching,
                   'coaching.motif_selection.coaching_taxonomy':self.taxonomy}
        with patch.dict(sys.modules,self.mods):
            self.module=isolated_module('test_copy_cache_v90','coaching/coaching_refresh/coaching_copy_refresh.py')

    def test_upgraded_model_never_reuses_previous_version(self):
        self.assertFalse(self.module.preserve_previous_coaching_copy(self.db,1))
        self.module.rebuild_coaching_copy(self.db,1)
        self.assertEqual(self.db.execute('SELECT coaching_version,coach_explanation FROM training_positions').fetchone()['coaching_version'],'v34')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coaching_message_cache').fetchone()[0],1)
        self.assertEqual(len(self.calls),1)
        self.module.rebuild_coaching_copy(self.db,1)
        self.assertEqual(len(self.calls),1)  # exact version and same evidence
        self.assertEqual(self.db.execute('SELECT coach_explanation FROM training_positions').fetchone()[0],'new-1')

    def test_changed_evidence_is_not_a_cache_hit(self):
        self.module.rebuild_coaching_copy(self.db,1)
        self.db.execute("UPDATE training_positions SET best_pv_uci='[\"d2d4\"]' WHERE id=1")
        self.module.rebuild_coaching_copy(self.db,1)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coaching_message_cache').fetchone()[0],1)

    def test_same_position_different_model_is_not_cache_hit(self):
        self.module.rebuild_coaching_copy(self.db,1)
        self.module.COACHING_VERSION='v35'
        self.module.rebuild_coaching_copy(self.db,1)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.db.execute('SELECT coaching_version FROM training_positions').fetchone()[0],'v35')

    def test_probe_fingerprint_and_reuse_reject_previous_versions(self):
        fake_chess=types.ModuleType('chess')
        fake_engine=types.ModuleType('chess.engine')
        fake_chess.engine=fake_engine
        for i,name in enumerate(('PAWN','KNIGHT','BISHOP','ROOK','QUEEN','KING'),1):
            setattr(fake_chess,name,i)
        evidence=types.ModuleType('explanatory_evidence')
        evidence.position_context=lambda *a:None
        evidence.board_events=lambda *a:None
        refutations=types.ModuleType('continuation_refutations')
        refutations.scan_branch=lambda *a,**k:None
        modules=dict(self.mods,chess=fake_chess,**{'chess.engine':fake_engine,
            'coaching.board_context.explanatory_evidence':evidence,
            'coaching.conceptual_understanding.continuation_refutations':refutations})
        with patch.dict(sys.modules,modules):
            probe=isolated_module('test_proactive_cache_v90','coaching/board_context/proactive_coaching.py')
            settings={}
            base={'fen':'initial','best_move_uci':'e2e4', 'proactive_coach_json':None}
            key=probe.coaching_probe_cache_key(base,settings,'Engine')
            base['proactive_coach_json']=json.dumps({'version':probe.PROACTIVE_VERSION,
                'coaching_version':'v33','cache_key':key,'branches':[]})
            self.assertIsNone(probe.reusable_coaching_probe(base,settings,'Engine'))
            base['proactive_coach_json']=json.dumps({'version':probe.PROACTIVE_VERSION,
                'coaching_version':'v34','cache_key':key,'branches':[]})
            self.assertIsNotNone(probe.reusable_coaching_probe(base,settings,'Engine'))
            self.coaching.COACHING_VERSION='v35'
            self.assertIsNone(probe.reusable_coaching_probe(base,settings,'Engine'))
            self.assertNotEqual(key,probe.coaching_probe_cache_key(base,settings,'Engine'))

    def test_startup_backfill_does_not_promote_previous_version(self):
        source=(ROOT/'app.py').read_text()
        f=source.split('def backfill_coaching_texts():',1)[1].split('\ndef import_existing_json_if_present():',1)[0]
        self.assertIn('AND coaching_version = ?',f)
        self.assertNotIn('coaching_version <> ?',f)

    def test_probe_refresh_does_not_reuse_old_tested_reply(self):
        source=(ROOT/'coaching/coaching_refresh/metadata_refresh.py').read_text()
        self.assertNotIn("decode_variations(row['explanatory_lines_json'])",source)
        self.assertIn('probe = None',source)

    def test_schema_has_versioned_cache(self):
        import ast
        tree=ast.parse((ROOT/'db.py').read_text())
        schema=next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(schema)
        columns=[r[1] for r in db.execute('PRAGMA table_info(coaching_message_cache)')]
        self.assertIn('evidence_fingerprint',columns)
        self.assertIn('generation_version',columns)
        self.assertIn('message_type',columns)


if __name__=='__main__': unittest.main()

class RecapVersionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE coach_threads(id INTEGER PRIMARY KEY,position_id INTEGER,
                account_id INTEGER);
            CREATE TABLE coach_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,role TEXT,content TEXT,structured_json TEXT);
            CREATE TABLE coach_solve_recaps(position_id INTEGER,session_key TEXT,
                message_id INTEGER,PRIMARY KEY(position_id,session_key));
            CREATE TABLE coach_message_feedback(message_id INTEGER,rating INTEGER);
            CREATE TABLE coaching_message_cache(position_id INTEGER,
                message_type TEXT,continuation_key TEXT,generation_version TEXT,
                content TEXT,content_sha256 TEXT,evidence_fingerprint TEXT,
                coach_prompt TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(position_id,message_type,continuation_key));
        ''')
        self.recap=isolated_module('test_recap_version_v90','coaching/narrative_composition/coach_session_recap.py')
        self.adaptive=types.ModuleType('adaptive_coach')
        def thread(conn,position_id,account_id):
            conn.execute('INSERT OR IGNORE INTO coach_threads VALUES (1,1,42)')
            return 1
        self.adaptive.get_or_create_thread=thread
        self.old={'id':1,'account_id':42,'learned':1,'coaching_version':'v33'}
        self.new={**self.old,'coaching_version':'v34'}
        def build(conn,row,key):
            version=row['coaching_version']
            from coaching.coaching_refresh.message_cache import cache_message
            cache_message(conn,row['id'],'attempted_move','e2e4',version,'attempt-'+version)
            return ('text-'+version, json.dumps({'kind':'solved_attempt_recap',
                'coaching_version':version,'explanation_version':8,
                'attempt_comments':[{'origin':'attempt','move_uci':'e2e4','text':'attempt-'+version}]}))
        self.build=build

    def test_old_recap_does_not_get_reused_or_edited_after_model_upgrade(self):
        with patch.dict(sys.modules,{'coaching.narrative_composition.adaptive_coach':self.adaptive}), patch.object(self.recap,'_build_recap',self.build):
            first=self.recap.save_solved_recap(self.db,self.old,session_key='session_321')
            self.db.execute('INSERT INTO coach_message_feedback VALUES (?,1)',(first['id'],))
            second=self.recap.save_solved_recap(self.db,self.new,session_key='session_321')
            again=self.recap.save_solved_recap(self.db,self.new,session_key='session_321')
        self.assertNotEqual(first['id'],second['id'])
        self.assertTrue(second['created'])
        self.assertFalse(again['created'])
        self.assertEqual(again['id'],second['id'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT content FROM coach_messages WHERE id=?',(first['id'],)).fetchone()[0],'text-v33')
        self.assertEqual(self.db.execute('SELECT rating FROM coach_message_feedback WHERE message_id=?',(first['id'],)).fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT message_id FROM coach_solve_recaps').fetchone()[0],second['id'])

    def test_refresh_does_not_rewrite_prior_version_chat(self):
        self.db.executescript('''
            INSERT INTO coach_threads VALUES (1,1,42);
            INSERT INTO coach_messages (id,thread_id,role,content,structured_json)
                VALUES (100,1,'assistant','old text',
                  '{"kind":"solved_attempt_recap","coaching_version":"v33","explanation_version":6}');
            INSERT INTO coach_solve_recaps VALUES (1,'session_321',100);
        ''')
        with patch.object(self.recap,'_build_recap',side_effect=AssertionError('must not touch old chat')):
            self.assertEqual(self.recap.refresh_saved_recaps(self.db,self.new),0)
        self.assertEqual(self.db.execute('SELECT content FROM coach_messages WHERE id=100').fetchone()[0],'old text')
