"""Stage 2: convert supported chess events into ONE causal decision finding.

Unlike the old ply reporter, we never describe every reply. A wrong move
requires a demonstrated refutation or an explicit missed alternative. A
correct move describes its actual strategic/tactical consequence. Claims
about mate forcedness require a mate score or a checkmating legal root.
"""
from __future__ import annotations
from dataclasses import dataclass
from coaching.board_context.decision_evidence import DecisionEvidence, Event

SIGNIFICANCE = {
    'forced_mate': 140, 'checkmate': 120, 'perpetual_check': 108, 'fork': 105, 'discovered_check': 100,
    'trapped_piece': 98, 'promotion': 95, 'mate_threat': 90,
    'discovered_attack': 89, 'pin': 87, 'skewer': 87,
    'capture': 65, 'recapture': 61, 'threat_neutralized': 75,
    'passed_pawn': 65, 'attack_loose_piece': 40,
    'check': 24, 'check_evasion': 22, 'exchange': 12,
    'queen_safety': 88, 'king_activity': 78, 'piece_activity': 42,
}

@dataclass(frozen=True)
class DecisionFinding:
    root_uci: str
    root_san: str
    purpose: str
    main_event: Event | None
    supporting_event: Event | None
    opponent_reply: str | None
    best_san: str
    grounded: bool
    motif: str
    note: str = ''
    better_event: Event | None = None


def event_score(event: Event):
    # Events become less persuasive farther from the actual decision. The
    # opponent's first tactical answer is especially relevant to a mistake.
    return SIGNIFICANCE.get(event.kind, 8) - 18*event.ply


def _take(events, *, start=0, stop=4, exclude=()):
    choices = [event for event in events if start <= event.ply <= stop
               and event.kind not in exclude]
    return sorted(choices, key=lambda e:(-event_score(e),e.ply,e.kind))


def compare_decision(evidence: DecisionEvidence, *, correct: bool):
    events = evidence.events
    role = 'explanation' if correct else 'learning'
    if correct:
        try:
            mate_count = int(evidence.mate_before)
        except (ValueError,TypeError,OverflowError):
            mate_count = 0
        if evidence.root_uci == evidence.best_uci and 0 < mate_count < 99:
            events=(Event('forced_mate',f'{evidence.root_san} forces mate in {mate_count}',
                          0,evidence.root_san,evidence.root_uci),)+tuple(events)
        # A major root tactical fact takes precedence over a later capture;
        # a later decisive checkmate/fork may explain a quiet combination.
        root = _take(events,stop=0,exclude=('exchange',))
        follow = _take(events,start=1,stop=4,exclude=('exchange','check_evasion'))
        best_root = root[0] if root else None
        best_follow = next((e for e in follow if e.ply % 2 == 0 and
                            e.kind in ('checkmate','fork','promotion','discovered_attack','pin')),None)
        if best_follow and (not best_root or best_root.kind in
                            ('check','check_evasion','attack_loose_piece','capture')):
            main,support=best_follow,best_root
        else:
            main,support=best_root,None
            if best_root and best_root.kind in ('check','capture'):
                support=best_follow
        return DecisionFinding(evidence.root_uci,evidence.root_san,role,main,support,
                               evidence.reply_san,evidence.best_san,
                               bool(main),evidence.root_motif)
    # Learning: a refutation must be in the opponent's branch, especially
    # an immediate tactical resource. Later friendly moves are NOT proof.
    root_capture=any(e.ply==0 and e.kind in ('capture','recapture') for e in events)
    replies = _take([e for e in events if e.ply % 2 == 1
                     and not (e.ply==1 and root_capture and e.kind in ('capture','recapture'))],
                    start=1,stop=3,
                    exclude=('check_evasion','exchange','recapture',
                             'threat_neutralized','attack_loose_piece'))
    root = _take(events,stop=0,exclude=('exchange',))
    concrete = [e for e in replies if e.kind in
                {'checkmate','fork','discovered_attack','pin','trapped_piece',
                 'promotion','capture','mate_threat','discovered_check','skewer'}]
    if concrete:
        main=concrete[0]
    elif replies and event_score(replies[0])>=40:
        main=replies[0]
    else:
        main=None
    # If the opponent's reply only evades check but the learner's next move
    # reveals a concrete loss, this is illustrative, not forced.
    if main is None:
        return DecisionFinding(evidence.root_uci,evidence.root_san,role,None,None,
                               evidence.reply_san,evidence.best_san,False,
                               evidence.root_motif, 'missed_best')
    return DecisionFinding(evidence.root_uci,evidence.root_san,role,main,
                           root[0] if root else None,evidence.reply_san,
                           evidence.best_san,True,evidence.root_motif)
