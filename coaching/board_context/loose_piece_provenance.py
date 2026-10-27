"""Classify *how* a material opportunity arose, not merely that a piece is attacked.

The root board is the training position (before either candidate move).
The two legal principal variations are supporting evidence, not proofs that a
capture is forced. Do not promote a loose-piece observation into a lesson
without an actual differential capture or an immediate legal hanging move.
"""
from __future__ import annotations

import chess


def initially_loose(board: chess.Board, square: int, color: chess.Color) -> bool:
    piece = board.piece_at(square)
    return bool(piece and piece.color == color and piece.piece_type != chess.KING
                and board.is_attacked_by(not color, square)
                and not board.is_attacked_by(color, square))


def new_hanging_mover(board: chess.Board, played: chess.Move) -> bool:
    """The game move places its own piece where it is en prise, with no defender."""
    if played is None or played not in board.legal_moves:
        return False
    mover = board.piece_at(played.from_square)
    if not mover or mover.piece_type == chess.KING:
        return False
    after = board.copy(stack=False)
    after.push(played)
    return bool(after.piece_at(played.to_square) and
                after.is_attacked_by(not board.turn, played.to_square) and
                not after.is_attacked_by(board.turn, played.to_square))


def differential_loss_motif(board: chess.Board, played: chess.Move, lost: dict) -> str:
    """Interpret a witnessed inferior-line loss using root piece identity.

    'Protect Loose Pieces' is exclusively a pre-existing loose-piece problem;
    a piece newly placed in danger is a hanging-piece mistake; other material
    losses can be described as 'Lost Material' without inventing a defense.
    """
    root = lost.get('root_square')
    if not root:
        return 'lost_material'
    try:
        square = chess.parse_square(root)
    except (TypeError, ValueError):
        return 'lost_material'
    if played and played.from_square == square:
        # A moved piece is not 'protected' merely because it used to be loose.
        # If its destination is en prise, the player hung it; otherwise the
        # continuation demonstrates a more general material loss.
        return 'dont_hang_pieces' if new_hanging_mover(board, played) else 'lost_material'
    if initially_loose(board, square, board.turn):
        return 'loose_piece_awareness'
    return 'lost_material'


def confirmed_differential_loss(board: chess.Board, decision: dict) -> dict | None:
    """Find a nearby own loss unique to the game-move variation.

    Require the compared best continuation to reach the loss horizon, and
    discard approximate equal-material exchanges. All capture records retain
    the original square even when the piece moves before it is captured.
    """
    if not decision or not decision.get('bad'):
        return None
    good, bad = decision['good'], decision['bad']
    if bad['material_delta'] >= good['material_delta'] - 1:
        return None
    good_losses = {c['root_square'] for c in good['captures'] if not c['by_solver']}
    return next((c for c in bad['captures']
                 if not c['by_solver'] and c['root_square'] and
                 c['root_square'] not in good_losses and c['ply'] <= 2 and
                 c['ply'] < len(good['steps'])), None)
