"""Board-grounded discovered-line evidence and counterfactual replies.

A revealed sliding attack is distinct from an attack by the moved piece. A
pseudo-legal capture failing to answer a discovered check is *illegal*, while a
legal capture that exposes another valuable target is merely an available
counterfactual; neither is a license to announce a forced win without an engine
or a proven continuation.
"""
from __future__ import annotations

import chess

VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
         chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
SLIDERS = {chess.ROOK, chess.BISHOP, chess.QUEEN}


def _opened_by_vacancy(source: int, target: int, vacated: list[int]) -> int | None:
    """Return the square actually cleared from the ray, if any.

    Ordinary moves clear their origin. En-passant clears the captured pawn's
    square as well; castling clears king AND rook origins. Restricting the test
    to move.from_square silently missed those discovered checks.
    """
    ray = chess.between(source, target)
    return next((sq for sq in vacated if ray & chess.BB_SQUARES[sq]), None)


def revealed_lines(before: chess.Board, move: chess.Move) -> list[dict]:
    """Find NEW attacks on occupied valuable enemy targets from stationary sliders.

    This includes pawn promotions, en-passant removal of a second blocker,
    and castling rook/king moves. An opened ray must actually be new, and the
    slider and valuable target must still be the same pieces.
    """
    if move not in before.legal_moves:
        return []
    side = before.turn
    opponent = not side
    after = before.copy(stack=False)
    after.push(move)
    vacated = [sq for sq in before.piece_map() if after.piece_at(sq) is None]
    result = []
    for source, slider in after.piece_map().items():
        if slider.color != side or slider.piece_type not in SLIDERS:
            continue
        # Exclude the piece which actually made the move; it cannot reveal its
        # own line as a different, stationary attacker.
        if source in (move.from_square, move.to_square):
            continue
        if before.piece_at(source) != slider:
            continue
        for target_sq in after.attacks(source):
            target = after.piece_at(target_sq)
            if not target or target.color != opponent or VALUE[target.piece_type] < 3:
                continue
            if before.piece_at(target_sq) != target:
                continue
            if target_sq in before.attacks(source):
                continue
            opened_square = _opened_by_vacancy(source, target_sq, vacated)
            if opened_square is None:
                continue
            is_check = target.piece_type == chess.KING and source in after.checkers()
            if target.piece_type == chess.KING and not is_check:
                continue
            result.append({
                'kind': 'discovered_check' if is_check else 'discovered_attack',
                'motif': 'discovered_attack', 'ply': 1,
                'revealed_piece': chess.piece_name(slider.piece_type),
                'attacker_square': source, 'target_square': target_sq,
                'target_piece': chess.piece_name(target.piece_type),
                'vacated_square': opened_square,
                'move_origin': move.from_square,
                'destination_square': move.to_square,
                'evidence': (f'The move uncovers your {chess.piece_name(slider.piece_type)} '
                             f'on {chess.square_name(source)}, giving check.')
                if is_check else
                (f'The move uncovers your {chess.piece_name(slider.piece_type)} '
                 f'on {chess.square_name(source)}, attacking the opponent’s '
                 f'{chess.piece_name(target.piece_type)} on {chess.square_name(target_sq)}.'),
            })
    return sorted(result, key=lambda item: (item['kind'] != 'discovered_check',
                                            -{'king': 100, 'queen': 9, 'rook': 5,
                                              'bishop': 3, 'knight': 3}.get(item['target_piece'], 0)))


def discovered_reply_checks(before: chess.Board, move: chess.Move,
                            discoveries: list[dict], max_replies: int = 5) -> list[dict]:
    """Explain tempting captures on the destination, never an invented PV.

    (a) A pseudo-legal capture that does not answer a *discovered check* is
        impossible, since the king remains attacked by the revealed slider.
    (b) After a LEGAL capture of the moved piece, a revealed slider may be able
        to capture the valuable target immediately.  This is a factual option,
        not a claim of a forced win or even favorable material balance.
    """
    if not discoveries or move not in before.legal_moves:
        return []
    after = before.copy(stack=False)
    mover = before.turn
    after.push(move)
    target = after.piece_at(move.to_square)
    if target is None or target.color != mover:
        return []
    checks = [d for d in discoveries if d['kind'] == 'discovered_check']
    findings = []
    attempted = [r for r in after.generate_pseudo_legal_moves(to_mask=chess.BB_SQUARES[move.to_square])
                 if after.is_capture(r)]
    for reply in attempted[:max_replies]:
        if reply in after.legal_moves:
            reply_san = after.san(reply)
            after_reply = after.copy(stack=False)
            after_reply.push(reply)
            if after_reply.is_check():
                continue  # Can't claim a winning follow-up while in check.
            for discovery in discoveries:
                if discovery['kind'] != 'discovered_attack':
                    continue
                followup = chess.Move(discovery['attacker_square'], discovery['target_square'])
                if (followup in after_reply.legal_moves and after_reply.is_capture(followup)):
                    followup_san = after_reply.san(followup)
                    findings.append({
                        'kind': 'legal_capture_allows_followup',
                        'reply_uci': reply.uci(), 'reply_san': reply_san,
                        'followup_uci': followup.uci(), 'followup_san': followup_san,
                        'discovery': discovery, 'ply': 3,
                        'evidence': (f'If the opponent plays {reply_san}, '
                                     f'{followup_san} can capture the '
                                     f'{discovery["target_piece"]} on '
                                     f'{chess.square_name(discovery["target_square"])}.'),
                    })
                    break
            continue
        if not checks:
            continue
        # A pseudo-legal move is not a legal candidate, and may be illegal for
        # many reasons. Confirm the revealed slider STILL checks after it.
        hypothetical = after.copy(stack=False)
        hypothetical.push(reply)
        king = hypothetical.king(not mover)
        if king is None:
            continue
        revealed_checker = next((d for d in checks
                                 if hypothetical.piece_at(d['attacker_square']) is not None
                                 and king in hypothetical.attacks(d['attacker_square'])), None)
        if revealed_checker is None:
            continue
        moving = after.piece_at(reply.from_square)
        findings.append({
            'kind': 'illegal_capture_during_discovered_check',
            'reply_uci': reply.uci(), 'discovery': revealed_checker, 'ply': 2,
            'evidence': (f'The {chess.piece_name(moving.piece_type) if moving else "piece"} '
                         f'on {chess.square_name(reply.from_square)} cannot take your '
                         f'{chess.piece_name(target.piece_type)} on '
                         f'{chess.square_name(move.to_square)}: the discovered check '
                         f'from your {revealed_checker["revealed_piece"]} remains.'),
        })
    return findings
