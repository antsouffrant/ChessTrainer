# Player learning metrics — v61

**Player** (`/player`) is a learning-progress dashboard, separate from **Coach** (coaching quality) and **Process** (analysis/retrieval status).

## Source-of-truth model

- `training_positions` remains the curriculum snapshot (`learned`, FEN, opening, current primary motif). Existing attempts counters are retained for compatibility, but are *not* used to reconstruct historical solve time or first-try success.
- `player_solve_sessions` is one genuine attempt cycle of a single puzzle. It is created on the **first legal submitted move**, never on display, browsing, or opening Player. It contains the opening/motif snapshot at first attempt, game list, lesson context, number of attempts, first-try result, solve status and active duration. Repeated practice after a reset creates another session without deleting earlier sessions.
- `player_solve_attempts` is an append-only event log of each legal attempted move in a session (`move_uci`, ordinal, correct flag, active time since previous attempt). This can support additional future metrics (hint use, accuracy by mode, retention, etc.) without altering the existing session/summary model.
- A manual reset/learned toggle closes an incomplete session as `abandoned_at` rather than misclassifying a later replay as part of the same attempt cycle. A completed session is immutable.

## Timing semantics

The Training page measures elapsed active time beginning when the *actionable puzzle* is ready. The clock pauses when the document is hidden or its window is not focused, and while awaiting the server's move evaluation. The client sends the elapsed duration with each legal move attempt. The server validates its numeric range and accumulates durations for a session. `max_puzzle_solve_seconds` (Settings, default 300 seconds) is snapshotted when the session begins. Completed solves with missing, zero or over-limit active time keep their attempt/solved data, but `solve_seconds` is NULL and the solve is omitted from time averages. Browser timing is a convenience metric and is not tamper-proof.

If a puzzle is displayed but never attempted, **no activity row exists**, even if the user leaves the tab open. If the user navigates away before making an attempt, its unsubmitted exposure time is not persisted. Old `training_positions.attempts` remain intact; new event history begins with this version and is not backfilled with fabricated durations or first-try outcomes.

## Metric definitions

- **Total positions:** count of matching training positions, regardless of activity.
- **Learned positions:** count of matching positions currently marked learned (including legacy statuses and manually marked learned puzzles).
- **Attempted positions:** unique matching positions with at least one session.
- **Total attempts:** total legal submitted moves across all tracked sessions.
- **First-time solve rate:** positions solved on their **very first attempted move of their first ever tracked session**, divided by distinct attempted positions. Repetition of an already-solved puzzle does not inflate the first-time rate.
- **Attempts per solve:** average number of legal attempted moves in completed sessions; repeated completed sessions each count as one solve. Incomplete sessions contribute to total attempts but not this average.
- **Average solve time:** mean of valid, positive `solve_seconds` across completed sessions. The excluded count is reported.
- **Attempt histogram:** completed sessions grouped by number of attempts (1, 2, 3, 4, 5+), after applying filters.
- **Trend:** completed sessions and first-time first-try success by date of session start.

Filters: game list, opening, **current** primary motif, learning mode, individual position ID. For historical audits, CSV also includes the *at-first-attempt* primary motif snapshot; after metadata refresh it may differ from the current motif used for filtering. Session and attempt CSV files export all matching recorded data, including incomplete and abandoned sessions. Attempt CSV captures the per-move events.

## Compatibility and reset behavior

- No game retrieval, reanalysis or metadata refresh is needed to activate Player tracking.
- The SQLite tables are created with `CREATE TABLE IF NOT EXISTS`, preserving old records.
- **Refresh Metadata** preserves Player history. **Coach feedback reset** is independent. **Restart Analysis** deliberately deletes derived training positions and cascades their associated Player activity, so export Player CSVs before restarting if needed.
- Tests: `python -m unittest discover -s tests -p 'test_player_learning_v61.py'` and `node tests/test_player_ui_v61.cjs`.

## Clock-in/out opt-out (v62)

The Training progress header has a **Learning stats on/off** toggle (on by default).
This preference is saved in the browser across game lists. When off, a legal
puzzle move still updates the existing learned/attempts counters but supplies
`track_learning=false` to the server, so no Player session or attempt event is
created. The client stops its timer immediately. Clocking out abandons any
open Player session (preserving existing events) and clocking back in starts
fresh on the next legal move. Both an explicit clock-out endpoint and a fresh
session flag on the next attempt protect against delayed/out-of-order requests.
An untouched puzzle never creates a Player event. Time spent while clocked out
is never reconstructed. The app does not have enough information to call an
untracked practice session a first-time solve; first-try statistics remain
explicitly scoped to recorded practice attempts.

Regression tests: `node tests/test_player_clock_toggle_v62.cjs`,
`python -m unittest discover -s tests -p 'test_player_clock_in_v62.py'`.


## Player exports and independent reset (v63)

The Player header offers **Sessions CSV** (`GET /api/player/sessions.csv`) and
**Attempt events CSV** (`GET /api/player/attempts.csv`). Both exports use the
current dashboard filters and include every matching row (not just the recent
sessions preview). Download **both** before resetting if you need a backup.
Even when empty, the exports retain their column headers.

**Reset Player records** (`POST /api/player/records/reset`) requires a two-step
UI confirmation, including typing `RESET PLAYER`. With a selected game list,
only its `player_solve_sessions` and their child `player_solve_attempts` are
deleted; with no game list selected, all Player history is deleted. This is
**intentionally scoped by game list only**: motif/opening/mode/position filters
are not applied to deletion, as the confirmation text makes clear. The server
checks for a valid list ID before modifying anything.

The reset does **not** modify `training_positions.learned`, legacy
`training_positions.attempts`, analysis evaluations, PGNs, positions, or any
Coach feedback. Thus `learned_positions` can remain nonzero while tracked
`attempted_positions` becomes zero. The next legal training attempt creates a
fresh session and starts a new first-encounter measurement for the recorded
history. This reset is irreversible without a prior database backup or export.

Tests: `python -m unittest discover -s tests -p 'test_player_reset_v63.py'`
and `node tests/test_player_reset_ui_v63.cjs`.
