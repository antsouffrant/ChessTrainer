# Chess Trainer v89 — SQLite connection lifetime hotfix

## Problem
The v88 Process listing endpoint (`GET /api/processes`) fetched jobs in a
`with connect() as conn:` block but called `benchmark_status(conn, job_id)`
outside that block. The application uses a custom `_ClosingConnection` whose
context manager **closes** the database connection upon exit, causing
`sqlite3.ProgrammingError: Cannot operate on a closed database` at the
`coach_benchmark_cohorts` query.

A second instance of the same lifetime mistake appeared in the solved-position
endpoint (`GET /api/positions/<id>/solution`): taxonomy was read using a closed
connection after the surrounding block.

## Fix
- Build every per-list benchmark status inside the live connection context in
  `process_listing()`. Serialize the already-fetched rows after closing.
- Fetch the current position taxonomy inside the live connection context in
  `position_solution()`, then serialize it from the local snapshot.
- Add `tests/test_process_benchmark_connection_v89.py`, which executes both
  real route function bodies with the production `_ClosingConnection` against
  a complete production SQLite schema and verifies the expected close behavior.

## Compatibility
No database migration, cache purge, or coaching refresh is needed. All previous
positions, Stockfish analysis, benchmark memberships, model snapshots, and
immutable feedback events remain unchanged. The coaching/taxonomy model version
is still the v88 version (v33 / 3.4).

## Verification
- New regression suite: 5 passed.
- Process UI benchmark test: passed.
- Python compilation: passed.
- Full Flask/Stockfish integration testing could not be executed in this
  environment because Flask and python-chess are not installed.
