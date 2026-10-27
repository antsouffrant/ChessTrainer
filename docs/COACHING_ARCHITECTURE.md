# Coaching architecture — canonical v94 layout

The coaching model is **`rules-v34-version-scoped-cache`**, unchanged by v94. This release removes the 34 root-level module aliases introduced by v93. All application code and tests use canonical modules under `coaching`.

| Stage | Package | Public interface | Internal implementation examples |
|---|---|---|---|
| Board context | `coaching.board_context` | `observe(...)` | `pv_reasoning`, `check_response`, `explanatory_evidence`, `proactive_coaching` |
| Conceptual understanding | `coaching.conceptual_understanding` | `compare(...)` | `decision_context`, `critical_moments`, `semantic_coaching` |
| Motif selection | `coaching.motif_selection` | `classify(...)`, `canonical_key(...)` | `coaching_taxonomy`, `causal_selection`, `motif_relevance` |
| Narrative composition | `coaching.narrative_composition` | `explain_position(...)`, `explain_continuation(...)` | `coaching`, `continuation_coach`, `coach_session_recap`, `adaptive_coach` |
| Coaching validation | `coaching.coaching_validation` | `validate_evidence(...)`, `validate_message_identity(...)` | Pure validation utilities; not yet a live generation gate |
| Coaching refresh | `coaching.coaching_refresh` | `rebuild_position(...)`, `refresh_batch(...)`, `clear_cache(...)` | `coaching_copy_refresh`, `coaching_cache`, `metadata_refresh` |

These six stage packages organize the **coaching pipeline**, not the entire chess application. `analysis.py`, `db.py`, `engine_service.py`, `evaluation_runs.py`, `feedback_history.py`, `coach_benchmark.py`, and Flask routes in `app.py` are intentionally outside the six stages because they provide shared capabilities.

## Import conventions

- Always import stage APIs from `coaching.<stage>` where possible.
- Import a specialist implementation using its canonical fully-qualified name when testing or extending individual detectors (for example `coaching.board_context.pv_reasoning`).
- The old `import pv_reasoning` and `from coaching import ...` forms no longer work: aliases were deleted.
- Monkeypatch the canonical name: `patch('coaching.narrative_composition.coaching.generate_coaching_text')`.
- Avoid cyclic imports across stages. Use lazy boundary imports for shared interactions only when necessary.

## Flow and cache ownership

Game data and saved engine evidence → Board context → Conceptual understanding → Motif selection → Narrative composition → Coaching validation → Coaching refresh / versioned cache. This is a **responsibility map** rather than a guarantee that every legacy code path is already composed into one function call.

The current feedback ledger, historical snapshots, frozen benchmark cohort, and independent evaluation-run progress remain separately owned. An explanation cache hit must match coaching version and evidence fingerprint; a refactor must not bypass that rule.

## Regression contracts

`tests/test_coaching_boundaries_v94.py` enforces canonical-only imports, the six-stage public interfaces, and preservation of the current coaching version. All other migrated test files are mapped in [`TEST_MAP_V94.md`](TEST_MAP_V94.md).

## Deliberate limits

This release is **maintenance only**, not a new explanation model. Full behavior-level refactoring (consolidating duplicated reasoning or adding a live validator) belongs to a future separately versioned release. Some stage internals remain large; do not collapse them into six giant source files merely to reduce the file count.
