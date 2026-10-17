# Application source and size audit — v55

## Scope and method

Compared the v54 Library ZIP with the v55 source, examining runtime Python imports (including tests), template and JavaScript references, duplicated Coach CSS, packaging artifacts, and README growth. The original v54 archive remains saved in the user's Library for recovery. No imported chess data, Stockfish binaries or SQLite database is included in either source archive.

## Changes applied

1. **Coach card responsiveness.** The previous overview required five columns inside the site's ~1180px shell, so cards were squeezed. The new layout automatically wraps cards before they become too narrow. Breakdowns become single-column at moderate widths. Long captions can wrap rather than collide, with larger inner and outer gaps and horizontally scrollable tables.
2. **One Coach stylesheet.** Removed overlapping v48/v51 Coach layout and reset styles appended to `static/styles.css`. Moved all Coach-specific styling to `static/coach.css`, loaded through a small `extra_head` block only on the Coach page. Other pages no longer load its selectors. Coach-related names/IDs were retained to preserve existing JavaScript and routes.
3. **Unused legacy Python.** Deleted `grounded_dialogue.py`: no active application module, template or regression test imported or referenced it, and the currently used coach path is `adaptive_coach.py` → `coach_reasoner.py` plus the common evidence modules. The old module remains available in the archived v54 ZIP if needed for historical comparison. This is an import/reference audit, not a runtime coverage proof.
4. **Current documentation.** Replaced ~102 KB of accumulated, often contradictory v1–v54 README release notes with a short current-state setup and maintenance guide. Kept the focused `COACHING_PIPELINE.md` and the regression tests. Historical notes are in earlier versioned archives.
5. **Packaging.** Removed incidental Python bytecode caches, retained actual runtime assets and tests, and excluded personal data/engine binaries.

## What was intentionally retained

The large `app.py`, `analysis.py`, `coach_reasoner.py`, `learning.py`, `coaching.py`, and `static/trainer.js` files remain active and interdependent. Renaming or deleting them based on size alone risks regression in the retrieval, analysis, coaching, or training flows. `templates/analytics.html` and `static/analytics.js` still implement the Coach view; these historical filenames are referenced by working UI contracts and need not be renamed solely for aesthetics. The `tests/` directory is development infrastructure worth retaining.

## Further refactoring candidates (not applied)

- **Flask routes:** split `app.py` into blueprints organized by process, training, Coach, and settings. Do this with application-context/API integration tests before moving route handlers.
- **Coaching package:** consolidate deterministic chess evidence/semantic components under a package with explicit public interfaces, then remove implementation duplication only after position-based tests run with python-chess.
- **Trainer JavaScript:** separate board UI state, game navigation, and coaching-feedback controls; add end-to-end browser tests before splitting.
- **Global CSS:** identify superseded training-page selectors with a real-browser visual regression comparison. Only Coach selectors were isolated during this release; other cascade overrides may still need work.

## Validation and limitations

Python source syntax checks and the existing Node/browser-contract and database tests can be run in this environment. The full chess/Flask integration suite requires the dependencies from `requirements.txt`, a Stockfish binary, and user-level local verification. A headless Chromium screenshot attempt failed in the container; the responsive Coach rules are covered by structural CSS tests but are not claimed to be visually verified in a running Flask browser here.
