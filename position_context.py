"""Board-verified causal features shared by lesson assignment and coaching.

We deliberately do not infer an engine variation from a static position.  These
checks identify what changed on the previous ply and what the proposed answer
actually fixes; otherwise the explanation must acknowledge missing evidence.
"""
from __future__ import annotations

from typing import Optional
import chess

from legal_counterfactuals import verified_legal_reply_traps, missed_threat_counterfactual
from discovered_counterfactuals import revealed_lines, discovered_reply_checks
from check_response import check_response

VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def piece_description(board: chess.Board, square: int) -> str:
    piece = board.piece_at(square)
    return (f'{chess.piece_name(piece.piece_type)} on {chess.square_name(square)}'
            if piece else chess.square_name(square))


def can_really_attack(board: chess.Board, attacking_color: chess.Color, square: int) -> bool:
    """Exclude pinned pieces whose apparent attack leaves the pin ray.

    Unlike `is_attacked_by`, this is meant for assessing an actionable capture
    threat. It does not replace full move legality, especially for king moves.
    """
    for source in board.attackers(attacking_color, square):
        if (not board.is_pinned(attacking_color, source)
                or square in board.pin(attacking_color, source)):
            return True
    return False


def pinned_capture_refutations(board: chess.Board, target_square: int) -> list[dict]:
    """Find apparent captures that are ILLEGAL because they expose the king.

    `board` is the position *after* a candidate reply, with the opponent to
    move. Stockfish will never provide these moves in a PV: they are relevant
    to a human's question, 'why can't that piece take mine?'. Never feed these
    moves to the engine or claim they are possible continuations.
    """
    target = board.piece_at(target_square)
    if target is None or target.color == board.turn:
        return []
    king_square = board.king(board.turn)
    if king_square is None:
        return []
    findings = []
    for source, piece in board.piece_map().items():
        if (piece.color != board.turn or piece.piece_type == chess.KING
                or not board.is_pinned(board.turn, source)):
            continue
        mask = chess.BB_SQUARES[source]
        target_mask = chess.BB_SQUARES[target_square]
        for move in board.generate_pseudo_legal_moves(from_mask=mask, to_mask=target_mask):
            if not board.is_capture(move) or board.is_legal(move):
                continue
            # A pinned piece may also have an illegal move for some unrelated
            # reason. Verify that THIS attempted capture reveals king attack.
            hypothetical = board.copy(stack=False)
            hypothetical.push(move)  # Deliberately hypothetical; not a legal PV.
            exposed_king = hypothetical.king(board.turn)
            if (exposed_king is None or
                    not hypothetical.is_attacked_by(not board.turn, exposed_king)):
                continue
            findings.append({
                'piece_square': source,
                'piece': piece,
                'target_square': target_square,
                'king_square': king_square,
                'attempted_move': move,
                'evidence': (f'The {chess.piece_name(piece.piece_type)} on '
                             f'{chess.square_name(source)} cannot capture '
                             f'{piece_description(board, target_square)}: it is pinned '
                             f'to the king on {chess.square_name(king_square)}.'),
            })
    return findings


def inspect_response(
    board: chess.Board,
    best_move: chess.Move,
    played_move: Optional[chess.Move] = None,
    previous_fen: Optional[str] = None,
    opponent_move_uci: Optional[str] = None,
) -> dict:
    """Identify causal evidence, not merely tactical shapes on the board.

    primary_key is intentionally conservative.  In particular a pin's mere
    existence never suffices to make it a primary lesson.
    """
    side, opponent = board.turn, not board.turn
    result = {'last_move': None, 'last_san': None, 'last_change': None,
              'new_pressure': [], 'new_loose': [], 'last_piece_square': None,
              'opponent_exposed': None, 'best_neutralizes': [],
              'best_recaptures': False, 'best_takes_last_piece': False,
              'best_takes_loose': False, 'best_capture': False,
              'best_capture_piece': None, 'played_ignores': [],
              'pin_relevant': [], 'primary_key': None, 'primary_evidence': None,
              'response_reason': None,
              'new_pins_on_us': [], 'new_pins_on_them': [],
              'pin_capture_refutations': [], 'legal_reply_traps': [],
              'discovered_lines': [], 'discovered_unique_lines': [],
              'discovered_reply_checks': [],
              'last_discovered_lines': [],
              'played_counterfactual': None, 'check_evasion': None,
              'context_motifs': [], 'prompt_motifs': [], 'response_motifs': [],
              'context_facts': [], 'prompt_facts': [], 'response_facts': []}
    if best_move not in board.legal_moves:
        return result
    before = None
    try:
        if previous_fen and opponent_move_uci:
            predecessor = chess.Board(previous_fen)
            last = chess.Move.from_uci(opponent_move_uci)
            if last in predecessor.legal_moves:
                after_last = predecessor.copy(stack=False)
                after_last.push(last)
                if (after_last.board_fen() == board.board_fen() and
                        after_last.turn == board.turn and
                        after_last.castling_rights == board.castling_rights):
                    before = predecessor
                    result['last_move'] = last
                    result['last_san'] = predecessor.san(last)
                    result['last_piece_square'] = last.to_square
                    result['last_discovered_lines'] = revealed_lines(predecessor, last)
    except (ValueError, TypeError):
        before = None

    if before is not None:
        last = result['last_move']
        newly_attacked = []
        newly_loose = []
        for sq, piece in board.piece_map().items():
            if piece.color != side or piece.piece_type == chess.KING:
                continue
            # Only count a change introduced by the opponent's last move.
            if (can_really_attack(board, opponent, sq)
                    and not can_really_attack(before, opponent, sq)):
                newly_attacked.append(sq)
                if not can_really_attack(board, side, sq):
                    newly_loose.append(sq)
        newly_attacked.sort(key=lambda sq: VALUES[board.piece_type_at(sq)], reverse=True)
        newly_loose.sort(key=lambda sq: VALUES[board.piece_type_at(sq)], reverse=True)
        result['new_pressure'] = newly_attacked
        result['new_loose'] = newly_loose
        for color, key in ((side, 'new_pins_on_us'), (opponent, 'new_pins_on_them')):
            result[key] = [sq for sq, piece in board.piece_map().items()
                           if piece.color == color and piece.piece_type != chess.KING
                           and board.is_pinned(color, sq)
                           and not before.is_pinned(color, sq)]
        moved = board.piece_at(last.to_square)
        if moved and moved.color == opponent and moved.piece_type != chess.KING:
            if can_really_attack(board, side, last.to_square) and not can_really_attack(board, opponent, last.to_square):
                result['opponent_exposed'] = last.to_square
        captured = before.piece_at(last.to_square)
        if before.is_en_passant(last):
            captured = chess.Piece(chess.PAWN, side)
        if captured and captured.color == side:
            result['last_change'] = f'The opponent just captured your {chess.piece_name(captured.piece_type)} on {chess.square_name(last.to_square)}.'
        elif board.is_check():
            result['last_change'] = f'The opponent’s {result["last_san"]} gave check.'
        elif newly_loose:
            result['last_change'] = f'The opponent’s {result["last_san"]} newly attacked your undefended {piece_description(board, newly_loose[0])}.'
        elif newly_attacked:
            result['last_change'] = f'The opponent’s {result["last_san"]} added pressure to your {piece_description(board, newly_attacked[0])}.'
        elif result['opponent_exposed'] is not None:
            result['last_change'] = f'The opponent’s {result["last_san"]} left their {piece_description(board, last.to_square)} exposed.'
        elif result['new_pins_on_us']:
            result['last_change'] = (f'The opponent’s {result["last_san"]} pinned your '
                                     f'{piece_description(board, result["new_pins_on_us"][0])} to the king.')
        elif result['new_pins_on_them']:
            result['last_change'] = (f'The opponent’s {result["last_san"]} left their '
                                     f'{piece_description(board, result["new_pins_on_them"][0])} pinned to the king.')

    if result['last_discovered_lines']:
        result['context_motifs'].append('discovered_attack')
        for discovery in result['last_discovered_lines']:
            source = chess.square_name(discovery['attacker_square'])
            target = chess.square_name(discovery['target_square'])
            if discovery['kind'] == 'discovered_check':
                result['context_facts'].append(
                    f'The opponent’s last move uncovered a check from their '
                    f'{discovery["revealed_piece"]} on {source}.')
            else:
                result['context_facts'].append(
                    f'The opponent’s last move uncovered their '
                    f'{discovery["revealed_piece"]} on {source}, attacking your '
                    f'{discovery["target_piece"]} on {target}.')
        if result['last_discovered_lines'][0]['kind'] == 'discovered_check':
            result['prompt_facts'].append('The previous move uncovered a check you must answer.')
    if result['last_change']:
        result['context_facts'].append(result['last_change'])
    if result['new_pins_on_us'] or result['new_pins_on_them']:
        result['context_motifs'].append('pin')
        for key, owner in (('new_pins_on_us', 'your'), ('new_pins_on_them', 'the opponent’s')):
            for square in result[key]:
                detail = f'The last move pinned {owner} {piece_description(board, square)} to the king.'
                if detail not in result['context_facts']:
                    result['context_facts'].append(detail)
    if board.is_check():
        if 'king_safety' not in result['context_motifs'] and before is not None:
            result['context_motifs'].append('king_safety')
        result['prompt_facts'].append('Your king is in check and must be addressed.')
        result['prompt_motifs'].append('king_safety')
    if result['new_loose']:
        result['context_motifs'].append('loose_piece_awareness')
        result['prompt_facts'].append('A newly attacked piece is undefended.')
        result['prompt_motifs'].append('loose_piece_awareness')
    elif result['new_pressure']:
        result['context_motifs'].append('threat_awareness')
        result['prompt_facts'].append('The last move created an immediate material threat.')
        result['prompt_motifs'].append('threat_awareness')
    if result['opponent_exposed'] is not None:
        result['context_motifs'].append('capture_loose_piece')
    if result['new_pins_on_them']:
        result['prompt_facts'].append('The opponent has a piece pinned to its king that may limit defensive captures.')
        result['prompt_motifs'].append('pin')

    best_piece = board.piece_at(best_move.from_square)
    captured = board.piece_at(best_move.to_square)
    if board.is_en_passant(best_move):
        captured = chess.Piece(chess.PAWN, opponent)
    after = board.copy(stack=False)
    after.push(best_move)
    result['check_evasion'] = check_response(board, best_move)
    if result['check_evasion']:
        response_key = result['check_evasion']['motif']
        result['response_motifs'].append(response_key)
        result['response_facts'].append(result['check_evasion']['evidence'])
    result['discovered_lines'] = revealed_lines(board, best_move)
    played_discoveries = (revealed_lines(board, played_move)
                          if played_move is not None and played_move in board.legal_moves else [])
    played_covered = {(d['attacker_square'], d['target_square'], d['kind'])
                      for d in played_discoveries}
    result['discovered_unique_lines'] = [d for d in result['discovered_lines']
        if (d['attacker_square'], d['target_square'], d['kind']) not in played_covered]
    result['discovered_reply_checks'] = discovered_reply_checks(
        board, best_move, result['discovered_lines'])
    if result['discovered_unique_lines']:
        result['response_motifs'].append('discovered_attack')
        result['response_facts'].append(result['discovered_unique_lines'][0]['evidence'])
    # A tempting legal capture is NOT proof of a tactical refutation. Only
    # include one if a fully legal, immediate mate demonstrates the error.
    result['legal_reply_traps'] = verified_legal_reply_traps(board, best_move)
    # The moved piece may deliver a discovered check. In that case a pinned
    # defender's apparent capture of the actual checking piece is just as
    # instructive as an attempted capture of the newly moved piece.
    apparent_targets = [best_move.to_square]
    if after.is_check():
        apparent_targets += [square for square in after.checkers()
                             if square != best_move.to_square]
    for target in apparent_targets:
        result['pin_capture_refutations'].extend(pinned_capture_refutations(after, target))
    if result['pin_capture_refutations']:
        result['response_facts'].append(result['pin_capture_refutations'][0]['evidence'])
        result['response_motifs'].append('pin')
    result['best_capture'] = board.is_capture(best_move)
    result['best_capture_piece'] = captured
    result['best_takes_last_piece'] = bool(
        result['best_capture'] and result['last_piece_square'] == best_move.to_square
    )
    result['best_recaptures'] = bool(result['best_takes_last_piece'] and before is not None
                                     and before.piece_at(result['last_piece_square']) is not None)
    result['best_takes_loose'] = bool(result['best_capture'] and captured
        and VALUES[captured.piece_type] >= 3
        and not can_really_attack(board, opponent, best_move.to_square))

    for sq in result['new_pressure']:
        attacked_after = (after.piece_at(sq) is not None and after.piece_at(sq).color == side
                          and can_really_attack(after, opponent, sq))
        newly_defended = (after.piece_at(sq) is not None and after.piece_at(sq).color == side
                          and can_really_attack(after, side, sq)
                          and not can_really_attack(board, side, sq))
        if not attacked_after or newly_defended:
            result['best_neutralizes'].append(sq)

    if played_move is not None and played_move in board.legal_moves:
        played_after = board.copy(stack=False)
        played_after.push(played_move)
        for sq in result['new_loose']:
            if (played_after.piece_at(sq) is not None
                and played_after.piece_at(sq).color == side
                and can_really_attack(played_after, opponent, sq)
                and not can_really_attack(played_after, side, sq)):
                result['played_ignores'].append(sq)

    result['played_counterfactual'] = missed_threat_counterfactual(
        board, best_move, played_move, result)

    # A pin must be newly created AND restrain a currently vulnerable, valuable
    # enemy piece; otherwise it is only a background positional motif.
    for sq, piece in after.piece_map().items():
        if piece.color != opponent or VALUES[piece.piece_type] < 3 or piece.piece_type == chess.KING:
            continue
        if (after.is_pinned(opponent, sq) and not board.is_pinned(opponent, sq)
                and after.is_attacked_by(side, sq) and not after.is_attacked_by(opponent, sq)):
            result['pin_relevant'].append(sq)

    # A double attack qualifies as the lesson only when TWO meaningful targets
    # are newly vulnerable to the moved piece. A geometric attack on defended
    # pieces is not enough evidence for a decisive fork.
    fork_targets = []
    moved = after.piece_at(best_move.to_square)
    if moved and moved.color == side and not after.is_attacked_by(opponent, best_move.to_square):
        for sq in after.attacks(best_move.to_square):
            target = after.piece_at(sq)
            if (target and target.color == opponent and target.piece_type != chess.KING
                    and VALUES[target.piece_type] >= 3
                    and not after.is_attacked_by(opponent, sq)):
                fork_targets.append(sq)
    fork_targets.sort(key=lambda sq: VALUES[after.piece_type_at(sq)], reverse=True)
    result['fork_targets'] = fork_targets

    if after.is_checkmate():
        # The caller distinguishes mating net from specific back-rank cases.
        result['primary_key'] = 'mating_net'
        result['response_reason'] = 'delivers immediate checkmate'
    elif board.is_check():
        evasion = result['check_evasion']
        result['primary_key'] = evasion['motif'] if evasion else 'king_safety'
        result['primary_evidence'] = (evasion['evidence'] if evasion else
                                      'The correct move legally resolves the check.')
        result['response_reason'] = 'answers the check'
    elif result['best_neutralizes'] and (result['new_loose'] or result['played_ignores']):
        relevant = result['best_neutralizes'][0]
        result['primary_key'] = 'loose_piece_awareness' if relevant in result['new_loose'] else 'threat_awareness'
        result['primary_evidence'] = f'The answer directly addresses the new threat against {piece_description(board, relevant)}.'
        result['response_reason'] = f'addresses the new threat against your {piece_description(board, relevant)}'
    elif result['best_recaptures']:
        result['primary_key'] = 'missed_capture'
        result['primary_evidence'] = 'The best move immediately recaptures the piece that made the opponent’s last capture.'
        result['response_reason'] = 'recaptures the piece from the opponent’s previous move'
    elif result['best_takes_last_piece'] and result['new_pressure']:
        result['primary_key'] = 'defensive_resource'
        result['primary_evidence'] = 'The best move removes the piece that created the new pressure.'
        result['response_reason'] = 'captures the piece that created the new threat'
    elif result['best_takes_loose']:
        result['primary_key'] = 'capture_loose_piece'
        result['primary_evidence'] = f'The best move captures an undefended {chess.piece_name(captured.piece_type)} on {chess.square_name(best_move.to_square)}.'
        result['response_reason'] = f'captures the undefended {chess.piece_name(captured.piece_type)} on {chess.square_name(best_move.to_square)}'
    elif result['best_capture'] and captured is not None and VALUES[captured.piece_type] >= 3:
        result['primary_key'] = 'missed_capture'
        result['primary_evidence'] = 'The answer is a concrete capture; its longer-term material value depends on the reply.'
        result['response_reason'] = f'captures the {chess.piece_name(captured.piece_type)} on {chess.square_name(best_move.to_square)}'
    elif len(fork_targets) >= 2:
        result['primary_key'] = 'fork'
        targets = ' and '.join(piece_description(after, sq) for sq in fork_targets[:2])
        result['primary_evidence'] = f'The answer simultaneously threatens two currently undefended targets: {targets}.'
        result['response_reason'] = f'creates a double attack on the {targets}'
    elif after.is_check():
        result['response_reason'] = 'gives check and forces the opponent to respond'
    if result['discovered_unique_lines'] and result['discovered_unique_lines'][0]['kind'] == 'discovered_check' \
            and result['primary_key'] is None:
        result['primary_key'] = 'discovered_attack'
        result['primary_evidence'] = result['discovered_unique_lines'][0]['evidence']
    if result['response_reason']:
        result['response_facts'].insert(0, result['response_reason'])
    if result['primary_key'] and result['primary_key'] not in result['response_motifs']:
        result['response_motifs'].insert(0, result['primary_key'])
    return result
