> **v76 — Balanced All Positions training:** A newly created, unfiltered general training playlist uses a randomized ordering that interleaves primary learning motifs and openings, with learning mode as an additional diversity signal. It preserves every eligible unlearned position and approximately preserves the underlying category frequencies while avoiding repetitive streaks. The complete session order is pinned for Last/Next and page reloads. Lesson, opening, individual-position and explicitly sorted playlists are unchanged. No game retrieval, Stockfish reanalysis, coaching refresh or database migration is required.

> **v75 — Separate Coach rate charts:** Coach now displays two independently grouped charts with controls inside their headings: **Changes** (default: primary learning motif, any corrected taxonomy field per solved position) and **Approval** (default: feedback area, showing Training positions, Explanations, and Chat coaching thumbs). Neither chart has an additional metric selector. The separate chat-approval summary card is hidden while chat history and approval-chart data remain available. CSV exports, regression data, historical versions, and feedback records are unchanged. See `COACH_METRICS.md`. No metadata refresh, reanalysis, or schema migration required.

> **v74 — Consolidated Coach metrics:** Thumbs-based summary cards are explicitly labeled **Approval rate**, while taxonomy context/type/motif cards remain **Change rate**. Four separate category tables have been replaced by a configurable chart (opening, motif, lesson, version, etc.) showing two **parallel 100%-stacked bars** on the same 0–100% axis. Aggregate chart approval uses *any approved thumbs category per rated solved position*; aggregate taxonomy change uses *any currently corrected field per solved position*. See `COACH_METRICS.md` for denominators, historical-version caveats, and filters. No database migration, metadata refresh, or reanalysis is required.

> **v73 — Historical Coach version filters:** Coach version options now combine the active position versions with saved historical feedback versions. Filtering uses the coaching version recorded with the rating/selection rather than the mutable version on the refreshed position. New taxonomy selections and chat ratings save their coach-version snapshot. Older chat/taxonomy records lacking a snapshot are shown using the current position version with an explicit CSV provenance flag. The existing latest-feedback-per-item behavior remains unchanged. No metadata refresh or game reanalysis is necessary.

> **v69 — Inline taxonomy feedback pills:** Training now displays clickable pill-shaped context, optional move type, and primary motif directly in the coaching path, replacing the separate feedback dropdown panel. Pill selections can be changed or cleared; they update only feedback, preserving the model prediction at the moment of the vote. Coach and Regression CSV exports include current and at-selection hierarchy, legacy motif mapping, and user corrections. Thumbs remain for position relevance, explanation and coach chat. No reanalysis required.

# Personal Chess Trainer — v76

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
| **Training** | Replay positions, test your moves, inspect Stockfish continuations, rate position relevance/explanations, and provide editable context, move-type and learning-motif feedback. New general playlists shuffle evenly across openings/motifs; resumed sessions keep their saved order. |
| **Lessons** | Explore the primary-motif curriculum, filters, progress and saved lesson playlists. |
| **Openings** | Review opening families and training-position playlists. |
| **Process** | Manage per-list Retrieval, Analysis and Metadata Refresh, including pause/resume and clean restart. |
| **Coach** | Review thumbs-based approval rates for positions, explanations, and interactive coaching, together with context/type/motif change rates. Compare categories in one chart, export CSV, or reset feedback. |
| **Player** | View learning progress by game list, motif and opening: first-time solve accuracy, attempts per solve, active solve time, trends, histograms, and session/attempt CSV exports. |
| **Settings** | Configure presentation and analysis settings, including Stockfish behavior. |

## Guided feedback and regression candidates

After solving a position, the three taxonomy attributes are **clickable, pill-shaped native dropdowns directly in the displayed learning path** (not a separate feedback panel):

- **Position context:** Attacking Plans or Defensive Resources.
- **Move type (optional):** Tactical Calculation, Strategic Comprehension, or No tactical/strategic qualifier. A two-level path has a small **+ Move type** pill.
- **Learning motif:** all active, alphabetized canonical curriculum labels, including evaluation-outcome fallbacks.

The pills initially display the coach's labels. You can choose **Confirm coach** to record agreement, choose a different label to propose a correction, or choose **Use coach's label (clear feedback)** to withdraw that field's feedback. The pill immediately shows the proposed choice, with a check mark for saved feedback, but that **does not modify** the classifier's stored taxonomy, lessons, Stockfish evaluations, or coaching explanation. Only the feedback record changes. Reselecting overwrites that field's previous vote rather than creating a new one. Each saved record contains the model's at-selection prediction, selected label, taxonomy version, **coaching version at selection**, and timestamps. **Refresh Metadata never overwrites these user-feedback snapshots.**

Thumbs-up/down remain for **position relevance**, **explanations**, and **coaching chat**. An explanation or chat downvote can include suggested replacement text; position downvotes can describe low learning relevance. Historical primary-motif thumbs and optional replacements collected in v67 and earlier are kept as legacy records and are still included in exports, but no longer appear as a Trainer rating control. Active dropdown motifs use only the cleaned canonical catalog.

**Coach version history:** A metadata refresh updates the *current* coaching version of the position, but does not erase version snapshots attached to saved feedback. The Coach version dropdown and version-grouped approval chart now use snapshot versions when available and include versions retained only by past ratings. CSV fields `coaching_version` (saved snapshot), `report_coaching_version` (used by the filter), `coaching_version_source` (`feedback_snapshot` or `current_position_fallback`) and `current_coaching_version` distinguish them. Earlier chat and taxonomy ratings created before v73 did not store a coach-version snapshot; they cannot be reliably assigned to their original historical version. Reselecting a field or rating replaces that item's most recent feedback and its version snapshot; this is not a complete event history. Taxonomy change-rate cards remain current-position statistics, not versioned historical accuracy metrics.

**Coach → Download CSV** contains all filtered feedback including the three new dropdown categories, agreement versus correction, original predicted labels, selected user labels, *current* context/move-type/motif after metadata refresh, canonical mapping columns for legacy motif records, game positions, FEN, Stockfish evidence and version metadata. **Coach → Regression candidates** includes corrected taxonomy selections and thumbs-down text corrections; confirmations and blank selections are excluded. These are human-proposed labels, not independently verified ground truth. Coach supports additional context/move-type/feedback-type filters. The rating dashboard keeps thumbs and dropdown agreement distinct.

**Training taxonomy pills** display the coach's suggested context, an optional Tactical/Strategic move type, and the specific primary motif. Click/tap a pill (or use the keyboard) to choose a different canonical label, explicitly agree with the coach, or clear feedback. A two-level path includes a subtle **+ Move type** pill for adding a qualifier. Corrections show a check mark and accent color, but **do not alter the model's classification, Stockfish evidence, lessons, or deep analysis**. The feedback is saved separately and already flows to Coach and regression exports.

**Coach → Reset feedback** deletes all thumb and taxonomy feedback for the chosen list (or all lists), preserving games, positions, analysis, learned state and Player activity. Restart Analysis still deletes derived positions and their feedback. Export first if you want an archive of earlier responses.

## Data processing and resets

A new game list **retrieves a PGN batch once**, then starts analysis. Analyze uses saved PGNs, commits progress at completed-game boundaries, and can resume from checkpoints. Additional passes refine analysis; retrieval is not repeated unless creating a new list or deliberately retrying a failed new retrieval.

| Control | Behavior |
| --- | --- |
| **Pause / Resume Analysis** | Continue at the last completed-game checkpoint, keeping results and progress. |
| **Analyze Again** | Continue with a deeper refinement pass using saved games. |
| **Refresh Metadata** | Run independent Stockfish reply probes and regenerate explanations/motifs from saved training positions; preserve root evaluations, learning progress and feedback. |
| **Restart Analysis** | **Destructive for one list.** Remove that list's derived training positions, evaluated results, learned progress, conversations and ratings, then start fresh Stockfish analysis from its existing PGN. Other lists are unaffected. |
| **Training taxonomy pills** display the coach's suggested context, an optional Tactical/Strategic move type, and the specific primary motif. Click/tap a pill (or use the keyboard) to choose a different canonical label, explicitly agree with the coach, or clear feedback. A two-level path includes a subtle **+ Move type** pill for adding a qualifier. Corrections show a check mark and accent color, but **do not alter the model's classification, Stockfish evidence, lessons, or deep analysis**. The feedback is saved separately and already flows to Coach and regression exports.

**Coach → Reset feedback** | Delete thumbs ratings only (selected game list, or all if unfiltered). Positions, engine data and chat content remain. |

**Export feedback CSV before a destructive restart or reset if you need a record of your previous coaching iteration.** Restart and feedback reset require confirmation.

## Explanation and motif pipeline

`analysis.py` obtains Stockfish evaluations and stores candidate positions. Context and variation modules (`decision_context.py`, `critical_moments.py`, `pv_reasoning.py`, `loose_piece_provenance.py`) distinguish root facts, short continuations, and vulnerabilities created by a move. `semantic_coaching.py` prioritizes one supported chess idea, `coaching.py` composes the user-facing explanation, `learning.py` selects motifs, and `metadata_refresh.py` updates derived text/classifications using new independent Stockfish coaching probes without rerunning game screening or deep root analysis.

See **`COACHING_PIPELINE.md`** for evidence standards, motif distinctions, endgame support, and reset semantics. Optional exact Syzygy tablebase recognition is enabled with `CHESS_SYZYGY_PATH`; ordinary centipawn evaluations do not prove endgame results.

## Project structure

- `app.py` — Flask routes, background-process coordination, application startup.
- `db.py`, `feedback_analytics.py`, `app_settings.py` — persistence, Coach reporting, settings.
- `analysis.py`, `engine_service.py`, `retrieval.py`, `metadata_refresh.py` — game ingestion and evaluation.
- `balanced_playlist.py` — fast, randomized, representative sequencing for a newly created All Positions training session.
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

## v70 solved review and motif refinements

- Returning to a learned position via Last/Next restores its saved explanation and explanation-rating controls immediately; the solution endpoint can refresh the details without leaving the puzzle in an unsolved hint state.
- Focusing or toggling Stockfish does not disable left/right board history or Shift+arrow puzzle navigation; typing fields and feedback menus still own their arrow keys.
- Canonical learning-motif pills list named chess concepts alphabetically, then append evaluation-outcome fallback labels alphabetically.
- New **Blocking** tactical motif requires an actual legal check interposition or interrupted sliding attack on valuable material. **Discovery** denotes a stationary slider revealed by another piece; **Double Attack** denotes two actionable threats from the mover.
- **Material Loss** is the general evidenced-loss label, distinct from newly hanging one's mover and from saving a loose piece already present at the root. A defended **strategic sacrifice** is supported with additional differential evidence, not by a blanket motif remapping.

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
installing the dependencies in `requirements.txt`. **Refresh Metadata** uses Stockfish to re-test opponent replies without redoing game evaluation; **Restart
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


### Proactive Stockfish coaching (v65)

After Analyze has identified and deep-confirmed training positions, an independent
Stockfish coaching probe tests credible replies to the engine-recommended and
actual game moves. The saved probe evidence (`proactive_coach_json`) contains
board context, observed move effects, scored reply variations, and supported
short-range mechanisms. **Screening, deep evaluation, position selection, root
evaluations/PVs, solve history, Coach feedback, and Player history are not
replaced by this follow-up evidence.** The reactive chat remains separate.

**Process → Refresh Metadata** now requires a configured local Stockfish
executable. It re-runs bounded coaching probes and regenerates curriculum labels
and explanations without reanalyzing the games or retrieving PGNs. Refresh runs
in a worker with per-position search budgets, bounded three-position batches,
probes outside database write transactions, persisted pause/resume progress, and
visible errors when Stockfish cannot start. Configure the extra coaching time,
number of opponent replies and search-depth cap in Settings → Proactive coaching.

The probes are supplementary evidence, not proof that every defense fails. A
verified, near-root refutation may replace a vague generic explanation or motif,
while already-supported precise explanations remain intact. See
`PROACTIVE_COACHING.md` for architecture and evidence limits.

### v71 — Games / Positions / Coaching performance

The Process page now separates **Games (Game Retrieval)**, **Positions (Position Evaluation)**, and **Coaching (Coaching Analysis)**. It reports measured stage times after new processing work, and reuses exact-input coaching Stockfish probes on a later unchanged Refresh Metadata. Coaching still regenerates current explanations, contexts, and motifs from the saved evidence. PGN parsing is reused across metadata batches. See [PROCESS_PERFORMANCE.md](PROCESS_PERFORMANCE.md) for the performance breakdown, cache invalidation rules, and local profiling workflow. No game reanalysis is needed to use the updated Coaching process.

### v72 · Coach taxonomy change-rate reporting

Coach reports the percentage of **solved** positions whose current taxonomy
feedback disagrees with the coach for each of context, move type, and motif.
Solved positions without edits are included as unchanged. Changing a pill
back to the coach's choice (or clearing it) removes that field from the changed
count. Legacy motif thumbs are absent from the UI but remain in exports.
Use **Taxonomy CSV** on Coach to audit all solved positions, including matches
without dropdown feedback. No metadata refresh or migration required.
