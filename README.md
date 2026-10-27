# Personal Chess Trainer

A local Flask and Stockfish application for personalized training positions, lessons, openings, coaching explanations, Player statistics, and fixed-cohort coaching-model evaluations.

**Release:** v116 accepted-move board review fix. **Coaching model:** `rules-v35-decision-findings` (unchanged). No Coaching refresh, cache clear, database migration, or new evaluation is required for this UI update. See [`RELEASE_NOTES_V116.md`](RELEASE_NOTES_V116.md).

The coaching engine follows the [six-stage architecture](docs/COACHING_ARCHITECTURE.md). v114 introduced the unified active coaching-message cache; v115 compacted the green solved-status banner; v116 ensures that accepted alternative moves remain on their played squares, with engine-best visual annotations only.

## Setup

Install Python 3.10+ and a compatible Stockfish engine, then:

```bash
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. Stockfish can be placed in `stockfish/` or configured in Settings. Lichess retrieval requires internet access, but already downloaded games can be analyzed locally. Keep your existing **`data/` directory** when installing a new version: it stores games, analysis, progress, coaching cache, feedback and evaluation history. The release packages do not include that database or your Stockfish binary.

## App areas

| Page | Function |
|---|---|
| Home | Game lists, retrieval and analysis readiness |
| Training | Solve positions, inspect continuations, rate coaching messages |
| Lessons | Curated positions and learning progress |
| Openings | Opening-specific training playlists |
| Player | Learning analytics and solving behavior |
| Coach | Coaching feedback, versioned comparisons and benchmark charts |
| Process | Job lifecycle, coaching refresh, cache reset and evaluation runs |
| Settings | Account and engine preferences |

## Data and model lifecycle

- Downloaded games and Stockfish position evidence are independent of generated coaching text.
- The single active message cache (`coaching_message_cache`) holds **best-move, attempted-move, and game-move** coaching. Entries are generation-version stamped. Position text columns are compatibility projections; chat transcripts and immutable feedback are separate historical records.
- Each game list has one authoritative evaluation per coaching model on the fixed benchmark cohort. Explicitly starting that model again replaces its active evaluation (new 0/N progress), while a repeated Coaching refresh does not reset its work. Earlier run/feedback records are kept in the append-only archive but excluded from active model metrics. Evaluation completion remains separate from global learner progress.
- Historical ratings and corrections live in an append-only ledger and immutable message snapshots. Clearing the active message cache does not erase those records or frozen evaluations.
- Clear Coaching Cache removes regenerable derived coaching content and warns about deleting live chat conversations. It should not affect games, Stockfish analysis or historical ratings.

## Source organization

The Python coaching pipeline lives under `coaching/` with six distinct packages: `board_context`, `conceptual_understanding`, `motif_selection`, `narrative_composition`, `coaching_validation`, `coaching_refresh`. Root-level compatibility aliases were removed in v94. Shared application modules (`app.py`, `db.py`, `analysis.py`, and other infrastructure) remain at the root until a separate application-wide restructuring.

Static UI assets are in `static/`, Jinja templates in `templates/`, automated checks in `tests/`, and offline development utilities in `tools/`. The complete test-to-module mapping is in [`docs/TEST_MAP_V94.md`](docs/TEST_MAP_V94.md).

## Verification

```bash
python -m unittest discover -s tests -p 'test_*.py'
for file in tests/*.cjs; do node "$file"; done
```

For the full Python suite, install the dependencies in `requirements.txt` first. Historical tests may assert previous text or taxonomy versions; the v94 maintenance audit distinguishes existing failures from regressions.

## Documents

- Current coaching architecture: [`docs/COACHING_ARCHITECTURE.md`](docs/COACHING_ARCHITECTURE.md)
- Test ownership: [`docs/TEST_MAP_V94.md`](docs/TEST_MAP_V94.md)
- Maintenance details: [`docs/MAINTENANCE_AUDIT_V94.md`](docs/MAINTENANCE_AUDIT_V94.md)
- Historical release notes, older coaching guides and analyses: `docs/archive/` (retained for development history, not the authoritative architecture).

## v95 navigation and housekeeping

- Training/Lessons/Openings navigation finds a usable game list rather than trapping users on Process when the newest list is empty.
- Fixed-cohort model comparison analytics live under **Coach → Model comparisons** (`/coach/benchmark`); create and resume evaluations from Process.
- The Home page provides **Delete list** with confirmation and active-worker safeguards. This deletes the list and its related training/evaluation records, but preserves the versioned feedback ledger and reusable analyzed-game cache. Back up your `data/` directory before deletion.
- **Position learned** appears after solving in normal Training/Lessons/Openings. Benchmark evaluation runs instead use run-specific progress; they never inherit global learned state.
- Coach feedback controls show selection state and display errors; successful ratings are announced accessibly without inserting persistent “Rating saved” text.

## Evaluation feedback submission (v96)

In an evaluation run, solve each position and submit at least one position, continuation, taxonomy, or coach response rating. The Trainer shows **Evaluation saved** after a successful server save and unlocks **Next position**. Withdraw the last effective rating to lock Next again. The saved state is scoped to the position, coaching version, and evaluation run; regular lessons/training are unchanged.

The six coaching stages are now under `coaching/`, not `coaching_pipeline/`; external imports must use the new package name.

## v97 hint fix

In both ordinary Trainer and evaluation mode, **Show hint** reveals the position's pre-solve `coach_prompt` beneath the button without exposing the hidden post-solve coach message. The hint is dismissed on solving or switching positions; its presence does not alter evaluation feedback requirements.

## v98 evaluation and Player controls

- **Evaluation saved** occupies the former **Position learned** control slot beside Reset puzzle and appears after feedback is recorded for the current evaluation. Next Position still requires persisted feedback.
- **Player stats** uses the same opt-in toggle in every mode. A new evaluation starts with it **off**; switching it on records evaluation attempts in Player reports without updating global learned progress. Evaluation Player sessions are identified by evaluation run to avoid mixing attempt cycles.
- After solving, selecting or dragging a piece enables **Stockfish** automatically, including when reviewing game-history positions. The new analysis branch remains separate from the original game moves.
- v98 performs an additive migration of `player_solve_sessions`; retain your current `data/` directory when upgrading. Coaching version and cache are unchanged.

## v100 · One evaluation per coaching model

Coach → Model comparisons displays one evaluation for each coaching version within a given game list. Evaluation #2 supersedes #1 when both used the same model. A newly introduced model receives its own evaluation when Coaching refresh finishes. Additional refreshes of an unchanged model do **not** erase its evaluation. Starting a new evaluation explicitly replaces that model's current progress and effective feedback results; old events stay in the historical ledger for provenance. The same fixed cohort and model-specific snapshots remain unchanged.

The first v100 startup automatically selects the **newest existing evaluation run ID** for each game list/model. It does not favor a previously completed but older run. The database enforces a unique non-superseded evaluation per game list/model.


## v101 evaluation lifecycle

Each game list shares one immutable representative cohort across coaching
versions. A model has one authoritative evaluation, and refreshing coaching
does not reset it. Only the currently installed coaching model's evaluation
can be opened in the Trainer and rated. Once a new model replaces it, its
completed evaluation remains in Coach analytics but is no longer playable.

Incomplete current-model evaluations appear as gold featured tiles above
Lessons and Openings. v33's one-off experimental evaluation feedback is
retired during the v101 migration; ordinary v33 feedback is preserved.
See `RELEASE_NOTES_V101.md` for migration scope and upgrade precautions.

## v102 evaluation navigation

Evaluations are explicit benchmark sessions, never the default Training or
Lessons/Openings playlist. Incomplete current-model evaluations are featured on
Lessons and Openings, while completed evaluations are retained in **Coach →
Model comparisons** for review and rating until a later coaching model freezes
them. The ordinary Training menu resumes only a non-evaluation playlist. If a
prior release saved an evaluation as the Training default, v102 automatically
cleans that stale browser resume state without touching feedback or SQLite.
See `RELEASE_NOTES_V102.md`.


### Change rates (v103)

Coach feedback change rates count corrected taxonomy judgments over ordinary
learned positions and the authoritative completed portions of model evaluation
runs; archived evaluations are excluded. The model comparison page also shows
each model's evaluation correction rates, distinct from between-model changes
to frozen coaching output. See `RELEASE_NOTES_V103.md`.


## v105: evaluation recovery after Coaching refresh

A finished refresh must create one authoritative evaluation for the current
coaching model. Previously suppressed activation errors are now reported;
Lessons and Openings safely activate a missing run using completed existing
model snapshots. The 36-position cohort and v34 historical results remain
unchanged. See `RELEASE_NOTES_V105.md`.

### v106 evaluation recovery

The fixed benchmark is one cohort across coaching model versions, with one current run per model. A completed older model is frozen for analytics. If a completed current-model refresh has not yielded its evaluation, the Lessons/Openings featured tile and the Process **Prepare and open current evaluation** action reconcile an unused, potentially stale current-model snapshot without resetting any existing evaluation. See `RELEASE_NOTES_V106.md`.


## v107 coaching refresh validation

A refresh is successful only when all saved positions are stamped with a nonempty current-model explanation. Older false-complete refreshes can be repaired for the fixed benchmark through Process → Prepare and open current evaluation. See `RELEASE_NOTES_V107.md` for limitations and data-preservation policy.

## v113 development update

See `RELEASE_NOTES_V113.md` for the post-solve recap delivery fix, missing-attempt diagnostics, filter dropdown layering, and instructions for keeping the completed v35 evaluation unchanged.
