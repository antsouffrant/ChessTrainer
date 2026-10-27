"""Six-stage coaching pipeline. Public stage boundaries live in each subpackage.

v35 makes the evidence-to-decision-to-message interfaces canonical while
preserving separate versioned snapshots and append-only feedback history.
"""

STAGES = (
    'board_context', 'conceptual_understanding', 'motif_selection',
    'narrative_composition', 'coaching_validation', 'coaching_refresh',
)
