# v83 · Continuation-owned coaching messages and feedback

After solving, the Adaptive Coach presents **one independently rateable card for each distinct attempted move** (including earlier sessions and the original game's move where there is verified saved line evidence), followed by a separately rateable **solving continuation**. Failed and original-game moves use light-blue cards; the solving continuation retains the gold card. Every message bubble occupies a consistent proportion of the responsive chat width, including one-sentence replies. Repeated attempts of the same UCI move are deduplicated within the rendered recap because their tactical root is identical.

`continuation_coach.explain_attempt()` owns chess statements for exactly one move root and only appends the opponent's reply observed on that root's saved or verified principal variation. If the saved proactive paragraph compares multiple alternatives, the composer extracts the root-specific lead where possible, rather than attaching the other variation's narration. No new Stockfish search is introduced at solve time. Earlier stored recap records are upgraded to `explanation_version=5` in place; the existing coach message ID remains stable.

**Feedback identities:** legacy `position_feedback` records in category `explanation` are the **solving continuation**. Earlier move cards use `continuation_explanation_feedback` keyed by `(position_id, root_uci)`. Each card has independent thumbs and optional correction text; replacing or withdrawing one does not change another. Reporting and CSV exports add `continuation_key` (`solving` for historical and current solution feedback; root UCI for other continuation feedback). Coach filters for solving/attempted lines and offers a per-message approval chart grouping solving, attempted, and other chat coaching. Ratings do not rewrite generated explanations or player learning results.

The notes under older version headings below are **historical implementation changes** and are superseded wherever they describe a single combined explanation or one shared thumbs vote.

---

## v80: Deduplicated continuation commentary

The solved-position explanation now has a **single authoritative lead** for the best move: its saved causal explanation. The individual move's root observation is appended only if it adds a different chess fact. The same rule prevents duplicate opponent-response and follow-up facts while retaining new reply evidence. This fixes cases such as “Rf1+ gives check, requiring an immediate reply. Rf1+ gives check” without losing the explanation of Kg2. Root-aligned variation interpretation and the single position-level feedback rating remain unchanged. The stored recap narrative version increases from 2 to 3, so opening a solved position automatically rewrites older v79 recap text in place with no Stockfish search, message-ID change, or feedback deletion.

# v77: post-solve coaching without additional move latency

## Responsibilities

* **Positions / Stockfish** continues to discover and deeply evaluate training
  positions. These root evaluations are not replaced or rewritten by Trainer.
* **Coaching Analysis** continues to interpret and store the reusable explanation,
  primary motif, taxonomy, PVs, and proactive evidence.
* **Trainer** accepts and verifies moves as before. The actual game move can
  reuse its already-saved Stockfish score rather than launching a duplicate
  review-engine search. Previously unseen alternatives still need the existing
  move-quality verifier; no additional, separate coaching search occurs while
  the board is waiting on an attempt.
* **Adaptive Coach** owns the solved-position explanation. It appears as the
  first message-style card in the chat and retains the existing explanation
  thumbs/correction workflow and Coach analytics category. The nearby
  `Your Task` panel shows status and, after solving, the opening.

## Learning from actual attempted moves

Every *server-verified legal board attempt* made while the Coach is enabled
writes a lightweight row to `coach_board_attempts` with a solve-session key,
move, correctness, cached-line status, and already-available engine outcome.
This is **separate from Player's opt-in learning statistics**: turning Learning
stats off prevents Player activity records, but Coach still retains local
attempt evidence to generate a personalized explanation after solving.
Unsolved moves never produce unsolicited coaching spoilers. On a correct move,
Trainer **fire-and-forgets** `/api/positions/{id}/coach/solve-recap` and makes the
board immediately usable. The endpoint validates learned state and a verified
correct attempt, assembles a concise recap using saved evidence, and adds one
persistent assistant message per puzzle/solve session. Calling it twice is
idempotent. Messages do not also receive a chat-feedback control; the main
model explanation keeps its distinct explanation rating.

Old solved positions immediately display their stored model explanation when
revisited. Earlier post-solve recaps are not returned by the Coach-history API
if a position is reset to unsolved. The database automatically creates both
new tables at startup and preserves old positions and ratings.

## Explicit performance boundary and next phase

The new recap route makes **no new Stockfish calls**. It uses cached PVs and
scores plus the output of pre-existing alternative-move verification. It does
not claim to calculate an uncached opponent variation beyond the evidence that
was saved. A later version can add a bounded, queued post-solve probe for
uncached attempts, with concurrency limits, cancellation/position guards,
explicit timestamps and model-versioned evidence. It must never compete with
interactive board verification for the engine lock.

Measure UI response time separately from Coach recap latency. The user should
never need to wait for a recap before choosing Next Position or entering
analysis mode.


## v78 · Single-continuation coaching and one explanation package

- The Adaptive Coach's message history now sits **above** the input field.
- Once solved, its one **Position explanation** block contains one small, labeled comment for **every attempted legal move**, followed by a solution comment. This is one feedback item (one existing Explanation thumbs rating), **not** a series of independent chat ratings.
- An attempted move is explained with its **own** server-verified reply and, if available, the legally replayed root-aligned `explanatory_lines_json` board observation. The solution's stored `coach_explanation` is used only for the original best move; alternative successful moves are identified as acceptable without borrowing an unrelated tactical claim.
- The existing `coach_board_attempts` and `coach_solve_recaps` tables are reused; `attempt_comments` is a new key within the existing `coach_messages.structured_json` payload, with no schema migration. Previously saved v77 recaps fall back to their recorded attempts when reopened.
- The explanation-feedback `content_snapshot` now captures the **full displayed package**, not just the solution paragraph. The position retains one Explanation vote, and the Coach report/export pipeline is unchanged.
- No additional Stockfish call occurs in the post-solve recap; legal move verification continues through the preexisting training endpoint. No comments are shown before solving. No generic explanation should be attributed to the wrong candidate continuation.
- A position solved before attempt logging existed shows its cached solution explanation only; previous attempts cannot be recreated retrospectively.


## v79 · Restore nuanced, single-continuation explanations

The v78 move comments became too mechanical: passing or missing a puzzle's
solution threshold is a *grading result*, not a chess explanation. This version
removes that language from new comments and uses `continuation_coach.py` to
interpret **one root move at a time**, using its own evidence rather than
borrowing the solution's tactical observations.

- For **cached attempts**, use only the saved `explanatory_lines_json` branches
  whose first move exactly matches the attempt. Describe observed attacks,
  captures, discoveries, checks, threats, defenses, opponent responses, and
  demonstrable subsequent payoffs in that particular sequence.
- For **uncached attempts**, keep the legal principal variation returned by the
  *existing* Stockfish move-quality check in the new nullable
  `coach_board_attempts.verified_pv_json`. On solving, replay that line legally
  and derive the same kind of chess events without another engine search.
- For the **correct move**, reuse the already-written higher-level coaching
  explanation where it addresses that move and doesn't cross into a distinct
  root continuation; supplement with any directly evidenced opponent response.
- If the evidence doesn't show a forced tactical outcome, report only the
  supported positional effect or observed reply. A sampled principal variation
  is not a proof of force, and an attack is not automatically material won.
- Preserve the one-block / one-thumbs feedback UI and existing feedback and
  learning tables. Existing solved v77/v78 recaps are recomposed **in place**
  when their position's Coach history is next loaded, without deleting votes.
- Schema migration adds only the nullable verified-PV field and does not require
  a metadata refresh or game reanalysis.

The post-solve comments are still bounded by the depth of saved/verified lines;
where a precise reason depends on an unsaved defense, the coach must not
invent it. The interactive board path incurs **no additional analysis**.

## v81 · Single ownership of chess narration

The saved proactive explanation **owns** the best move's root-move lesson.
The reactive continuation composer is the **sole source** of all additional
post-solve opponent-reply and near-term solver-follow-up commentary, based on
the matching saved/verified branch. The recap module only persists assembled
comments; it no longer selects or narrates competing saved variations.
Synonymous board observations are not appended to the saved root explanation.
A reply with no observed explanatory consequence is omitted rather than
stated as a naked PV move. Existing recaps are rewritten in place with
`explanation_version=4` when revisited, retaining feedback and message IDs.
No extra Stockfish calls are added. See `NARRATIVE_ARCHITECTURE.md` for the
ownership audit, consolidation scope, and remaining roadmap.
