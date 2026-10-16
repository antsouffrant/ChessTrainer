"""One-ply, legality-aware evidence at the actual training decision.

Prefer a verifiable immediate capture or defensive oversight to remote motifs
from a sampled principal variation. A PV remains useful when the immediate
position cannot adequately explain the difference. Do not claim all captures
win material: legal recaptures and equal exchanges have distinct explanations.
"""
from __future__ import annotations

import chess

_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
           chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def _name(piece):
    return chess.piece_name(piece.piece_type) if piece else 'piece'


def _move_san(board, move):
    return board.san(move) if move and move in board.legal_moves else None


def _can_capture(board, square):
    """A real legal capture, not merely a geometrical attack from a pinned piece."""
    return any(board.is_capture(move) and move.to_square == square
               for move in board.legal_moves)


def _under_threat(after, square, side):
    piece = after.piece_at(square)
    return bool(piece and piece.color == side and _can_capture(after, square))


def _hanging(after, square, side):
    return (_under_threat(after, square, side)
            and not after.is_attacked_by(side, square))


def immediate_decision(board, best, played=None, context=None):
    """Return a single supported nearest-decision fact, or None.

    Evidence only describes the CURRENT move or its legal immediate reply.
    Mate and check-evasion reasoning remain higher-level special cases.
    Does not estimate the objective value of an exchange or an endgame.
    """
    if best not in board.legal_moves:
        return None
    if played is not None and played not in board.legal_moves:
        played = None
    context = context or {}
    side = board.turn
    opponent = not side
    best_san = board.san(best)
    played_san = _move_san(board, played)
    same_move = played == best
    best_after = board.copy(stack=False)
    best_after.push(best)
    played_after = None
    if played is not None:
        played_after = board.copy(stack=False)
        played_after.push(played)

    # Respond to a *demonstrated* immediate threat against the same piece.
    # Not every attack is a hanging piece: a defender may already protect it.
    shared = set(context.get('best_neutralizes') or []) & set(context.get('played_ignores') or [])
    newly_threatened = set(context.get('new_loose') or []) | set(context.get('new_pressure') or [])
    for square in sorted(shared, key=lambda sq: _VALUES.get(board.piece_type_at(sq), 0), reverse=True):
        piece = board.piece_at(square)
        if piece is None or piece.color != side:
            continue
        # If the game move permits an immediate legal capture, a direct defense
        # explains more than a distant positional or geometry-based consequence.
        if (played_after is not None and _under_threat(played_after, square, side)
                and (square in newly_threatened or _hanging(played_after, square, side))):
            left = 'hanging' if _hanging(played_after, square, side) else 'under attack'
            text = (f'{best_san} addresses the immediate attack on your {_name(piece)} on {chess.square_name(square)}. '
                    f'In the game, {played_san} leaves it {left}.')
            return {'motif': 'loose_piece_awareness' if left == 'hanging' else 'threat_awareness',
                    'explanation': text, 'strength': 1.0, 'kind': 'missed_defense'}

    # The game move itself placed a valuable piece en prise, while the best
    # move does not share that immediate vulnerability. Require an actually
    # legal capture, and no friendly defender for the word 'hanging'.
    if played_after is not None and not same_move:
        moved = played_after.piece_at(played.to_square)
        if (moved and moved.color == side and _VALUES.get(moved.piece_type, 0) >= 3
                and _hanging(played_after, played.to_square, side)):
            # Only claim a contrast if the BEST move doesn't create the same
            # avoidable loose-piece problem at its own destination.
            if not _hanging(best_after, best.to_square, side):
                return {'motif': 'dont_hang_pieces', 'strength': 1.0,
                        'kind': 'played_hangs_piece',
                        'explanation': (f'In the game, {played_san} leaves your '
                                        f'{_name(moved)} on {chess.square_name(played.to_square)} '
                                        f'hanging; {best_san} does not leave its moved piece hanging in the same way.')}

    # A capture is a missed immediate opportunity only when the game move
    # fails to take the same target AND the capture is not legally recaptured.
    # Equal exchanges should be left to the exchange-aware PV comparison.
    if board.is_capture(best) and not board.is_en_passant(best):
        victim = board.piece_at(best.to_square)
        if victim and victim.color == opponent:
            if played is not None and board.is_capture(played) and played.to_square == best.to_square:
                return None  # Explain what differs *after* the shared capture.
            if not _can_capture(best_after, best.to_square):
                target = chess.square_name(best.to_square)
                direct = f'{best_san} takes the opponent\'s unprotected {_name(victim)} on {target}.'
                if played_san and not same_move:
                    direct += f' In the game, {played_san} misses the capture.'
                return {'motif': 'capture_loose_piece', 'strength': 0.98,
                        'kind': 'free_capture', 'explanation': direct}

    # Capturing a newly threatening attacker is a directly intelligible
    # defensive action, but never call it a *free* capture without evidence.
    if (context.get('best_takes_last_piece') and context.get('new_pressure')
            and board.is_capture(best) and not same_move):
        piece = board.piece_at(best.to_square)
        if piece:
            text = (f'{best_san} captures the {_name(piece)} that was threatening your pieces.')
            return {'motif': 'defensive_resource', 'strength': 0.96,
                    'kind': 'remove_attacker', 'explanation': text}
    return None
