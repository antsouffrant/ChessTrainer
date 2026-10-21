# Chess Trainer v90 — version-scoped coaching cache

## Problem corrected

Earlier releases could reuse a cached Stockfish coaching probe across explanation-rule versions because the probe fingerprint used the probe algorithm version, engine and settings, **not** the active coaching model. Further, startup text backfills could stamp a new `COACHING_VERSION` on an explanation reconstructed from previous-version causal evidence. Saved solve-session recaps were also keyed by session alone, not by model version.

This could affect the perpetual-check changes introduced in v88/v89: a user who refreshed coaching without explicitly clearing the old cache could receive some stale supporting evidence or old post-solve messages while the current-position record bore a newer version label.

## v90 behavior

- New model identifier: `rules-v34-version-scoped-cache`. The taxonomy version remains `3.4-verified-perpetual-check`. This new identifier distinguishes results of a correctly versioned refresh from potentially mixed v33 results, even though the underlying chess explanation rules have not been otherwise rewritten.
- `proactive_coaching.py` includes the active coaching version in the probe fingerprint and cached probe JSON. Previous-version or unversioned JSON is **not reusable** under v34. Stockfish re-probes it on refresh; raw deep-analysis scores and PVs are unaffected.
- `coaching_explanation_cache` is a new, versioned SQLite table keyed by `(position_id, coaching_version, evidence_fingerprint)`. An identical current-model explanation can be reused; changes to relevant board state, PVs, causal evidence, labels, taxonomy, or probe data cause a cache miss. Previous-version explanations can be retained for audit as previous-version records, not reinterpreted as current.
- Startup backfills no longer automatically reclassify old coaching copy as the newly installed model. An explicit **Coaching refresh** is required to migrate positions from v33 to v34.
- Metadata refresh no longer inherits historical `tested_reply` snippets from previous coaching copy. Missing/failed fresh probes are not replaced with stale previous-version proactive evidence.
- Metadata refresh has one authoritative coaching-copy generation pass after labels and causal evidence are refreshed.
- A solve recap whose saved coaching version differs from the current model is never served as a current-model recap. Regeneration uses a **new chat message** so previous rated messages and feedback snapshots remain intact. Historical stale recaps are hidden in the current conversation view but not deleted from storage. A stale message cannot acquire a new-model chat rating.
- **Clear coaching cache** also drops the disposable versioned explanation cache for the selected game list. It does **not** remove benchmark snapshots, feedback events, games, Stockfish root analysis or learning progress.

## What you should do

1. Back up your existing `data/` directory (especially `chess_trainer.sqlite3`).
2. Install v90 and start the app; the additive cache table is created at startup.
3. In **Process**, run **Coaching refresh** on each game list you want to rate under v34. Unlike v89, v90 will not reuse v33 coaching probes or explanations as if they belonged to v34. You do **not** need to clear the coaching cache first solely for model correctness.
4. If you want to discard old coaching conversations or purge all disposable coaching data for that list anyway, choose **Clear coaching cache** first, confirm the chat deletion warning, and then **Coaching refresh**. Historical feedback and benchmark snapshots remain preserved.
5. Wait for the refresh to complete and check that the current coaching version is `rules-v34-version-scoped-cache` before rating fresh explanations. Future rules changes should increment `COACHING_VERSION` to trigger the same protection.

The original v33 benchmark snapshot is deliberately left unchanged. If generated from mixed caches, treat it as an **uncertain historical baseline** rather than silently modifying it. The v34 refresh adds its own snapshot against the same frozen cohort.

## Verification performed

- New 9-test versioned-cache/recap suite: pass.
- Historical feedback ledger suite: 6 pass.
- Historical cache-clear suite: 5 pass.
- Fixed benchmark/perpetual-check suite: 6 pass.
- JavaScript UI test scripts: 30 pass.
- Python syntax compilation: pass.

Full Flask + `python-chess` + Stockfish integration could not be exercised in this environment because Flask and `python-chess` are not installed. Confirm the final refresh in your local runtime before collecting new feedback.
