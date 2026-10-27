"""Evaluation retirement, access, and featured-playlist regression tests (v101)."""
import sqlite3
import unittest
from evaluation_runs import (
    retire_v33_evaluation_feedback, resolve_run, run_position, run_history,
    featured_evaluation,
)

V33 = "rules-v33-fixed-cohorts-perpetual-check"
V34 = "rules-v34-version-scoped-cache"


def connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE evaluation_runs(
          id INTEGER PRIMARY KEY, job_id INTEGER, coaching_version TEXT,
          benchmark_run_id INTEGER, status TEXT, created_at TEXT,
          completed_at TEXT);
        CREATE TABLE evaluation_run_positions(
          run_id INTEGER, position_id INTEGER, status TEXT, attempts INTEGER);
        CREATE TABLE feedback_events(
          id INTEGER PRIMARY KEY, evaluation_run_id INTEGER,
          coaching_version TEXT, feedback_type TEXT, rating INTEGER);
        CREATE TABLE coach_benchmark_runs(
          id INTEGER PRIMARY KEY, job_id INTEGER, coaching_version TEXT,
          expected_positions INTEGER, captured_positions INTEGER);
    """)
    conn.executemany("INSERT INTO evaluation_runs VALUES(?,?,?,?,?,?,?)", [
        (1, 10, V33, 101, "active", "2026-10-19", None),
        (2, 10, V34, 102, "completed", "2026-10-20", "2026-10-20"),
        (3, 11, V34, 103, "active", "2026-10-21", None),
    ])
    conn.executemany("INSERT INTO evaluation_run_positions VALUES(?,?,?,?)", [
        (1, 100, "solved", 1), (1, 101, "pending", 0),
        (2, 100, "solved", 1), (2, 101, "solved", 1),
        (3, 201, "solved", 1), (3, 202, "pending", 0),
    ])
    conn.executemany("INSERT INTO feedback_events VALUES(?,?,?,?,?)", [
        (1, 1, V33, "explanation", -1),
        (2, None, V33, "explanation", 1),
        (3, 2, V34, "explanation", 1),
        (4, 3, V34, "taxonomy_motif", -1),
    ])
    conn.executemany("INSERT INTO coach_benchmark_runs VALUES(?,?,?,?,?)", [
        (101, 10, V33, 2, 2), (102, 10, V34, 2, 2),
        (103, 11, V34, 2, 2)
    ])
    return conn


class EvaluationLifecycle(unittest.TestCase):
    def test_only_evaluation_scoped_v33_votes_removed(self):
        with connection() as conn:
            self.assertEqual(retire_v33_evaluation_feedback(conn), 1)
            self.assertEqual(
                [tuple(row) for row in conn.execute(
                    "SELECT id,evaluation_run_id FROM feedback_events ORDER BY id")],
                [(2, None), (3, 2), (4, 3)])
            self.assertEqual(conn.execute(
                "SELECT status FROM evaluation_runs WHERE id=1").fetchone()[0],
                "superseded")
            self.assertEqual(retire_v33_evaluation_feedback(conn), 0)

    def test_frozen_run_cannot_be_accessed_or_edited(self):
        with connection() as conn:
            self.assertIsNone(resolve_run(conn, 10, 1, V34))
            self.assertIsNone(run_position(conn, 1, 100, 10, V34))
            self.assertEqual(resolve_run(conn, 10, 2, V34)["id"], 2)
            self.assertEqual(run_position(conn, 2, 100, 10, V34)["status"], "solved")
            self.assertEqual([x["id"] for x in run_history(conn, 10, V34)], [2])

    def test_featured_when_unfinished_but_not_completed(self):
        with connection() as conn:
            self.assertIsNone(featured_evaluation(conn, 10, V34))
            feature = featured_evaluation(conn, 11, V34)
            self.assertEqual((feature["solved"], feature["total"]), (1, 2))
            self.assertEqual(feature["run_id"], 3)
            self.assertIn("run_id=3", feature["href"])
            conn.execute("UPDATE evaluation_runs SET status='completed' WHERE id=3")
            self.assertIsNone(featured_evaluation(conn, 11, V34))
            conn.execute("UPDATE evaluation_runs SET status='active' WHERE id=3")
            conn.execute("UPDATE evaluation_run_positions SET status='solved' WHERE run_id=3")
            self.assertIsNone(featured_evaluation(conn, 11, V34))

    def test_prepared_benchmark_without_run_links_to_process(self):
        with connection() as conn:
            conn.execute("DELETE FROM evaluation_runs WHERE id=3")
            feature = featured_evaluation(conn, 11, V34)
            self.assertFalse(feature["ready"])
            self.assertIn("/processes", feature["href"])


if __name__ == "__main__":
    unittest.main()
