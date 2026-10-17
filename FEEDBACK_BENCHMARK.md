# Coach feedback benchmark — v58

## Source and scope

Imported the user's October 16, 2026 Coach CSV. The distributable fixture
`tests/fixtures/coach_feedback_v58.jsonl` contains **109 feedback observations**
and preserves the actual FEN, both candidate moves, saved UCI principal
variations, rating and any suggested correction. Account names, opponent names,
game IDs and other identifying account metadata are deliberately excluded.
The corresponding original export should remain the user's own historical
source of truth; this source package contains only the minimized fixture.
Chat feedback is excluded from this benchmark.

| Feedback | Positive | Negative | Positive share |
|---|---:|---:|---:|
| Training positions | 32 | 1 | 97.0% |
| Explanations | 29 | 12 | 70.7% |
| Primary motifs | 18 | 17 | 51.4% |

24 negative votes have an explicit suggested correction: 14 replacement motifs
and 10 proposed explanations. Six further negative votes have no correction.
The suggested labels and explanations are **proposals**, not independently
verified ground truth. They may be incomplete or based on a different
understanding of the variation. Never train or override a chess detector from
a proposed label without checking the legal board and saved continuation.

## Dataset-driven observations

* Defensive Resource appears in nine negatively rated motif examples.
  Several propose Skewer, Double Attack, Pawn Structure or See the Threat.
* Protect Loose Pieces is sometimes used for a decisive double attack rather
  than a defensive saving move.
* Some negative explanation proposals request a more specific mechanism,
  such as a queen trapped by a reply, an exchange lost, a discovered attack,
  or a pawn structure concession.
* For endgames, a generic King Safety description can obscure an active
  king move, although an unavoidable check must still be answered.
* A plain equal trade is not automatically a sufficient explanation; check
  whether the exchange prevents a near-term loss in the compared line.

## How the revised app uses these cases

1. `motif_hierarchy.py` stores specific-to-broad pedagogical relationships.
   It never infers the existence of a fork from the generic presence of a
   threat. Only separately verified evidence can promote a specific motif.
2. `continuation_refutations.py` runs symmetrical short-PV checks: the
   solution's tactic *and* the opponent's refutation of the played move.
   A claim of winning material requires an actual legal captured target in
   the saved continuation, not mere attacked-square geometry.
3. `coaching_language.py` identifies the game move and the opponent's reply,
   avoiding technical narration such as “analyzed continuation.”
4. `semantic_coaching.py` rewards immediate, decision-distinguishing
   refutations and explicitly states the avoided loss where an exchange
   prevents material damage supported by both saved lines.
5. A late critical-moment classification cannot overwrite a more specific,
   already-supported primary motif with generic material-loss context.

## Regression process for future development

Every Coach export can be evaluated from saved analysis without new Stockfish
calls. With `python-chess` installed:

```bash
python tools/evaluate_coach_feedback.py \
  --input tests/fixtures/coach_feedback_v58.jsonl \
  --output coach_regression_v58.csv
```

Or use a fresh unmodified Coach CSV as the input. The output pairs current
classifications and explanations with user-approved/proposed references,
separately reporting candidate motif match rates. For explanation proposals,
inspect meaning, correctness and brevity manually; exact string matching
is not an adequate semantic metric. Approved thumbs-up examples act as
*stability signals* rather than mathematical proofs of correctness.

Review corrections before labeling them `verified`. Retain an immutable
snapshot of old feedback before resetting Coach ratings or restarting
analysis; new CSV exports should be versioned. Avoid mixing the old app's
stored explanation text with text newly generated from a newer classifier.

### Validation limits

The fixture and ontology unit tests run without Stockfish. Chess-position
regression tests and the full replay report require `python-chess`, which is
listed in `requirements.txt`. The evaluator uses **saved** PVs; it does not
establish that the sampled line is forced, and cannot substitute for a fresh
Stockfish run when engine settings change. Systematic refutation scanning
currently covers *local* checks, double attacks, skewers and uncovered line
attacks **when their material payoff occurs in the near continuation**;
it does not claim full tactical completeness.

## v60: cumulative correction analysis and causal-comprehension iteration

The user supplied a further Coach regression-candidates CSV with 51 proposed
negative-feedback corrections (25 motif substitutions, 26 explanation rewrites)
spanning 33 distinct training positions. These corrections are stored as a
minimal, anonymized fixture:

`tests/fixtures/coach_regression_candidates_v60.jsonl`

The original 109-record positive/negative fixture remains in the archive.
**The 51-record fixture is selected failures only**: it is not an accuracy
estimate or representative sample of all puzzles, and multiple ratings can
refer to the same position. Individual proposed corrections are suggestions,
not independently verified chess truth.

The v60 coaching update adds:

- `causal_selection.py`: a single deterministic ranking policy consumed by
  both explanation selection and primary-motif classification. It prefers
  demonstrated consequences, short causal chains, specific mechanisms, and
  close proximity to the training decision. It penalizes remote, speculative
  motifs and broad fallback labels without inventing tactics.
- `continuation_refutations.py`: in addition to forks, skewers and discovered
  attacks with demonstrated payoffs, identifies short sequences in which a
  captured defender's disappearance enables a later capture. An aligned
  slider does not count as a skewer unless it *actually* checks the king.
- `semantic_coaching.py`: endgame king activation and newly doubled pawns
  require near-root, branch-comparable evidence. Neutral exchanges no longer
  risk using an unset material-loss variable. The chosen explanation states
  a chess idea instead of narrating the reasoning machinery.
- `learning.py`: the primary label is aligned with the same leading causal
  finding while protecting exact tablebase verdicts, forced mating obligations,
  and established hanging-piece provenance.

Run the pure-Python ranking and fixture checks without chess dependencies:

```bash
python -m unittest -q tests.test_causal_comprehension_v60 tests.test_feedback_hierarchy_v58
```

Install `requirements.txt` to run the **chess-specific** acceptance tests and
replay the two fixture generations (no Stockfish needed for offline replay):

```bash
python tools/evaluate_coach_feedback.py \
  --input tests/fixtures/coach_feedback_v58.jsonl \
  --output coach_approved_and_corrected_v60.csv
python tools/evaluate_coach_feedback.py \
  --input tests/fixtures/coach_regression_candidates_v60.jsonl \
  --output coach_corrected_failures_v60.csv
```

A successful run gives comparative *suggested-motif agreement* and material
for manual review of explanation semantics; it cannot automatically prove
correctness or improvement. Check candidate legality, evaluation perspective,
PV coverage and plausible alternative refutations before promoting a proposal
to a verified acceptance case. Preserve earlier approved motifs as stability
checks, rather than optimizing only on downvotes.
