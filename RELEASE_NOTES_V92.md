# v92 · Evaluation coaching feedback hotfix

This is a UI/feedback interaction repair on top of v91. **The coaching model remains `rules-v34-version-scoped-cache`** and benchmark snapshot/model identifiers are unchanged. No cache reset or Coaching refresh is required.

## Problem

In a benchmark evaluation, the current run's solved status is independent of global `training_positions.learned`. The Trainer still applied an extra `explainedPositionId` eligibility marker to the solution's thumbs, which is fragile when the saved coach thread/recap is loaded or replaced asynchronously. Moreover, inline votes are invisible without hover, and an API rejection appeared only in a tooltip. This made evaluation explanation votes appear missing or nonfunctional while the three taxonomy select controls remained usable.

## Fix

- Feedback eligibility in evaluation mode is derived from the currently displayed, solved evaluation position and an actual visible solution explanation. Global learned history does not unlock feedback for an unsolved evaluation.
- The separate stale `explainedPositionId` marker no longer controls whether explanation thumbs are shown. The unsolved prompt and empty explanation are not rateable.
- Explanation and continuation thumbs are always visible after solving in evaluation mode; ordinary training retains its original presentation.
- Saving or withdrawing a rating shows a small inline confirmation. Server validation failures (including a stale coaching model) are visible alongside the controls, not just as a hidden tooltip. The same error visibility applies to interactive coaching-message ratings.
- Votes still carry `evaluation_run_id` and the currently displayed explanation text. The existing feedback ledger retains each event; withdrawals remain explicit history entries.
- No change to any game, evaluation run, learning status, benchmark membership, Stockfish analysis, model label, taxonomy, or historical feedback data.

## Regression tests

- `tests/test_evaluation_explanation_feedback_v92.cjs`: current-run eligibility, globally learned-but-unsolved exclusion, blank/pre-solve text exclusion, visible buttons and mocked successful/error POST paths.
- `tests/test_evaluation_explanation_feedback_v92.py`: database-level vote/write/revote/withdraw paths for a solved evaluation position whose global `learned` flag is false; verification that runs have independent thumbs.
- Existing JavaScript suite and v86 feedback-history/v91 evaluation-architecture suites.

## Install

Back up your `data/` directory as usual, then replace application files with v92. **Do not clear the Coaching cache or start a new Coaching refresh for this UI-only fix.** Continue the existing evaluation run.

## Test-environment limitations

The targeted SQLite feedback tests pass. Full Flask/Stockfish/browser end-to-end interaction could not be exercised in this environment because Flask and `python-chess` are not installed. Errors will now be surfaced directly should a separate version-guard or server failure occur on the user's installation.
