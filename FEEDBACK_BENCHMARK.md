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
