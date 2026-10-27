# Chess Trainer v94 — Maintenance audit and deletion ledger

## Scope

This is **structural cleanup only**. The coaching model remains `rules-v34-version-scoped-cache`. It does not change the database schema, existing coaching explanations, Stockfish analysis, benchmark cohort, evaluation-run progress, or immutable feedback history. No coaching refresh is required solely because of this release.

## Completed work

| Cleanup | Result | Safety basis |
|---|---:|---|
| Root-level coaching compatibility modules | **34 removed** | Every Python application/test import migrated to canonical `coaching.<stage>.<module>` paths; architecture test enforces their absence |
| Unreferenced private Python functions | **8 removed** | No non-definition symbol reference across Python/UI/test sources; removed only private undecorated module functions |
| Unused JavaScript helper functions | **4 removed** | No production call sites or template use; updated two tests to verify the active inline motif sorter |
| Exact duplicate CSS rule blocks | **4 removed** | Equivalent qualified rules retained at later cascade positions |
| Superseded Markdown/release notes | **23 archived** | Moved under `docs/archive/`, retained for development provenance |
| UI assets | **15 retained** | Each asset has a template reference; no entire CSS/JS file could safely be deleted |
| HTML templates | **12 retained** | All are referenced by Flask routes or the Jinja base/extends mechanism; no wholly orphaned template |
| Large historical benchmark fixture | **Retained in development only** | Required to reproduce historical regression evaluation, excluded from runtime package |

### Removed private Python helpers

- `app.py`: `_sync_account_learning_progress`.
- `coaching/conceptual_understanding/semantic_coaching.py`: `_role`, `_root_piece_capture`, `_capture_value`.
- `coaching/narrative_composition/coaching.py`: `_opponent_pressure_prompt`, `_observable_fallback`.
- `coaching/narrative_composition/coach_reasoner.py`: `_piece_type_from_text`.
- `coaching/narrative_composition/continuation_coach.py`: `_opponent_consequence`.

### Removed JavaScript helpers

- `static/trainer.js`: `learningModeLabel`, `alphabeticalMotifs`, `isUsersPiece` (the app uses `learningModeMeta`, an inline taxonomy sorter, and `isPieceForColor` instead).
- `static/lessons.js`: `toggleLessonAnalysis` (no invocation in the app or templates).

### Consolidated CSS

`static/styles.css`: duplicate rules for `.board-column`, `.engine-arrow #engine-arrow-highlight`, `.lesson-page .lesson-status-text`, and `.history-controls #history-back`. The later declarations remain in the stylesheet.

### Archived documentation

`docs/archive/releases/` contains old release notes v87–v93. `docs/archive/legacy_guides/` contains earlier standalone coaching and maintenance documents. `docs/archive/historical_reviews/` contains historical audits and review cases. The root README and `docs/COACHING_ARCHITECTURE.md` are now the canonical technical entrypoints.

## Tests and validation

- Baseline **v93**: **354 Python tests, 8 failures, 25 errors, 52 skipped** in this environment.
- After v94 cleanup: **354 Python tests, 8 failures, 25 errors, 52 skipped**, with the same failing test identities.
- JavaScript: **32/32 test files pass** using Node.js; all application JavaScript files pass syntax checks.
- AST parsing: all 147 packaged Python source and test files pass syntax parsing.
- CSS: no stylesheet parsing errors with `tinycss2`.
- Automated import-boundary tests verify that all normal Python imports use canonical coaching modules. See [`TEST_MAP_V94.md`](TEST_MAP_V94.md) for coverage ownership.

The Python suite is **not fully green**. `Flask` and `python-chess` could not be installed in this offline execution environment; 25 baseline errors include dependency failures and existing fixture assumptions. The 8 older assertions include historical narrative/taxonomy behaviors not introduced by v94. Full application/Stockfish integration should still be run locally.

## What was deliberately retained

1. Existing chess heuristics, even when they overlap conceptually: removing them would change coaching behavior and deserves separate versioned evaluation.
2. All Flask routes, SQLite functions, and public processing helpers without clear proof of being unused: route registration, callbacks, and dynamic lookups make naive unused-symbol scans unsafe.
3. Existing HTML templates and referenced static assets: no safe whole-file removal identified.
4. Historical test fixtures and reports: the complete development package retains reproducibility; the runtime package excludes development-only material.

## Suggested next cleanup (separate behavioral release)

- Consolidate overlapping `coaching` reasoning helpers through structured findings and a live validator. Preserve the current model as a baseline first.
- Split `app.py` and `static/trainer.js` by feature behind stable interfaces; current source files are still large.
- Refactor scattered styles into scoped component CSS after browser-based visual regression snapshots. Duplicate **selectors** with different declarations are not necessarily redundant.
- Audit historical tests based on expected current behavior, not filenames; remove or rewrite failing outdated assertions as a separate explicit test-contract decision.
