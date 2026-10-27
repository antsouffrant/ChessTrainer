"""Concrete, legal check-evasion evidence for explanations and motifs.

Being in check is a constraint on the *decision*, not just an attack on an
opponent's piece.  A blocking move may offer a trade, but a claimed exchange
requires the checker's capture AND our recapture to be legal.  Nothing here
claims the opponent is forced to take the offered piece.
"""
from __future__ import annotations
import chess

POINTS = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
SLIDERS = {chess.BISHOP, chess.ROOK, chess.QUEEN}


def check_response(board: chess.Board, move: chess.Move) -> dict | None:
    """Describe how this legal move meets a check, including a possible trade.

    Returns None when the king wasn't in check.  An interposition is detected
    by the line between the checking slider and king, never by generic attack
    counts.  A legal checking-piece capture plus a legal recapture demonstrates
    the *option* of an exchange, not that a particular PV is forced.
    """
    if not board.is_check() or move not in board.legal_moves:
        return None
    side = board.turn
    moving_piece = board.piece_at(move.from_square)
    king = board.king(side)
    checkers = list(board.checkers())
    after = board.copy(stack=False)
    san = board.san(move)
    capture = board.is_capture(move)
    after.push(move)

    kind = 'other_evasion'
    checker_sq = checkers[0] if len(checkers) == 1 else None
    checker = board.piece_at(checker_sq) if checker_sq is not None else None
    if moving_piece and moving_piece.piece_type == chess.KING:
        kind = 'king_move'
    elif checker_sq is not None and capture and move.to_square == checker_sq:
        kind = 'capture_checker'
    elif (checker_sq is not None and checker and checker.piece_type in SLIDERS
          and king is not None and
          chess.between(checker_sq, king) & chess.BB_SQUARES[move.to_square]):
        kind = 'interpose'

    trade = None
    if kind == 'interpose' and checker_sq is not None and moving_piece:
        taking = chess.Move(checker_sq, move.to_square)
        if taking in after.legal_moves and after.is_capture(taking):
            taking_san = after.san(taking)
            after_take = after.copy(stack=False)
            after_take.push(taking)
            possible = [m for m in after_take.legal_moves
                        if m.to_square == move.to_square and after_take.is_capture(m)]
            if possible:
                reply = possible[0]
                trade = {'capture_san': taking_san,
                         'recapture_san': after_take.san(reply),
                         'equal_value': abs(POINTS[moving_piece.piece_type] -
                                            POINTS[checker.piece_type]) == 0,
                         'checking_piece': checker.piece_type,
                         'blocking_piece': moving_piece.piece_type}

    checker_name = chess.piece_name(checker.piece_type) if checker else 'checking piece'
    checker_loc = chess.square_name(checker_sq) if checker_sq is not None else ''
    if kind == 'interpose':
        sentence = f'{san} blocks the check from the {checker_name} on {checker_loc}.'
        if trade and trade['equal_value']:
            sentence += (f' If {trade["capture_san"]}, {trade["recapture_san"]} '
                         f'trades the two {chess.piece_name(moving_piece.piece_type)}s.'
                         if moving_piece.piece_type == checker.piece_type else
                         f' If {trade["capture_san"]}, {trade["recapture_san"]} '
                         f'exchanges your {chess.piece_name(moving_piece.piece_type)} '
                         f'for the {checker_name}.')
    elif kind == 'capture_checker':
        sentence = f'{san} captures the checking {checker_name}, ending the check.'
    elif kind == 'king_move':
        sentence = f'{san} moves the king out of check.'
    else:
        sentence = f'{san} answers the check.'

    return {'kind': kind, 'checker_square': checker_sq,
            'checker_type': checker.piece_type if checker else None,
            'trade': trade, 'evidence': sentence,
            'motif': ('blocking' if kind == 'interpose' else
                      'defensive_resource' if kind == 'capture_checker' else 'king_safety')}


def blocking_response(board: chess.Board, move: chess.Move) -> dict | None:
    """Evidence of a *legal interposition*, not mere defensive geometry.

    A blocking piece must occupy a square between an opposing sliding attacker
    and the same valuable friendly target that the attacker threatened at root.
    After the move the target must survive and that specific line must be cut.
    This also handles blocking check through ``check_response``.
    """
    if move not in board.legal_moves:
        return None
    evasion = check_response(board, move)
    if evasion and evasion['kind'] == 'interpose':
        return {'motif': 'blocking', 'evidence': evasion['evidence'], 'kind': 'check'}
    if board.is_check() or board.is_capture(move):
        return None
    moving = board.piece_at(move.from_square)
    if not moving or moving.piece_type == chess.KING:
        return None
    after = board.copy(stack=False)
    after.push(move)
    # A freshly sacrificed interposing piece does not by itself establish a
    # successful defense: require either a defender or no immediate attack.
    if after.is_attacked_by(not board.turn, move.to_square) and not after.is_attacked_by(board.turn, move.to_square):
        return None
    for target_sq, target_piece in board.piece_map().items():
        if target_piece.color != board.turn or target_piece.piece_type in {chess.PAWN, chess.KING}:
            continue
        if target_sq == move.from_square:
            continue
        for attacker_sq in board.attackers(not board.turn, target_sq):
            attacker = board.piece_at(attacker_sq)
            if not attacker or attacker.piece_type not in SLIDERS:
                continue
            if not chess.between(attacker_sq, target_sq) & chess.BB_SQUARES[move.to_square]:
                continue
            if after.piece_at(target_sq) != target_piece:
                continue
            if after.is_attacked_by(not board.turn, target_sq) and attacker_sq in after.attackers(not board.turn, target_sq):
                continue
            return {'motif': 'blocking', 'kind': 'material',
                    'evidence': (f'{board.san(move)} blocks the '
                                 f'{chess.piece_name(attacker.piece_type)} on '
                                 f'{chess.square_name(attacker_sq)} from attacking '
                                 f'your {chess.piece_name(target_piece.piece_type)} '
                                 f'on {chess.square_name(target_sq)}.')}
    return None
