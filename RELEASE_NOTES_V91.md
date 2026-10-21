# Chess Trainer v91 — Evaluation runs and fixed-cohort model comparison

## Purpose

Evaluation is an experiment on a fixed collection of positions, **not another view of the learner's historical completion flags**. Coaching explanations, learner proficiency and benchmark evaluation results have distinct storage lifecycles. Versioned coaching benchmark snapshots remain immutable; feedback remains append-only.

## New tables

| Table | Purpose |
| --- | --- |
| `evaluation_runs` | One independent evaluation of the unchanged benchmark sample, associated with one coaching version and a frozen model snapshot. |
| `evaluation_run_positions` | Run-specific `pending`/`solved` state, attempt count and completion timestamp for each selected position. |
| `evaluation_attempts` | Accepted/legal and unsuccessful legal attempts in move order; neither global `training_positions.learned` nor Player statistics are updated by evaluation attempts. |
| `feedback_events.evaluation_run_id` | Optional new nullable attribute. Run-specific thumbs and taxonomy selections are appended without mutating ordinary-training feedback projections. Old feedback remains NULL and intact. |

The existing `coach_benchmark_cohorts`, `coach_benchmark_positions`, `coach_benchmark_runs` and `coach_benchmark_snapshots` tables retain their meanings. **The cohort is selected once** at the first Coaching refresh and never redrawn during subsequent refreshes, new evaluation starts, or cache invalidation.

## Lifecycle

1. First successful Coaching refresh: establish frozen cohort if missing, save the model's first immutable snapshot, and create a fresh evaluation run if the snapshot is complete and agrees with current coaching evidence.
2. Subsequent successful Coaching refresh: create another independent run of the same cohort, retaining all previous runs. If evidence differs from the model's previous immutable snapshot without a new model label, refuse to create a mislabeled run.
3. **Process → Start new evaluation**: manually create an additional empty run against the current model snapshot; does not change learned positions, history or Player stats.
4. **Process → Continue evaluation**: navigate to `/trainer/<job>?benchmark=1&run_id=<run>`; progress and solution permissions are read from that run, never `training_positions.learned`.
5. Cache reset: clears coaching content as before, but does **not** clear benchmark membership, historical evaluation attempts, previous model snapshots or feedback history. Old evaluation runs may become read-only if their model differs from the currently deployed version.

The normal Training, Lessons and Openings workflows intentionally retain account-level learned-state semantics. Fresh, independent evaluation applies to the benchmark workflow; it does not silently reset the ordinary lesson curriculum.

## Coach → Coaching model comparison

New configurable **Fixed-position benchmark** chart:

- Game list, Model A (baseline), and Model B **or all other models**.
- Explanation change rate = stored explanation strings that differ / positions with snapshots for both models.
- Primary motif, context, move-type change rates use the same paired-position denominator.
- Matched explanation approval reports two approval percentages from the same `(position, continuation)` pairs explicitly rated under **both** coaching versions; unrated positions are never counted as thumbs-down.
- Motif correction percentages use each version's explicitly rated motifs as their own denominator, and their rated counts are displayed. These are not equivalent to cross-model motif output change rates.
- Zero paired feedback produces **—**, not 0% approval.
- "Model A vs all others" shows one comparison per other version with its own pairing and coverage. It does not pool noncomparable feedback cohorts.

This view answers *what changed* and *what users approved*. It does not claim that changed wording necessarily means an improved chess explanation.

## Backward compatibility

`db.init_db()` creates new tables and adds the nullable `evaluation_run_id` feedback column to existing v90 SQLite databases. Previously saved global learning, v86 feedback ledger, coach versions and fixed benchmark snapshots are preserved. Earlier solves cannot be retrospectively attributed to new evaluation runs; the new run starts pending even if the position was learned globally. Back up `data/` before upgrading.

No Stockfish reanalysis is necessary to install the evaluation architecture. A Coaching refresh is required only to initialize the first run for a list that lacks a complete benchmark snapshot; otherwise use Process → Start new evaluation. Changing coaching engine rules still requires the normal version bump and version-compatible refresh.

## Regression checks

- Five SQLite-only tests: independent run progress, second-run reset without loss of first-run history, model version isolation, matched approvals and change rates, run-scoped feedback, cache deletion preserving evaluation.
- 31 existing/new JavaScript test scripts (some contain several individual tests) pass, including Process and Trainer regression checks.
- Python compilation of changed modules passes.
- Full Flask and actual Stockfish integration was **not** executed here because those runtime dependencies are unavailable. Test against a backup of your local database before replacing your active installation.
