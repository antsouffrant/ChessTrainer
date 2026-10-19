# Chess Trainer v81 — maintenance and footprint audit

## Scope

Inspected `personal_chess_trainer_v81.zip` (193 files; 5,348,359 uncompressed bytes; 726,731 archive bytes). This iteration applies **documentation-only changes**. No Python, JavaScript, CSS, templates, schema, tests, or benchmark records were removed or modified.

## Inventory and findings

| Area | Evidence | Decision |
| --- | --- | --- |
| Historical README change log | README carried overlapping notes for v57–v81, plus a malformed/duplicated reset-table row and conflicting reset guidance | Removed version-by-version sections in favor of current guidance and links to focused documents |
| Historical maintenance audit | `MAINTENANCE_AUDIT.md` explicitly describes v55 | Keep as an archival artifact; this file supersedes it for v81 |
| Full Coach feedback fixture | `tests/fixtures/coach_feedback_full_v64.jsonl` ~3.24 MB; referenced by `tests/test_full_coach_benchmark_v64.py` and benchmark CLI | Keep for development/regression. Exclude only from a **separate** runtime distribution |
| Other feedback fixtures | v58 and v60 fixtures referenced by corresponding tests and benchmark docs | Keep for development/regression |
| Runtime Python modules | Static AST import survey of 47 root-level modules: all but `app.py` are imported by other Python source. `app.py` is the entry point | No safe orphan-module deletion identified; static import reachability is not proof of runtime use |
| Runtime pages | `templates/analytics.html`, `static/analytics.js` have historical filenames but support Coach | Keep routes, template filenames, API shapes and JS contracts |
| Single large files | `app.py` ~169 KB, `static/trainer.js` ~124 KB, `static/styles.css` ~120 KB, `analysis.py` ~83 KB, `coach_reasoner.py` ~81 KB | Split only behind compatibility tests, not as this cleanup |
| Narrative components | `adaptive_coach.py`, `proactive_coaching.py`, `continuation_coach.py`, `root_explanation.py`, `narrative_editor.py`, `coach_session_recap.py` are actively connected via Python imports | Consolidate ownership and duplication through targeted tests, not deletion by name |
| Cache/binary/data | No Stockfish engine or imported personal database included in source archive | Continue excluding binaries, saved PGNs, SQLite databases, `__pycache__` and `*.pyc` |

## Size optimization strategy

The important distinction is **installed runtime** versus **development regression**. The 3.24 MB historical feedback file is around 61% of uncompressed source-archive contents. Removing it from the only developer ZIP would discard reproducibility. If a smaller runtime package is useful, create an additional `runtime` ZIP that excludes `tests/`, `tools/`, and developer-only `*.md` except `README.md`, while keeping all Python sources, `static/`, `templates/`, settings and `requirements.txt`. Keep a complete `development` ZIP as the canonical editing and regression source.

ZIP already compresses fixtures well. Optimize maintainability and startup load before optimizing a sub-megabyte source ZIP for download size.

## Recommended next refactoring, ordered by risk

1. **Readability / contracts (low):** Keep the concise README as the only current operating guide. Mark historical architecture references with versions. Add an explicit module-to-feature ownership table and consolidate conflicting prose about resets and coaching.
2. **Tests (low/medium):** Classify the 73 Python test modules and 28 Node `.cjs` suites into smoke, unit, integration, and historical benchmark groups. Do **not** remove historical tests simply because the version suffix is old; prune only exact duplicates confirmed to cover identical behavior and assertions.
3. **Narrative logic (medium):** Move all solved-position commentary through one explanation composer, with explicit ownership of root cause versus observed reply versus consequence, and deduplication of semantic facts. Preserve the cached-PV no-extra-engine guarantee and stable recap feedback identifiers.
4. **Python orchestration (medium/high):** Isolate Flask route groups from `app.py` while preserving endpoint names, database migrations, retrieval/analysis process state, progress and readiness gating, Coach/Player CSV exports, and saved sessions.
5. **UI/CSS (medium/high):** Inventory live selectors and JS event handlers against templates; remove superseded declarations only after desktop/mobile screenshots and interactive regression checks. Split `trainer.js` along state/navigation/board/feedback boundaries with a stable public interface.

## Protect these workflows

- List creation: retrieving → analyzing → training-ready, and associated disabled Home buttons.
- Resume/pause/restart processing and checkpoint recovery; cached Stockfish coaching probes and metadata refresh.
- Position selection, balanced playlists, lessons/openings, learning-mode and motif filters.
- Trainer move verification, Stockfish continuation, proactive/reactive coaching, unique chess-grounded commentary and existing thumbs/taxonomy corrections.
- Coach approval and change-rate denominator semantics, saved version snapshots, exports and feedback reset.
- Player solve sessions/attempts, time caps, learning progress, exports and reset.
- SQLite compatibility with the user's existing local `data/` directory.

## Validation and limitations

Ran `python -m compileall -q .` (passed) and all available `tests/*.cjs` using Node (no failures reported). `python-chess` and Flask were not installed in this execution environment, so the Python chess/Flask integration test suite was **not** run. No live Stockfish, browser visual regression, or end-to-end retrieval test was performed. The changed files are documentation only; no behavioral improvement or runtime speedup is claimed from this pass.
