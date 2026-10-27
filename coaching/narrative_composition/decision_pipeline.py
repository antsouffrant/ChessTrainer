"""New v35 one-finding coach pipeline across the six stage interfaces.

This is the single canonical post-solve path for attempts, game moves and
best moves. It emits diagnostics for discrepancies without claiming the
motif's truth simply because the classifier selected that key.
"""
from __future__ import annotations
from dataclasses import replace
from coaching.board_context.decision_evidence import extract_decision, board_root_facts, field
from coaching.conceptual_understanding.decision_comparator import compare_decision
from coaching.motif_selection.explanation_selector import select_finding
from coaching.narrative_composition.pedagogical_narrative import compose_finding
from coaching.coaching_validation.narrative_validator import validate_narrative


def coach_decision(row, attempt, *, correct, branch=None, motif_key=None):
    from coaching.coaching_refresh import model_version
    evidence=extract_decision(row,attempt,branch=branch,motif_key=motif_key or '')
    if correct:
        board_facts = board_root_facts(row, evidence.root_uci, evidence.root_san)
        # A root-verified strategic safety fact can displace an incidental
        # saved attack on an irrelevant pawn. Never suppress a verified
        # mating tactic, fork or forced continuation.
        strong=any(e.kind in ('checkmate','fork','discovered_attack','pin','promotion','mate_threat')
                   for e in evidence.events if e.ply==0)
        special=[e for e in board_facts if e.kind in ('queen_safety','king_activity','fork','checkmate')]
        if not strong and special:
            evidence=replace(evidence,events=tuple(special)+evidence.events)
    finding=compare_decision(evidence,correct=correct)
    if not correct and finding.main_event is None and evidence.best_uci and evidence.best_uci!=evidence.root_uci:
        from coaching.board_context.decision_evidence import branch_evidence
        best_attempt={'move_uci':evidence.best_uci,'move_san':evidence.best_san,'correct':1}
        best=extract_decision(row,best_attempt,
                              branch=branch_evidence(row,evidence.best_uci,best_attempt),
                              motif_key=evidence.root_motif)
        best_finding=compare_decision(best,correct=True)
        if best_finding.main_event is not None:
            finding=replace(finding,better_event=best_finding.main_event)
    finding=select_finding(finding,evidence)
    prose=compose_finding(finding)
    errors=validate_narrative(finding,prose)
    if errors:
        # Fail closed: no alternate PV narrator and no invented causality.
        root=finding.root_san
        prose=(f'{root} is the solving move, but the saved evidence is insufficient for an explanation.'
               if correct else
               f'The saved analysis does not establish a specific refutation of {root}.')
    return {
        'move_san':finding.root_san,'move_uci':finding.root_uci,
        'correct':bool(correct),'purpose':finding.purpose,
        'cached':bool(evidence.events),
        'source':'decision-finding-v35','reply_san':finding.opponent_reply,
        'text':prose,'evidence_role':evidence.role,
        'finding_kind':finding.main_event.kind if finding.main_event else 'insufficient',
        'finding_ply':finding.main_event.ply if finding.main_event else None,
        'motif_alignment':finding.note or 'no_motif',
        'coaching_version':model_version(),
        'validation_problems':errors,
    }
