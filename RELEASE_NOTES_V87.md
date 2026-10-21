# Chess Trainer v87 — continuation-focused coaching

## Model and taxonomy

- Explanation model: `rules-v32-ordered-learning-recaptures`
- Learning classifier: `3.3-best-move-recapture`
- Taxonomy model: `3.3-best-move-recapture`
- Recap schema `explanation_version = 6`

## Coaching conversation

After a completed solve, messages now follow this order:

1. **Solution · Explanation** — why the solving move is beneficial.
2. **Attempted moves · Learning** — why each incorrect attempt was inferior, based on root-locked, saved PV evidence (including previous sessions, deduplicated by UCI).
3. **Your game · Learning or Explanation** — whether the original game move was weak or strong, independent of whether it was retried during training.

Each message uses a consistent width; attempts are blue and original-game moves have a separate purple tone. The solution retains its distinct styling. The original-game card may be shown separately for a move that was also attempted in training.

## Move chronology and recaptures

The continuation composer reuses only a first-sentence immediate claim from the pre-existing proactive explanation, if that sentence does not reference other continuation moves. Every subsequent claim comes from the correct root's stored board-event PV in move order (up to five plies including the first move). Where possible, concrete recaptures, captures, discovered attacks and check defenses take priority over generic piece activity and evaluation. A recapture is recognized when the captured target square matches the immediately previous capture's destination. This is not automatically called a *favorable* trade or *simplification*.

The learning classifier introduces a dedicated **Recapture** learning motif when the solving move captures back on the square of a legal, verified immediate prior enemy capture. The primary motif is screened against best-move evidence so a fork, discovery, skewer, or pin seen only in an alternate losing line cannot displace the actual best-move mechanism. Such failed-line tactical facts are still available in learning messages.

## Separate feedback identities

The v86 feedback ledger remains append-only. Solving feedback uses `solving`, an attempted move uses its root UCI (such as `d2d4`), and the original-game card uses a distinct `game:d2d4` origin key. The `feedback_continuations` dictionary holds both origin-aware identities, allowing separate ratings for the same chess move as a training attempt and as a historical game move. The reporting continuation breakdown and CSV filters distinguish solving, attempted and original-game ratings. Older unprefixed game-move feedback remains untouched, as historical origin may be ambiguous.

## Illegal move notification

Illegal-move notices use a transient, timed message beside Stockfish in the board footer, rather than manipulating the position-feedback container. The position rating and solved-result indicators are not cleared when an illegal move is attempted.

## Upgrade guidance

Use **Process → Clear Coaching Cache → Coaching refresh** after installing v87. The previous coaching cache's saved narrative and recap wording is version-specific. Back up the `data/` directory before switching releases. Cache removal does not delete the immutable feedback ledger; it does delete stored chat histories as described in the Process confirmation.

## Verification

- All 51 JavaScript tests pass.
- 17 targeted Python tests pass (6 continuation-dedup, 7 recap, 4 v87 regression tests).
- Python source compilation and JavaScript syntax checks pass.
- Stockfish, full Flask integration and the entire Python suite were not run here because `python-chess` and Flask are not available in the execution environment.

## Sample-driven changes

The uploaded v31 feedback dataset contains 116 historical records, including 62 explanation ratings. It highlighted cases such as Bxf7+ → Kxf7 → Ng5+ → Ke8 → Qxg4 and Nxe5 → Nxe5 → Bxg5 → Nxg5 → Qxg5. Both now narrate actual intermediate moves before later captures, and immediate recaptures are described explicitly. This is a targeted correction, not a measured approval uplift over v31.
