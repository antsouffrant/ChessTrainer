# V84 · Feedback-calibrated coaching (v31 explanation / v3.2 taxonomy)

The v84 release uses the saved feedback to improve v30 conservatively. Historical
feedback and taxonomy selections remain intact and are **not** automatically
accepted as ground truth. The user must run **Process → Refresh Metadata** on
existing game lists to regenerate their teaching labels and explanations.

## Feedback audit (2026-10-16 to 2026-10-19)

The supplied feedback export has **771 rows across 297 positions**, but rows are
*votes*, not independent positions, and a position may have multiple generations
of votes. `report_coaching_version` refers to the version saved at vote time,
not the current implementation. Some older records without a version snapshot
have a fallback value; these should not be treated as controlled test cohorts.

| Explanation model | Positive | Negative | Approval | Distinct rated positions |
|---|---:|---:|---:|---:|
| v24 specific endgame | 4 | 2 | 66.7% | 6 |
| v25 loose-piece provenance | 25 | 10 | 71.4% | 35 |
| v26 refutations | 17 | 16 | 51.5% | 33 |
| v27 causal comprehension | 58 | 44 | 56.9% | 102 |
| v28 evidence & purpose | 16 | 10 | 61.5% | 26 |
| v29 proactive Stockfish | 1 | 1 | 50.0% | 2 |
| **v30 clean taxonomy outcomes** | **74** | **17** | **81.3%** | **87** |

**Important:** 91 v30 explanation votes include **87 solving** votes (70 up,
17 down) and **4 attempted-continuation** votes (all up). Historical explanation
votes were mostly for the solving continuation. Different positions, time ranges,
review practices, and explanation snapshots mean these percentages cannot prove
that v30 causally improved accuracy. **None of the 87 v30 explanation-rated
positions has a prior-version explanation rating in this export.** No paired
comparison can therefore be calculated. Only repeated ratings on the same set
of positions with blinded review support a controlled comparison.

On v30, the same export also contains **79/79 positive position votes**; that
shows satisfaction with the *position*, not independently with explanations.
Taxonomy feedback contains **25 motif selections**, **12 move-type selections**
and **4 context selections**. These are explicit user classification feedback,
not thumb votes; 9 motif suggestions choose King Safety and 7 choose Don't Hang
Pieces. These 25 selections are not a measured error rate among all lessons.

## Highest-value findings and disposition

1. **Check-first explanations, direct fixes.** Examples 2453 (`Re5+`) and 2452
   (`Re8+`) were described principally as occupying an open file. On a
   legally verified checking move, the direct check is a more relevant root
   description. `root_explanation.py` now prioritizes it before open-file
   wording, while stronger verified tactics from upstream remain eligible.
2. **Captures with check, direct fixes.** Example 2585 (`fxg7+`) was described
   only as taking a free rook; now the established free-capture sentence also
   mentions check when the *root board* proves the move checks.
3. **Safe king evasions, classification fix.** In examples 3392, 3169, 3987,
   3453 and 3316, the better noncapturing king move follows an opponent check,
   while the classified tactic/loose-piece motif commonly refers to later or
   alternative events. A validated noncapturing king evasion now gives primary
   priority to King Safety, preserving already-verified mate-defense and
   endgame king-activity motifs. This is applied only during reclassification.
4. **Moved-piece hanging vs pre-existing loose-piece, pending evidence work.**
   Seven user motif corrections prefer Don't Hang Pieces, often over Defend
   Loose Pieces. These are not synonymous. `loose_piece_provenance.py` already
   requires a near-term differential legal capture, so we **do not** promote
   these votes into automatic classifications without that proof. Next improve
   availability of compared reply PVs and trace the original victim identity.
5. **Outcome before incidental geometry, pending deeper chess verification.**
   Examples 3397 (passed pawn versus simplification), 3987 (perpetual check
   versus incidental fork), 2712 (different winning capture), 2559
   (discovered check versus double attack), and 2452 (skewer over check)
   need validated multi-ply evidence or stronger specialized detectors. Do
   not claim these findings as forced from a single sampled PV.
6. **Missing decision contrast.** Examples 2740 and 2222 want to connect
   the better move to why the game choice fails; continuation-specific cards
   in v83 separate the alternative's story, but a good explanation still
   needs an independently justified reason. Do not concatenate cross-root
   sentences or manufacture claims from classifier names.

## Implementation and safety

- CSS: the solving message is a natural-height block at the same adaptive
  width as the other messages. Removes the extra nested styling and oversized
  padding; feedback controls stay in that message.
- Coaching: model now reports `rules-v31-feedback-calibrated-checks`.
- Taxonomy: `3.2-king-evasion-feedback` stored separately, primary lesson
  selection preserved through existing `position_concepts` and taxonomy table.
- No deletion, rewrites, or schema change to existing feedback, learned
  positions, game history, continuation votes, or saved raw engine lines.
- Run `Process → Refresh Metadata` to generate v31 content / v3.2 classifier
  for existing lists. Previously saved votes must remain associated with the
  exact explanation and classifier version at the time of feedback.

## Recommended follow-up evaluation

Build a **paired** 30–50-position evaluation from the 17 v30 negative
explanations, 25 motif corrections (with overlaps deduplicated), and
20 high-rated v30 controls. For each, store initial FEN, legal best and played
moves, source line for every claim, before/after explanation, and blind
user review. Inspect root event, opponent's best reply, and eventual material,
check, mate, promotion, or pawn-structure outcome independently. Report rates
by actual continuation key, context, move type, motif and evidence depth;
keep "unsubstantiated" distinct from "factually false". Only change classifiers
for labels shown correct by independently validated board evidence.

## Curated review fixture

`tests/fixtures/v30_feedback_review_v84.json` contains deduplicated positions
from the 17 v30 explanation downvotes and 25 taxonomy-motif suggestions, with
original FEN, best/game moves, principal variations and saved user suggestions.
Treat all suggested corrections as review hypotheses, not automatic test truth.
The file contains no account handles, opponents, or dates.
