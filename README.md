> **v92 evaluation feedback hotfix:** Explanation and continuation thumbs remain visible and saveable after solving a benchmark position, independent of global learned state; feedback save failures are shown inline. No Coaching refresh is needed. See `RELEASE_NOTES_V92.md`.

> **v90 coaching-cache fix:** Coaching probes and explanations are now scoped to `COACHING_VERSION` and an evidence fingerprint. After upgrading, run **Coaching refresh** to create clean v34 results; a manual cache clear is optional unless you also want to erase old chats. See `RELEASE_NOTES_V90.md`.

> **v89 hotfix:** Fixes `sqlite3.ProgrammingError: Cannot operate on a closed database` in the Process benchmark listing and solved-position taxonomy routes. This is a SQLite connection-scope fix only; no cache clearing or coaching refresh is required. See `RELEASE_NOTES_V89.md`.

# Personal Chess Trainer — v88

A local Flask application that retrieves Lichess games, evaluates them with Stockfish, and builds training positions, lessons, opening playlists, and position-aware chess coaching. Saved game lists, evaluations, training progress, and thumbs feedback use a local SQLite database.

## v88 changes

Coaching chat shows a compact solving card followed by one attempted learning card per unique move, then an original-game card only when its move is distinct. The coach differentiates checking sequences from verified threefold repetition and adds a conservative Perpetual Check motif.

The Process view creates a **permanently pinned 36-position diagnostic benchmark cohort** at the first Coaching refresh. The same positions and order can be reopened after refresh; per-version snapshots, approval coverage and *paired* identical-position/continuation ratings support model comparison. Cache clear preserves the frozen benchmark and the append-only feedback ledger. See `RELEASE_NOTES_V88.md` for nuances and known limitations.

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
| **Process** | Manage per-list Retrieval, Analysis, Coaching refresh, coaching-cache invalidation, pause/resume and clean Analysis restart. |
| **Coach** | Review thumbs-based approval rates for positions, explanations, and interactive coaching, together with context/type/motif change rates. Compare categories in one chart, export CSV, or reset feedback. |
| **Player** | View learning progress by game list, motif and opening: first-time solve accuracy, attempts per solve, active solve time, trends, histograms, and session/attempt CSV exports. |
| **Settings** | Configure presentation and analysis settings, including Stockfish behavior. |

## v91: independent evaluation runs and Coach model benchmark

The fixed coaching cohort is a **playlist definition**, not a solved-state source. Every completed Coaching refresh can initialize an independent evaluation run of the same positions. Evaluation attempts and solved flags live under `evaluation_runs`/`evaluation_run_positions`, separate from the account-wide `training_positions.learned` curriculum and Player statistics. The Process view includes **Continue evaluation** and **Start new evaluation**. Each new run starts unanswered even for positions learned earlier. Feedback events can be tied to a run and never disappear on coaching-cache clear.

The Coach view now has a fixed-cohort **model-comparison chart** with game-list and A-versus-B/A-versus-all model selectors, snapshot explanation and taxonomy change rates, matched-continued explanation approvals and motif-correction feedback. Paired, explicitly rated continuations are the approval denominator; unvoted positions do not create feedback. The comparison is read-only and does not require additional Stockfish search. See `RELEASE_NOTES_V91.md`.

## Guided feedback and regression candidates

After solving a position, the three taxonomy attributes are **clickable, pill-shaped native dropdowns directly in the displayed learning path** (not a separate feedback panel):

- **Position context:** Attacking Plans or Defensive Resources.
- **Move type (optional):** Tactical Calculation, Strategic Comprehension, or No tactical/strategic qualifier. A two-level path has a small **+ Move type** pill.
- **Learning motif:** all active, alphabetized canonical curriculum labels, including evaluation-outcome fallbacks.

The pills initially display the coach's labels. You can choose **Confirm coach** to record agreement, choose a different label to propose a correction, or choose **Use coach's label (clear feedback)** to withdraw that field's feedback. The pill immediately shows the proposed choice, with a check mark for saved feedback, but that **does not modify** the classifier's stored taxonomy, lessons, Stockfish evaluations, or coaching explanation. Only the feedback record changes. Reselecting updates the visible field selection, while v86 retains the previous choice as a separate historical feedback event. Each saved record contains the model's at-selection prediction, selected label, taxonomy version, **coaching version at selection**, and timestamps. **Refresh Metadata never overwrites these user-feedback snapshots.**

Thumbs-up/down remain for **position relevance**, **explanations**, and **coaching chat**. An explanation or chat downvote can include suggested replacement text; position downvotes can describe low learning relevance. Historical primary-motif thumbs and optional replacements collected in v67 and earlier are kept as legacy records and are still included in exports, but no longer appear as a Trainer rating control. Active dropdown motifs use only the cleaned canonical catalog.

**Coach version history:** A metadata refresh updates the *current* coaching version of the position, but does not erase version snapshots attached to saved feedback. The Coach version dropdown and version-grouped approval chart now use snapshot versions when available and include versions retained only by past ratings. CSV fields `coaching_version` (saved snapshot), `report_coaching_version` (used by the filter), `coaching_version_source` (`feedback_snapshot` or `current_position_fallback`) and `current_coaching_version` distinguish them. Earlier chat and taxonomy ratings created before v73 did not store a coach-version snapshot; they cannot be reliably assigned to their original historical version. Reselecting a field or rating replaces that item's most recent feedback and its version snapshot; this is not a complete event history. Taxonomy change-rate cards remain current-position statistics, not versioned historical accuracy metrics.

**Coach → Download CSV** contains all filtered feedback including the three new dropdown categories, agreement versus correction, original predicted labels, selected user labels, *current* context/move-type/motif after metadata refresh, canonical mapping columns for legacy motif records, game positions, FEN, Stockfish evidence and version metadata. **Coach → Regression candidates** includes corrected taxonomy selections and thumbs-down text corrections; confirmations and blank selections are excluded. These are human-proposed labels, not independently verified ground truth. Coach supports additional context/move-type/feedback-type filters. The rating dashboard keeps thumbs and dropdown agreement distinct.

**Training taxonomy pills** display the coach's suggested context, an optional Tactical/Strategic move type, and the specific primary motif. Click/tap a pill (or use the keyboard) to choose a different canonical label, explicitly agree with the coach, or clear feedback. A two-level path includes a subtle **+ Move type** pill for adding a qualifier. Corrections show a check mark and accent color, but **do not alter the model's classification, Stockfish evidence, lessons, or deep analysis**. The feedback is saved separately and already flows to Coach and regression exports.

**Coach → Reset feedback** deletes all thumb and taxonomy feedback for the chosen list (or all lists), preserving games, positions, analysis, learned state and Player activity. Restart Analysis deletes the derived positions, but v86 retains the historical feedback ledger even if the source positions are no longer available. Export first if you want an archive of earlier responses.

## Data processing and resets

A new game list **retrieves a PGN batch once**, then starts analysis. Analyze uses saved PGNs, commits progress at completed-game boundaries, and can resume from checkpoints. Additional passes refine analysis; retrieval is not repeated unless creating a new list or deliberately retrying a failed new retrieval.

| Control | Behavior |
| --- | --- |
| **Pause / Resume Analysis** | Continue at the last completed-game checkpoint, keeping results and progress. |
| **Analyze Again** | Continue with a deeper refinement pass using saved games. |
| **Refresh Metadata / Coaching refresh** | Run versioned Stockfish coaching probes and regenerate explanations and motifs from saved training positions. Only **same-version, same-evidence** coaching outputs are reusable. Earlier-version probes, explanations and solve recaps are not promoted as current; previous feedback and fixed benchmark snapshots remain intact. |
| **Clear coaching cache** | **Destructive only for generated coaching on the selected list.** Clears previous coach messages and legacy live chat-thumb projections, proactive probes, assembled continuation evidence, explanations and current taxonomy assignments. Keeps game PGNs, engine evaluations and PVs, training positions, learned status, player attempts, and version-stamped position/continuation/taxonomy feedback. Marks the list **Needs refresh** so new Coach explanations are blocked until a fresh coaching pass. |
| **Restart Analysis** | **Destructive for one list.** Remove that list's derived training positions, evaluated results, learned progress, conversations and ratings, then start fresh Stockfish analysis from its existing PGN. Other lists are unaffected. |
**Export feedback CSV before a destructive restart or reset if you need a record of your previous coaching iteration.** As of v86, a coaching-cache clear deletes coach conversations but preserves every rated chat message's feedback snapshot. New votes append immutable records even when another rating already exists for that position or continuation. Restart and feedback reset require confirmation.

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
- `docs/MAINTENANCE_AUDIT_V85.md` — current maintenance and dependency audit; older v55/v81 audits are in `docs/archive/`.

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

## Current coaching architecture and historical regression material

The v83 solved-position coach renders a separately rateable explanation for each attempted continuation, plus a distinct solving continuation. Previous-session attempts and the original game move appear as light-blue messages; the solving continuation remains gold. Thumbs and suggested revisions attach to the continuation and position, not to a merged recap. Historical explanation ratings remain attached to the solving continuation. All feedback exports and Coach filtering retain this dimension.

The solving-position explanation is assembled from saved chess evidence. The proactive explanation supplies one coherent root explanation; observed moves and their consequences are appended only when they add distinct information. It does not trigger an additional Stockfish search at solve time. See `NARRATIVE_ARCHITECTURE.md`, `COACH_SESSION_GUIDE.md`, and `COACHING_PIPELINE.md` for implementation contracts and evidence ownership.

For test data and earlier behavior changes, refer to `FEEDBACK_BENCHMARK.md`, `PROACTIVE_COACHING.md`, `PROCESS_PERFORMANCE.md`, and prior versioned source archives. The historical feedback fixtures in `tests/fixtures/` are deliberate benchmark inputs, **not runtime data**. Keep them when executing the full regression suite; a production-only distribution may exclude `tests/`, `tools/`, and developer documentation.

See `docs/MAINTENANCE_AUDIT_V85.md` for the current inventory, pruning candidates, cleanup decisions and recommended restructuring.


## v84: compact solving bubble and feedback calibration

The solution message now has natural content height. Direct root checks precede open-file development, confirmed free captures also mention check, and verified noncapturing king evasions receive King Safety priority over unrelated tactical geometry. See `docs/reviews/V30_FEEDBACK_REVIEW.md` for a version-by-version audit of the 771 supplied feedback rows, limitations, examples, and deferred chess evidence questions. For a completely fresh coaching run, use Process → Clear coaching cache → Coaching refresh. A normal coaching refresh is cheaper and can reuse matching engine evidence.

## v86: permanent coaching-feedback ledger

Feedback is now **independent of the disposable Coaching cache**. New tables `feedback_positions`, `feedback_position_sources`, `feedback_continuations`, and `feedback_events` record the stable chess subject and **every explicit rating, correction, and withdrawal**. Multiple votes for the same position, UCI continuation, and model version are retained. Ratings on a newer coaching version never overwrite previous-model feedback. Chat feedback snapshots survive when the original coach conversation is deleted; only the chat transcript and the old live chat-thumb projection disappear.

The Coach dashboard uses the latest effective vote **per item and version** without counting repeated votes multiple times. Coach CSV contains all positive/negative rating events with durable position and continuation IDs. Unrated puzzles do not create feedback records; all solved/learned positions remain the denominator of taxonomy-change coverage metrics. `GET /api/analytics/feedback/history?position_id=N` provides the full per-position event sequence, including withdrawals. The first v86 launch imports all still-existing older feedback exactly once; feedback deleted or overwritten before this upgrade cannot be recovered.

**To regenerate coaching:** Process → Clear coaching cache → Coaching refresh. Your feedback history is safe; **the coach conversation transcript will be deleted**. **Coach → Reset feedback is different**: it intentionally deletes feedback, including the historical ledger, after confirmation. Make a backup of the `data/` directory before upgrading or using a destructive action.

See `docs/FEEDBACK_HISTORY_V86.md` for database keys, lifecycle invariants, report semantics, migration and test coverage. 

## v85: coaching cache lifecycle (historical; feedback behavior superseded by v86)

**When upgrading explanation rules:** For a routine change to the wording or motif hierarchy, run Coaching refresh. To guarantee no old generated teaching material or persisted solve recap survives, use **Process → Clear coaching cache** for each affected game list, then run **Start coaching refresh**. This intentionally reprobes Stockfish for the coaching layer; previously saved root evaluations and candidate PVs are not discarded. Do not confuse this with Restart Analysis, which discards the training curriculum.

While a list shows **Needs refresh**, startup backfills skip that list and new solve-recap/chat generation is blocked, rather than silently generating explanations from an incomplete or old cache. A refresh that is interrupted can be resumed. Historical feedback records can still be exported; ratings from older explanation versions are not pre-selected for the new model.

To reduce the installation footprint without discarding developer tests, use the separately packaged **runtime** archive. Keep the complete **development** archive for source changes and regression testing.

## v87 — continuation teaching model

After solving, the adaptive coach shows the solving continuation first (explanation), attempted continuations next (learning from inferior moves), and the original game continuation last (learning or explanation, depending on move quality). The v32 composer narrates root-locked PV events in move order, emphasizes recaptures and concrete opponent consequences, and uses the v3.3 best-move-driven taxonomy including Recapture. Illegal-move alerts appear briefly next to the Stockfish control. Game-move feedback is stored under `game:<uci>`, independently of a training-attempt `<uci>` feedback event; historical feedback is preserved through coaching-cache resets. See `RELEASE_NOTES_V87.md`.
