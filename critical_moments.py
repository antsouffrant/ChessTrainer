"""Decision-rooted critical events from two saved Stockfish continuations.

A root evaluation gap is measured at the *decision*, not when a capture
subsequently appears on the board. A later move only realizes that already
anticipated cost. Sampled PVs do not prove inevitability or a unique refutation.
This module never runs the engine; metadata refresh can rebuild its evidence.
"""
from __future__ import annotations

import json
import chess
from pv_reasoning import legal_pv
from explanatory_evidence import describe_variation, decode_variations, explanation_variations

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
         chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
EVIDENCE_VERSION = 2


def _branch(board, moves, horizon=8):
    replay = board.copy(stack=False)
    events = []
    net = 0
    for ply, move in enumerate(moves[:horizon]):
        if move not in replay.legal_moves:
            break
        side = replay.turn
        victim = (chess.Piece(chess.PAWN, not side) if replay.is_en_passant(move)
                  else replay.piece_at(move.to_square) if replay.is_capture(move) else None)
        gain = VALUE.get(victim.piece_type, 0) if victim else 0
        if move.promotion:
            gain += VALUE.get(move.promotion, 0) - 1
        net += gain * (1 if side == board.turn else -1)
        events.append({'ply': ply, 'uci': move.uci(), 'san': replay.san(move),
                       'square': chess.square_name(move.to_square),
                       'piece': chess.piece_name(victim.piece_type) if victim else None,
                       'piece_value': VALUE.get(victim.piece_type, 0) if victim else 0,
                       'net': net, 'is_ours': side == board.turn,
                       'is_capture': bool(victim)})
        replay.push(move)
    return events


def critical_decision_evidence(board, best, played, best_pv=None, played_pv=None,
                               eval_before_cp=None, eval_after_cp=None, alternatives=None, explanatory_lines=None):
    """First *demonstrated* non-trivial disadvantage from the played branch.

    Don't promote the first capture of an equal exchange into a lost piece.
    Require an evaluation gap and a material difference at comparable horizons;
    prefer the earliest event to a downstream fork or pressure description.
    """
    result = {'version': EVIDENCE_VERSION, 'kind': None, 'root_loss_cp': None,
              'critical_ply': None, 'critical_move': None, 'motif': None,
              'realizations': [], 'comparison_role': 'played'}
    try:
        if eval_before_cp is not None and eval_after_cp is not None:
            result['root_loss_cp'] = max(0, int(eval_before_cp) - int(eval_after_cp))
    except (ValueError, TypeError):
        pass
    # In a positive lesson, compare the played best move with a saved ranked
    # alternative; otherwise the original move has no inferior branch at all.
    if not best or best not in board.legal_moves or not played:
        return result
    if played == best:
        try:
            import json as _json
            options = _json.loads(alternatives) if isinstance(alternatives, str) else alternatives
            options = options if isinstance(options, list) else []
            option = next((x for x in options if isinstance(x, dict)
                           and x.get('move_uci') and x.get('eval_cp') is not None
                           and x.get('pv_uci') and x['move_uci'] != best.uci()), None)
            if not option:
                return result
            played = chess.Move.from_uci(option['move_uci'])
            if played not in board.legal_moves or eval_before_cp is None:
                return result
            eval_after_cp = option['eval_cp']
            played_pv = option['pv_uci']
            result['comparison_role'] = 'alternative'
            result['root_loss_cp'] = max(0, int(eval_before_cp) - int(eval_after_cp))
        except (TypeError, ValueError, KeyError):
            return result
    if played not in board.legal_moves:
        return result
    # Without an evaluation gap we cannot claim that an observed material event
    # actually explains the move's inferior engine assessment.
    if result['root_loss_cp'] is None or result['root_loss_cp'] < 65:
        return result
    best_moves = legal_pv(board, best_pv, first_move=best, max_plies=8)
    played_moves = legal_pv(board, played_pv, first_move=played, max_plies=8)
    if len(played_moves) < 2 or len(best_moves) < 2:
        return result
    structured = decode_variations(explanatory_lines)
    if not structured:
        structured = {'lines': []}  # No extra evidence needed without a saved reply probe.
    # For the alternative comparison, the supplied played PV is authoritative.
    best_signals = describe_variation(board, best_moves, 'recommended')['plies']
    poor_signals = describe_variation(board, played_moves, 'comparison')['plies']
    opponent_facts = []
    for ply in range(1, min(len(poor_signals), 8), 2):
        for feature in poor_signals[ply]['effects']:
            if feature['kind'] == 'check':
                continue  # A check alone rarely explains the lost evaluation.
            if feature['kind'] in {'capture', 'exchange'}:
                continue  # Exchanges are not material wins; test the net separately.
            # A shared check or pin is contextual, not a contrast. Compare board
            # facts and positions on both branches before promoting it.
            if any(other['kind'] == feature['kind']
                   for other_ply in best_signals[1:min(len(best_signals), ply + 2):2]
                   for other in other_ply['effects']):
                continue
            # Pins and quiet discoveries count only if the PV demonstrates a
            # follow-up or the evaluation gap is large enough to justify a
            # qualified, non-forced tactical explanation.
            if (feature['kind'] in {'pin', 'discovered_attack', 'trapped_piece'}
                    and result['root_loss_cp'] < 140):
                continue
            opponent_facts.append({'kind': feature['kind'], 'motif': feature['motif'],
                'critical_ply': ply, 'critical_move': poor_signals[ply]['san'],
                'text': feature['text'],
                'weight': feature['weight'] - 17 * max(0, ply - 1),
                'played_move': board.san(played), 'best_move': board.san(best)})
    # An independent reply probe checks how much of a tactical hypothesis is
    # visible in another credible engine continuation. It is never required to
    # show the same tactic (defenders may choose a different way to lose), and
    # a sampled line does not prove inevitability.
    tested = next((line for line in structured['lines']
                   if line.get('role') == 'tested_reply'), None)
    if tested:
        signatures = {effect['kind']
                      for ply in tested.get('plies', [])[1:4:2]
                      for effect in ply.get('effects', [])}
        for event in opponent_facts:
            event['also_seen_in_tested_reply'] = event['kind'] in signatures
            if event['also_seen_in_tested_reply']:
                event['weight'] += 8
    result['probe_checked'] = bool(tested)
    result['realizations'] = sorted(opponent_facts, key=lambda x: -x['weight'])[:5]
    good = _branch(board, best_moves)
    bad = _branch(board, played_moves)
    for event in bad[1:6:2]:
        if event['is_ours'] or not event['is_capture'] or event['piece_value'] < 1:
            continue
        ply = event['ply']
        # If we recapture the same attacker, this may be an equal exchange.
        next_event = bad[ply + 1] if len(bad) > ply + 1 else None
        recaptured = bool(next_event and next_event['is_ours']
                          and next_event['is_capture']
                          and next_event['square'] == event['square'])
        # Is the loss actually material relative to the better continuation?
        # Compare at the first common stable boundary after an immediate reply.
        common = min(len(good), len(bad))
        if common <= ply:
            continue
        stable = min(common - 1, ply + (1 if recaptured else 0))
        difference = good[stable]['net'] - bad[stable]['net']
        if difference < max(1, event['piece_value'] - 1):
            continue
        if recaptured and difference < max(2, event['piece_value']):
            continue
        # The same piece getting taken in both branches is not an explanatory
        # difference. The root decision must actually change that exposure.
        if any(e['is_capture'] and not e['is_ours']
               and e['square'] == event['square']
               and e['piece'] == event['piece'] for e in good[:stable + 1]):
            continue
        # A demonstrated mate on an earlier reply supersedes a later capture.
        if any(x['kind'] == 'checkmate' and x['critical_ply'] < ply for x in result['realizations']):
            break
        result.update({'kind': 'material_loss', 'critical_ply': ply,
                       'critical_move': event['san'], 'critical_uci': event['uci'],
                       'piece': event['piece'], 'square': event['square'],
                       'net_difference_pawns': difference,
                       'best_move': board.san(best), 'played_move': board.san(played),
                       'motif': 'loose_piece_awareness'})
        return result
    # The first sufficiently close *demonstrated* tactical realization is
    # usually more relevant than an incidental motif deep in the continuation.
    # Do not call a sampled response inevitable: the root eval gap establishes
    # the error; the event illustrates a concrete way it is exploited.
    if result['realizations']:
        strongest = result['realizations'][0]
        if strongest['weight'] >= 28:
            result.update({key: strongest[key] for key in
                           ('kind', 'motif', 'critical_ply', 'critical_move',
                            'played_move', 'best_move', 'text')})
    return result


def decode_critical_evidence(raw):
    if isinstance(raw, dict):
        return raw if raw.get('version') == EVIDENCE_VERSION else None
    if isinstance(raw, str) and raw.strip():
        try:
            item = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return decode_critical_evidence(item)
    return None


def critical_explanation(evidence):
    """Give the first tactical realization without reciting later PV motifs."""
    if not evidence or not evidence.get('kind'):
        return ''
    if evidence.get('kind') != 'material_loss':
        move = evidence.get('played_move')
        best = evidence.get('best_move')
        event = evidence.get('text')
        if not all((move, best, event)):
            return ''
        context = ('After the alternative ' if evidence.get('comparison_role') == 'alternative'
                   else 'After ')
        # An illustrative PV is not a universal forced refutation. Keep SAN
        # capitalization intact and explain the recorded response concretely.
        return f'{context}{move}, the analyzed reply {event}. The engine rates {best} higher; this sampled line does not prove that every such threat disappears.'
    played = evidence.get('played_move')
    reply = evidence.get('critical_move')
    best = evidence.get('best_move')
    piece = evidence.get('piece')
    square = evidence.get('square')
    ply = evidence.get('critical_ply')
    if not all((played, reply, best, piece, square)):
        return ''
    if ply == 1:
        qualifier = 'the alternative ' if evidence.get('comparison_role') == 'alternative' else ''
        return (f'After {qualifier}{played}, {reply} wins your {piece} on {square}. '
                f'{best} retains more material at the compared point in the saved variations.')
    qualifier = 'the alternative ' if evidence.get('comparison_role') == 'alternative' else ''
    return (f'After {qualifier}{played}, the analyzed continuation reaches '
            f'{reply}, winning your {piece} on {square}. {best} avoids that loss.')
