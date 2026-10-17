# Personal Chess Trainer — v61

A local Flask application that retrieves Lichess games, evaluates them with Stockfish, and builds training positions, lessons, opening playlists, and position-aware chess coaching. Saved game lists, evaluations, training progress, and thumbs feedback use a local SQLite database.

## Requirements and launch

- Python 3.10+ and the packages in `requirements.txt` (Flask, requests, python-chess).
- A compatible Stockfish executable placed in `stockfish/` or configured in app settings.
- Network access for the initial Lichess import. Previously retrieved games can be analyzed offline.

From the extracted project directory:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. Keep the `data/` folder when installing a newer source archive: it stores `chess_trainer.sqlite3` and saved PGN batches (`data/batches/`). Neither imported games nor engine binaries nor Syzygy tablebase files are included in the source ZIP.

## App pages

| Page | Purpose |
| --- | --- |
| **Home** | Connect Lichess and manage saved game lists. Training is enabled after a list has training positions. |
| **Training** | Replay positions, test your moves, inspect Stockfish continuations, and rate training positions, explanations, and primary motifs. |
| **Lessons** | Explore the primary-motif curriculum, filters, progress and saved lesson playlists. |
| **Openings** | Review opening families and training-position playlists. |
| **Process** | Manage per-list Retrieval, Analysis and Metadata Refresh, including pause/resume and clean restart. |
| **Coach** | Review thumbs feedback for positions, explanations, motifs, and interactive coaching; filter, compare versions, export CSV, or reset feedback. |
| **Player** | View learning progress by game list, motif and opening: first-time solve accuracy, attempts per solve, active solve time, trends, histograms, and session/attempt CSV exports. |
| **Settings** | Configure presentation and analysis settings, including Stockfish behavior. |

## Guided feedback and regression candidates

After solving a position, the Training page accepts thumbs-up/down ratings for the position, explanation, and primary motif. Each chat coach reply can also be rated. On a **thumbs-down**, a correction dialog opens:

- **Position:** explain why the puzzle is not helpful or how it should change.
- **Explanation or chat response:** write what the coach should have said instead.
- **Primary motif:** choose one better motif from the active built-in/personal catalog.

The downvote is saved immediately. **Not now** dismisses the optional correction without removing the vote; use **Edit suggestion** to reopen the editor while keeping the downvote. Clicking an already-selected thumb again **unchecks it**, deleting the rating and its correction entirely. Switching to thumbs-up clears any correction from the database; switching back to thumbs-down begins with an empty correction. One latest rating is stored per item/category, not one row per click. No record is stored when a rating is unchecked, and the withdrawn vote no longer appears in Coach statistics or exports. All primary-motif options are alphabetized by motif name. Typing and arrow-key editing in feedback boxes take precedence over board shortcuts.

**Coach → Download CSV** includes all matching ratings and suggestions, rated coaching snapshots, FENs and engine lines, current coaching, version metadata, and a stable regression-case identifier. **Coach → Regression candidates** exports only downvotes with saved corrections, respecting Coach filters. They are user-proposed examples awaiting verification, *not* automatically validated ground truth. The export includes `review_status=proposed` for corrected examples, ready for curating into gold-standard fixtures. Export before **Restart Analysis** or **Reset feedback**: both delete relevant saved feedback.

## Data processing and resets

A new game list **retrieves a PGN batch once**, then starts analysis. Analyze uses saved PGNs, commits progress at completed-game boundaries, and can resume from checkpoints. Additional passes refine analysis; retrieval is not repeated unless creating a new list or deliberately retrying a failed new retrieval.

| Control | Behavior |
| --- | --- |
| **Pause / Resume Analysis** | Continue at the last completed-game checkpoint, keeping results and progress. |
| **Analyze Again** | Continue with a deeper refinement pass using saved games. |
| **Refresh Metadata** | Regenerate derived explanations/motifs from saved evaluations, without rerunning Stockfish or clearing learning/feedback. |
| **Restart Analysis** | **Destructive for one list.** Remove that list's derived training positions, evaluated results, learned progress, conversations and ratings, then start fresh Stockfish analysis from its existing PGN. Other lists are unaffected. |
| **Coach → Reset feedback** | Delete thumbs ratings only (selected game list, or all if unfiltered). Positions, engine data and chat content remain. |

**Export feedback CSV before a destructive restart or reset if you need a record of your previous coaching iteration.** Restart and feedback reset require confirmation.

## Explanation and motif pipeline

`analysis.py` obtains Stockfish evaluations and stores candidate positions. Context and variation modules (`decision_context.py`, `critical_moments.py`, `pv_reasoning.py`, `loose_piece_provenance.py`) distinguish root facts, short continuations, and vulnerabilities created by a move. `semantic_coaching.py` prioritizes one supported chess idea, `coaching.py` composes the user-facing explanation, `learning.py` selects motifs, and `metadata_refresh.py` updates derived text/classifications without rerunning Stockfish.

See **`COACHING_PIPELINE.md`** for evidence standards, motif distinctions, endgame support, and reset semantics. Optional exact Syzygy tablebase recognition is enabled with `CHESS_SYZYGY_PATH`; ordinary centipawn evaluations do not prove endgame results.

## Project structure

- `app.py` — Flask routes, background-process coordination, application startup.
- `db.py`, `feedback_analytics.py`, `app_settings.py` — persistence, Coach reporting, settings.
- `analysis.py`, `engine_service.py`, `retrieval.py`, `metadata_refresh.py` — game ingestion and evaluation.
- Coaching modules — deterministic position evidence and generation; see the pipeline document.
- `templates/` — Jinja page templates. `templates/analytics.html` remains the Coach view template for route compatibility.
- `static/styles.css` — shared app styles; `static/coach.css` — responsive Coach page layout, loaded only on Coach; `static/*.js` — page-specific interactions.
- `tests/` — Python database/chess logic and Node JavaScript UI tests. Tests are preserved for future iterations.
- `MAINTENANCE_AUDIT.md` — v55 source/size review and conservative cleanup policy.

## Testing

After installing the dependencies:

```bash
python -m unittest discover -s tests -v
```

And, with Node installed:

```bash
for test in tests/*.cjs; do node "$test" || exit 1; done
```

On Windows PowerShell, run the `.cjs` tests individually or use `Get-ChildItem tests/*.cjs | ForEach-Object { node $_.FullName }`.

Some tests need a live Stockfish executable or optional tablebases to validate complete integration. A green syntax check alone is not proof that a real-engine workflow succeeds.

## Maintenance policy

This source archive intentionally includes regression tests but excludes runtime caches (`__pycache__`, `*.pyc`), imported personal games, SQLite files, and engine binaries. Obsolete historical release notes are not carried forward in the main README; prior versioned ZIP archives preserve their history. Audit before deleting a source module—most coaching modules are connected despite their overlapping names.

## v57 UI feedback refinements

- Clicking an active 👍 or 👎 removes the rating and deletes any correction associated with it. Click the other thumb to change the rating instead.
- A separate **Edit suggestion** button appears on downvotes so feedback can be refined without unchecking the vote.
- Board arrow-key navigation is suspended while a feedback modal is open or a text field/select is active.
- Motifs in feedback, lesson picker, and lesson listings are alphabetized by name.

The SQLite schema is unchanged; unchecking removes rows instead of storing a zero-valued vote.

### Coaching feedback and regression (v58)

See `FEEDBACK_BENCHMARK.md` for an anonymized 109-record Coach feedback fixture,
a motif hierarchy, near-root refutation scans and an offline regression
reporter. Run `python tools/evaluate_coach_feedback.py --input tests/fixtures/coach_feedback_v58.jsonl --output coach_report.csv` after
installing the dependencies in `requirements.txt`. **Refresh Metadata** uses
the new text and classifier versions without rerunning Stockfish; **Restart
Analysis** is destructive and not needed for this coaching-only update.

## v59 — Direct board analysis after solving

After a puzzle is solved, the displayed board accepts normal click-to-move or drag-and-drop input without requiring the Stockfish checkbox first. The first attempted move switches the board to Analysis and applies that same move to the displayed FEN; no second gesture is necessary. The server validates legal moves and handles queen promotion as the default. The board uses the FEN's active side, which may be the opponent after the learner's correct move. Navigating game history or revisiting solved positions preserves this convenience. Unsolved positions still require the ordinary training move verification. Manual Stockfish toggling remains available, and failed moves leave the analysis board ready for further input.

## Coaching comprehension and regression (v60)

The coaching and primary-motif engines share a causal ranking layer
(`causal_selection.py`). It favors demonstrated near-term tactics and concrete
strategic consequences over generic context or incidental long-PV effects.
`continuation_refutations.py` checks short supported replies and defender
removal, while `semantic_coaching.py` adds positional differentiation for
endgame king activity and demonstrated pawn-structure damage.

See `FEEDBACK_BENCHMARK.md` for the historical 109-record feedback corpus,
the additional 51 proposed correction cases, tests, offline benchmark command,
and caveats about unverified user-proposed corrections. Existing local
feedback and training databases are unchanged; use **Refresh Metadata** to
regenerate current coaching from saved positions and PVs.

## Player learning analytics (v61)

The new Player page uses two SQLite tables: `player_solve_sessions` and `player_solve_attempts`. Each legal training attempt is an event, with a session starting only on the first attempt of an unsolved puzzle. This preserves repeat solve history without collecting statistics from untouched puzzles. A foreground-aware clock accumulates active solving time while the Training page is visible and focused. Puzzle solves exceeding the configurable **Maximum recorded puzzle solve time** (default 300 seconds) are excluded from time averages, but still count as solves. Change the limit in Settings → Trainer. The Player page supports game-list, motif, opening, learning mode, and position filters, plus separate CSV exports for sessions and attempt events.

The first-time solve rate counts only each puzzle's earliest attempted session so replaying an easy puzzle cannot inflate the score. **Existing attempts and learned flags remain in place, but historical first-try accuracy and solve durations cannot be reliably backfilled.** See `LEARNING_PIPELINE.md` for definitions, timestamps, and reset semantics.

### Player tracking clock-in/out (v62)

The Training progress header contains **Learning stats on/off**. The preference is
remembered in the current browser across game lists (default: on). Turning it
off stops the foreground solve timer and ends any unfinished tracked practice
session. Future legal moves still solve puzzles and change the ordinary learned
status and legacy attempts, but do **not** create Player session/attempt events.
Turning it back on begins a fresh tracked session on the next legal attempt.
Already recorded Player history is never deleted by this switch. The Player
dashboard's total/learned positions still reflect ordinary puzzle progress.

Note: First-try statistics describe the first *recorded* training encounter;
training with the clock turned off is intentionally not reconstructible.


### Player data export and reset (v63)

On **Player**, use *Sessions CSV* and *Attempt events CSV* for filtered
exports. *Reset Player records* deletes practice sessions/attempts for the
selected game list, or all lists when unfiltered by game list, after explicit
confirmation. It preserves learned-position flags, engine analysis, game lists,
and Coach feedback. Other Player filters never limit deletion; see
`LEARNING_PIPELINE.md` for the complete data contract. Download both CSVs first.

### v64: evidence-and-purpose coaching

The Coach model now looks for **demonstrated material recovery after a
sacrifice**, and the *positional purpose* of some balanced trades (such as
creating doubled opponent pawns), rather than describing every exchange as
simple simplification or every sacrifice as an unexplained investment.
Straightforward captures and trades remain concise when the saved variations
show no more instructive cause. The motif taxonomy is deliberately stable;
classification and prose use the same ranked causal evidence.

The full 281-rating positive/negative Coach feedback snapshot and reproducible
evaluation process are documented in `FEEDBACK_BENCHMARK.md`. Refresh Metadata
regenerates coaching text and motif assignments **without reanalyzing games**;
previous Coach feedback is retained. Chess-specific tests and benchmark replay
require installing dependencies from `requirements.txt`.

The top navigation keeps your requested order: **Home, Training, Lessons,
Openings, Player, Coach, Process, Settings**.
