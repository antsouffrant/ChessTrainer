# Active coaching-message ownership (v114)

**Coaching model remains `rules-v35-decision-findings`**. This is a storage and rendering fix, not a new evaluation/model. No re-evaluation is necessary.

## Canonical active cache

`coaching_message_cache` is the only reusable generated teaching-text cache, containing one active row per `(position_id, message_type, continuation_key)`. Kinds are `best_move`, `attempted_move`, and `game_move`. Every row contains `generation_version`, immutable-for-that-generation `content`, `content_sha256`, and an optional `evidence_fingerprint` and `coach_prompt`. Replacing an active row is a versioned/revised generation event, not a feedback edit.

The position's old `coach_explanation`/`coach_prompt`/`coaching_version` fields remain compatibility projections for playlist metadata; they cannot by themselves make text current or rateable. The live UI checks the canonical cache and current version. The old `coaching_explanation_cache` table is dropped by the additive v114 startup migration after its historical role is retired.

`coach_messages` / `coach_solve_recaps` are chat/session transcripts, **not a current coaching cache**. Prior assistant transcript messages are returned in ordinary training only when they match the active generation; solved recaps additionally must match every typed active note's text. History reads never upgrade or rewrite saved recaps in place.

`feedback_message_snapshots` and append-only `feedback_events` are **historical provenance**, not a live cache. Their original explanation text, message identity, generation version and ratings are retained independently of cache clear. Evaluation runs and frozen benchmark snapshots remain independent and unchanged.

## Generation paths

- Metadata/Coaching refresh: saves one `best_move`/`position` active entry with model and evidence fingerprint. Updates the position's legacy display projection as an atomic companion write.
- Verified post-solve recap: saves one typed active record per `best_move`/`solving`, `attempted_move`/root move, and `game_move`/original-game root, with the generation version. The session transcript references these generated texts without being a reusable cache.
- Display: only current version and matching message content can populate live training cards or recaps. Old model chat is not current advice. Historical snapshots remain available to the feedback analytics layer.

## Migration and operations

Startup migrates saved best-move projections and *current model* stamped recap notes into the canonical table **once**. Legacy v34 recaps are never imported as if they were v35. The retired versioned explanation-copy table is dropped; back up the SQLite database before upgrading as a general precaution. The one-time marker prevents rehydrating removed cache entries on subsequent restarts.

Clear Coaching Cache is game-list scoped and removes all three active message types; it preserves feedback and evaluations. Coaching refresh rebuilds best-move entries. A newly completed solve generates attempted/game-move entries without repeating an evaluation.

The Process diagnostics at `/api/jobs/<job-id>/coaching-health` now include cache counts by generation and type, archived transcript counts by generation, and current-best-move integrity checks.
