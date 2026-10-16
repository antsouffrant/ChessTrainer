# Chess Trainer: coaching and evidence architecture (v54)

## Source of truth

`analysis.py` owns Stockfish scores, candidate move selection, PVs and the persisted training-position record. It does **not** infer that a PV proves every possible reply. The list's retrieved PGN is the immutable input to a new analysis run. `decision_context.py`, `critical_moments.py` and `pv_reasoning.py` calculate legal tactical facts and the short-root consequences of the game move and alternative. `semantic_coaching.py` ranks these findings and selects **one demonstrated chess idea**. `coaching_language.py` standardizes game-specific, evidence-aware sentences. `coaching.py` produces the pre-solve hint and post-solve explanation, using the causal finding first and conservative fallbacks where no single idea is established. `learning.py` classifies motifs using this evidence; `motif_relevance.py` discounts remote, tangential motifs. `metadata_refresh.py` regenerates labels and wording from already-saved analysis rather than rerunning Stockfish.

## Evidence strength and language

1. **Legal root facts** (capture, checkmate, immediate recapture, exact tactical constraint) take priority. Describe a free piece only when a legal recapture does not exist.
2. **Opponent's reply and short continuation** establish how the game move can be refuted. Use “In the game you played X, allowing Y ...”; when the decisive reply is later, say it occurs *in the analyzed continuation*.
3. **Strategic consequences** (activity, defense, structure) require root-board evidence, and must not be presented as inevitable material losses.
4. **Distant PV tactics** are supportive detail only unless they follow causally from a demonstrated plan, e.g. a pawn sacrifice opening a bishop route.
5. **True endgame proofs** use an optional Syzygy tablebase when installed, not a centipawn threshold. `CHESS_SYZYGY_PATH` must point to a local directory with relevant ≤7-piece Syzygy WDL tables; no tables are bundled. Mate scores remain legitimate evidence of forced mate from the evaluated node, but are not equivalent to a tablebase win/draw proof. Missing table data falls back to ordinary engine/board analysis, without a “solved” claim.

## Motif standards

There is no **Evaluate Candidate Moves** motif. **Forcing-Move Scan** is a fallback only when the root position or candidate moves genuinely contain checks or captures. Primary motifs favor direct, verified tactics (mate defense, sacrifice, simplification, material win) over loose-piece geometry. If no concrete tactic survives evidence ranking, choose a low-confidence root-grounded positional motif, without asserting a material win. An old `candidate_evaluation` entry may remain as a historical reference in a legacy database, but cannot be newly assigned after a v53 reclassification.

## Loose-piece provenance (v54)

The classifier now distinguishes **the source of the vulnerability**, not merely whether a piece is attacked:

- **Protect Loose Pieces**: the user's piece was already attacked and undefended in the training position; the superior move demonstrably prevents its near-term loss.
- **Don't Hang Pieces**: the game move places its own piece on a loose square; a legal immediate capture is available. A stored variation is needed to claim that material *was lost* rather than merely risked.
- **Lost Material**: the inferior line demonstrably loses material that was not already loose in the root position, e.g. moving its defender away.
- **Capture Loose Pieces**: the recommended move immediately takes an enemy target already available in the training position, without a legal immediate recapture.
- **Attack Loose Pieces**: the recommended move creates a *new* threat against an enemy target, and a legal near-term continuation demonstrates a differential material payoff. Simply capturing a pre-existing free piece does not count.

`loose_piece_provenance.py` centralizes the distinction for the classifier and causal explanation generator. Old labels and votes remain historical records until Refresh Metadata or clean Restart Analysis; the increased `CLASSIFIER_VERSION` updates derived labels from saved lines without repeating Stockfish analysis.

## Iteration controls and data retention

| Control | Engine evaluation | Derived training positions | Learned progress/chat/ratings | Downloaded games |
| --- | --- | --- | --- | --- |
| Pause / resume | Continues last checkpoint | Preserved | Preserved | Preserved |
| Analyze again | Adds a deeper pass | Preserved and enriched | Preserved | Preserved |
| Refresh Metadata | Not rerun | Same IDs and evaluations; regenerated labels/text | Preserved | Preserved |
| **Restart Analysis** | Recomputed from game one with current settings | **Deleted and regenerated** | **Deleted for that list** | **Preserved** |
| **Coach → Reset feedback** | Not rerun | Preserved | **Thumbs ratings removed** (selected list or all) | Preserved |

Restart is an irreversible clean-iteration operation. Export Coach CSV first to archive the old coaching assessment. Only the selected list is cleared; other lists are untouched. Reset waits until analysis and any in-flight metadata refresh worker have stopped before deleting records. Coach reset requires a confirmation phrase, and deletes only position/explanation/motif/chat *ratings*, not the conversations themselves.

## Validation

Run `python -m unittest discover -s tests` with the packages in `requirements.txt`, plus `node tests/*.cjs` individually. SQLite/process and browser-contract tests run even without python-chess; true chess-board tests require python-chess. Full Stockfish and optional Syzygy integration require local engine/table files and must be verified in the running app.
