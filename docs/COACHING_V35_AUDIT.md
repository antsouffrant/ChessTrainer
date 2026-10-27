# Coaching v35 — Architecture and feedback audit

## Scope and methodology

The user-supplied v34 feedback export was audited **in full**, not sampled for
individual successful examples: 256 feedback events on 57 distinct positions.
It includes 160 explanation votes (including repeated votes on the same
continuation). For the explanatory approval snapshot, retain the last event
for each `(position_key, continuation_key)`, yielding **71 distinct rated
continuations, 63 thumbs-down and 8 thumbs-up**. This is feedback collected
from the user's selected evaluation/training experiences, not a random or
statistically representative test of the model.

The deterministic replay runs the new v35 selection/composition path on all
71 distinct continuations where the saved decision is identifiable. It compares
word counts and structural behaviors **without a new chess-engine search**;
independent board validation requires the full local chess environment.

| Structural measure | v34 saved text | v35 offline replay |
| --- | ---: | ---: |
| Rated distinct continuations previewed | 71 | 71 |
| Mean words | 44.1 | 12.6 |
| Maximum words | — | 25 |
| Repetitive reply-by-reply narration phrases | Frequent in v34 examples | 0 |
| Exact motif supported by a selected saved event | Not evaluated | 17/71 |
| Selected mechanism/refutation insufficient | Not evaluated | 24/71 |
| Narrative-validation failure/fallback | Not evaluated | 0/71 |

**Do not interpret word count or these diagnostics as approval improvement.**
The 17/71 motif-verified statistic is a diagnostic limitation, not a success
claim: taxonomy and explanatory evidence may disagree, and the narrator must
not fabricate tactics simply to match a label. Some of the 24 insufficient
findings still convey a concrete *missed best move* as a comparison, rather
than an invented refutation. Chess-aware root facts (such as moving an attacked
queen or activating a king in a sparse endgame) were unavailable to this
standalone replay and may improve actual coverage in the running application.

## The six cohesive coaching stages

1. **`coaching/board_context` — chess evidence.** Owns the single canonical
   root-locked saved/verified PV selector, legal root/SAN checking, factual
   root observations, threefold/checking-cycle evidence and spoiler-conscious
   pre-solve prompts. No prose from other candidate branches can enter.
2. **`coaching/conceptual_understanding` — decision comparator.** Separately
   asks *what does the solution accomplish?* and *what does the candidate
   permit or miss?*. Opponent's demonstrable refutation takes precedence over
   incidental captures; even-capture/recapture exchanges are not automatically
   treated as losses. A candidate without supported refutation instead has
   an explicit missed-opportunity comparison, if its best line is evidenced.
3. **`coaching/motif_selection` — explanation selector.** Cross-checks the
   position's currently selected primary motif against the actual evidence;
   only a supported near-root matching event can take priority. Unverified
   labels are retained as diagnostics (`motif_unverified`), not narrated as
   fact.
4. **`coaching/narrative_composition` — two distinct purposes.** Explanation
   confirms a move's mechanism; learning foregrounds the opponent's refutation
   or precise missed alternative. A single finding generates at most one or
   two causal sentences. Engine continuations remain available on the board.
5. **`coaching/coaching_validation` — explanation validator.** Checks root
   attribution, purpose, word budget, referenced reply and prohibits multi-ply
   play-by-play templates. Unsupported output fails closed instead of being
   smoothed by another legacy fallback.
6. **`coaching/coaching_refresh` — versioned cache.** Canonical version
   `rules-v35-decision-findings`; refresh fingerprints existing inputs and
   stores distinct v35 snapshots. Historical v34 evaluations and feedback
   remain immutable. Historical recap messages cannot be rewritten by the new
   narrator in place.

### Data flow

`Stored legal PV + position + motif` → `DecisionEvidence` → `DecisionFinding`
→ `Motif-informed selection` → `Explanation OR Learning` → `Validation`
→ `Version-scoped snapshot / recap`.

The exact same source move drives the evidence, finding, prose and feedback
identity. No stage is allowed to promote a guessed reply into a forced claim.

## Evidence and limitations

- Stored PVs demonstrate **a** legal continuation; absent a proof of mate,
  they do not demonstrate a uniquely forced refutation. A signed mate score
  from Stockfish is required to state the mate distance, and only for the
  matching best move.
- Endgame king activity/queen safety descriptions rely on direct legal-board
  observations when python-chess is available.
- A correct/brilliant *game move* receives an explanation; failed attempts
  and incorrect game moves receive learning messages. No caption-label swap
  is used in place of reasoning.
- Some v34 feedback corrections themselves refer to chess facts that require
  manual validation; this code does not treat free-text corrections as facts.
- The general coaching classifier/taxonomy is unchanged in v35. The selection
  layer has been improved; this is not a complete retraining of the taxonomy.
- Purely strategic or undocumented positions may still produce an honest
  insufficient-evidence message. Future work should add corroborated decision
  evidence, **not** more unsupported tactical labels.
- Free-form Adaptive Coach reasoning remains a separate chat path. v35
  integrates the deterministic post-solve cards, prompt and saved solution;
  it does not replace every dialog-generation utility.

## Evaluation design

The fixed 36-position cohort must remain the same for v34 and v35. Run
**Coaching refresh** to capture v35 snapshots and create the v35 evaluation.
Evaluate all positions, including correct and attempted/original-game cards,
and compare approval on matched rated continuations. Record separate rates for
solving explanations, failed-attempt learning, and game-move learning, as well
as word length, motif support and unsupported fallback rate.

**Acceptance must be measured on the new evaluation; no uplift is claimed.**
The audit can be repeated without copying private CSV rows into the repository:

```
python tools/audit_coaching_feedback_v35.py "path/to/feedback.csv"
```

### Regression coverage and limitations

11 v35-specific isolated tests cover root identity, exact purpose, supported
motifs, mate proof, refutation, missed opportunity, recapture neutrality,
pre-solve separation and frozen recap safety. The six-stage architecture tests
and all JavaScript tests were also run. The historical Python suite contains
numerous v34-era exact-wording expectations that no longer represent the v35
contract; those need migration. This environment lacks Flask and python-chess,
so no full UI/engine integration result is asserted.
