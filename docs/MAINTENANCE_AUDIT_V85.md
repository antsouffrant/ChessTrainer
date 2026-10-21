> Historical v85 audit. **The latest-per-item and chat-vote-deletion limitations described below have been resolved in v86.** See [Feedback History v86](FEEDBACK_HISTORY_V86.md) for current lifecycle semantics.

# Chess Trainer v85 — coaching-cache lifecycle and deep maintenance audit

**Baseline:** v84 development ZIP, audited and updated into v85. **Scope:** static import/call inventories, database table dependencies, coaching refresh/cache/replay flow, process UI, JavaScript contracts, regression assets, documentation, and archive contents. No user games, feedback database, or Stockfish installation was included in the source ZIP. The reset behavior was tested on synthetic SQLite data; **it was not executed on your personal database.**

## Executive findings

1. **A model-version check is not a complete cache-invalidation strategy.** Explanation text can be version-backfilled, while persisted solve recaps and chat messages can remain from the old model. Probe reuse is keyed to engine/probe inputs, not narrative version. This release adds a one-list cache clear and `needs_refresh` marker, independent of game retrieval, deep analysis, and learning state.
2. **Do not delete wholesale by apparent age.** There are 48 root-level Python modules and all but `app.py` have inbound Python imports in a static AST survey. Several legacy-looking modules are actively used. The Flask app is deliberately an entry point. Runtime-removal needs an API/dependency test, not a filename heuristic.
3. **The largest on-disk component is test evidence, not runtime code.** Before this release, the v84 ZIP contained approximately **5.44 MB / 202 non-generated files** when unpacked. The four JSON/JSONL test fixtures total **3.52 MB (64.6%)**; the single 3.24 MB full-coach fixture contributes **59.5%**. It is read by actual benchmarks. The safe footprint reduction is **two distributions**, not deleting evidence.
4. **The largest maintainability concentrations** are `app.py` (~175 KB), `static/trainer.js` (~128 KB), `static/styles.css` (~122 KB), `analysis.py` (~84 KB), and `coach_reasoner.py` (~81 KB). Their size reflects coupled responsibilities and needs decomposition behind contracts and integration tests.
5. **CSS has significant layering.** A coarse selector-count scan found about **1,054 rule groups** and **126 selector strings appearing more than once** in `static/styles.css`. Many may be intentional media-query or later-state overrides. They are audit targets, **not proven dead CSS**. Removing them blindly could break training-board layout and responsive coaching.

## What the new Cache Clear actually does

**Process → Clear coaching cache** is scoped to one existing game list and requires a confirmation string. It rejects operations while a retrieval/analysis/coaching worker is active and synchronizes against the app's local worker lock. On success, it:

- Deletes persisted Coach conversation threads/messages, saved solve recaps, proactive/historical coach message markers, chat thumbs and message-based personal *evidence* for that list.
- Clears position `coach_prompt`, `coach_explanation`, `coaching_version`, `proactive_coach_json`, `explanatory_lines_json`, and `critical_events_json`.
- Removes current derived `position_concepts` and `position_motif_taxonomy` assignments. The subsequent refresh rebuilds them.
- Sets the list's metadata job to `needs_refresh`, resets its coaching cursor/performance counters, and invalidates `metadata_refreshed_at`. Startup's non-engine coaching/label backfills skip the invalidated list, and a new saved solve recap or interactive Coach message is blocked until the relevant position is rebuilt.

**Deliberately preserved:** downloaded PGNs, `analyzed_games`, `analysis_candidates`, training position IDs, FEN, `best_pv_uci`, `played_pv_uci`, `alternative_pvs_json`, deep root evaluations and mate values, analysis checkpoint/pass, estimated difficulty, learned/attempt totals, recorded individual board attempts, Player sessions, global learning-concept catalog, and version-stamped **position explanation**, **attempted-continuation**, and **taxonomy** feedback. Other game lists are unaffected. Cached root Stockfish analysis is not cleared.

**Feedback integrity:** Old-version position/continuation/taxonomy ratings remain in Coach reports and CSV but are not preselected for newly generated explanations when their model-version snapshots differ. The stored feedback model is *latest per (position, category or continuation)*, not event-sourced; re-voting the same key replaces that historical row. Export Coach CSV before clearing if you need to keep chat thumbs (deleted with their messages) or preserve a before/after snapshot for paired model comparison. Future work should add immutable version-keyed rating history.

**Refresh cost:** clearing `proactive_coach_json` intentionally defeats the probe cache for this list; the following Coaching refresh reruns bounded coaching probes and rebuilds labels/explanations. Deep root Stockfish passes do **not** rerun. A normal Coaching refresh remains the cheaper choice when deterministic probe evidence can be reused.

**Concurrency caveat:** this app's scheduler is explicitly single-process and thread-based. The lock protects against same-process workers; the reset endpoint is not intended for multiple independent WSGI processes writing to the same SQLite file.

## Repository inventory (v84 reference, before the v85 edits)

| Area | Files | Approximate uncompressed size | Assessment |
| --- | ---: | ---: | --- |
| Root Python | 47 | 962 KB | Active import graph; modularization rather than deletion |
| `static/` | 14 | 356 KB | Preserve responsive selectors and dynamic UI handlers |
| `templates/` | 12 | 83 KB | Current routes use them, even templates with historical names |
| `tests/*.py` | 75 | 319 KB | Broad regression coverage, includes versioned tests still protecting contracts |
| `tests/*.cjs` | 29 | 72 KB | Node-based DOM behavior checks |
| `tests/fixtures/` | 4 | 3,516 KB | Historical/benchmark evidence; development-only |
| Root Markdown | 13 | 104 KB | Several superseded audits and a v83 README header were stale |

*The extra root Python module and two tests added by v85 change these counts. Counts exclude `__pycache__`, `.pyc`, engines and personal databases.*

## Deprecated, obsolete, duplicated: disposition

| Candidate | Evidence | v85 action | Remaining risk / recommendation |
| --- | --- | --- | --- |
| `MAINTENANCE_AUDIT.md` (v55), `MAINTENANCE_AUDIT_V81.md` | Superseded dated audits, linked by v84 README as if current | **Moved to `docs/archive/`**, kept for provenance | Do not ship in small runtime ZIP |
| `V30_FEEDBACK_REVIEW.md` | Historical v84/v30 feedback study | **Moved to `docs/reviews/`** | Preserve the 34-case regression fixture |
| `README.md` v83 heading and old restart guidance | No longer described v84/v85 coaching lifecycle | **Updated** with reset semantics, versioned feedback and current paths | Maintain a single operational guide |
| `COACHING_PIPELINE.md` v54 heading/reset table | Core standards remain useful; some process claims predate per-continuation recaps | **Annotated** and updated cache/reset contract | Consolidate other pipeline docs after systematic ownership review |
| `analysis.download_game_batch` | Only definition in the Python source inventory | **Review candidate**, no removal | Could be an external legacy API; add a migration/deprecation test first |
| `coaching_taxonomy.taxonomy_from_rows`, `pv_reasoning.evidence_summary` | Definition-only in current Python corpus | **Review candidates**, no removal | Retain public helpers until imports beyond source are checked |
| `semantic_coaching._root_piece_capture`, `._capture_value`; `coaching._opponent_pressure_prompt`, `._observable_fallback` | No source-level uses beyond own definitions | **Possible low-risk private-function removals**, deferred | Chess regression + paired narrative fixtures needed before removing |
| Version-named Python/JS tests (`_v29`–`_v84`) | Tests encode historical contracts and still run | **Kept** | Classify by feature and deduplicate assertions only after coverage comparison |
| Four large historical fixtures | Referenced by benchmarking tests/tools | **Kept in development**, excluded from runtime | Prefer fixture subsets for routine smoke runs, full evidence for regression releases |
| `templates/analytics.html`, `static/analytics.js` | Historical `analytics` naming but used by Coach | **Kept** | Rename only with route/template/asset contract migration |
| Old `/api/jobs/<id>/refresh-metadata` | Explicit HTTP 410 compatibility response | **Kept as compatibility stub** | Can remove after callers and API usage verified |
| Overlapping narrative modules (`coaching.py`, `semantic_coaching.py`, `continuation_coach.py`, `coach_session_recap.py`, `narrative_editor.py`) | All appear in active call graphs, but prose and evidence ownership remain distributed | **Not deleted** | Consolidate sentence ownership and branch narrative composer in targeted refactor |

**Static-analysis warning:** functions used as Flask route handlers, dynamically imported names, template endpoints, plugins, database triggers, and external scripts can appear unused in a naive symbol search. The audit explicitly excludes Flask routes from proposed deletion. The module graph is not a substitute for runtime call tracing.

## Recommended directory decomposition (next phase, not a risky wholesale move)

```text
chess_trainer/
    app.py                  # thin entry point, registered route groups
    web/                    # home, training, Coach, Player, Process blueprints
    pipelines/              # retrieval, root Stockfish analysis, coaching refresh
    coaching/
        evidence/           # legally checked branch and PV facts
        taxonomy/           # context / type / motif classification
        narrative/          # one branch-owned prose composer
        feedback/           # ratings, model versions, exports
    persistence/            # DB schema migrations and repositories
    training/               # playlists, progress and sessions
    static/                 # feature-specific JS and CSS
    templates/
tests/
    unit/
    integration/
    ui/
    fixtures/
tools/
docs/
    archive/
```

**Sequencing:** (1) Add tests for stable blueprint endpoints and test startup/restart flows on a copy of a real saved database; (2) split `app.py` route families while preserving endpoint names; (3) introduce a single typed continuation evidence/interpretation API; (4) split UI/stylesheet by training, Coach, Process, and shared shell; (5) consolidate schema migrations into numbered, reversible changes; (6) move historical tests only after import paths/tests are updated. Avoid simultaneously renaming routes, schema, module paths and JS selectors.

## High-priority correctness/performance debt

1. **Feedback version lifecycle:** current votes are latest-per-key. When users rate another coaching version on the same move, the previous row is overwritten. Add append-only `model_version + continuation_key` events and a truly paired evaluation report before benchmarking v31 against v30 on the same positions.
2. **Generated explanation provenance:** have every continuation message carry an immutable composite `(position, move_uci/solving, coaching_version, evidence_fingerprint)` so stale messages cannot be voted on or replayed as current. The new manual clear is a safety escape hatch, not a replacement for automatic invalidation.
3. **Cache provenance:** `PROACTIVE_VERSION` and input-fingerprints cover engine probes but do not version every downstream transformation. Keep Stockfish evidence reusable while invalidating narrative/labels when their **own** versions change.
4. **Function/file-size debt:** extract route orchestration from `app.py`, and preserve core semantic ownership across proactive/reactive Coach rather than generating and deduplicating the same claim twice.
5. **CSS specificity and mobile behavior:** use browser visual regression on responsive training and Coach layouts before consolidating the 126 repeated selectors; JS-only DOM tests do not establish pixel equivalence.
6. **Test cadence:** keep small pure-SQL/process/JS tests quick; reserve full Stockfish and 3 MB feedback fixtures for a thorough release gate. Avoid parsing the full benchmark file on app startup.

## Validation

- Verified synthetic SQLite reset isolates the selected list, deletes stale coaching and chat votes, preserves root evidence, Player moves and other lists, and marks coaching `needs_refresh`.
- Tested explicit-confirmation and active-worker/process-state rejection; repeated cache clear is idempotent.
- Tested old-version ratings remain in storage but are hidden from current-position feedback controls until a same-version vote is added.
- All available Node UI contract tests passed (30 files); syntax checks passed on Python/JS.
- The full Python/Stockfish/Flask end-to-end suite could **not** be run because `python-chess` and Flask are not installed in this execution environment. No claims of successful live-browser appearance or real-engine refresh are made.

**Backups:** the dev ZIP includes all historical test fixtures and developer documents, the runtime ZIP intentionally excludes tests/tools/most docs, and **neither** ZIP overwrites any user SQLite database. Copy your existing `data/` directory before installing or trying a destructive reset, and export Coach CSV if old chat feedback matters.
