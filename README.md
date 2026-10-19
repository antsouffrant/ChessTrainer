# Personal Chess Trainer — v83

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
- `MAINTENANCE_AUDIT_V81.md` — current dependency and distribution audit (`MAINTENANCE_AUDIT.md` is the historical v55 snapshot).

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

See `MAINTENANCE_AUDIT_V81.md` for the current inventory, cleanup decisions, and safe next steps.
