"""One evidence-ranking policy for both explanations and primary curriculum motifs.

A material capture, pin, or checking move is an observation, not yet a
reason for an evaluation difference. The shortlist is ranked on the supported
consequence, nearness to the decision, certainty, and motif specificity. A
sampled continuation is not proof that every other response fails.

No python-chess dependency; regression tests can validate ranking in isolation.
"""
from __future__ import annotations

from motif_hierarchy import BROAD_FALLBACKS, ancestors

# Causal mechanisms are more instructive than a generic description of the
# same result. Specificity is a tiebreaker, never evidence that a tactic exists.
CONCRETE = frozenset({
    'fork', 'skewer', 'discovered_attack', 'removal_of_defender',
    'deflection', 'overloaded_defender', 'trapped_piece', 'back_rank_mate',
    'mating_net', 'mate_defense', 'mate_threat', 'exchange_sacrifice',
    'material_sacrifice', 'dont_hang_pieces', 'capture_loose_piece',
    'counterattack', 'king_activity', 'pawn_structure',
})


def finding_score(f):
    """Sort a supported chess consequence, favoring near-root evidence.

    `impact` remains the calibrated strength of the existing detectors. A
    distant detail is penalized rather than promoted merely for being exotic.
    """
    distance = {0: 0, 1: 3, 2: 9, 3: 25}.get(f.horizon, 48)
    certainty = {3: 5, 2: 0, 1: -12}.get(f.confidence, -15)
    concrete = 4 if f.motif in CONCRETE else 0
    broad = -9 if f.motif in BROAD_FALLBACKS else 0
    # The evaluator's raw scores cannot establish that a refutation is forced.
    return f.impact - distance + certainty + concrete + broad


def ranked_findings(findings):
    return sorted(findings, key=lambda f: (
        -finding_score(f), f.horizon, -f.confidence,
        -len(ancestors(f.motif)), f.key))


def primary_causal_finding(findings, *, min_confidence=2):
    """Allow a well-supported specific cause to anchor both written feedback
    and classification. Low-confidence positional ideas remain legal fallbacks
    for explanations but are not 'verified' tactical classifications.
    """
    return next((f for f in ranked_findings(findings)
                 if f.confidence >= min_confidence), None)
