"""Manual Analyze must never redo a saved retrieval or erase checkpoint/positions."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from process_policy import queue_analysis

class ProcessPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db=sqlite3.connect(Path(self.tmp.name)/'state.db')
        self.addCleanup(self.db.close)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
            CREATE TABLE analysis_jobs (id INTEGER PRIMARY KEY,status TEXT,
                error TEXT,finished_at TEXT,force_reanalysis INTEGER,max_passes INTEGER,
                current_pass INTEGER,passes_completed INTEGER,checkpoint_pass INTEGER,
                checkpoint_game_index INTEGER,checkpoint_file_offset INTEGER,
                games_processed INTEGER,positions_found INTEGER);
            INSERT INTO analysis_jobs VALUES (1,'paused','old error','yesterday',0,
                4,2,1,2,63,8192,63,9);
        ''')
    def row(self):
        return self.db.execute('SELECT * FROM analysis_jobs WHERE id=1').fetchone()
    def test_pause_stop_error_resume_checkpoint(self):
        for status in ('paused','stopped','error'):
            self.db.execute('UPDATE analysis_jobs SET status=? WHERE id=1',(status,))
            action=queue_analysis(self.db,1,status,completed_passes=1,max_passes=4)
            self.assertEqual(action,'resuming')
            row=self.row()
            self.assertEqual(row['status'],'queued')
            self.assertEqual((row['checkpoint_pass'],row['checkpoint_game_index'],row['checkpoint_file_offset']),(2,63,8192))
            self.assertEqual((row['games_processed'],row['positions_found']),(63,9))
            self.assertIsNone(row['error'])
    def test_completed_analysis_extends_one_pass_without_losing_positions(self):
        self.db.execute("UPDATE analysis_jobs SET status='complete',current_pass=4,passes_completed=4,checkpoint_pass=4,checkpoint_game_index=100,checkpoint_file_offset=123456,games_processed=100 WHERE id=1")
        action=queue_analysis(self.db,1,'complete',completed_passes=4,max_passes=4)
        r=self.row()
        self.assertEqual(action,'refining')
        self.assertEqual((r['max_passes'],r['current_pass'],r['checkpoint_pass']),(5,5,5))
        self.assertEqual((r['checkpoint_game_index'],r['checkpoint_file_offset'],r['games_processed']),(0,0,0))
        self.assertEqual(r['positions_found'],9)
        self.assertEqual(r['force_reanalysis'],0)
if __name__=='__main__':unittest.main()
