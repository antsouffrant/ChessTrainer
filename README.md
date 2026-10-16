# Personal Chess Trainer

## October 16, 2026 — v46 game-list processes and durable analysis

- **Retrieval** is a creation-only, distinct Lichess downloader. A successful import saves an immutable PGN batch under `data/batches/`, marks retrieval complete, and automatically queues **Analysis**. Further clicks on Analyze or Refresh never call the Lichess downloader. An interrupted retrieval can be retried on the *same* list, without creating a new list; a partial download is discarded and downloaded again, not byte-range resumed.
- **Home** shows *Retrieving games*, then *Analyzing games*. Train, Lessons, and Openings are disabled and grey until at least one actual training position is stored. The Train button becomes white on readiness. Analyze and Refresh also disable while the list is retrieving or either operation is active.
- **Process** groups retrieval, evaluation and metadata refresh within each saved game list. One Play/Pause/Stop transport controls that list's current task. Analyze and Refresh remain explicit operations, disabled whenever incompatible work is underway. Status counters and progress are persisted in SQLite and polled in the UI.
- **Analyze** now resumes from the last committed per-game PGN offset after pause, stop, error, or app restart: no checkpoint reset. After a completed list, *Analyze again* starts exactly one **next, deeper refinement pass** on the saved PGN, retaining prior confirmed positions and solve history. Enabling new learning modes on a completed list also schedules an additional pass instead of clearing earlier work. Refresh remains a non-Stockfish metadata rebuild with its own resumable cursor.
- **Startup** continues to leave interrupted work paused rather than launching unrequested CPU-intensive jobs. Resume is explicit on the Process page. The local SQLite database (`data/`) and saved batches must be preserved between runs; they are not shipped with this source archive. The source archive contains no imported game data.
- Tests: `python -m unittest discover -s tests -p 'test_process_policy_v46.py' -v`, `python -m unittest discover -s tests -p 'test_retrieval_v45.py' -v`, `python -m unittest discover -s tests -p 'test_analysis_checkpoint_v38.py' -v`, `node tests/test_processes_ui.cjs`, `node tests/test_retrieval_ui_v45.cjs`, `node tests/test_process_media_v38.cjs`.

---

## October 16, 2026 — v42 root evaluation gap and critical-moment attribution

- The explanation system distinguishes **where the evaluated mistake is made** (the training decision's before/after centipawn gap) from the **first move in the saved continuation that demonstrates its cost**. A PV realization is not a second centipawn swing: Stockfish already anticipates the reply in its root evaluation.
- Deep-confirmed training positions now save `critical_events_json`: an evidence-versioned, root-aligned first material realization from the best and played Stockfish lines, including its ply, SAN, victim square, and saved root score difference. It does not add new engine requests or alter evaluated positions.
- Priority is given to an early concrete loss (e.g., after a player hangs a bishop on d4, `...Qxd4` wins it) over a later incidental fork or positional-pressure description. Immediate clean wins, mating responses, and forced check defenses remain respected.
- Only claim material loss when both valid PV prefixes allow comparison, a meaningful root eval gap exists, the lines show a net material difference, and the loss is not simply an equal recapture/exchange. Missing/inconclusive PVs generate no claim.
- Primary motif selection on newly analyzed or metadata-refreshed positions can be corrected to **Protect Loose Pieces** when the early material loss is demonstrated and doesn't conflict with mate or a directly winning root capture.
- Older saved positions are compatible. **Refresh metadata** reconstructs these critical moments and coaching copy from the existing evaluations/PVs, without downloading games or invoking Stockfish. No learned status or attempts are changed. Some old positions lack sufficiently detailed PVs; those need evaluation to gain new evidence.
- Regression cases: `python -m unittest tests.test_critical_moments_v42 -v` (requires `python-chess`). SQL placeholder/schema and JS trainer checks can be validated independently.


## October 15, 2026 — v38 resumable analysis and compact Process controls

- Process now uses accessible Play (`▶`), Pause (`Ⅱ`) and Stop (`■`) controls with tooltips. Play on a paused job resumes, while Play after Stop or completion explicitly starts a fresh analysis.
- Previously the analysis loop reset `games_processed` and replayed the PGN from the beginning whenever a paused thread restarted. Analysis now commits a durable checkpoint (pass, completed-game index, PGN seek position) **only after each game's screening, deep confirmation, cache and position updates have been committed**. Resume seeks straight to the first unfinished game in that pass. A game paused mid-evaluation may be repeated; earlier completed games are not reevaluated.
- Completing one refinement pass advances the persisted checkpoint into the next pass. Stop followed by Play resets all checkpoint fields. The local worker waits for a previous stopped thread to exit before restarting, preventing competing workers for the same job.
- Older v37 paused tasks have no durable checkpoints. Where a partial pass has a trustworthy count, the first v38 resume conservatively revisits the last counted game rather than replaying the entire earlier portion; other ambiguous legacy states may repeat the pass once. All subsequent pauses have accurate checkpoints.
- These are local SQLite-backed state transitions; progress survives leaving the Process page and restarting the app. A restart still starts idle, preserving interrupted jobs as paused until explicitly resumed.
- Regression checks: `python -m unittest discover -s tests -p 'test_*_v38.py' -v`; `node tests/test_process_media_v38.cjs`.


## October 15, 2026 — v31 decision relevance and verified legal counterfactuals

- Classifier now compares candidate learning motifs across **Context → Threat/Opportunity → Response**, rewarding the same threatened piece/square and explicit contrast between the recommended move and the move played. Neither an incidental pin on the board nor a tactic only found late in a sampled engine PV can own a lesson without near-root response evidence. This is an evidence-ranking heuristic, not a calibrated chess-theory probability.
- Legal counterfactuals supplement illegal pinned-capture analysis. A legal played move can be contrasted with a best move that protects a specifically threatened piece. A tempting *legal opponent capture* is described as a trap only when a fully legal, immediate mating refutation is provable from the board. Other plausible replies require targeted Stockfish verification before the app may call them mistakes or traps.
- The explanation can now describe both a legal opponent capture that permits a demonstrable mate in one and a missed defense of the same threatened piece. Solver-facing hints do not reveal this evidence until after the puzzle is solved.
- Classifier/coaching versions are updated. **Refresh metadata** regenerates explanations, motif labels, and lesson membership from saved PGNs/evaluations and existing PVs without changing source games, engine scores, learned states, or prior attempts.
- Pure relevance regressions: `python -m unittest discover -s tests -p 'test_motif_relevance_v31.py' -v`. Chess-specific regressions require `python-chess`; Stockfish-dependent deeper legal reply probes are not yet automatic.


## October 15, 2026 — v30 context → threat → response comprehension

- The coaching and motif classifier share a three-stage board-evidence packet: (1) the opponent's previous move and new geometric constraints, (2) actionable threats and opportunities at the training position, and (3) the recommended response, including verified reasons an apparent defense is impossible.
- Detect pseudo-legal captures by pinned enemy pieces that are actually **illegal** because the attempt exposes their king. This can explain why a seemingly hanging checking piece cannot be captured. These illegal moves are never passed to the engine as candidate continuations. Discovered checks can also benefit when the apparently capturable checking piece did not just move.
- The learning motif **Pin** is supported by a specifically blocked capture, even if the pin existed before the recommended move; the primary motif remains Mate when mate is decisive. Merely observing a geometric pin is not sufficient.
- New-attacker and hanging-piece context discounts pinned attackers whose capture leaves the pin line; raw `is_attacked_by` geometry alone does not prove a viable capture.
- Versioned coaching and classifier metadata can be refreshed from saved games without reimporting or reevaluating. Run `python -m unittest discover -s tests -p "test_context_prompt_response_v30.py" -v` in an environment with the installed requirements to check the new pin/illegal-reply regression fixtures.


## October 15, 2026 — v16 learning motifs and PV-grounded coaching

- All user-facing curriculum terminology now reads **learning motifs**; stable SQLite identifiers remain unchanged so older analyses and adaptive coaching records continue to work.
- New Stockfish deep confirmations retain legal, bounded best-move and game-move principal variations in SQLite. A solved older position can acquire these lazily on review with the configured post-solve review budget, without reimporting the games. If Stockfish is not present, the original explanation remains available.
- Explanations distinguish the changed position, the mechanism behind the best move, and a short *sampled* engine continuation. A sampled PV is evidence, not proof of a forced sequence.
- Motif ownership now lets checks that fork king and material, safe double attacks on two loose pieces, and demonstrated continuations become **Double Attack** instead of defaulting to **Forcing-Move Scan**. Incidental pins are still not promoted without proof they matter.
- Versioned relabeling preserves attempts and learned state. Engine-enriched motifs are refreshed for the position when its solution is opened; newly analyzed positions include PV evidence from the start.
- Run targeted tests with `python -m unittest discover -s tests -v` after installing requirements; analysis-engine behavior has to be checked with a real Stockfish executable.


Local Flask prototype that turns your Lichess games into personalized Stockfish training positions and lesson playlists.

## October 14, 2026 — v13 dual progress indicators and trainer spacing

- A prominent progress bar above the training workspace tracks learned vs. remaining positions in the **current fixed playlist**. It works for individual lessons and the all-positions playlist, updates on solve/reset/learning-status changes, and retains the playlist denominator while reviewing solved puzzles.
- The floating Analysis dashboard now shows **current evaluation cycle** progress instead of lesson-learning progress. It reports games screened within the current refinement pass (`games_processed / games_retrieved`), resets when the next pass begins, and identifies the pass number. Screening completion can precede final deep confirmation.
- Added modest vertical spacing throughout Your Task (instructions, hints, feedback, solution), keeping the four position controls in their reserved layout. No game reimport is needed.

## October 14, 2026 — v12 lesson controls and fixed playlists

- The lesson save-status text sits immediately to the left of **Save lesson**, next to **Reset lesson**.
- **Train lesson (N)** and **Select all filtered (N)** are above the filter shelf. The five existing filters share equal-width columns where space permits.
- Select individual position tiles, or select every match across all pages. Use **Mark learned** or **Mark to train**, then **Save lesson** to commit the staged changes. **Clear selection** preserves staged changes until they are saved or changed again.
- The active training session uses a fixed ordered playlist: completed/learned cards remain available with **Last position**, and Resume restores that same playlist. Fresh launches exclude positions currently marked learned. On finishing the last puzzle, Next returns to the lesson tiles, and Reset lesson is available to reopen learned positions.
- Saved playlist membership is browser-local; game data and learned status remain in the SQLite database. No reimport/reanalysis is needed for this release.

## October 14, 2026 interface update

- The top-left Trainer label opens an app introduction. Home opens the starting dashboard; Training and Lessons resume their saved context for the active analysis job.
- Lesson filters and sort order persist locally for each analysis job; position selection and trainer playlist context persist on navigation. Changing lessons starts a new training context.
- Lesson filters have additional padding; training lesson metadata now lives inside Your Task instead of a separate banner.
- Your Task identifies the learning outcome and game move, when available; the initial instruction appears only after revealing the hint.
- **Brilliancy logic already present:** annotated PGN `!!` and `!` are respected after an engine-best-move check; unannotated brilliant classifications require an apparent sacrifice plus a uniqueness gap, and forced mate alone is not brilliant. This is a heuristic, not verified Lichess analysis labels; historical positions need reanalysis to acquire new classifications.



**v2.5 trainer feedback & review UX:** training positions can be refreshed back to unsolved, accepted near-optimal moves are shown in gold while the engine-preferred move remains green, the Stockfish arrow uses a darker gold with a larger arrowhead, and adaptive-coach replies support persistent thumbs-up/down feedback. Ratings are stored separately from chess truth; when local Ollama coaching is enabled, prior liked/disliked replies are used only to adapt future presentation style.

**v2.0 adds an adaptive coaching system:** a persistent right-side conversation parses player explanations into structured chess claims, verifies/refutes them against the board, stores evidence, and can promote recurring user-discovered ideas into personal learning motifs that are applied on future analysis passes.

## v1.5 coaching and analysis overlay

- Stockfish recommendations are now drawn as an explicit full shaft + arrowhead, so even one-square moves display as a visible source-to-destination arrow rather than an oversized arrowhead.
- The arrow uses a translucent metallic-gold shaft with a darker outline and a subtle highlight.
- Coaching text is regenerated with a more specific rules engine that describes attacked pieces, captures, checks, queen exchanges, defensive moves, new threats, added defenders, and tactical motifs whenever those facts can be established from the board.
- The lesson vocabulary is normalized into short titles plus action-oriented subtitles, with consistent families: Tactics, Defense, Strategy, Endgames, and Calculation.
- Additional broad learning motifs include Build the Attack, Counterattack, Simplify, and Coordinate Pieces. Existing databases are relabeled/backfilled automatically through versioned classifiers.

## v1.3 analysis mode and move-quality acceptance

- The Stockfish toggle now analyzes the exact board currently displayed. It no longer snaps a solved puzzle back to the original training position.
- After solving a puzzle, Stockfish mode makes the displayed board interactive for the side to move. You can play legal hypothetical continuations and Stockfish reevaluates each resulting position.
- The engine arrow uses a silver/graphite metallic gradient to match the interface.
- Puzzle answers are no longer always exact-move tests. The stored engine-best move is accepted immediately; another legal move is also accepted when a short verification keeps it within 0.60 pawns of the best evaluation and improves by at least 0.75 pawns over the move actually played in the game.
- In forced-mate lessons, an alternative move is accepted when it preserves a forced mate.
- The trainer language now asks for a "strong move" and labels the revealed top line as the engine preference.


## Local setup

1. Put a Stockfish executable anywhere inside `stockfish/`.
2. Install the Python dependencies with `pip install -r requirements.txt`.
3. Start the app with `python app.py`.
4. Open `http://127.0.0.1:5000`.

## Current workflow

- Verify a public Lichess username.
- Choose a relative date range and game types.
- Download the selected games in one Lichess PGN batch.
- Screen each game with an approximate total Stockfish time budget (default: 3 seconds/game).
- Deep-confirm only candidate mistakes with a second time budget (default: 10 seconds/candidate).
- After the first pass finishes, automatically repeat the same downloaded batch at progressively higher Stockfish depth caps (8/16 → 10/20 → 12/24 → 14/28 by default). Time budgets remain fixed, so each refinement pass is bounded.
- Save distinctive learning positions to SQLite as soon as they are confirmed.
- Classify each saved position into one or more explainable chess-learning motifs.
- Populate lesson playlists live while analysis continues.
- Rank lessons by the number of distinct games containing each primary motif; order positions within a lesson from lower estimated difficulty to higher estimated difficulty.

## Progressive, resumable analysis

Version 1.1 turns analysis into a sequence of refinement passes while retaining the persistent analyzed-game cache keyed by account + game ID.

- Games are cached with the deepest screening/deep-confirmation depth completed under the current analyzer version. A pass skips a game only when the cache is already at least that deep.
- Cached training positions, concepts, difficulty estimates, and learned state are carried into the new analysis job.
- Games that produced zero training positions are also cached at each completed depth. A later, deeper pass can still revisit them and discover a line the shallower pass missed.
- An interrupted job reuses its existing downloaded PGN batch and resumes the same refinement pass. Games already completed at that depth are skipped.
- Jobs left queued/retrieving/running are paused when the app restarts, and the user resumes them explicitly from Process.
- Older databases are backward-compatible: existing positions and learned/attempt history are retained. Legacy cache rows begin at depth 0 under the new progressive analyzer, so a new analysis can re-screen those games and progressively apply current outcome criteria and lesson labels.

Downloaded PGN batches remain under `data/batches/` and SQLite is stored at `data/chess_trainer.sqlite3`.


## Windows Stockfish reliability

Version 0.8 launches Stockfish in its own process group so console Ctrl+C/close events do not propagate into the engine process. Analysis is serialized in the local prototype, and both background analysis and post-solve review automatically respawn Stockfish and retry the current operation if the engine terminates unexpectedly. This specifically hardens the app against Windows `0xC000013A` / `3221225786` control-event exits.

## Learning motifs

The app seeds a compact amateur curriculum spanning tactics, defense, strategy, endgames, and calculation habits. Classification is multi-label: one motif is marked primary, but a position can support several lessons.

Existing database positions without labels are automatically backfilled at startup when enough saved move information is available.

## Lessons

Lessons are available while asynchronous analysis is still running. The lesson page refreshes live as new positions are confirmed. Each lesson is a clickable tile showing:

- distinct games contributing to the lesson;
- total labeled training positions;
- positions already marked learned.

Within a lesson playlist, at most one representative position is kept from each game and the resulting playlist is sorted from easiest estimated puzzle difficulty upward.

## Estimated puzzle difficulty

Stockfish does **not** provide an Elo or human move-rating estimate. The app therefore stores a transparent first-pass `difficulty_score` plus an `estimated_rating` intended only for curriculum ordering.

The heuristic uses information already available during deep confirmation, including legal move count, whether the best move is a check/capture/promotion or a quiet move, mating distance, and the evaluation gap between Stockfish's best and second-best choices. The resulting number is shown only after the puzzle has been solved and is labeled an **estimated puzzle rating** rather than Elo.

This estimate is designed to be replaced or calibrated later using real solve rates and player-rating data.

## Trainer behavior

- The board orients from the user's side and preserves standard square colors.
- The opponent's immediately preceding move plays once after a short pause.
- Piece movement uses a short, responsive animation (~140 ms), with a brief pause before the opponent replay so the position remains readable.
- The side to move is stated explicitly.
- Use the history arrows or PGN tokens to inspect earlier moves.
- Only legal moves can be submitted. Dropping a piece back on its starting square or attempting an illegal destination does not count as a failed attempt.
- Legal destinations are subtly indicated after selecting a piece. Empty-square hints are absolute centered dots; capture hints are rings and never affect board-row layout.
- A submitted move is actually played on the board, including captures, before correctness feedback appears.
- A wrong legal attempt shows the resulting position briefly, highlights the destination red, shows a red X, then restores the training position by replaying the opponent's prior move.
- A correct attempt leaves the winning/resulting position on the board, highlights the move green, shows a green check, and marks the position learned.
- Learned state propagates across cached copies of the same position from different analysis jobs.
- After a puzzle has been solved, a **Stockfish** toggle appears alongside the move-history controls. When enabled, it evaluates the board exactly as currently displayed, shows the score from the user's perspective, and draws Stockfish's preferred move as an arrow. Legal continuation moves can then be explored interactively.
- On-demand historical evaluations are cached by FEN in SQLite.

## Data tables

Important tables include:

- `analyzed_games`: persistent account/game cache used to avoid redundant Stockfish work;
- `learning_concepts`: seeded lesson catalog;
- `position_concepts`: many-to-many labels, confidence, primary flag, evidence, and classifier version;
- `training_positions`: puzzle, solve history, and estimated difficulty fields;
- `engine_eval_cache`: cached post-solve Stockfish evaluations for reviewed FENs.

## Outcome-symmetric mistake detection (v1.0)

The analyzer now searches both sides of the learning problem. In addition to missed wins, it retains defensive mistakes that turn playable positions into losses. Outcome categories include:

- `missed_checkmate`: a forced mate was available and lost.
- `blundered_win`: a large error while remaining clearly winning.
- `squandered_advantage`: a winning position was reduced to a non-winning but non-losing position.
- `threw_away_win`: a winning position became clearly losing.
- `blundered_draw`: an approximately equal position became clearly losing.
- `blundered_into_loss`: another playable position crossed into a clearly losing evaluation.
- `allowed_checkmate`: the move allowed a forced mate that was not present beforehand.
- `major_blunder`: a very large one-move evaluation loss from an otherwise playable position that does not fit a more specific outcome category.

The lesson taxonomy also includes defensive concepts such as stopping mating threats, opponent-threat awareness, loose-piece awareness, and finding defensive resources. Cached games from older win-only analyzer versions are re-screened once, while existing puzzles and learned state are retained.

## Progressive depth refinement (v1.1)

Each analysis job now performs four passes by default. `screen_depth` and `deep_depth` remain the base caps (8 and 16), then each completed pass raises them by +2 and +4 respectively. The time budgets do not increase, which preserves the fast-first experience while allowing Stockfish to search farther whenever the hardware can do so within the same budget.

Known positions are **upserted** on deeper passes: evaluation, best move, outcome category, estimated difficulty, and lesson labels can be refreshed without losing `learned`, `attempts`, or `correct_attempts`. Positions that only become visible at a deeper pass are added to the existing playlist. The analysis UI, lesson page, and trainer HUD expose the active pass and depth so users can train while refinement continues.


## v1.3 UI refinement

- Stockfish arrows use a translucent metallic-gold treatment.
- Engine-arrow SVGs are padded beyond the board so edge arrows do not clip.
- Enabling Stockfish analysis hides the solved check mark.
- Every newly opened puzzle still starts with Stockfish analysis disabled.

## Coaching voice (v1.4)

Each training position now stores two local, rule-generated coaching fields:

- `coach_prompt`: spoiler-safe context shown before the user solves the puzzle.
- `coach_explanation`: concise explanation shown after the puzzle is solved.

The coaching generator uses the stored FEN, the opponent's previous move, piece attack geometry, the engine preference, the game move, the outcome category, and lesson labels. It does not require an external LLM or API. Existing positions are backfilled at startup, and progressive Stockfish passes refresh the coaching text when a deeper pass changes the underlying analysis.


## v1.6 trainer behavior

- Contextual coaching hints are opt-in before solving.
- Outcome/category labels and Stockfish review controls remain hidden until the puzzle is solved.
- Learned positions stay in SQLite but are excluded from active training playlists.
- Lesson tiles can reset their learned positions without deleting analysis data.
- The engine recommendation arrow uses a heavier metallic-gold shaft for clearer board visibility.


## v1.7 UI hierarchy

- Makes the side-to-move instruction the primary trainer heading.
- Treats the opponent name as secondary context.
- Repeats “Find a strong move. [Color] to play.” in the task panel.

## v1.8 — pause/resume and global analysis settings

The app now has a `/settings` page for Stockfish, screening, refinement, puzzle-selection, and trainer thresholds. Settings are stored in SQLite and snapshotted into each new analysis job. Changing analysis-relevant settings changes the game's cache signature, so a future analysis can reconsider previously cached games under the new rules without deleting learned positions.

Active jobs can be paused from the analysis page, lesson page, or trainer HUD. Pause is cooperative: the current Stockfish call is allowed to finish, then the worker exits and releases the engine. Resume continues the same pass and uses the analyzed-game cache to skip work already completed at that depth.

`SCREEN_MIN_ADVANTAGE_CP` from earlier prototypes is intentionally not exposed because the symmetric win/loss analyzer no longer uses a separate advantage-only screening threshold; `screen_playable_cp` is the active shallow eligibility threshold.


## v1.9 interface updates

- Stockfish move annotations use a wider, softer translucent-gold arrow that begins just outside the source piece and points to the destination-square center.
- Settings includes an optional polished wooden board theme with pine-toned White pieces and hickory-toned Black pieces.
- The Settings Back control follows browser history instead of routing directly to Setup.

## v2.0 — adaptive coaching and learned curriculum

Version 2 adds a persistent coaching system beside the trainer. It is deliberately split into language understanding and chess verification:

1. A user message is parsed into one or more structured claims (`intent`, `claim_type`, square/file references, candidate concept).
2. The coach tests those claims against the saved puzzle position, the engine-preferred move, attack/defense geometry, material changes, king mobility, center control, open files, bishop color complexes, and other reusable board features.
3. Each claim receives a verdict (`confirmed`, `partial`, `refuted`, `uncertain`, or `pending`) plus evidence and confidence.
4. Verified ideas that already match the seeded taxonomy are attached to the existing concept rather than duplicated.
5. Verified ideas outside the seeded taxonomy can create a user-scoped **candidate concept** with a declarative detector.
6. Candidate detectors are immediately tested against the account's existing saved positions and are also applied during future analysis passes.
7. A candidate becomes a visible **personal learning motif** only after it passes the configured recurrence / verified-claim / promotion-score thresholds.

Initial adaptive detector templates include open-file control, opposite-colored bishops, central space, square clearance, king routes, long diagonals, outposts, and the bishop pair. These deliberately demonstrate the extensible detector model rather than pretending arbitrary chess language can already be converted into a safe rule automatically.

### Coach database tables

- `coach_threads`: one persistent conversation per account / training position.
- `coach_messages`: user and coach turns plus structured parser output.
- `coach_claims`: normalized claims, verdicts, confidence, explanation, and concept links.
- `concept_evidence`: auditable evidence connecting a claim/position to a learning motif.
- `learning_concepts`: now supports built-in and user-scoped concepts, lifecycle status, aliases, detector JSON, evidence counts, distinct games, and promotion score.

### Candidate concept lifecycle

`claim → verified evidence → candidate concept → account-wide detector scan → personal concept → lesson playlist`

Candidate concepts are used by the adaptive classifier even before promotion, but they are hidden from the lesson-plan page until they have enough evidence to become a personal concept. This prevents one speculative comment from becoming a permanent curriculum category.

### Optional local model parsing

The adaptive coach works without a language-model dependency. Settings includes an optional **Use local Ollama for claim parsing** switch, plus Ollama URL/model fields. If enabled, Ollama is asked only to convert free-form language into structured claims. If it is unavailable or returns invalid output, the app falls back to the built-in parser. Verification and curriculum promotion remain deterministic.

### Spoiler safety

Before a puzzle is solved, coach messages are stored as pending context and replies remain non-spoiling. They cannot create or promote learning motifs. Once the position is solved, the thread can fully validate/refute ideas and create evidence for the adaptive curriculum.

## v2.2 Grounded Chess Dialogue

The adaptive coach now resolves concrete human chess language against the board before concept classification. It can handle examples such as:

- `What if the knight blocks on c3?`
- `Why not Nf5?`
- `What if Nc3 Rxe1 Qxe1?`
- `Can I take the queen?`
- `What is the threat here?`
- `What is the plan?`

Move questions are checked for legality from the exact FEN currently displayed in the trainer. Candidate moves and user-proposed lines are evaluated with the local Stockfish review engine. Before a puzzle is solved, the coach may evaluate a move the player explicitly proposes, but it does not reveal Stockfish's preferred alternative. After solve, comparisons may include the engine preference and evaluation gap.

Conceptual statements still flow through the adaptive concept/evidence system and can become personal learning motifs when they are verifiable and recurrent.

## v2.11 progress and lesson-plan refinement

- Learned/unlearned status is now bidirectional during a solved review session without interrupting Stockfish or analysis.
- Exact duplicate puzzle signatures (same FEN + best response) share curriculum learned state across cached jobs/games.
- Lessons now includes a browsable Position Library with thumbnails, concepts, estimated rating, filtering, sorting, direct-open links, and bulk learned/review-again controls.
- Live and displayed evaluation uses conventional White POV: positive favors White, negative favors Black.
- Training learning motifs use the full explanation-panel width to reduce vertical overflow.

## v2.14 pagination and explicit progress reporting
Lesson-detail position browsing is server-paginated (50 positions per page by default, configurable under Settings → Lesson browsing) after applying the selected status filter and sort order. Learning-status edits remain staged across pages until Save learning progress is used.

Analysis reporting now uses explicit, shared metrics across the analysis page, trainer HUD, and lesson overview: Total games, Games screened, Positions analyzed (unique candidate positions sent to deep confirmation), Training positions (confirmed retained puzzles), Positions learned, and % learned. A persistent analysis_candidates table records candidate-level deep-analysis coverage for new/refined jobs; legacy jobs use confirmed puzzles as a conservative lower bound where rejected-candidate history was never stored.


October 2026 changes: deep seconds input accepts 10.0; adaptive coach defaults on for fresh settings; two negative learning modes are consequential mistakes and smaller blunders (legacy stored positions retain their existing mode); positive reinforcement uses estimated puzzle rating relative to PGN player Elo when available, with verified PGN annotations taking precedence. Existing analyzed data is not silently recalculated.

### Navigation and task layout update
- Lessons in the top navigation always opens the lesson tile index for the active job.
- Train active positions on the lesson tile page explicitly starts an all-position playlist (`listing=1`), bypassing saved lesson playlist redirects.
- The colored outcome chip includes the played move, and the redundant plain-text outcome is removed.
- The opponent preview includes whose turn it is. The basic instruction appears directly below Show hint.


**v2.16 trainer compactness:** Removed the redundant top-level opponent/color banner. Opponent, game date, and move number now sit in the compact board-history shelf alongside the position state, with Stockfish to the right. Position navigation lives immediately under the task instructions rather than below the board-height row. Initial neutral feedback no longer repeats the instructions; actual move feedback and errors still appear.

### UI/navigation refinements (October 14, 2026)
- Solved puzzle actions (Reset puzzle, Position learned) sit together in the navigation column immediately above the Last/Next position controls.
- Engine analysis appears in yellow in the board's top metadata rim, separate from correct/learned feedback.
- The final solved puzzle's Next position button returns to the lesson index; the saved playlist pointer is cleared.
- Lesson-detail filters and sort/page state are saved separately for each learning motif, with default filters on first visit to each lesson.

- v2.28: Puzzle reset/learned controls occupy a reserved board-bottom row; the Last/Next pager remains in its own fixed row aligned with the move list and no longer shifts when a puzzle is solved.

- v2.29: Lesson detail now groups **Save lesson** and **Reset lesson** in the lesson header. The filtered **Train lesson (N)** action lives at the end of the filter shelf, reflecting the currently eligible positions. Removed the redundant “N shown” badge above the position list; pagination retains the matching count. No reanalysis is needed.

## v2.33 — primary lesson ownership and grounded explanations

- **One lesson per position:** a prioritized, evidence-based primary concept is selected at classification time. Forced mate and mandatory mate defense outrank incidental tactical tags. Secondary concepts remain visible in the solved-position explanation but are not separate lesson memberships. Older stored positions are automatically reclassified on next normal app startup; learned status is unaffected. Existing playlists retain their position IDs and can still be resumed.
- **Outcome wording:** non-forced engine evaluations use descriptive position transitions (e.g., "Drawn → Losing Position") instead of "Blundered a Draw". Forced checkmates remain explicitly identified as forced.
- **Difficulty:** `heuristic-v3-choice-complexity` uses plausible forcing alternatives, legal response count, quiet moves and mating distance. Existing puzzle ratings can be recomputed locally at startup without Stockfish or reimport. Ratings remain *heuristic*, **not verified Elo**; empirical calibration needs actual solve rates at known player ratings.
- **Explanations:** regenerated at startup under `rules-v3-primary-and-mate-grounded`, emphasizing forced mate/defense first and the primary tactic instead of incidental checks or captures. Because stored analysis lacks complete principal variations, text does not fabricate forced continuations. Future improvement: persist Stockfish multi-ply PVs at analysis time and support feedback-driven corrections.
- **About popdown:** clicking the Trainer title toggles an anchored dropdown, closed by Escape, outside click or the Close button. No modal overlay.
- **Compatibility:** no schema change or game reimport is necessary to apply existing-position concept/rating/explanation changes. Rating-aware excellent/brilliant selection that was decided during import remains unchanged until a fresh game analysis; rescoring ratings does not retroactively rewrite those classifications.

## v2.34 — contextual explanations and causal lesson ownership

- **What changed?** `position_context.py` compares `previous_fen` plus the recorded opponent move against the puzzle FEN. It identifies *new* attacks, undefended targets, exposed opposing pieces, and captures. The pre-solve prompt only calls something a new threat when this comparison confirms it.
- **Why is the response useful?** The same checks examine the recommended move and, where relevant, the game move. They identify concrete recaptures, removal or protection of newly threatened pieces, undefended captures, and genuinely two-target attacks. The post-solve explanation prioritizes this cause-and-response connection, with a specific contrast when the game move fails to address an identified loose piece.
- **Primary lesson versus incidental detail:** A geometrical motif (especially a pin) cannot become the primary lesson merely because it appears on the board. Newly created pins are kept only as secondary evidence when they constrain an *undefended, attacked, valuable* enemy piece. An immediate or engine-confirmed mating consequence outranks all of these checks. When no causal lesson is established, the position belongs to **Forcing-Move Scan**, with candid wording instead of an invented pin/fork story.
- **Backward compatibility:** The `CLASSIFIER_VERSION` and `COACHING_VERSION` strings change, so the app reclassifies concepts and regenerates prompts/explanations for saved positions at next startup. Learned flags, sessions, games, and engine analyses are preserved. No reimport is required. As before, lesson playlists already in progress retain their position IDs.
- **Important limitation:** Saved puzzles do **not** include full engine principal variations. The context checks validate *immediate* board consequences, not multi-ply tactical causality. Some positions will now receive deliberately generic but accurate explanations; teaching more complex combinations reliably requires storing and interpreting engine continuation lines. These labels have not been benchmarked against expert-annotated puzzle explanations.

To run the included regression examples in an environment with requirements installed: `python -m unittest discover -s tests -v`.


## v17 · Comparative continuation reasoning and lesson motif refresh

- Post-solve explanations inspect **two branches from the same training FEN**:
  the engine-best root move and the move actually played. Rather than displaying
  the raw SAN lines, the app now extracts delayed material captures, checking
  sacrifices that recoup material, later double attacks, sampled mating finishes,
  and specific material losses along the played branch. A sampled PV illustrates
  one engine response; it is not a proof that every move in the line is forced.
- The learning-motif classifier uses these same verified continuation events
  to prioritize later tactical payoffs, including a new **Tactical Combination**
  motif where appropriate. The earlier one-move pin heuristic does not regain
  primary priority. Position classification and coaching text are versioned and
  rebuilt automatically on startup without changing learned/attempt history.
- In v17, the lesson tile page included **Improve learning motifs**, an optional
  targeted Stockfish pass over positions missing saved best/played continuations.
  It works in small batches, changes only cached PVs/primary motifs/explanations,
  and does *not* retrieve games or rerun deep candidate discovery. You can leave
  and restart the action; completed batches remain saved in the local SQLite DB.
  Stop/pause the original game evaluator before using this action. Stockfish
  must be installed in the configured folder.
- The actual lesson membership is `position_concepts.is_primary = 1`; refreshing
  the primary motif changes the bucket immediately. You do **not** need to
  reimport the PGNs or run the full evaluator, but positions with no saved
  continuations cannot receive line-based motif evidence until enriched.
- Existing source data/learning history are preserved. The scoring and
  explanation models remain rule-based heuristics and should be validated
  against representative annotated games and Stockfish continuations.

## v18 · Outcome-led explanation and learning motifs

- The post-solve explanation now ranks concrete consequences of the **best** and **played** continuations from the identical puzzle FEN, rather than relying on the presence of unrelated static shapes or saying a move "changes the tactical balance."
- Priority: an observed mate; delayed material gains, exchanges, checking sacrifices and defections of defenders; newly added/removed attackers and defenders; structure (doubled, isolated, conservatively detected backward pawns); passed pawn creation/advancement; king danger and endgame king activity; finally added space. An attack is not automatically described as a material win. Forced mate needs engine mate evidence; no endgame is called tablebase-proven without a tablebase.
- Equal-ply snapshots compare materially and positionally different branches to avoid mistaking a longer saved engine line for a better result. A truncated PV does not establish that a final capture cannot be recaptured. Motifs and explanation sentences draw from the same continuation evidence, so the one-primary-motif lesson bucket follows the actual outcome. New motifs include **Pawn Structure**, **Space Advantage**, and **Distraction / Deflection**.
- If PVs cannot establish the deeper mechanism, the text reports verifiable move consequences and changing control rather than inventing a tactical outcome. Some quiet strategic choices still need deeper analysis or external human annotation to be fully explanatory.
- The classifier/coaching versions have been raised. The next normal startup refreshes **existing** labels, primary lesson membership and copy from saved position/PV data; learned status, imports and playlist history are unchanged. Positions missing or requiring longer variations could previously be enriched using the retired **Improve learning motifs** control; no full game reimport was required.
- `tests/test_advantage_outcomes.py` adds regressions for added pressure, passed-pawn advancement and delayed material payoffs. Run after installing the project dependencies with `python -m unittest discover -s tests -v`.

## v19 — Opening playlists and classical-game connections

A new **Openings** section is available from the top navigation and the active game list. It parallels the lesson index/detail interfaces, with opening family names as the grouping key and PGN opening variations and ECO codes as secondary metadata. It includes opening-specific completion metrics, paginated positions, rating/mode/status/variation filters, bulk learned-status editing, save/reset, a move-sequence tree, and a **Train opening (N)** playlist. Opening playlists start in **move-number ascending** order and retain every position in the active session even after it is learned; new playlists omit learned positions. The Opening detail and trainer links preserve their scope. A saved opening playlist can be resumed on the Opening index.

The existing Lessons taxonomy remains based on **primary learning motif** and starts in difficulty order; the same training positions may appear in one motif lesson and one opening family, without duplicating their stored solved status.

Opening metadata is backfilled lazily from cached PGNs (preferring the PGN Opening/Variation/ECO tags, then recognizing a modest built-in move-prefix repertoire). Positions lacking classification receive *Unclassified Opening*. This first version of the local repertoire is **not** a complete ECO database and should not be presented as exhaustive. Older databases are migrated by adding nullable metadata columns and an index. No reimport or full Stockfish evaluation is needed.

A small curated, sourced set of quintessential historical games provides starting points: **Paul Morphy's Opera Game (1858)**, **Anderssen–Kieseritzky's Immortal Game (1851)**, and **Kasparov–Topalov (1999)**. An opening detail page offers linked historical examples for that family. A *training position* is called an **exact historical-position match** only when board placement and side to move coincide with a reference position at least six full moves into that game; sharing an opening name or the early move history alone is not treated as a match. In training, historical references are introduced by **adaptive coaching after solving** and recorded once per classic per game list, so the same reference does not repeatedly interrupt the task UI.

Historical game sources:
- Morphy's Opera Game: https://github.com/georgi/morphy
- Anderssen–Kieseritzky, Immortal Game: https://en.chessbase.com/post/kieseritzky-s-immortal-game
- Kasparov–Topalov, 1999: https://betterchess.co/games/kasparov-topalov-1999

Validation performed: Python compilation, JS syntax, Jinja2 template rendering, SQLite initial/migrated schema and sample grouped queries, and stubbed PGN-opening fallback tests. The development environment did not have Flask, python-chess, Stockfish, or a working headless browser binary, so live historical-position matching and the full trainer UI still require runtime verification in the project environment.

### Exporting or sharing a game from Training (v20)

Use **↗ Share** in the compact strip beneath the chessboard, beside the
Stockfish switch. It works before or after solving a position, and always
references the **original imported game**, not temporary engine-analysis moves.

- **Copy PGN** copies the original game's PGN to the clipboard.
- **Download PGN** saves that game as a `.pgn` file.
- **Copy Lichess link** / **Open on Lichess** are offered only when the
  original game's `Site` metadata contains a verifiable Lichess game URL.

The options adjust for each position. On older imports with no preserved PGN,
PGN export is disabled; on non-Lichess imports, the Lichess actions are disabled.
Existing analyzed games and learning progress need no migration or reanalysis.
The backend also checks the original analyzed-games cache if a training position
is missing its PGN or source metadata.


## v21 · Stable controls and one position per opening branch

- Globally display **Lessons**, not Lesson Plans.
- Keep Share and Stockfish centered in fixed-width board-footer slots before and after solving.
- Remove the text-based Opening move tree (future graphical explorer can be built separately).
- Opening training playlists group positions by FEN board, side, castling rights and en-passant state, excluding move counters; every matching imported game move appears in the post-solve **Your game moves** field, with its occurrence count. Non-opening lesson playlists are unchanged.
- The fixed playlist snapshot saves representative position IDs, so revisiting a solved puzzle never reinserts duplicates. Learning a grouped opening board retires every matching game record in that opening, including records with different played moves.
- Historic game connections are surfaced as adaptive-coach messages after solving (v26), rather than permanently expanding the task/explanation panel. Exact position matches are labeled as such; opening-only connections are explicitly distinguished.
- No PGN reimport or engine reanalysis is required. Original PGNs, sharing, learning history and underlying position records are preserved.

## v22 — Fast training playlists and solved review

- User-facing **Analysis status** references are shortened to **Analysis**.
- Solved cards restore the resulting board FEN, highlighted correct move, and green check when revisiting them using Last position or resuming a playlist. The exact accepted move is cached for the current playlist (including accepted near-optimal alternatives); older learned positions use their saved engine-best move to reconstruct a solved review board. Reset puzzle clears that saved solution.
- The trainer requests a lightweight playlist **manifest** (ordered IDs and learned states) instead of transferring the full set of position records before drawing the first board. The `/api/jobs/<id>/positions/manifest` route also restores an existing pinned playlist, preserving its order and learned cards. The full position cards are hydrated through the existing playlist endpoint **20 at a time**, cached without eviction, and the next chunk is fetched near the end of the current chunk. No solved positions are purged from the active playlist. Historical full-card endpoints remain supported.
- Board and core controls now render before asynchronous game history, explanation and coaching requests complete. The collapsible Analysis dashboard's first polling request runs after initial board and playlist loading, instead of competing with the initial render.

No PGN reimport, Stockfish reanalysis or data migration is necessary. Browser storage remains subject to normal browser quotas and the existing API's maximum playlist size. Full timing measurements should be made against the user's actual database.

## v23 — Per-game-list metadata refresh (replaces “Improve learning motifs”)

On the home **Game lists** index, or within **Lessons**, **Openings**, or
**Analysis** for a given list, choose **Refresh metadata**. The former
"Improve learning motifs" button is retired from the UI because it conflated
an optional engine-enrichment operation with a metadata rebuild. Its legacy
backend endpoint is retained for compatibility but is not part of the new UI.

Refresh processes existing training positions in short, cursor-based SQLite
batches. It uses only saved board FENs, the original PGN (from position records
or the analyzed-games cache), saved engine evaluations, and existing saved PVs.
It recalculates puzzle difficulty estimates, primary/secondary learning motifs,
coaching prompts and explanations, opening family/variation/ECO, opening history,
and exact-position historical-game matches. Lesson assignment is the primary
motif, so refreshed lesson/opening listings reflect the updated classifications
without duplicating the game list. Where PGNs are available, the previous-move
context is reconstructed only when the position and played move match the PGN
exactly. Missing PGNs do not prevent other fields being recalculated, and
existing opening labels are retained when no PGN is present.

**Refresh deliberately does not contact Lichess, download or add games, run
Stockfish, add new training positions, or change stored engine evaluations,
principal variations, positive/negative learning modes or category, learned
flags, attempts, or existing playlist IDs.** Thus it cannot produce new PVs or
recover missed training positions that an earlier engine analysis never saved.
Those require a separate evaluation task. It refuses to run while the original
analysis job is active. The frontend displays fixed-position progress rather
than inserting text into the lesson header; a progress failure reports a clear
error and completed batches remain committed. Refresh can be restarted safely.

A `metadata_refreshed_at` timestamp is added to each existing job through the
normal migration. The Game lists home index provides access to previous saved
lists and their independent Refresh actions. Source code checks and database
migration checks should be complemented by integration tests with Flask and
python-chess installed, especially for legacy records with incomplete PGNs.

## v24 — Unified Process queue and game-list actions

Home contains one **Game lists** index, without a second personal training-set
summary. Each list has **Training · Lessons · Openings · Refresh · Analyze**.
The navigation order is **Home · Training · Lessons · Openings · Process · Settings**.
The legacy `/analyzing/<job>` URL redirects to `/processes?job_id=<job>`.

**Process** displays the status, counts and controls for both engine analysis and
metadata refresh for every game list. The refresh action is now a server-owned
background worker with persisted cursor, counts and status in
`metadata_processes`, rather than a browser-dependent loop of POST requests.
Each process can be started, paused, resumed or stopped independently. Analysis
uses the original locally cached PGN batch; starting a *new* analysis forces
an engine rerun rather than a cache-only no-op. If the original batch is missing,
the action reports that it cannot rerun without an import instead of silently
downloading an unrelated or incomplete game sample. Analysis can be paused or
stopped at the next engine checkpoint, which is not necessarily instantaneous.

Metadata refresh never downloads games or runs Stockfish. It updates derived
motifs, explanations, openings and ratings only, retaining the original
positions, evaluations, attempts and learning progress. Refresh uses small
committed batches so that users can leave Process and continue training. On
restart, queued and interrupted jobs are recovered; paused/stopped tasks are
not resumed automatically. Concurrent analysis and metadata tasks are gated by
one shared execution lock. Different game lists may be queued; the same game
list must finish/pause its current task before beginning the other type.

SQLite is configured for WAL mode during initialization, with a busy timeout on
ordinary connections. The previously repeated `PRAGMA journal_mode=WAL` call
on every connection was removed because it can itself require a database lock.
The critical path commits cached records *before* running expensive Stockfish
screening, reducing prolonged SQLite writer locks. Training reads can operate
alongside writer transactions; a brief write delay is still possible.

**Runtime constraint:** this task scheduler is meant for the included desktop
Flask server started from `python app.py` with its single application process.
Do not run multiple independent WSGI worker processes against the same database
without replacing the local thread lock with a cross-process task coordinator.

Browser layout and action-panel checks were performed at widths 390, 860 and
1366 px using mocked task responses. Template parsing, Python/JS syntax, and
SQLite schema creation checks passed. Full Stockfish/Flask integration and
long-running concurrency/load tests still need to be run with the real game
library and installed dependencies.

## v25 — Home alignment, resilient Process controls, process-aware training HUD

- The saved Game lists card is aligned with the interior width of the Lichess
  username/connect section. Each row has **Train** (white primary action),
  **Lessons**, **Openings**, **Refresh**, and **Analyze**, with distinct icon gaps
  for the background-process actions.
- The global Process page always renders Start, Pause, and Stop controls, with
  non-applicable actions visibly disabled. Interrupted jobs can be restarted or
  resumed as appropriate. Errors from a *previous* worker are not presented as
  evidence that the database is currently locked.
- SQLite's standard `with sqlite3.connect(...)` context manager commits or
  rolls back but does not close its connection. The app's closing-connection
  subclass now commits/rolls back **and closes** each handler's connection on
  context exit, reducing accumulated concurrent readers and long-lived WAL
  snapshots. Engine workers that own their connection directly still close it
  explicitly. `/api/processes` performs short busy retries, and the metadata
  worker retries transient lock contention without immediately storing a
  permanent task failure. The task scheduler still serializes refresh/analysis
  within the single-process local server; other processes using the same SQLite
  file are outside this scheduler's control.
- The bottom-right **Process** HUD now shows the currently active evaluation or
  metadata refresh, even when training a different game list. Analysis metrics
  show evaluated/screened games, discovered positions, and the current pass;
  refresh metrics show positions checked, updates, and failures. The progress
  bar follows the active process. If no job is running/queued/paused, the HUD
  says **No active process** and links to the centralized Process page. Process
  controls remain on that page.
- Source validation includes Python and JavaScript syntax, Jinja template
  parsing, an actual SQLite context-manager transaction/closure test, and a
  Process-page DOM fixture testing available controls and action routing.
  Full Flask/Stockfish testing and long-running overlapping-transaction tests
  must still be performed with the local game database and installed packages.

## v26 — Process-aware home actions and historical coaching messages

- **Refresh** and **Analyze** on Home first inspect the global Process queue. If any
  analysis or metadata refresh is queued, retrieving, or running, either button
  navigates to the centralized Process page without launching a competing task.
  When the queue is idle, the chosen operation launches as before. A concurrent
  start (409) or temporarily busy status request also routes to Process.
- Historic game references are now delivered as **proactive Adaptive Coach**
  messages after solving, rather than taking permanent vertical space in Your
  Task. A per-game-list/classic SQLite record ensures each historical example is
  announced only once; the message itself is retained in its original position's
  coach conversation and retains the curated external source link.
- The historical coach distinguishes **exact board-position matches** from
  **related opening-family examples**. The link is styled with a muted warm-gold
  color rather than the browser's default bright link color. Training and
  problem-solving continue even if the optional historical message cannot be
  loaded. Historical introductions require Adaptive Coach to be enabled.
- Verification: Python compilation, JavaScript syntax checks, SQLite schema
  creation, dedicated one-time historic-coach endpoint fixture, safe historic
  link rendering and duplicate suppression, and Home process routing scenarios.
  Complete Flask/Stockfish integration still requires a local runtime.

## v27 — Unlearning respects playlist history; brighter historical coaching

- Unchecking **Position learned** now clears the remembered accepted move and
  solved-board state for the position, immediately returns it to the unsolved
  training board, and allows the user to solve it again. Visiting a different
  position and clicking **Last position** restores the unsolved state rather
  than resurrecting the green check from session storage.
- The learned flag is authoritative when restoring positions; any leftover
  solved-move snapshot for an unlearned position is discarded. For opening
  playlists, equivalent imported records whose learned flags are updated on
  the server have their in-session state synchronized as well. Solved positions
  still reopen with the accepted move and green check when genuinely learned.
- The playlist order and unlimited backward review are unchanged. Persistent
  saved-playlist metadata is updated along with status changes to prevent a
  stale in-memory snapshot from reintroducing an old solution.
- Historical-game Adaptive Coach spotlights now have a brighter warm-gold
  border, heading and link, with slightly stronger background contrast.
  The one-time historical-message behavior remains unchanged.
- Regression: `node tests/test_unlearn_navigation.cjs` exercises the unlearn
  handler and equivalent-position cache invalidation; existing JS fixture
  tests and syntax checks also pass. Full Flask/Stockfish testing still
  requires the app dependencies and a real game list.

## v28 — Rooted continuation comparisons and simpler chess explanations

- The continuation interpreter checks that stored lines begin from the training
  position with their intended first move. Normal Stockfish root-constrained
  output is unchanged; certain older reply-only records can be normalized when
  the first saved reply is legal *after* the played move. Invalid or unrelated
  lines are not used as evidence.
- Where two pieces can capture the **same pawn or piece**, the explanation now
  compares the resulting positions before claiming that the capture itself is
  the benefit. A verified difference in defending a second threatened pawn can
  take priority over incidental square control. This also feeds the primary
  learning-motif classifier.
- Explanations name the actual played move, use *hanging* for an attacked and
  undefended piece, remove the generic 'gain appears after the reply' phrase,
  and reserve *Eventually* for payoffs occurring later in the sampled PV.
- The analysis engine retains at most 12 PV plies (six full moves). Deep search
  starts with a **depth cap**, not a guaranteed achieved depth; time budgets can
  stop the search earlier. These short PVs do not justify calling every
  continuation forced or declaring a strategically won endgame.
- Added regression tests for legal root alignment, same-target captures with
  different defensive consequences, and move-specific narration.
- **Limitations:** A sampled best-reply PV does not by itself explain why an
  apparently hanging piece cannot be taken. That requires an additional
  counterfactual engine search (force the tempting capture and inspect its
  strongest refutation). The present release does *not* pretend to verify
  overworked-king or overloaded-defender claims in such cases.
- Existing evaluations, positions, PGNs and learning history remain unchanged.
  On startup, classifier/coaching version bumps refresh the derived learning
  motifs and prose. The Process > Refresh metadata action remains available.

## v29 — explicit startup and exchange-aware explanations

The application now starts with **no background workers**: interrupted queued/running
analysis and metadata refresh tasks are marked paused on startup and can be
resumed explicitly from Process. New analysis requests remain explicit actions.

Motif detection rejects a geometric double attack when the purported attacker
is immediately recaptured in the saved line. A normal exchange is not called a
sacrifice unless an actual material deficit and recovery are demonstrated.
Only the first two solver moves (up to four plies) may generate a new
continuation-based motif; longer-term moves can still inform prose when their
connection to the decision is supported. Metadata Refresh applies these
classification changes to existing positions without retrieving games.

## v32 — Natural-language explanation editing

- The solved-position explanation uses a **single central takeaway**, rather than concatenating independent tactical observations, evaluator outcomes, and classifier-ranking commentary. Motif selection remains internal: an incidental fork is not described as "secondary" in the learner-facing text.
- A verified forced mating result is stated **once**: when the saved engine score proves mate and a legal saved continuation ends with the finishing move, the explanation names both without repeating the outcome or citing "saved analysis depth". A sampled PV mate without a mate score is described only as what happens *in the analyzed line*, not as a proven forced sequence.
- The player’s actual move is named only when it adds a distinct comparison; a second generic sentence such as "missed this idea" is not appended to every explanation. Explanations retain concrete counterfactuals (including pinned illegal captures) when they answer a different, useful question.
- The comparison editor shortens analysis provenance and tail-end boilerplate, connects delayed captures to the initiating move, and expresses *two ways of capturing the same pawn* as the real difference in what remains defended.
- An isolated pure-language module `narrative_editor.py` can be regression tested without a chess engine. `tests/test_narrative_editor_v32.py` covers repetitions, proven/unproven mate distinctions, and concrete move comparisons. Chess-specific tests and Flask/Stockfish integration still require installing the dependencies in `requirements.txt`.
- `COACHING_VERSION` is incremented so cached explanations can be regenerated from existing game data and PVs without downloading games or changing learned status. The user's **Refresh metadata** action also rebuilds them.

## October 15, 2026 — v33 discovered lines and legal counterfactuals

- A new board-grounded line detector identifies a **discovered check** or **discovered attack** when the recommended move vacates a square and exposes a previously blocked rook, bishop, or queen attack on an occupied enemy target. This includes some diagonal pawn-promotion captures; direct attacks by the promoted piece are not misidentified as discoveries.
- Context, threat assessment, response evidence and lesson-motif ranking distinguish discoveries that the best move creates from discoveries **also created by the move actually played**. Only the differential evidence helps explain why the recommendation is better. Mere incidental discovered geometry is supporting evidence, not automatically the primary lesson.
- Check-related counterfactuals test apparent captures of the moved piece that are pseudo-legal but **illegal because they leave the discovered check unresolved**. For *legal* opponent captures, the model may identify a verified immediate capture of a newly exposed valuable target by the revealed slider. It does **not** claim that such a capture is forced or winning without evaluated proof.
- Explanations now mention a discovered check/attack in plain language and answer the practical question of why an apparently hanging bishop, pawn promotion, or other moved piece can or cannot be captured. The model keeps these counterfactual claims separate from actual Stockfish principal variations.
- Added chess-board regression fixtures for discovered checks, a blocked knight capture, quieter revealed queen attacks, shared discoveries (not a distinguishing factor), and promotions. Run `python -m unittest discover -s tests -p 'test_discovered_counterfactuals_v33.py' -v` with `python-chess` installed.
- Existing PGNs, evaluations, positions and learned statuses are unchanged. Use **Refresh metadata** to apply the upgraded motif/classifier and coaching rules retroactively; no game reimport is needed.

## v34 — Unified Adaptive Coach

Adaptive Coach uses a shared reasoning pathway with the saved puzzle explanation:

- **General understanding:** Ask *"Why is the move better?"* or *"Explain the position"*. After solving, the coach recalls the contextual explanation; before solving, it gives only the spoiler-safe task prompt.
- **Concrete moves/lines:** Ask *"What if Nf3?"*, *"Why not ...?"*, or provide an entire SAN sequence. The coach validates legality, evaluates the move or resulting line with the configured Stockfish review engine, and compares the move with the preferred branch using the same `generate_coaching_text` model used by training explanations. Responses can be rated as helpful/unhelpful. Clear move specifications take precedence over incidental mentions of motifs.
- **Learning motifs:** Ask *"Show me a double attack"* or *"Can I use a pin?"*. After solving, the coach requests up to six Stockfish principal variations, runs motif detectors on those lines, and considers only sufficiently supported and reasonably strong candidate moves. It reports uncertainty rather than inventing a matching tactic. Before solving, it provides only a concept-oriented prompt.
- **Proactive suggestions:** Classic-game recommendations continue to appear after solving. The coach may also recommend up to three distinct creative/brilliant-labeled moves from the user's other games in the same saved game list, preferring the same primary motif and checking that the move was actually played and near optimal. Suggestions are retained in the conversation and can be opened from the message. The app does not assert a literal `!!` PGN annotation merely from a heuristic brilliant label.

The SQLite schema introduces `coach_proactive_spotlights` for deduplication. Existing positions, saved chats, lesson assignments, analysis data, and learned progress are preserved. Nothing is sent to Stockfish automatically when entering a playlist; move/motif probes run only on user request. The post-solve proactive suggestions query stored metadata without running new evaluations.

**Verification:** Run `node tests/test_historic_coach.cjs` and `python -m pytest tests/test_adaptive_coach_v34.py` once `pip install -r requirements.txt` has installed `python-chess` and Flask. The current packaging environment lacks these runtime dependencies; source, SQL, and JavaScript checks alone do not validate full Stockfish behavior.

## v35 — Check-evasion explanations and expanded discovered checks

- The explanation engine now evaluates a legal **check response before generic attacks and continuation features**. A move that interposes a piece is described as blocking the checking line, rather than as newly applying pressure. Capturing the checking piece or moving the king receives its corresponding direct explanation.
- If the checking rook/bishop/queen can legally capture the interposed piece **and** the defender has a legal recapture, the explanation can describe a *possible* exchange. Only equal-value exchanges receive the Simplify motif on this evidence; an offered piece is not automatically a sacrifice or a winning trade. A check-blocking move without the verified trade is treated as a Defensive Resource.
- The discovered-check detector now examines **every square cleared by the move**, not only its origin. This also handles en-passant removal of an intervening pawn and castling squares, provided a stationary rook, bishop or queen has genuinely acquired a new line to the king or another valuable target. An ordinary direct check is not called discovered.
- Root check defense also contributes to learning-motif relevance. When an interposition simultaneously reveals a genuine countercheck, both facts can be explained concisely; discovered checks are still distinct from an attack by the moved piece itself.
- Existing game lists and evaluations are unchanged. Use **Refresh metadata** to regenerate cached explanations and primary-motif lesson membership. No full evaluator rerun is required for these rules.
- `tests/test_check_evasions_and_discoveries_v35.py` adds concrete chess-board regression cases for check interpositions, verified exchange offers, ordinary discovered checks, en-passant discovered checks, and direct-check false positives. Run with `python-chess` installed. Source compilation and JS tests are useful but do not substitute for executing these board tests or a live Flask/Stockfish session.

### v36 — Immediate-position relevance before longer continuations

The shared `immediate_decision.py` evidence check now gives priority to a
legally verifiable one-move explanation when it distinguishes the recommended
move from the actual game move. It detects immediate captures that cannot be
legally recaptured, missed defenses of newly threatened pieces, and game moves
that leave a valuable piece hanging. Captures of the *same* target by both moves
are intentionally passed to the existing branch-differential explanation,
which can describe what one capture leaves defended. Immediate checkmate,
verified mate defense, check evasions, and established discovered tactical
refutations remain distinct higher-priority explanatory cases. PV-based
positional outcomes are retained for positions with no adequate immediate
explanation. Classifier and coaching versions are incremented to regenerate
existing metadata through the Process page's **Refresh** action. Existing
PGNs, puzzle IDs, evaluations, and learning history remain untouched.

New `tests/test_immediate_decision_v36.py` requires `python-chess` and includes
cases for a hanging queen, a newly exposed rook, a legally recapturable pawn,
and two ways to capture the same pawn.

## Decision-aware explanations (v37)

Deep evaluation now retains up to **three ranked Stockfish root variations**
(the best line plus up to two evaluated alternatives). Those alternatives are
saved in `training_positions.alternative_pvs_json`; existing installations gain
the column through the ordinary database migration. This is new engine evidence:
**Refresh metadata** can reuse any lines already saved but cannot generate new
alternatives. Use an explicit reanalysis for older games that need MultiPV data.
Existing game records, puzzles, ratings, learned status, and attempts remain
intact.

The explanation model now distinguishes the **quality of the played move** from
the consequence of the best move. For a mistake or blunder it first looks for a
concrete tactical cost in the *played* continuation (a near-root fork,
checkmating reply, or demonstrable material loss compared at the same ply
horizon). For an excellent/brilliant move played in the game it checks whether
another ranked, materially worse candidate falls into a verifiable tactic.
The comparator declines to manufacture a refutation when the available engine
lines are too short or roughly equal. Check evasion and obvious immediate
captures remain context, but a documented tactical reason can take precedence
over a generic statement such as “the king escapes check.”

Only near-term consequences are promoted as the explanation of the current
decision. A principal variation is a **sampled line** and is never described as
forced without an appropriate mate result. Counterfactual analysis is still
bounded by the stored Stockfish PV; arbitrary, unexplored alternatives are not
claimed to be losing. Engine-dependent regression positions are provided in
`tests/test_decision_contrast_v37.py`.

## v39 — Progressive lesson/opening loading

Large game lists now render the first filtered, sorted page (normally 16
positions) without waiting for full-list totals. The lesson/opening detail
client starts two independent queries in parallel: `phase=page` hydrates just
16 cards plus one look-ahead row, and `phase=summary` computes the exact
filtered totals, lesson completion and trainable count. The totals are cached
per filter combination while paging; saved learning status and metadata
refresh invalidate the cache. Other pages remain on demand. `include_selection`
continues to select all matching positions, not only the current page.

The Lessons and Openings tile views show the last browser-session snapshot
immediately on return navigation and then revalidate using the current
SQLite data. The Opening overview aggregates unique board positions within
SQLite instead of transferring every FEN to Python. The opening detail's
unique trainable count is also computed directly in SQLite. Added query
indexes for rating, learning mode, opening, and primary learning motif.

Read-only lesson and position listing requests no longer perform a costly
account-wide learned-status repair pass; learning-status write endpoints
already propagate the changes. Existing database and playlist formats are
unchanged. New indexes are created on startup, which may take additional
time once on a large database.

Validation: `python -m unittest tests.test_progressive_pages_v39` verifies
paged sorting, full-list counts, and opening deduplication. Full live load-time
testing against the user's large local database remains necessary.

## v40 — Grounded-first explanation outcomes

The coach now ranks an **observable result at the training position** ahead of
unrelated positional observations from later Stockfish continuations. It
recognizes a recommended capture and checks whether legal recaptures exist,
identifies ordinary equal-value exchanges, and does not call shared captures
an advantage that distinguishes two candidate moves. Strong tactical evidence
such as checkmate, check evasion, and a demonstrated fork still overrides a
merely descriptive first-move fact where appropriate.

For quieter moves, the new board-aware fallback seeks newly defended attacked
pieces, concrete attacked enemy pieces, pawn-created space and controlled
squares, passed pawns, blocked attacks, king activity in simplified endings,
castling, and rooks entering open files. It avoids tautological statements such
as “e6 places your pawn on e6.” When no supported benefit can be inferred from
the saved lines, it explicitly avoids inventing a tactical advantage.

The coaching version has been bumped for metadata refresh. Existing evaluations,
positions, lesson history, and learned status are retained. Test cases are in
`tests/test_root_explanation_v40.py` (requires python-chess); JS tests and Python
source compilation do not require a local Stockfish binary.


## v41 — Dual chessboard input restored

- Mouse/trackpad and touch users can **drag a piece to a destination square** or **click/tap a piece and then click/tap its destination**. Both routes use the same legal-move validation and promotion selection as before.
- Replaced fragile HTML5 drag events on Font Awesome `<i>` elements with pointer gestures (6px mouse / 10px touch threshold), a lightweight moving-piece preview, and release-point hit testing. The gesture leaves normal click events intact.
- Cancels pending gestures when a position or board frame changes, and avoids forcibly focusing the board at pointerdown on a piece. Incorrect drops are ignored.
- Added an isolated Chromium browser test in `tests/test_dual_board_input_v41.py` covering mouse drag, click-to-move, touch drag, and invalid drop recovery. It requires Playwright and a local Chromium binary. The full Flask/Stockfish integration has not been run in this build environment.

### v43 — Context-aware explanation evidence and reply probing

Deep analysis now stores `explanatory_lines_json` for **up to three distinct
explanatory continuations** (recommended, played, and a tested opponent reply
or independently ranked alternative). Each line includes root-aligned legal
moves, SAN, ply distance, the solver/opponent perspective, score provenance,
and observed effects such as captures, checks/checkmate, pins, discovered lines,
forks supported by the PV, exposure of loose pieces, pawn promotion, passed
pawns, trapped pieces, and defensive threat neutralization. The record also
stores a board-context snapshot and the root evaluation comparison. Observed
features are **not** automatically considered a forced tactical win.

A configurable extra Stockfish probe runs **only after deep confirmation** of
a candidate. Settings → Passes → **Test explanatory replies** controls this;
**Reply-probe time budget** defaults to 18% of the candidate's deep-search
budget *in addition* to the original confirmation work. The probe compares
two opponent replies after the played move; it stores a distinct response when
available. No extra engine work occurs on lesson tiles, opening tiles or
Refresh metadata. Probe failure preserves the original deep evaluation.

The versioned `critical_events_json` now considers nonmaterial realizations
in the opponent's demonstrated response and checks whether a second saved
engine reply supports the same event. An immediate verified material loss
remains preferable to a remote geometric pattern; sampled checks, forks, pins,
discoveries and king-danger outcomes can be the central explanation when
material doesn't suffice. Positive-move lessons can use a saved scored
alternative for the same comparison. Both critical evidence and lesson labels
are regenerated by Refresh metadata using the stored evaluations and PVs.
Previously saved reply probes remain available through refresh; older positions
need deep analysis to gain a new reply probe.

### v45 — retrieval → analysis → training-ready lifecycle

**Creating a new game list** now starts a separate Retrieval process first. It
streams Lichess PGN to an unpublished `.part` file, tracks bytes downloaded in
`retrieval_processes`, and atomically saves the completed batch. Retrieval
then queues and automatically starts the existing checkpointed Stockfish
Analysis process. Existing saved game lists are **never re-downloaded**.

On Home, a list reports *Retrieving games* then *Analyzing games*. Train,
Lessons, and Openings are unavailable until the database contains its first
training position; they unlock immediately when a position is committed, even
if deeper analysis is still running. The Train action becomes white again.
The Home view polls current process state without a page reload; direct routes
also redirect to Process when there are no training positions. A completed
analysis with no positions remains untrainable with a specific message.

Process shows independent Retrieval, Analysis, and Metadata refresh cards.
Retrieval exposes downloaded bytes (and percentage when Lichess supplies a
Content-Length). A failed or stopped new retrieval can be explicitly retried
on Process; it will not publish or analyze a partial PGN. The retrieval worker
checks persisted cancellation state between streamed chunks. Existing lists
show "Saved" retrieval and retain their usual analysis/refresh controls.

On application restart, interrupted new retrievals are marked paused and may
be retried explicitly from Process. Analysis does not start automatically on
application boot; only successful new-list retrieval triggers the handoff.
All changes are additive migrations; no new Python dependencies are required.
