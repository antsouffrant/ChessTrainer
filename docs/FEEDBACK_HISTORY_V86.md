# v86 — Independent, Versioned Coaching Feedback

## Invariant

**No Coaching refresh or Clear coaching cache operation deletes feedback history.** The feedback ledger records only explicit feedback actions: an upvote, a downvote, a taxonomy selection, a correction attached to an existing vote, or an intentional withdrawal (`rating = 0`). Unrated positions do not create artificial records. Player progress and solved-position counts continue to supply population denominators where appropriate.

Coaching cache and chat threads are disposable. Games, Stockfish root analysis, saved principal variations, and player outcomes retain their previous ownership and lifecycle.

## Durable identity dictionary

| Table | Key | Purpose |
|---|---|---|
| `feedback_positions` | `pos_` + SHA-256 digest prefix | Deterministic identity derived from account provider/username, game-list ID, game identity, move/ply, the first four FEN fields, and the side to move. Stores the original FEN, game identifier, account, and source job for orphan reporting. |
| `feedback_position_sources` | original `training_positions.id` | Links the current or historical position row to the durable identity, allowing the same chess position to be rediscovered. No FK to `training_positions`, so analysis restarts cannot cascade into history. |
| `feedback_continuations` | `cont_` + SHA-256 digest prefix | Unique per position identity and root UCI move (or the special `solving` key). |
| `feedback_events` | append-only integer event ID | Each deliberate user vote/selection/withdrawal, with FKs to the two dictionaries, a model version, rating, explanation/chat content snapshot, user correction, and original message ID **without** a cascading chat-message FK. |

The position identity includes more than just FEN: the same board in different game lists or unrelated games may have distinct training intent. A clean analysis restart of the *same* list retains the list ID and reproduces the identity. The digest uses a reproducible serialization; the database stores readable identifiers and source metadata to aid audits. Event IDs never depend on the message cache's lifetime.

## Feedback semantics

- Clicking 👍 or 👎 creates an event. Changing 👍 to 👎 creates another, retaining both snapshots. Voting again on the same continuation after a model upgrade creates a new event with the new `coaching_version`.
- Unselecting a thumb or clearing a taxonomy selection records a withdrawal event, so it is possible to reconstruct the earlier vote without counting the withdrawn item in current approval statistics.
- Explanation messages have an explicit `solving` or UCI continuation dimension. Original-game and attempted moves use the same canonical UCI key.
- Chat replies are snapshotted when rated: their text, structured response, immediately preceding user question, proposed correction, rating, and model version survive deletion of the chat transcript.
- UI thumbs represent the latest effective vote **for the currently displayed coaching model**. Position relevance votes remain model-independent.
- Dashboard approval counts use the latest effective rating per position/continuation/message and model version, **not every vote event**. Taxonomy change rates still use all matching learned positions (including never-rated positions) as their denominator.
- Coach CSV exports the recorded positive/negative event timeline (including repeated votes); withdrawal events are available through `GET /api/analytics/feedback/history?position_id=…`. Report rows show latest effective rating per item *per model version* by default. Historical feedback preserves its original content and classification snapshots while showing current chess metadata when available.

## Cache, reset, and analysis lifecycle

1. **Clear coaching cache**: removes generated explanations, taxonomy assignments, coach threads, chat messages, and their legacy thumbs projections; retains every `feedback_events` row and dictionary identity. New coaching requires Coaching refresh, but does not require a new game download or root Stockfish analysis.
2. **Coaching refresh**: replaces derived explanations/metadata, leaving the feedback ledger untouched. Old votes remain attributable to the previous model version, and are not preselected for the new model.
3. **Restart Analysis**: can remove/recreate the original `training_positions`; the ledger has no cascading dependency and remains queryable. The report can fall back to identity-registry FEN/game/account snapshots when the original position row is absent. Some current-only chess fields are then naturally blank until the position is reanalyzed.
4. **Coach → Reset feedback**: a **separate, explicitly confirmed action** that intentionally removes the chosen list's feedback history as well as its compatibility projections. It must not be confused with clearing the cache. As a safeguard, export your feedback CSV and back up `data/` before using it.

## Migration and compatibility

At v86 startup, the migration imports **surviving** v85 rows from `position_feedback`, `continuation_explanation_feedback`, `position_taxonomy_feedback`, and `coach_message_feedback`, saving snapshots before any coach threads are cleared. A durable `app_settings` migration marker prevents the mutable legacy projections from being imported again on each subsequent launch. An additional unique source reference prevents duplicate imports if migration is retried in a transaction.

Older releases stored one latest vote per item, and chat feedback may already have been lost during a previous cache clear. Earlier overwritten/deleted votes **cannot be reconstructed**; v86 preserves all available historical votes and all subsequent feedback actions.

The old latest-state tables remain temporarily as compatibility projections for existing UI/queries. New feedback is written to the durable ledger and compatibility projection in the same SQLite transaction. A later structural refactor can remove the projections once every consumer has been migrated.

## Validation

- Migrated an actual v85 schema with legacy position and chat votes; verified the marker and no double import on a second v86 startup.
- Regression tests cover multiple votes on one continuation, same-version changes, model upgrades, corrections, withdrawals, chat cache deletion, orphaned analysis positions, taxonomy reversions, and denominator deduplication.
- No dependencies have been added. Full Flask/Stockfish integration still requires installing `requirements.txt` on a configured application machine.
