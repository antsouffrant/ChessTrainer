"""Conservative board-outcome evidence for contrasting two lines from one FEN.

No engine lines are called forced without a mate score. Do not infer tablebase
wins from a materially favorable endgame, or infer a tactic from a bare pin.
All geometric comparisons use equal-ply positions when both branches exist.
"""
from __future__ import annotations

import chess

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
               chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def _board_at(board, line, n=None):
    copy = board.copy(stack=False)
    for move in line[:n]:
        copy.push(move)
    return copy


def _square(s):
    return chess.square_name(s)


def _name(piece):
    return chess.piece_name(piece.piece_type)


def _passed(board, square, color):
    r, f = chess.square_rank(square), chess.square_file(square)
    return not any(abs(chess.square_file(e) - f) <= 1 and
                   ((chess.square_rank(e) > r) if color else (chess.square_rank(e) < r))
                   for e in board.pieces(chess.PAWN, not color))


def _passed_positions(board, side):
    return sorted((sq for sq in board.pieces(chess.PAWN, side) if _passed(board, sq, side)),
                  key=lambda s: (chess.square_rank(s) if side else 7 - chess.square_rank(s)), reverse=True)


def _pawn_weakness(board, side):
    pawns = list(board.pieces(chess.PAWN, side))
    files = {f: sum(chess.square_file(s) == f for s in pawns) for f in range(8)}
    doubled = sum(max(0, v - 1) for v in files.values())
    isolated = sum(not files.get(chess.square_file(s) - 1, 0) and
                   not files.get(chess.square_file(s) + 1, 0) for s in pawns)
    return doubled, isolated


def _backward_pawns(board, side):
    """High-precision approximation: unsupported pawn unable to advance safely.

    Backward-pawn theory has strategic exceptions; report only a new, clearly
    pawn-blockaded backward candidate (never assert the endgame is lost).
    """
    own_pawns = list(board.pieces(chess.PAWN, side))
    result = []
    for sq in own_pawns:
        rank, file = chess.square_rank(sq), chess.square_file(sq)
        nxt = rank + (1 if side else -1)
        if not 0 <= nxt <= 7:
            continue
        forward = chess.square(file, nxt)
        if board.piece_at(forward) is not None:
            continue
        enemy_pawn_controls = any(
            (pc := board.piece_at(attacker)) is not None and
            pc.piece_type == chess.PAWN and pc.color != side
            for attacker in board.attackers(not side, forward)
        )
        if not enemy_pawn_controls:
            continue
        neighbors = [p for p in own_pawns if abs(chess.square_file(p) - file) == 1]
        if not neighbors:
            continue  # isolated, not backward
        # A neighboring pawn at or behind this pawn could eventually support
        # its push; do not call the structure backward in this case.
        if any((chess.square_rank(p) <= rank if side else chess.square_rank(p) >= rank)
               for p in neighbors):
            continue
        result.append(sq)
    return result


def _king_danger(board, side):
    king = board.king(side)
    if king is None:
        return 0
    ring = set(board.attacks(king)) | {king}
    return sum(min(2, len(board.attackers(not side, sq))) for sq in ring)


def _king_activity(board, side):
    king = board.king(side)
    if king is None:
        return 0
    f, r = chess.square_file(king), chess.square_rank(king)
    return 7 - min(abs(f-3)+abs(r-3), abs(f-3)+abs(r-4),
                   abs(f-4)+abs(r-3), abs(f-4)+abs(r-4))


def _endgame(board):
    if not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK):
        return True
    return sum(PIECE_VALUE[p.piece_type] for p in board.piece_map().values()
               if p.piece_type not in (chess.KING, chess.PAWN)) <= 16


def _space(board, side):
    enemy_half = range(4, 8) if side == chess.WHITE else range(0, 4)
    count = 0
    for rank in enemy_half:
        for file in range(8):
            sq = chess.square(file, rank)
            if board.is_attacked_by(side, sq):
                count += 1
    return count


def _attack_defense(board, best_one, played_one, side, has_played, best_move, played_move=None):
    """Compare pressure on pieces that remain on the same square after both moves.

    Merely attacking a piece is not said to win it. Require increased pressure
    relative to the played move and the starting position.
    """
    candidates = []
    for sq, pc in board.piece_map().items():
        if pc.piece_type == chess.KING:
            continue
        bpc, ppc = best_one.piece_at(sq), played_one.piece_at(sq)
        if bpc != pc or ppc != pc:
            continue
        if pc.color != side and PIECE_VALUE[pc.piece_type] >= 3:
            ours_initial = len(board.attackers(side, sq))
            ours_best = len(best_one.attackers(side, sq))
            ours_played = len(played_one.attackers(side, sq))
            if (ours_best > max(ours_initial, ours_played)
                    and (best_one.is_check()
                         or not best_one.is_attacked_by(not side, best_move.to_square)
                         or best_one.is_attacked_by(side, best_move.to_square))):
                defenders = len(best_one.attackers(not side, sq))
                urgency = 1 if ours_best > defenders else 0
                candidates.append((urgency, PIECE_VALUE[pc.piece_type], 'attack', sq, pc,
                                   ours_best - ours_initial))
        elif pc.color == side and PIECE_VALUE[pc.piece_type] >= 1:
            attacked = bool(board.attackers(not side, sq))
            if not attacked:
                continue
            defenders_initial = len(board.attackers(side, sq))
            defenders_best = len(best_one.attackers(side, sq))
            defenders_played = len(played_one.attackers(side, sq))
            if defenders_best > max(defenders_initial, defenders_played):
                candidates.append((1, PIECE_VALUE[pc.piece_type], 'defend', sq, pc,
                                   defenders_best - defenders_initial))
    if not candidates:
        return None
    _, _, kind, sq, pc, count = max(candidates)
    best_san = board.san(best_move)
    if kind == 'defend':
        # The word "hanging" requires a real attack and *zero* defenders.
        hanging = (has_played and played_one.is_attacked_by(not side, sq)
                   and not played_one.is_attacked_by(side, sq))
        if hanging:
            return {'motif': 'defensive_resource', 'narrative':
                    f'{best_san} protects your {_name(pc)} on {_square(sq)}; '
                    f'in the game, {board.san(played_move) if played_move is not None else "the alternative"} leaves it hanging.'}
        return {'motif': 'piece_coordination', 'narrative':
                f'{best_san} adds protection to your attacked {_name(pc)} on {_square(sq)}.'}
    return {'motif': 'attack_building', 'narrative':
            f'{best_san} increases pressure on the opponent’s {_name(pc)} on {_square(sq)}.'}


def _same_capture_defense(board, best_move, played_move, best_one, played_one, side):
    """Both moves win the same target, but one abandons a hanging pawn.

    Detect what differs AFTER the common capture before crediting the best
    move for incidental control or the identical pawn capture.
    """
    if (played_move is None or best_move == played_move
            or best_move.to_square != played_move.to_square
            or not board.is_capture(best_move) or not board.is_capture(played_move)):
        return None
    target = board.piece_at(best_move.to_square)
    if not target or target.color == side:
        return None
    best_san = board.san(best_move)
    played_san = board.san(played_move)
    threatened = []
    for sq in board.pieces(chess.PAWN, side):
        if best_one.piece_at(sq) != chess.Piece(chess.PAWN, side) or played_one.piece_at(sq) != chess.Piece(chess.PAWN, side):
            continue
        if (played_one.is_attacked_by(not side, sq)
                and not played_one.is_attacked_by(side, sq)
                and best_one.is_attacked_by(side, sq)):
            threatened.append((chess.square_rank(sq), sq))
    if not threatened:
        return None
    sq = threatened[0][1]
    return {'motif': 'defensive_resource', 'narrative':
            f'{best_san} and {played_san} both capture the opponent’s '
            f'{_name(target)} on {_square(best_move.to_square)}, but {best_san} '
            f'keeps your pawn on {_square(sq)} protected. '
            f'In the game, {played_san} leaves that pawn hanging.'}


def _capture_geometry(board, best_one, played_one, side, first_move):
    """Only describe removing a defender/attacker when its protected target changes."""
    if not board.is_capture(first_move) or board.is_en_passant(first_move):
        return None
    victim_sq = first_move.to_square
    victim = board.piece_at(victim_sq)
    if victim is None or victim.color == side:
        return None
    for sq, piece in board.piece_map().items():
        if sq == victim_sq or piece.piece_type == chess.KING:
            continue
        if piece.color != side and PIECE_VALUE[piece.piece_type] >= 3:
            if not board.is_attacked_by(side, sq) or victim_sq not in board.attackers(not side, sq):
                continue
            if best_one.piece_at(sq) != piece:
                continue
            if (len(best_one.attackers(not side, sq)) < len(board.attackers(not side, sq))
                    and best_one.is_attacked_by(side, sq)):
                return {'motif': 'removal_of_defender', 'narrative':
                        f'The best move removes the {_name(victim)} that defended the '
                        f'opponent’s {_name(piece)} on {_square(sq)}, leaving that target under pressure.'}
        if piece.color == side and PIECE_VALUE[piece.piece_type] >= 3:
            if victim_sq in board.attackers(not side, sq) and best_one.piece_at(sq) == piece:
                if len(best_one.attackers(not side, sq)) < len(board.attackers(not side, sq)):
                    return {'motif': 'defensive_resource', 'narrative':
                            f'The best move captures the {_name(victim)} attacking your '
                            f'{_name(piece)} on {_square(sq)}, removing that threat directly.'}
    return None


def _pin_change(original, best_one, played_one, side):
    enemy = not side
    new = []
    for sq, pc in best_one.piece_map().items():
        if pc.color != enemy or pc.piece_type in (chess.KING, chess.PAWN):
            continue
        if (best_one.is_pinned(enemy, sq)
                and not original.is_pinned(enemy, sq)
                and not played_one.is_pinned(enemy, sq)
                and best_one.is_attacked_by(side, sq)):
            # A newly pinned piece matters most when a real attack on that
            # piece is part of the plan; avoid inferring that a pin wins it.
            new.append((PIECE_VALUE[pc.piece_type], sq, pc))
    if not new:
        return None
    _, sq, pc = max(new)
    return {'motif': 'pin', 'narrative':
            f'The best move pins the opponent’s {_name(pc)} on {_square(sq)} and adds direct pressure to it. '
            'Moving that piece would expose the piece behind it.'}


def _material_balance(board, side):
    return sum((1 if pc.color == side else -1) * PIECE_VALUE[pc.piece_type]
               for pc in board.piece_map().values())


def positional_outcome(board, best_moves, played_moves, side=None):
    """Find the *first well-supported* advantage from comparable PV states.

    The lines are assumed to have already passed legal-PV validation. Prefer
    the first-move contrast for geometry, then matched-horizon positional
    evidence. Without a played line, only clearly created changes qualify.
    """
    if not best_moves:
        return None
    if side is None:
        side = board.turn
    best_one = _board_at(board, best_moves, 1)
    played_one = _board_at(board, played_moves, 1) if played_moves else board
    if played_moves:
        common_capture = _same_capture_defense(
            board, best_moves[0], played_moves[0], best_one, played_one, side)
        if common_capture:
            return {**common_capture, 'ply': 1}
    if (played_moves and len(best_moves) >= 2 and
            board.is_capture(best_moves[0]) and best_one.is_capture(best_moves[1]) and
            best_moves[1].to_square == best_moves[0].to_square):
        victim = board.piece_at(best_moves[0].to_square)
        if victim is not None and victim.color != side:
            for sq, ally in board.piece_map().items():
                if (ally.color != side or ally.piece_type == chess.KING or
                        PIECE_VALUE[ally.piece_type] < 3):
                    continue
                if (best_moves[0].to_square in board.attackers(not side, sq)
                        and played_one.piece_at(best_moves[0].to_square) == victim
                        and played_one.piece_at(sq) == ally
                        and played_one.is_attacked_by(not side, sq)):
                    return {'motif': 'defensive_resource', 'ply': 2, 'narrative':
                        f'{board.san(best_moves[0])} trades off the opponent’s '
                        f'{_name(victim)}, removing its attack on your {_name(ally)} '
                        f'on {_square(sq)}. In the game, {board.san(played_moves[0])} '
                        'leaves that threat in place.'}
    capture = _capture_geometry(board, best_one, played_one, side, best_moves[0])
    if capture:
        return {**capture, 'ply': 1}
    # A piece exchanged on the opponent's next move cannot maintain the
    # double attack, pin or pressure it momentarily appears to generate.
    immediately_recaptured = False
    if len(best_moves) >= 2:
        reply = best_moves[1]
        immediately_recaptured = (best_one.is_capture(reply)
                                   and reply.to_square == best_moves[0].to_square)
    if not immediately_recaptured:
        immediate = _attack_defense(board, best_one, played_one, side, bool(played_moves), best_moves[0],
                                    played_moves[0] if played_moves else None)
        if immediate:
            return {**immediate, 'ply': 1}
    pin = None if immediately_recaptured else _pin_change(board, best_one, played_one, side)

    # Positional changes more than two moves into each branch are often
    # unrelated to the original decision. They may inform the explanation
    # but must not establish its primary motif.
    horizon = min(len(best_moves), len(played_moves), 4) if played_moves else min(len(best_moves), 4)
    if horizon < 2 or not played_moves:
        return ({**pin, 'ply': 1} if pin else None)
    best = _board_at(board, best_moves, horizon)
    played = _board_at(board, played_moves, horizon) if played_moves else board
    # Simplification is meaningful when it actually keeps an existing material
    # advantage. Fewer pieces alone is not proof of an endgame win.
    if (not best.pieces(chess.QUEEN, chess.WHITE)
            and not best.pieces(chess.QUEEN, chess.BLACK)
            and (played.pieces(chess.QUEEN, chess.WHITE) or played.pieces(chess.QUEEN, chess.BLACK))
            and _material_balance(best, side) >= 2):
        return {'ply': horizon, 'motif': 'simplification', 'narrative':
                'The best continuation trades off the queens while retaining a material lead. '
                'It reaches a simpler, materially favorable endgame instead of keeping the queens on.'}
    # Different endpoints are necessarily hypothetical branch consequences;
    # describe what the sampled continuation does, not a forced conclusion.
    bp = _passed_positions(best, side)
    pp = _passed_positions(played, side)
    if len(bp) > len(pp) and len(bp) > len(_passed_positions(board, side)):
        sq = bp[0]
        return {'ply': horizon, 'motif': 'passed_pawn', 'narrative':
                f'The stronger continuation creates a passed pawn on {_square(sq)}, '
                'creating a more advanced pawn threat than in the starting position.'}
    # Existing passed pawn advances substantially in one branch.
    if bp and pp and len(bp) >= len(pp):
        bmax = max(chess.square_rank(sq) if side else 7-chess.square_rank(sq) for sq in bp)
        pmax = max(chess.square_rank(sq) if side else 7-chess.square_rank(sq) for sq in pp)
        if bmax - pmax >= 2:
            return {'ply': horizon, 'motif': 'passed_pawn', 'narrative':
                    f'The best continuation advances your passed pawn to {_square(bp[0])}, '
                    'closer to promotion than in the game continuation.'}
    # Opponent's pawn structure deteriorates in the best continuation.
    bw = _pawn_weakness(best, not side)
    pw = _pawn_weakness(played, not side)
    ow = _pawn_weakness(board, not side)
    if bw[0] > max(pw[0], ow[0]):
        return {'ply': horizon, 'motif': 'pawn_structure', 'narrative':
                'The best continuation leaves the opponent with doubled pawns, '
                'weakening the opponent’s pawn structure relative to the played-move branch.'}
    if bw[1] > max(pw[1], ow[1]):
        return {'ply': horizon, 'motif': 'pawn_structure', 'narrative':
                'The best continuation leaves an isolated opposing pawn without support from adjacent pawn files.'}
    backward_best = _backward_pawns(best, not side)
    backward_played = _backward_pawns(played, not side)
    backward_original = _backward_pawns(board, not side)
    if (len(backward_best) > len(backward_played)
            and len(backward_best) > len(backward_original)):
        return {'ply': horizon, 'motif': 'pawn_structure', 'narrative':
                f'The best continuation leaves an opposing pawn on '
                f'{_square(backward_best[0])} behind its neighbors, with its '
                'advance square controlled by an opposing pawn. This backward-pawn weakness '
                'does not appear in the game continuation.'}
    # Averting weakness in our own position can be a quieter defensive benefit.
    own_best = _pawn_weakness(best, side)
    own_played = _pawn_weakness(played, side)
    if own_best[0] < own_played[0] and own_played[0] > _pawn_weakness(board, side)[0]:
        return {'ply': horizon, 'motif': 'pawn_structure', 'narrative':
                'The best continuation avoids the doubled pawns created in the game continuation.'}
    # Kings matter in both tactical and simplified positions; compare ring
    # exposure rather than using castling alone as evidence of safety.
    danger_best, danger_played = _king_danger(best, side), _king_danger(played, side)
    if danger_played - danger_best >= 3:
        return {'ply': horizon, 'motif': 'king_safety', 'narrative':
                'The best continuation leaves fewer squares around your king under attack, '
                'while the game continuation gives the opponent more access to your king.'}
    enemy_best, enemy_played = _king_danger(best, not side), _king_danger(played, not side)
    if enemy_best - enemy_played >= 3:
        return {'ply': horizon, 'motif': 'attack_building', 'narrative':
                'The best continuation creates more threats around the opposing king '
                'than the game continuation.'}
    if _endgame(board) and _endgame(best) and _endgame(played):
        if _king_activity(best, side) - _king_activity(played, side) >= 2:
            return {'ply': horizon, 'motif': 'king_activity', 'narrative':
                    'The best continuation activates your king toward the center of the endgame, '
                    'while the game continuation keeps it farther from the action.'}
    if (_space(best, side) - _space(played, side) >= 4 and
            _space(best, side) - _space(board, side) >= 3):
        return {'ply': horizon, 'motif': 'space_advantage', 'narrative':
                'The best continuation increases your control of squares in the opponent’s half '
                'of the board, giving your pieces more room to operate.'}
    return ({**pin, 'ply': 1} if pin else None)
