"""Stage 3: choose a supported explanation that usually addresses the motif.

Motif names are expectations, not evidence. A motif can only win selection
when an event independently supports it. Otherwise explain the supported
mechanism, and expose the mismatch for future taxonomy audits.
"""
from __future__ import annotations
from dataclasses import replace
from coaching.conceptual_understanding.decision_comparator import DecisionFinding, event_score

MATCHES = {
    'mating_net': {'forced_mate','checkmate','mate_threat'},
    'perpetual_check': {'perpetual_check'},
    'mate_defense': {'threat_neutralized','check_evasion'},
    'fork': {'fork'}, 'skewer': {'skewer'}, 'pin': {'pin'},
    'discovered_attack': {'discovered_attack','discovered_check'},
    'capture_loose_piece': {'capture','attack_loose_piece'},
    'hanging_piece': {'capture','attack_loose_piece'},
    'dont_hang_pieces': {'capture','threat_neutralized'},
    'loose_piece_awareness': {'threat_neutralized','capture','attack_loose_piece'},
    'king_safety': {'checkmate','check_evasion','threat_neutralized','check'},
    'passed_pawn': {'promotion','passed_pawn'},
    'promotion_tactic': {'promotion'},
    'blocking': {'check_evasion','threat_neutralized'},
    'material_sacrifice': {'fork','discovered_attack','mate_threat','checkmate'},
    'simplification': {'exchange','recapture','capture'},
}

def select_finding(finding: DecisionFinding, evidence):
    if not finding.motif or finding.main_event is None:
        return finding
    candidates=[e for e in evidence.events if e.kind in MATCHES.get(finding.motif,())
                and e.ply<=2 and (finding.purpose=='explanation' and e.ply%2==0
                                   or finding.purpose=='learning' and e.ply%2==1)]
    candidates.sort(key=lambda e:(-event_score(e),e.ply))
    # A late trivial motif hit does not displace a major immediate finding.
    match=candidates[0] if candidates else None
    if match and event_score(match)>=event_score(finding.main_event)-18:
        return replace(finding,main_event=match,
                       supporting_event=(finding.main_event if match!=finding.main_event
                                         else finding.supporting_event),note='motif_grounded')
    return replace(finding,note='motif_unverified')
