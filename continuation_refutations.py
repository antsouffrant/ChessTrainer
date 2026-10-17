"""Short-horizon tactical mechanisms demonstrated by saved *legal* PVs.

A checking move is not automatically a fork/skewer, and a geometric attack
is not automatically a material win. We require a matching capture in the
following 3 plies before returning a material-winning mechanism. PVs are
illustrations, not proofs of forced outcomes; no calls to Stockfish are made.
"""
from __future__ import annotations

from dataclasses import dataclass
import chess
from pv_reasoning import legal_pv

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


@dataclass(frozen=True)
class Refutation:
    motif: str
    branch: str          # 'best' = solver's opportunity, 'played' = opponent's reply
    ply: int             # zero-based ply of the move creating the threat
    san: str
    payoff: str
    text: str


def _skewer_victim(after, attacking_square, victim_color):
    attacker = after.piece_at(attacking_square)
    king_sq = after.king(victim_color)
    if not attacker or attacker.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN) or king_sq is None:
        return None
    df = chess.square_file(king_sq) - chess.square_file(attacking_square)
    dr = chess.square_rank(king_sq) - chess.square_rank(attacking_square)
    if df == 0 and dr == 0 or king_sq not in after.attacks(attacking_square):
        # A different piece may have given check. Don't infer a skewer from
        # an aligned king unless this attacker actually checks it.
        return None
    diagonal = abs(df) == abs(dr)
    straight = df == 0 or dr == 0
    if not ((diagonal and attacker.piece_type in (chess.BISHOP, chess.QUEEN))
            or (straight and attacker.piece_type in (chess.ROOK, chess.QUEEN))):
        return None
    sf = (df > 0) - (df < 0)
    sr = (dr > 0) - (dr < 0)
    f, r = chess.square_file(king_sq) + sf, chess.square_rank(king_sq) + sr
    while 0 <= f < 8 and 0 <= r < 8:
        sq = chess.square(f, r)
        pc = after.piece_at(sq)
        if pc is not None:
            return sq if pc.color == victim_color and pc.piece_type != chess.KING else None
        f += sf
        r += sr
    return None


def scan_branch(board, root_move, raw, *, branch, max_threat_ply=3):
    """Find mechanisms near the decision with verified subsequent payoffs.

    For the best line, only our moves can demonstrate a winning opportunity.
    For the played line, only the opponent's moves show a refutation.
    """
    if not root_move or root_move not in board.legal_moves:
        return []
    moves = legal_pv(board, raw, first_move=root_move, max_plies=8)
    if len(moves) < 3:
        return []
    replay = board.copy(stack=False)
    snapshots = []
    for i, move in enumerate(moves):
        before = replay.copy(stack=False)
        san = before.san(move)
        replay.push(move)
        snapshots.append((before, replay.copy(stack=False), move, san))
    findings = []
    for ply, (before, after, move, san) in enumerate(snapshots):
        if ply > max_threat_ply:
            break
        is_solver = before.turn == board.turn
        if is_solver != (branch == 'best'):
            continue
        # A direct response matters more than remote follow-ups.
        targets = [(sq, piece) for sq, piece in after.piece_map().items()
                   if piece.color != before.turn and piece.piece_type != chess.KING
                   and sq in after.attacks(move.to_square)]
        large_targets = [(sq, pc) for sq, pc in targets if VALUES[pc.piece_type] >= 3]
        is_check = after.is_check()
        victim = _skewer_victim(after, move.to_square, not before.turn) if is_check else None
        # Captures in the saved continuation by the same side, reasonably
        # close to the threat. The target must be one of the threatened pieces.
        payoff = None
        for j in range(ply + 1, min(len(snapshots), ply + 5)):
            b, a, follow, follow_san = snapshots[j]
            if b.turn != before.turn or not b.is_capture(follow):
                continue
            captured = b.piece_at(follow.to_square)
            if captured is None and b.is_en_passant(follow):
                captured = chess.Piece(chess.PAWN, not b.turn)
            if not captured or captured.color == before.turn:
                continue
            # Do not describe a recapturable trade as material won. A saved
            # next-ply recapture of equal or greater value cancels this
            # *particular* payoff; a different downstream consequence must
            # establish any broader compensation.
            if j + 1 < len(snapshots):
                next_board, _, reply, _ = snapshots[j + 1]
                recaptured = next_board.piece_at(reply.to_square)
                moved = b.piece_at(follow.from_square)
                if (reply.to_square == follow.to_square
                        and next_board.is_capture(reply)
                        and recaptured and moved and
                        VALUES[moved.piece_type] >= VALUES[captured.piece_type]):
                    continue
            # The same piece may remove an opposing defender at the root,
            # allowing us to take what that defender previously guarded.
            removed = before.piece_at(move.to_square) if before.is_capture(move) else None
            defender_removed = bool(
                removed and removed.color != before.turn and
                follow.to_square != move.to_square and
                follow.to_square in before.attacks(move.to_square) and
                before.piece_at(follow.to_square) is not None and
                before.piece_at(follow.to_square).color == removed.color and
                not after.is_attacked_by(removed.color, follow.to_square))
            if (follow.to_square in {sq for sq, _ in targets}
                    or follow.to_square == victim or defender_removed):
                payoff = (follow_san, captured, follow.to_square)
                break
        if not payoff:
            continue
        payoff_san, captured, square = payoff
        removed = before.piece_at(move.to_square) if before.is_capture(move) else None
        was_guarded = bool(
            removed and removed.color != before.turn and
            square != move.to_square and square in before.attacks(move.to_square) and
            before.piece_at(square) is not None and
            before.piece_at(square).color == removed.color and
            not after.is_attacked_by(removed.color, square))
        if victim == square and is_check:
            motif, kind = 'skewer', 'skewers the king and the piece behind it'
        elif (is_check and large_targets) or len(large_targets) >= 2:
            motif, kind = 'fork', 'creates a double attack'
        elif was_guarded:
            motif, kind = 'removal_of_defender', 'removes a defender'
        else:
            # Discovered attack: the mover leaves an origin square that
            # obstructed a line from another slider to the captured target.
            pre_attackers = before.attackers(before.turn, square)
            post_attackers = after.attackers(before.turn, square)
            newly_revealed = any(
                sq != move.to_square and sq not in pre_attackers
                and after.piece_at(sq) is not None
                and after.piece_at(sq).piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)
                for sq in post_attackers)
            if not newly_revealed:
                continue
            motif, kind = 'discovered_attack', 'uncovers an attack'
        if branch == 'best':
            text = (f'{san} {kind}, and {payoff_san} later wins '
                    f'the {chess.piece_name(captured.piece_type)}.')
        else:
            root_name = snapshots[0][3]
            text = (f'In the game you played {root_name}. Your opponent can '
                    f'respond with {san}, which {kind}; '
                    f'{payoff_san} then wins your {chess.piece_name(captured.piece_type)}.')
        findings.append(Refutation(motif, branch, ply, san, payoff_san, text))
    return findings
