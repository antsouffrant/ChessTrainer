# Coaching narrative architecture — v81 ownership audit

## Root cause and scope

The v79/v80 post-solve composer duplicated descriptions because the proactive
`coaching.py` saved a fully worded best-move explanation, while
`explanatory_evidence.board_events` independently emitted a *second* immediate
move event. `continuation_coach.explain_attempt` concatenated both and attempted
to deduplicate English phrases. Synonyms defeat this approach:

> Kh1 moves the king out of check. Kh1 legally answers the check.

The same code appended every principal-variation response even where no
chess consequence was established:

> After Kh1, your opponent can respond with Kh8.

These are two **different generators of prose**, not necessarily two Stockfish
calls. Deleting a repeated string or inventing a reply rationale would obscure
the underlying problem.

## One evidence source, one narrative composer

```
Positions / Stockfish root evaluations + Coaching Stockfish probes
                 |
                 v
    Persisted legally replayed continuation evidence
    (explanatory_lines_json, verified_pv_json)
                 |
      +----------+----------------------+
      |                                 |
      v                                 v
Proactive coaching                Attempt verification
 - root decision context           - attempted UCI/SAN
 - motif and purpose               - saved or verified PV
 - one saved best-move lead        - correctness/eval
      |                                 |
      +----------------+----------------+
                       |
                       v
            continuation_coach.py
           SINGLE commentary composer
     one root lead  +  novel reply consequence
                    +  novel solver follow-up
                       |
                       v
            coach_session_recap.py
           persistence and lifecycle ONLY
                       |
                       v
          ONE post-solve explanation package
             ONE explanation thumbs record
```

**Responsibility contract**

1. `analysis.py` and `proactive_coaching.py` ask Stockfish questions, save
   position evidence, and never generate an extra post-solve chat paragraph.
   Position selection and deep root scores remain independent of the Coach.
2. `explanatory_evidence.py` is the canonical source of *typed move events*
   (`kind`, `text`, `ply`, mover, SAN); it does not decide what to say twice.
3. `coaching.py` may save **one best-move coaching lead** for the canonical root.
   When selected, this complete lead *owns the root observation*. Another
   observation of the root move is never appended, even if it uses different
   vocabulary (check evasion versus king safety, for example).
4. `continuation_coach.py` chooses only an **exact-root-matching** stored branch
   and constructs one comment per user attempt. An incorrect attempt cannot
   inherit a best-move claim. Reply/follow-up annotations are appended only
   when they add an actually recorded tactical/positional consequence and
   their SAN is not already discussed in the proactive lead. A bare legal PV
   move is not an explanation and is omitted. An opponent's move must remain
   from the *learner's* perspective in the resulting text. When no proven
   specific fact exists, the Coach reports that limitation rather than invent
   a win or a forced refutation.
5. `coach_session_recap.py` owns **only** the attempted-move log, post-solve
   message lifecycle, compatibility view, and idempotence. Its previously
   separate root-PV selection logic now delegates to the shared branch selector
   in `continuation_coach.py`; its recap text comes from that one composer.
6. `coach_learning.py`/`adaptive_coach.py` still handle **explicit user chat
   queries**. They should not independently append unsolicited summary prose
   to the post-solve explanation block. They may invoke the established
   analysis/coaching engine to answer a specific new question.

## Evidence selection and prose budget

- Root: exactly **one** main claim. For the recommended move, prefer its
  existing proactive explanation. For other attempts, use the rooted event;
  when none exists, reuse `check_response` / `board_events` /
  `root_move_impact`, not a new heuristic library.
- Opponent reply: only where the line has a concrete effect (capture, check,
  discovery, changed vulnerability, etc.). A PV reply without such an effect
  is not narrated merely for being available.
- Solver continuation: retain demonstrable near-term tactical payoff if it
  is not already explained. A sampled variation is **not** proof of force.
- Current v81 composer is deliberately engine-free: it reads existing
  evidence only, preserving the Training board's interactive latency.

## Consolidation in this release

- Removed the phrase-based root-fact redundancy rules. They failed on
  synonymous concepts and conflated prose quality with chess semantics.
- Replaced a second independent board-fact detector in
  `continuation_coach` with calls to the existing board-events,
  `check_response`, and `root_move_impact` utilities.
- Replaced `coach_session_recap`'s duplicate saved-variation selector with
  a compatibility view of the canonical branch selector.
- Removed bare-PV-reply narration (the `Kh8` issue).
- Ranked informative captures ahead of incidental checks in the opponent
  reply, and kept references to the learner's pieces from the learner's view.
- Bumped the stored recap-narrative version to **4**, upgrading previous
  explanation messages on next solved-position open without changing IDs or
  deleting feedback. This is a narration-only update, not a data migration.

## Where modules still overlap and what not to collapse indiscriminately

There are ~47 top-level Python files. Several older utilities (`coach_reasoner`,
`semantic_coaching`, `root_explanation`, `decision_context`, `coaching_language`,
`continuation_refutations`) contribute complementary *evidence detection*,
ranking, or wording, and a mass deletion would risk losing chess-specific
behaviors that earned positive feedback. They should be evaluated as a later,
separately benchmarked refactor with dependency and usage tests. The immediate
problem was **overlapping prose composition and branch selection**, which has
now been given a single owner.

Next architectural candidate (not implemented here): persist a structured
`causal_finding` per candidate (move UCI, observed mechanism, realized outcome,
shortest supporting reply, confidence) rather than requiring the reactive
renderer to interpret legacy freeform proactive prose. The proactive engine
could then share the *same* typed finding with spontaneous coaching and
on-demand chat, without re-running Stockfish. This requires testing on the
positive as well as negative full-history coaching benchmark; a reader should
not be told a more complex story when a simple capture correctly explains the
position.

## Regression cases

`tests/test_narrative_ownership_v81.py` checks the reported check-evasion
synonyms, inert reply omission, Rf1+/Kg2 with a real consequence, material
capture prioritization, protection of solved-move explanations, attempted
branch isolation, and honest evidence gaps. The existing recap tests also
verify lazy upgrades without changing assistant-message identity. Full
board/Stockfish integration requires python-chess and the user's local engine.
