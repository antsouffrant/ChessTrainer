# V94 test-to-module map

Tests targeting coaching internals import the canonical `coaching.<stage>` implementations; no root-level coaching alias is required. Many integration tests legitimately exercise several stages. Tests below are grouped by code references and may appear in multiple sections. Other Python tests exercise the app, database, training, benchmarks, and processing.

## Board context (17 test files)

- `test_advantage_outcomes.py`
- `test_board_motif_refinements_v70.py`
- `test_causal_context.py`
- `test_check_evasions_and_discoveries_v35.py`
- `test_coaching_v53.py`
- `test_context_prompt_response_v30.py`
- `test_decision_context_v47.py`
- `test_discovered_counterfactuals_v33.py`
- `test_exchange_and_startup_v29.py`
- `test_explanation_contrast_v28.py`
- `test_explanatory_evidence_v43.py`
- `test_legal_counterfactuals_v31.py`
- `test_loose_piece_provenance_v54.py`
- `test_proactive_coaching_v65.py`
- `test_process_performance_v71.py`
- `test_pv_motifs.py`
- `test_versioned_coaching_cache_v90.py`

## Conceptual understanding (16 test files)

- `test_causal_comprehension_v60.py`
- `test_causal_consequences_v64.py`
- `test_chess_idea_coaching_v50.py`
- `test_coach_v51.py`
- `test_coaching_v53.py`
- `test_critical_moments_v42.py`
- `test_decision_context_v47.py`
- `test_decision_contrast_v37.py`
- `test_explanatory_evidence_v43.py`
- `test_immediate_decision_v36.py`
- `test_loose_piece_provenance_v54.py`
- `test_refutation_scan_v58.py`
- `test_root_explanation_v40.py`
- `test_semantic_coaching_v49.py`
- `test_v84_feedback_calibration.py`
- `test_versioned_coaching_cache_v90.py`

## Motif selection (10 test files)

- `test_causal_comprehension_v60.py`
- `test_coaching_taxonomy_v66.py`
- `test_coaching_taxonomy_v67.py`
- `test_discovered_relevance_v33.py`
- `test_feedback_hierarchy_v58.py`
- `test_motif_relevance_v31.py`
- `test_proactive_coaching_v65.py`
- `test_trainer_motif_refinements_v70.py`
- `test_v84_feedback_calibration.py`
- `test_versioned_coaching_cache_v90.py`

## Narrative composition (28 test files)

- `test_adaptive_coach_v34.py`
- `test_advantage_outcomes.py`
- `test_causal_context.py`
- `test_check_evasions_and_discoveries_v35.py`
- `test_chess_idea_coaching_v50.py`
- `test_coach_attempt_comments_v78.py`
- `test_coach_session_recap_v77.py`
- `test_coaching_boundaries_v94.py`
- `test_coaching_v53.py`
- `test_context_prompt_response_v30.py`
- `test_continuation_dedup_v80.py`
- `test_continuation_feedback_v83.py`
- `test_critical_moments_v42.py`
- `test_decision_context_v47.py`
- `test_decision_contrast_v37.py`
- `test_discovered_counterfactuals_v33.py`
- `test_explanation_contrast_v28.py`
- `test_feedback_hierarchy_v58.py`
- `test_immediate_decision_v36.py`
- `test_narrative_editor_v32.py`
- `test_narrative_ownership_v81.py`
- `test_pv_motifs.py`
- `test_root_explanation_v40.py`
- `test_semantic_coaching_v49.py`
- `test_single_continuation_coach_v79.py`
- `test_v87_coach_order_and_recap.py`
- `test_v88_benchmark_and_perpetual.py`
- `test_versioned_coaching_cache_v90.py`

## Coaching validation (1 test files)

- `test_coaching_boundaries_v94.py`

## Coaching refresh (6 test files)

- `test_coaching_boundaries_v94.py`
- `test_coaching_cache_reset_v85.py`
- `test_feedback_history_v86.py`
- `test_proactive_coaching_v65.py`
- `test_process_performance_v71.py`
- `test_versioned_coaching_cache_v90.py`

## Application and infrastructure Python tests (no direct stage dependency)

- `test_analysis_checkpoint_v38.py`
- `test_balanced_playlist_v76.py`
- `test_checkpoint_schema_v38.py`
- `test_clean_restart_v53.py`
- `test_coach_comparison_v74.py`
- `test_coach_export_v51.py`
- `test_coach_metric_charts_v75.py`
- `test_coach_reset_v53.py`
- `test_coach_spotlight_schema_v34.py`
- `test_coach_version_history_v73.py`
- `test_dual_board_input_v41.py`
- `test_evaluation_architecture_v91.py`
- `test_evaluation_explanation_feedback_v92.py`
- `test_explanatory_sql_v43.py`
- `test_feedback_analytics_v48.py`
- `test_feedback_corrections_v56.py`
- `test_feedback_toggle_v57.py`
- `test_full_coach_benchmark_v64.py`
- `test_game_sharing.py`
- `test_historic_coach_schema.py`
- `test_idle_startup_v29.py`
- `test_opening_classification.py`
- `test_opening_playlist.py`
- `test_opening_schema.py`
- `test_opening_templates.py`
- `test_player_clock_in_v62.py`
- `test_player_learning_v61.py`
- `test_player_reset_v63.py`
- `test_playlist_manifest.py`
- `test_process_api_v46.py`
- `test_process_benchmark_connection_v89.py`
- `test_process_policy_v46.py`
- `test_process_restart_v52.py`
- `test_progressive_pages_v39.py`
- `test_retrieval_v45.py`
- `test_taxonomy_change_rates_v72.py`
- `test_taxonomy_feedback_v68.py`

## Front-end / browser-contract JavaScript tests

- `test_benchmark_chart_v91.cjs`
- `test_brilliant_coach_ui_v34.cjs`
- `test_chunked_trainer.cjs`
- `test_coach_attempt_comments_ui_v78.cjs`
- `test_coach_change_rate_ui_v72.cjs`
- `test_coach_comparison_ui_v74.cjs`
- `test_coach_layout_v55.cjs`
- `test_coach_post_solve_ui_v77.cjs`
- `test_coach_ui_v51.cjs`
- `test_coaching_cache_reset_ui_v85.cjs`
- `test_coaching_taxonomy_ui_v66.cjs`
- `test_continuation_feedback_ui_v83.cjs`
- `test_evaluation_explanation_feedback_v92.cjs`
- `test_feedback_corrections_ui_v56.cjs`
- `test_feedback_toggle_ui_v57.cjs`
- `test_feedback_ui_v48.cjs`
- `test_historic_coach.cjs`
- `test_home_process_launch.cjs`
- `test_player_clock_toggle_v62.cjs`
- `test_player_reset_ui_v63.cjs`
- `test_player_ui_v61.cjs`
- `test_process_media_v38.cjs`
- `test_process_perf_ui_v71.cjs`
- `test_process_restart_ui_v52.cjs`
- `test_process_ui_v46.cjs`
- `test_processes_ui.cjs`
- `test_retrieval_ui_v45.cjs`
- `test_solved_auto_analysis_v59.cjs`
- `test_taxonomy_feedback_ui_v68.cjs`
- `test_taxonomy_pills_ui_v69.cjs`
- `test_trainer_navigation_motifs_ui_v70.cjs`
- `test_unlearn_navigation.cjs`

Python files: 84; JS test files: 32. Detection uses static import declarations plus references to canonical source paths.
