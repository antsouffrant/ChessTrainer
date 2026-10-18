# Proactive coaching — Stockfish-guided understanding (v65)

The app supports two distinct kinds of coaching:

- **Proactive** — for retained training positions, compile position context,
  form tactical/strategic hypotheses, and test concrete opponent responses
  with Stockfish before assigning curriculum motifs and drafting explanations.
- **Reactive** — contextual chat questions and answers; no change to chat.

## Processing stages

1. **Retrieve** — fetch PGNs only on game-list creation.
2. **Analyze** — screen games and deep-confirm significant decisions. Store the
   root evaluation, recommended/game moves, PVs, game context, and learning mode.
   An additional bounded coaching probe runs only for retained positions, not
   for every game ply. Probing failure cannot discard a confirmed position.
3. **Refresh Metadata** — reuse the saved training positions and deep-analysis
   results but launch Stockfish for *new* independent coaching probes. This is
   separate from game evaluation; no new positions are discovered. A stored
   cursor permits pause/stop/resume; failed startup is reported on Process.
4. **Proactive interpretation** — compile board context (`position_context`),
   root-move effects, and up to the configured number of Stockfish replies to
   each of the recommended and game/contrast moves. Track whose turn each
   response belongs to and normalize its evaluation to the training side.
5. **Evidence selection** — test short, legal continuations for consequences
   such as demonstrated double attacks, skewers, discovered attacks, and removal
   of defenders. Root evaluation differences come from Analyze; a low-depth
   coaching probe **never replaces** saved deep root scores or PVs.
6. **Coach and curriculum** — enrich generic explanations and broad primary
   motifs when a concrete close-to-root mechanism is actually demonstrated.
   Protect the many approved simple captures, exchanges and existing specific
   primary lessons from speculative or merely geometric reassignment.

## Persistence

`training_positions.proactive_coach_json` is versioned JSON containing
`root_fen`, `context`, `strategic_context`, `branches`, `selection`,
`method`, and `limits`. Strategic context observes material balance, game phase,
pawn structure (doubled/isolated/passed pawns), and king activity. These facts
help formulate hypotheses; they do not themselves prove that a tactical or
positional claim changes the evaluation.
Each branch records its root SAN/UCI, observed board changes, multiple tested
reply PVs, engine centipawn/mate scores and depths. `explanatory_lines_json`
retains additional legal probed reply lines alongside the original saved
principal variations; no costly searches run during normal page rendering.

### Accuracy boundaries

A PV represents a credible engine line at a bounded search, **not a proof of
forced material win against every opponent response**. Engine evals describe
positions; moving geometry alone is not sufficient to declare a proven tactic.
High-confidence tactical descriptions require a legal, nearby realized payoff.
The engine should not create unsupported claims when probe evidence is weak.

### Performance and failure behavior

- Settings: `coaching_probe_enabled` during Analyze; refresh always uses
  Stockfish; `coaching_probe_seconds` (default 1.2 s per position),
  `coaching_probe_variations` (2), and `coaching_probe_depth` (14).
- Reuse one dedicated Stockfish process for each refresh job, close on exit.
- Engine computations are performed **outside SQLite write transactions**;
  three-position metadata batches then commit atomically.
- The shared process mutex avoids simultaneous full Analyze/Refresh workers.
- Pausing/stopping preserves the last committed cursor; rerunning Refresh
  recomputes the coaching probes and derived metadata only.
- Stockfish startup failures appear as Process errors instead of quietly
  pretending the refresh succeeded.

The Coach feedback corpus remains the benchmark. An additional probe should
be considered a net improvement only after verifying more corrected cases
without regressing previously approved specific motifs and explanations.


## v66 contextual motif hierarchy

The proactive probe still supplies evidence for specific chess mechanisms. `coaching_taxonomy.py` now projects the verified primary motif into an Attack/Defend decision context and an optional Tactical/Strategic move type (see `COACHING_TAXONOMY.md`). These are learning dimensions, not inferred additional forced lines. Metadata refresh regenerates the hierarchy along with coaching.

## Canonical taxonomy integration (v67)

After the engine's `prefer_evidenced_primary` selection, all lesson labels are normalized to the canonical Attack/Defend taxonomy. Legacy generic primary motifs cannot be repeated as context and leaf; sufficiently supported tactics and strategies are searched regardless of context, followed by concrete general lessons and a saved-evaluation outcome fallback. `Refresh Metadata` reruns this work from retained root evaluations and new Stockfish probes; it never invokes game retrieval or deep position screening.

## v71 profiling and exact-input reuse

See `PROCESS_PERFORMANCE.md`. Coaching refresh caches a completed probe only when `cache_key` matches the saved position, engine version and relevant search configuration, while always regenerating derived coaching metadata. Older JSON is reprobed once; updated probe generator semantics must bump `PROACTIVE_VERSION`. Stage timings appear in Process. This replaces the previous unconditional rerun behavior.
