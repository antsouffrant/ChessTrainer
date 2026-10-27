"""Full schema: restart purges only one list's derived state via FK cascade."""
import ast
import sqlite3
import unittest
from pathlib import Path

from process_policy import restart_analysis
from app_settings import get_settings

ROOT=Path(__file__).resolve().parents[1]


def schema():
    tree=ast.parse((ROOT/'db.py').read_text())
    return next(node.value.value for node in tree.body if isinstance(node,ast.Assign)
                if any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in node.targets))


class CleanRestartTests(unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(':memory:')
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(schema())
        self.addCleanup(db.close)
        self.db=db
        db.execute("INSERT INTO accounts(provider,username) VALUES('lichess','anna')")
        db.execute("INSERT INTO learning_concepts(key,name,family,description) VALUES('fork','Fork','Tactics','A fork')")
        for i in (1,2):
            db.execute("INSERT INTO analysis_jobs(account_id,date_range,game_types,positions_found,games_retrieved) VALUES(1,'month','[]',1,23)")
            db.execute("INSERT INTO retrieval_processes(job_id,status) VALUES(?,'complete')",(i,))
            db.execute("INSERT INTO metadata_processes(job_id,status,cursor) VALUES(?,'complete',12)",(i,))
            db.execute("INSERT INTO training_positions(job_id,game_id,category,fen,user_color,move_number,best_move_uci,learned) VALUES(?,?,'mistake',?,'white',12,'d2d4',1)", (i,f'game{i}',f'fen{i}'))
            db.execute("INSERT INTO position_concepts(position_id,concept_key,confidence,classifier_version) VALUES(?,'fork',0.9,'old')",(i,))
            db.execute("INSERT INTO position_feedback(position_id,account_id,category,rating) VALUES(?,1,'motif',-1)",(i,))
            db.execute("INSERT INTO coach_threads(account_id,position_id) VALUES(1,?)",(i,))
            db.execute("INSERT INTO coach_messages(thread_id,role,content) VALUES(?,'assistant','Sample answer')",(i,))
            db.execute("INSERT INTO coach_message_feedback(message_id,account_id,position_id,rating) VALUES(?,1,?,1)",(i,i))
            db.execute("INSERT INTO analyzed_games(account_id,game_id,source_job_id) VALUES(1,?,?)",(f'game{i}',i))
            db.execute("INSERT INTO analysis_candidates(job_id,game_id,ply) VALUES(?,?,4)",(i,f'game{i}'))
        db.commit()

    def test_restart_clears_only_selected_list(self):
        restart_analysis(self.db,1,get_settings(self.db),queued=False)
        for table,cond in [('training_positions','job_id'),('analysis_candidates','job_id'),
                           ('analyzed_games','source_job_id')]:
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE {cond}=1').fetchone()[0],0)
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE {cond}=2').fetchone()[0],1)
        for table,foreign in [('position_concepts','position_id'),('position_feedback','position_id'),
                              ('coach_threads','position_id'),('coach_message_feedback','position_id')]:
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE {foreign}=1').fetchone()[0],0)
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE {foreign}=2').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coach_messages').fetchone()[0],1)
        job=self.db.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone()
        self.assertEqual((job['positions_found'],job['checkpoint_game_index'],job['force_reanalysis'],job['games_retrieved']), (0,0,1,23))
        self.assertEqual(self.db.execute('SELECT status FROM metadata_processes WHERE job_id=1').fetchone()[0],'idle')
        self.assertEqual(self.db.execute('SELECT status FROM retrieval_processes WHERE job_id=1').fetchone()[0],'complete')
        self.assertEqual(self.db.execute('SELECT positions_found FROM analysis_jobs WHERE id=2').fetchone()[0],1)

if __name__=='__main__':unittest.main()
