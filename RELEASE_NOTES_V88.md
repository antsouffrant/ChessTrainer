# Chess Trainer v88 — fixed coaching comparisons and repetition-aware explanations

## Coaching cards

- All three coaching card families now use a non-growing, content-height flex layout at 88% width. The solution retains its amber accent and individual thumbs.
- The server emits exactly one summary card per root continuation: solved move, attempted and previous-session moves, then the original game move *if its root move has not already appeared*. An attempted card wins when the same move occurred in both training and the original game. The browser independently deduplicates older cached recaps, so this applies before a fresh coaching rebuild.
- Archived explanation-v6 recaps are upgraded to v7 when opened. Durable feedback history is not deleted or rewritten.

## Perpetual check

- Newly generated PV evidence retains the board identity following each legal move, enabling exact repetition detection without extra Stockfish searches.
- Checking sequences require at least three observed checks by the same player. **Threefold is asserted only if the saved continuation actually reaches the same legal-position identity three times**. Returning to an earlier position twice is described as a possibility, not proof of a draw; checks without repetition are explicitly *not* marketed as perpetual.
- `Perpetual Check` is a canonical learning motif **only if the best-move PV itself** demonstrates threefold repetition amid repeated checks; forced mate and tablebase verdicts retain precedence. A repetition solely in the refuted game line is coaching commentary rather than the position's primary motif.
- Version: `rules-v33-fixed-cohorts-perpetual-check`, taxonomy/classifier `3.4-verified-perpetual-check`.
- Caveat: an engine principal variation is a sample, not a proof all opponent defenses lead to a forced draw. Board identity is based only on the moves explicitly replayed from the saved starting FEN; earlier game history not in that FEN is not assumed.

## Frozen coaching benchmark (Process view)

- On the **first coaching refresh request** for a game list with confirmed positions, the app creates one immutable 36-position (or fewer if fewer exist) deterministic, stratified diagnostic cohort. It draws across saved lesson modes, difficulty bands, and learned/unlearned positions, not random new positions on every refresh.
- A completed coaching refresh creates **one immutable per-model snapshot** per list, including each member's explanation, prompt and primary context/type/motif. Running the same model again cannot overwrite its baseline.
- Process shows the frozen cohort size, available positions, model snapshots, explicit thumbs, taxonomy confirmations/corrections, approved percentage of rated messages, *matched* approval on identical position/continuation pairs under consecutive versions, and motif differences on the common snapshot cohort. Approval is **not calculated as positive votes divided by the entire sample**; unrated messages are genuinely missing feedback, not negatives. Rating coverage is displayed independently.
- `Review same positions →` launches `/trainer/<job>?benchmark=1` using the frozen playlist in order. It includes learned positions for review and bypasses stale local playlists. The read-only `GET /api/jobs/<job>/coaching-benchmark` gives raw cohort member IDs and summary data.
- An Analysis restart may delete the original training-position rows; the fixed cohort is *not silently redrawn*. The Process UI warns if some original members are no longer available. This ensures users never believe two samples were identical when they were not.
- Cohorts are selected starting in v88; no historic v86/v87 explanation snapshots are reconstructed from overwritten cache text. Paired data becomes meaningful when the frozen cohort has been rated under two or more completed coaching versions.

## Refresh integrity

- The older Coaching refresh path rebuilt labels and evidence but could leave `coach_explanation` on an old version. Startup backfill and ongoing refresh now share `coaching_copy_refresh.rebuild_coaching_copy` and regenerate the model-specific prose **after** updating evidence and classification, before persisting a completed benchmark snapshot.
- Coaching cache deletion does **not** remove frozen benchmark cohorts, version snapshots, games, Stockfish evaluations, learning progress, or durable feedback events. It still deletes chat conversations, with the existing confirmation warning.

## Tests and limitations

- Unit coverage includes immutable cohort selection, independent model snapshots, feedback-only-on-explicit-vote denominators, effective vote history and withdrawals, distinct original-game and attempted-move identity, and repeated vs nonrepeated checking lines.
- Python-chess, Flask and a configured Stockfish engine are required for complete end-to-end integration in the installed environment. Their availability is not implied by syntax and isolated unit-test success here.
