"""Stage 2 — decision comparator: meaning of the best and candidate roots.

The comparator consumes validated chess evidence. It owns causal/contrastive
reasoning, not source-PV generation, motif persistence or English prose.
"""


def compare(board, best, candidate, *, best_pv=None, candidate_pv=None,
            alternatives=None, best_cp=None, candidate_cp=None):
    """Existing board-grounded comparator behind one canonical stage API."""
    from .decision_context import decision_facts
    return decision_facts(board, best, candidate, best_pv=best_pv,
                          played_pv=candidate_pv, alternatives=alternatives,
                          best_cp=best_cp, played_cp=candidate_cp)
