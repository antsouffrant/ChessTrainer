"""Check *observed consequences* before describing tactical purpose.

A principal variation is an example of play, not a proof that every opposing
response fails.  Return consequences only when a legal trace contains the
claimed compensation or structural change.  None of these functions infer
engine evaluations, nor is a geometrically attacked piece counted as won.
"""
from __future__ import annotations

import chess


PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def sacrifice_compensation(trace, *, maximum_ply=7):
    """Describe compensation for an immediate unequal exchange, if observed.

    The sacrifice is established by capture/recapture at plies 0 and 1.
    Compensation must be realized by the *solver* subsequently capturing
    material in the same legal line. Merely attacking a piece is insufficient.
    A subsequent immediate recapture that erases the claimed recovery is not
    presented as a clean payoff. No force claim is made.
    """
    if not trace or not trace.get('exchanges'):
        return None
    exchange = next((x for x in trace['exchanges']
                     if x['first']['ply'] == 0 and x['recapture']['ply'] == 1
                     and x['first']['by_solver'] and not x['recapture']['by_solver']
                     and x['recapture']['value'] - x['first']['value'] >= 2), None)
    if not exchange:
        return None
    if trace.get('material_delta', -1) < 0:
        return None  # Do not turn a temporary recapture into net compensation.
    captures = trace['captures']
    steps = trace['steps']
    for capture in captures:
        ply = capture['ply']
        if not (2 <= ply <= maximum_ply and ply < len(steps) and capture['by_solver']):
            continue
        if steps[ply]['material_delta'] < 0:
            continue  # One capture without recovering the investment is not compensation.
        if ply + 1 < len(steps):
            next_capture = next((c for c in captures if c['ply'] == ply + 1
                                 and not c['by_solver'] and c['square'] == capture['square']), None)
            if next_capture and next_capture['value'] >= capture['value']:
                continue
        return {'reply': steps[1]['san'], 'payoff': steps[ply]['san'],
                'piece': capture['piece'], 'ply': ply,
                'net_material': steps[ply]['material_delta']}
    return None


def _doubled_files(board, color):
    counts = [0] * 8
    for square in board.pieces(chess.PAWN, color):
        counts[chess.square_file(square)] += 1
    return {i for i, value in enumerate(counts) if value >= 2}


def structural_exchange_gain(board, best, played, good, bad):
    """Detect a trade causing the opponent's *new* doubled pawns.

    Require a root capture and the opponent's immediate pawn recapture,
    plus a comparable two-ply inferior branch that does not cause the same
    damage. Both branches must replay legally. We don't infer an advantage
    from doubling alone: the classifier may use it as a *purpose* of a
    clearly engine-preferred equal trade, not as a forced material win.
    """
    if not played or not board.is_capture(best) or not good or not bad:
        return None
    if len(good.get('steps', [])) < 2 or len(bad.get('steps', [])) < 2:
        return None
    exchange = next((x for x in good.get('exchanges', [])
                     if x['first']['ply'] == 0 and x['recapture']['ply'] == 1
                     and x['first']['by_solver'] and x['recapture']['piece'] != 'pawn'
                     and abs(x['first']['value'] - x['recapture']['value']) <= 1), None)
    # The recaptured item is our exchanged piece; the opponent's pawn must be
    # the *mover* of their reply, independently of the captured piece type.
    if not exchange:
        return None
    reply = chess.Move.from_uci(good['steps'][1]['uci'])
    after_best = board.copy(stack=False)
    after_best.push(best)
    pawn = after_best.piece_at(reply.from_square)
    if (reply not in after_best.legal_moves or not pawn
            or pawn.color == board.turn or pawn.piece_type != chess.PAWN
            or reply.to_square != best.to_square):
        return None
    def two(steps):
        b = board.copy(stack=False)
        for step in steps[:2]:
            move = chess.Move.from_uci(step['uci'])
            if move not in b.legal_moves:
                return None
            b.push(move)
        return b
    good_after = two(good['steps'])
    bad_after = two(bad['steps'])
    if not good_after or not bad_after:
        return None
    opponent = not board.turn
    created = _doubled_files(good_after, opponent) - _doubled_files(board, opponent)
    distinct = created - _doubled_files(bad_after, opponent)
    if not distinct:
        return None
    return {'file': chess.FILE_NAMES[min(distinct)], 'reply': good['steps'][1]['san']}
