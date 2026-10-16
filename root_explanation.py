"""Concrete, legality-aware first-move facts for the human coaching narrative.

Do not use a remote positional-PV observation to displace what a move does at
its root. These facts are *not* claims that a move is objectively winning; they
are suitable as the first statement when no more decisive verified tactic wins.
"""
from __future__ import annotations

import chess
from pv_reasoning import legal_pv

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
         chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTRAL = {chess.D4, chess.E4, chess.D5, chess.E5}


def _name(piece):
    return chess.piece_name(piece.piece_type)


def _square(square):
    return chess.square_name(square)


def _legal_recaptures(after, target):
    return [move for move in after.legal_moves
            if after.is_capture(move) and move.to_square == target]


def _passed(board, sq, side):
    f, r = chess.square_file(sq), chess.square_rank(sq)
    return not any(abs(chess.square_file(other) - f) <= 1
                   and (chess.square_rank(other) > r if side else chess.square_rank(other) < r)
                   for other in board.pieces(chess.PAWN, not side))


def _new_defense(board, after, side, move):
    targets = []
    for square, piece in board.piece_map().items():
        if piece.color != side or piece.piece_type == chess.KING:
            continue
        if after.piece_at(square) != piece:
            continue
        if (board.is_attacked_by(not side, square)
                and not board.is_attacked_by(side, square)
                and after.is_attacked_by(side, square)):
            targets.append((VALUE[piece.piece_type], square, piece))
    return max(targets) if targets else None


def _new_safe_attack(board, after, side, move):
    moved = after.piece_at(move.to_square)
    if moved is None or moved.color != side:
        return None
    # An attacker immediately removable by legal capture should not be
    # credited with durable pressure. A check can still be forcing elsewhere.
    if _legal_recaptures(after, move.to_square):
        return None
    choices = []
    for sq in after.attacks(move.to_square):
        victim = after.piece_at(sq)
        if (victim and victim.color != side and victim.piece_type != chess.KING
                and move.from_square not in board.attackers(side, sq)):
            choices.append((VALUE[victim.piece_type], sq, victim))
    return max(choices) if choices else None


def root_move_impact(board, best, played=None, best_pv=None):
    """Return an immediate informative sentence, or None if evidence is thin.

    Stronger rooted comparisons (hanging material, identical captures with
    divergent defensive effects, mate, check evasion) are handled by callers.
    """
    if best not in board.legal_moves:
        return None
    san = board.san(best)
    side = board.turn
    mover = board.piece_at(best.from_square)
    after = board.copy(stack=False)
    after.push(best)
    played_san = board.san(played) if played is not None and played in board.legal_moves else ''

    if board.is_capture(best):
        # If two candidate moves take the identical target, describing their
        # shared capture does not explain the advantage of one over the other.
        if (played is not None and played != best and played in board.legal_moves
                and board.is_capture(played) and played.to_square == best.to_square):
            return None
        victim = board.piece_at(best.to_square)
        if board.is_en_passant(best):
            victim = chess.Piece(chess.PAWN, not side)
        if not victim:
            return None
        target = _square(best.to_square)
        pv = legal_pv(board, best_pv, first_move=best, max_plies=3)
        recapture = bool(len(pv) >= 2 and after.is_capture(pv[1])
                         and pv[1].to_square == best.to_square)
        reply_possible = bool(_legal_recaptures(after, best.to_square))
        if recapture and mover and VALUE[mover.piece_type] == VALUE[victim.piece_type]:
            text = f'{san} exchanges your {_name(mover)} for the opponent’s {_name(victim)} on {target}.'
            return {'kind': 'exchange', 'text': text}
        if recapture:
            # Never count the captured piece as free material or a sacrifice.
            return {'kind': 'contested_capture', 'text':
                    f'{san} captures the opponent’s {_name(victim)} on {target}, followed by a recapture in the saved line.'}
        if reply_possible:
            return {'kind': 'contested_capture', 'text':
                    f'{san} captures the opponent’s {_name(victim)} on {target}; the opponent also has a legal recapture.'}
        suffix = (f' In the game, {played_san} misses that capture.'
                  if played_san and played != best else '')
        return {'kind': 'capture', 'text':
                f'{san} takes the opponent’s {_name(victim)} on {target}, which cannot be recaptured immediately.{suffix}'}

    defended = _new_defense(board, after, side, best)
    if defended:
        _, sq, piece = defended
        return {'kind': 'defense', 'text':
                f'{san} adds a defender to your attacked {_name(piece)} on {_square(sq)}.'}

    # The attacking square is newly controlled by the moved piece, not simply
    # present in a later PV; an immediately capturable mover cannot exert it.
    target = _new_safe_attack(board, after, side, best)
    if target:
        _, sq, piece = target
        return {'kind': 'attack', 'text':
                f'{san} attacks the opponent’s {_name(piece)} on {_square(sq)}.'}

    if mover and mover.piece_type == chess.PAWN:
        target = best.to_square
        if _passed(after, target, side) and not _passed(board, best.from_square, side):
            return {'kind': 'passed_pawn', 'text':
                    f'{san} creates a passed pawn with no opposing pawn ahead on its file or neighboring files.'}
        if _passed(after, target, side):
            return {'kind': 'passed_pawn', 'text':
                    f'{san} advances your passed pawn toward promotion.'}
        # Detect a pawn move that physically cuts off an enemy sliding line to
        # a friendly piece, without relying on stale attacker-count metadata.
        sheltered = []
        for sq, piece in board.piece_map().items():
            if piece.color != side or piece.piece_type == chess.KING or sq == best.from_square:
                continue
            if (after.piece_at(sq) == piece and board.is_attacked_by(not side, sq)
                    and not after.is_attacked_by(not side, sq)):
                sheltered.append((VALUE[piece.piece_type], sq, piece))
        if sheltered:
            _, sq, piece = max(sheltered)
            return {'kind': 'block_attack', 'text':
                    f'{san} blocks an attack on your {_name(piece)} on {_square(sq)}.'}
        # A central advance has an immediate territorial effect, even if the
        # available PV is too short to establish a deeper tactical reason.
        file = chess.square_file(target)
        rank = chess.square_rank(target)
        advanced = rank >= 3 if side else rank <= 4
        controls = sorted(sq for sq in after.attacks(target)
                          if not board.is_attacked_by(side, sq))
        if advanced and 2 <= file <= 5:
            if controls:
                squares = ' and '.join(_square(sq) for sq in controls[:2])
                return {'kind': 'pawn_space', 'text':
                        f'{san} gains space in the center and brings {squares} under your pawn’s control.'}
            return {'kind': 'pawn_space', 'text': f'{san} gains space with a central pawn advance.'}
        if controls:
            squares = ' and '.join(_square(sq) for sq in controls[:2])
            return {'kind': 'pawn_control', 'text':
                    f'{san} extends your pawn’s control to {squares}.'}

    if board.is_castling(best):
        return {'kind': 'castle', 'text': f'{san} castles, moving your king away from its original square and activating a rook.'}

    if mover and mover.piece_type == chess.KING:
        # In a simplified ending, king activity can be a concrete benefit,
        # unlike the tautology that the king merely reached a new square.
        heavy = any(board.pieces(chess.QUEEN, color) for color in (chess.WHITE, chess.BLACK))
        minors = sum(len(board.pieces(kind, color)) for kind in
                     (chess.ROOK, chess.BISHOP, chess.KNIGHT)
                     for color in (chess.WHITE, chess.BLACK))
        if not heavy and minors <= 2:
            def central_distance(sq):
                return min(abs(chess.square_file(sq) - f) +
                           abs(chess.square_rank(sq) - r)
                           for f in (3, 4) for r in (3, 4))
            if central_distance(best.to_square) < central_distance(best.from_square):
                return {'kind': 'king_activity', 'text':
                        f'{san} brings your king closer to the center, improving its activity in the endgame.'}

    if mover and mover.piece_type == chess.ROOK:
        original_file, new_file = chess.square_file(best.from_square), chess.square_file(best.to_square)
        if new_file != original_file:
            pawns_new = sum(sum(chess.square_file(sq) == new_file for sq in after.pieces(chess.PAWN, color)) for color in (chess.WHITE, chess.BLACK))
            pawns_old = sum(sum(chess.square_file(sq) == original_file for sq in board.pieces(chess.PAWN, color)) for color in (chess.WHITE, chess.BLACK))
            if pawns_new == 0 and pawns_old > 0:
                return {'kind': 'open_file', 'text':
                        f'{san} puts your rook on the open {_square(best.to_square)[0]}-file, free of pawns.'}

    moved = after.piece_at(best.to_square)
    if mover and mover.piece_type != chess.KING and moved:
        if (board.is_attacked_by(not side, best.from_square)
                and not _legal_recaptures(after, best.to_square)):
            return {'kind': 'escape', 'text':
                    f'{san} moves your attacked {_name(mover)} out of immediate danger.'}
        # A direct check is specific, but avoid overshadowing a mate or an
        # actual tactical result established elsewhere.
        if after.is_check():
            return {'kind': 'check', 'text': f'{san} gives check, requiring an immediate reply.'}
        new_central = [sq for sq in CENTRAL if
                       sq in after.attacks(best.to_square) and not board.is_attacked_by(side, sq)]
        if new_central:
            sq = _square(new_central[0])
            return {'kind': 'central_control', 'text':
                    f'{san} brings your {_name(mover)} to bear on the central square {sq}.'}

    # No tautologies such as "e6 places a pawn on e6". When even the one-ply
    # effect is inconclusive, a truthful gap is preferable to invented pressure.
    return None
