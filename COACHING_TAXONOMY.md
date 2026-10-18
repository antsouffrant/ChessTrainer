# Canonical coaching taxonomy — v67

Each training position has **one** primary learning path: 

- **General:** `Attacking Plans / Defensive Resources → supported general motif` (two levels).
- **Qualified:** `Attacking Plans / Defensive Resources → Tactical Calculation / Strategic Comprehension → supported specific motif` (three levels).
- **Evidence fallback:** `Attacking Plans / Defensive Resources → saved evaluation outcome` (two levels).

The coaching context is always a separate **Attack / Defend** field; a context label is never also its own primary motif. A tactical or strategic concept can occur under either context when the position and continuations support it. A verified fork used as a counterattack can therefore be filed under defense without restricting which tactical motifs the coach may discover.

## Canonical curriculum and legacy mapping

`coaching_taxonomy.py` defines the supported general motifs (`ATTACK_GENERAL` and `DEFEND_GENERAL`), optional tactical/strategic groups (`TACTICAL`, `STRATEGIC`), and `LEGACY_MOTIF_MAP`. Detector keys and the displayed curriculum are deliberately separate:

| Previous primary | Canonical primary on refresh |
| --- | --- |
| Activate the King | **King Activity** (same database key, updated display name) |
| Back-Rank Mate | **Mating Net** |
| Exchange Sacrifice | **Sacrifice Material** |
| Piece Exchange | **Simplify** |
| Develop Pieces | **Piece Activity** |
| Build the Attack | **Initiative** |
| Defensive Resource | A supported specific/general motif, otherwise **evaluation outcome** |
| Forcing Moves | A supported specific/general motif, otherwise **evaluation outcome** |
| Tactical Combination | A supported specific/general motif, otherwise **evaluation outcome** |
| Endgame Conversion | A supported specific/general motif, otherwise **evaluation outcome** |

Other approved canonical concepts keep their keys. **Discovery**, **King Activity**, and **Distraction / Deflection** have refreshed display names. Legacy built-in rows remain as `retired` catalog entries for old Coach rating snapshots, adaptive concept references, and regression exports. Retired rows cannot become new primary lessons or appear in the replacement-motif selection list.

Internal `learning.py` detectors may continue to emit their former key; `normalize_learning_labels` combines duplicates and chooses the canonical leaf **after** the regular causal/proactive evidence-selection pass. A specifically supported primary is preserved, protecting previously useful free captures and exchanges. When the old primary is a generic theme, the broader search considers **all** sufficiently supported concrete tactical, strategic, attacking, and defending motifs, not merely candidates nested under the old context. Unsupported geometry alone cannot become a named tactic.

If no supported motif survives, the coach uses the stored evaluation change without manufacturing tactical claims. Examples include **Winning to Losing Position**, **Winning to Drawn Position**, and **Drawn to Losing Position**. The v67 thresholds classify scores by user-perspective centipawns (approximately +180 / -180) or mate scores; they are heuristic outcome descriptions, **not exact tablebase win/draw/loss proofs**, except when supplied by exact mate information. Their classifier confidence is low by design.

## Database and refresh behavior

The existing `position_motif_taxonomy` table already stores `context_key`, `move_type_key`, `motif_key`, `confidence`, `evidence`, and `taxonomy_version` for each position. No additional duplicate fields on the training position or destructive schema migration are needed. `position_concepts` retains one canonical primary and any supported secondary concepts; the Lesson tile and Player filters operate on these same canonical keys.

1. Install v67 while **preserving `data/`**.
2. Existing concept rows are seeded/renamed, and the versioned taxonomy may be backfilled using saved evidence (no Stockfish required at startup).
3. For a complete reclassification of an existing game list, select **Process → Refresh Metadata**. It independently runs bounded Stockfish coaching probes, repeats the causal motif search, writes the canonical primary and hierarchy, and regenerates the explanation. No Lichess retrieval, PGN reimport, or full deep Analysis pass is required.
4. Saved root evaluations/PVs, training positions, learned flags, Player sessions, and historical Coach feedback are preserved. Prior votes are **not reinterpreted as endorsements of a newly renamed primary**; their original snapshots remain available for longitudinal regression.

Lesson Detail continues to support context, move type and primary-motif filters (including All primary motifs), and all filters propagate to the actual training playlist. Retired labels are omitted from new lesson tiles; refresh an old list to regenerate every leaf using the current catalog.

## Testing and safety

`tests/test_coaching_taxonomy_v67.py` checks every legacy mapping, two/three-node paths, duplicate prevention, broader motif search, preservation of already-specific primary motifs, evaluation fallbacks, and SQLite foreign keys. Additional v66 taxonomy and existing Coach/Player regression suites remain available. Full Stockfish-guided acceptance testing and measured human approval-rate comparison are still required to establish net coaching accuracy improvements.

## v68: feedback on each level

The taxonomy used for lessons and proactive coaching remains `position_motif_taxonomy`.
User feedback is deliberately **not** written into that classifier output. Instead,
`position_taxonomy_feedback` stores one latest user selection per `(position_id, field_key)`.
The supported fields are `context`, `move_type`, and `motif`:

- `selected_key` records the user's preferred canonical label, including `none` to
  explicitly indicate no Tactical/Strategic move type.
- `model_key_at_vote` and `taxonomy_version_at_vote` capture what the coach had
  assigned when the user made that selection. On reselection, they are replaced
  along with the selection. A blank choice deletes just that field's row.
- Current assignments remain in `position_motif_taxonomy` and change normally
  with Refresh Metadata; historic user selections and original predictions do not.
- Position relevance, explanation, chat and retired motif thumbs remain in their
  historic tables, with historic motif keys mapped to canonical keys for CSV analysis.

The full Coach CSV combines both feedback types and includes present-day taxonomy,
original predictions, user selections, classifier versions and evidence. Dropdown
agreement means selected=predicted **at selection time**, not a positive/negative
thumb; a disagreement is a proposed regression example. Neither automatically
reclassifies lessons. Deleting training positions cascades their feedback.

## v69: feedback from the inline learning path

The Training page's context, move-type, and learning-motif chips are now
**native-select pills**. These replace the separate three-dropdown panel while
using the unchanged `/api/positions/<id>/taxonomy-feedback` endpoint and
`position_taxonomy_feedback` table. The visible chip uses the user's latest
feedback when present, otherwise the coach's current assignment; corrected
chips are visually marked. The original `position_motif_taxonomy` classification
and the saved engine evaluation remain unmodified.

Pill choices include **Confirm coach** (positive agreement) and **Use coach's
label / clear feedback**. The optional **+ Move type** pill lets a user propose
Tactics or Strategy even when the model produced only a two-level path. A
change from a qualifier to **No tactical/strategic qualifier** displays a
two-level path again, while retaining that explicit preference in feedback.
The existing Coach CSV, regression-candidate export, and reset workflow
continue to capture these records without a data migration.


## v70: defensive blocking, geometry and material provenance

- **Blocking** is an active tactical motif. A check-blocking move must be a legal interposition against the checking slider; a material-blocking move must interrupt an actual sliding attack on a valuable piece, not merely look defensive. Recorded evidence identifies the blocked line; a sample variation is not proof against every reply.
- **Discovery** means the move reveals an attack from *another, stationary* sliding piece. **Double Attack** means the moved piece creates two actionable threats. A verified differential discovered attack takes priority over incidental moved-piece threats.
- **Defend Loose Pieces** requires the losing piece to have been already attacked and undefended in the root position, with a nearby evaluated line showing it can be saved. **Don't Hang Pieces** requires the player's move to newly place its moving piece en prise. **Material Loss** labels other witnessed losses caused by the game move; its stable key remains `lost_material`.
- **Defensive Resources → Strategic Comprehension → Sacrifice Material** is supported when the material-investment detector has produced its motif *and* the evaluation comparison independently demonstrates a defensive material save. A sacrifice is otherwise still classified as a tactical investment.
- Feedback snapshots retain their existing taxonomy keys, and the new Blocking key is seeded through the normal curriculum initialization. **Refresh Metadata** regenerates the classification from saved positions using the independent Stockfish coaching pass, without retrieving or deeply reanalyzing games.


## v72 · Changed-position reporting

Coach now reports three **change rates** (context, move type, learning motif),
not approval percentages for taxonomy dropdowns:

`change rate = number of solved positions with a saved selection differing from
current coach assignment / number of solved positions in the selected scope`.

No dropdown response means *unchanged*, not missing from the denominator.
Confirming the coach label, changing a selection back to its current prediction,
or clearing feedback also means unchanged. Each field is counted independently.
Only positions with `training_positions.learned=1` appear in this denominator.
The relevant game list, opening, primary motif, mode, coach version, category,
context, and move-type filters apply to the position set. Feedback-type and
thumb-rating filters intentionally do not change the position denominator.

The **Taxonomy CSV** endpoint `/api/coach/taxonomy.csv` downloads one row per
solved position, including those without selections. It exports current model
values, optional user selections, three current changed flags, and the original
model snapshot from the most recent selection. This makes all denominators
and numerator decisions verifiable. The previous full-feedback CSV and
regression-candidate CSV remain available with historical snapshots and old
legacy category ratings for backward compatibility; these retired thumbs no
longer have any Training or Coach dashboard controls. Current change status
may differ from the historical at-selection status when metadata is regenerated.

There is no schema change, data deletion, or deep reanalysis in v72.
