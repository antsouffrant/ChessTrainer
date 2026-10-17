from __future__ import annotations

from typing import Iterable, Mapping, Optional

import chess

from position_context import inspect_response, piece_description
from decision_context import decision_facts, unanswered_mate_threat
from immediate_decision import immediate_decision
from root_explanation import root_move_impact
from branch_diagnostics import decisive_contrast
from critical_moments import (critical_decision_evidence, decode_critical_evidence,
                              critical_explanation)
from pv_reasoning import comparative_insight, fork_evidence, legal_pv
from narrative_editor import mate_explanation, polish_comparison, concise
from semantic_coaching import causal_coaching

COACHING_VERSION = 'rules-v28-evidence-and-purpose'

PIECE_NAMES = {
    chess.PAWN: 'pawn',
    chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop',
    chess.ROOK: 'rook',
    chess.QUEEN: 'queen',
    chess.KING: 'king',
}

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


def _piece_name(piece: Optional[chess.Piece]) -> str:
    return PIECE_NAMES.get(piece.piece_type, 'piece') if piece else 'piece'


def _piece_value(piece: Optional[chess.Piece]) -> int:
    return PIECE_VALUES.get(piece.piece_type, 0) if piece else 0


def _square(square: Optional[int]) -> str:
    return chess.square_name(square) if square is not None else ''


def _human_list(items: list[str]) -> str:
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f'{items[0]} and {items[1]}'
    return ', '.join(items[:-1]) + f', and {items[-1]}'


def _safe_move(board: chess.Board, uci: Optional[str]) -> Optional[chess.Move]:
    if not uci:
        return None
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def _concept_keys(labels: Optional[Iterable]) -> list[str]:
    keys = []
    for label in labels or []:
        key = getattr(label, 'key', None)
        if key is None and isinstance(label, Mapping):
            key = label.get('key') or label.get('concept_key')
        if key is None:
            try:
                key = label['key']
            except (KeyError, TypeError, IndexError):
                try:
                    key = label['concept_key']
                except (KeyError, TypeError, IndexError):
                    key = None
        if key and str(key) not in keys:
            keys.append(str(key))
    return keys


def _target_phrase(board: chess.Board, square: int) -> str:
    piece = board.piece_at(square)
    if piece is None:
        return _square(square)
    return f'{_piece_name(piece)} on {_square(square)}'


def _attacked_valuable(board: chess.Board, attacker: chess.Color, victim: chess.Color) -> list[tuple[int, chess.Piece]]:
    result = []
    for square, piece in board.piece_map().items():
        if piece.color != victim or piece.piece_type == chess.KING:
            continue
        if board.is_attacked_by(attacker, square):
            result.append((square, piece))
    result.sort(key=lambda item: _piece_value(item[1]), reverse=True)
    return result


def _last_move_features(board: chess.Board, previous_fen: Optional[str], opponent_move_uci: Optional[str]) -> dict:
    result = {
        'move': None,
        'moved_piece': None,
        'moved_to': None,
        'captured_piece': None,
        'captured_square': None,
        'newly_attacked': [],
        'attacked_now': [],
    }
    if not previous_fen or not opponent_move_uci:
        return result

    try:
        before = chess.Board(previous_fen)
        move = chess.Move.from_uci(opponent_move_uci)
    except (ValueError, TypeError):
        return result
    if move not in before.legal_moves:
        return result

    opponent = before.turn
    user = not opponent
    moved_piece = before.piece_at(move.from_square)
    captured_piece = before.piece_at(move.to_square)
    before_attacked = {square for square, _ in _attacked_valuable(before, opponent, user)}
    after = before.copy(stack=False)
    after.push(move)
    after_attacked = _attacked_valuable(after, opponent, user)
    newly_attacked = [(square, piece) for square, piece in after_attacked if square not in before_attacked]

    result.update({
        'move': move,
        'moved_piece': moved_piece,
        'moved_to': move.to_square,
        'captured_piece': captured_piece if captured_piece and captured_piece.color == user else None,
        'captured_square': move.to_square if captured_piece and captured_piece.color == user else None,
        'newly_attacked': newly_attacked,
        'attacked_now': after_attacked,
    })
    return result


def _best_move_features(board: chess.Board, best: chess.Move) -> dict:
    side = board.turn
    opponent = not side
    moving_piece = board.piece_at(best.from_square)
    captured_piece = board.piece_at(best.to_square)
    from_attacked = board.is_attacked_by(opponent, best.from_square) if moving_piece else False

    before_defended = set()
    if moving_piece:
        for square in board.attacks(best.from_square):
            piece = board.piece_at(square)
            if piece and piece.color == side and piece.piece_type != chess.KING:
                before_defended.add(square)

    after = board.copy(stack=False)
    after.push(best)
    moved_after = after.piece_at(best.to_square)
    to_attacked = after.is_attacked_by(opponent, best.to_square) if moved_after else False

    after_targets = []
    after_defended = set()
    if moved_after:
        for square in after.attacks(best.to_square):
            piece = after.piece_at(square)
            if piece and piece.color == opponent and (piece.piece_type == chess.KING or _piece_value(piece) >= 3):
                after_targets.append((square, piece))
            elif piece and piece.color == side and piece.piece_type != chess.KING:
                after_defended.add(square)
    after_targets.sort(key=lambda item: _piece_value(item[1]), reverse=True)

    queen_exchange = bool(
        moving_piece and captured_piece
        and moving_piece.piece_type == chess.QUEEN
        and captured_piece.piece_type == chess.QUEEN
    )

    return {
        'after': after,
        'moving_piece': moving_piece,
        'captured_piece': captured_piece,
        'capture': board.is_capture(best),
        'check': after.is_check(),
        'checkmate': after.is_checkmate(),
        'from_attacked': from_attacked,
        'to_safe': not to_attacked,
        'new_targets': after_targets,
        'newly_defended': sorted(after_defended - before_defended),
        'queen_exchange': queen_exchange,
    }


def _opponent_pressure_prompt(board: chess.Board, last: dict) -> Optional[str]:
    moved_piece = last.get('moved_piece')
    moved_to = last.get('moved_to')
    new = last.get('newly_attacked') or []
    attacked_now = last.get('attacked_now') or []
    important_new = [(sq, pc) for sq, pc in new if _piece_value(pc) >= 3]
    important_now = [(sq, pc) for sq, pc in attacked_now if _piece_value(pc) >= 3]

    if len(important_new) >= 2:
        targets = [_target_phrase(board, sq) for sq, _ in important_new[:3]]
        if moved_piece and moved_to is not None:
            return (
                f"The opponent's {_piece_name(moved_piece)} on {_square(moved_to)} has created simultaneous pressure on your "
                f"{_human_list(targets)}. Find one move that resolves the immediate threats."
            )
        return f"The opponent's last move now attacks your {_human_list(targets)}. Find one move that solves both problems."

    if important_new:
        sq, piece = important_new[0]
        actor = f"{_piece_name(moved_piece)} on {_square(moved_to)}" if moved_piece and moved_to is not None else 'last move'
        return (
            f"The opponent's {actor} now attacks your {_piece_name(piece)} on {_square(sq)}. "
            'Find a response that deals with the threat while keeping your position active.'
        )

    if len(important_now) >= 2:
        targets = [_target_phrase(board, sq) for sq, _ in important_now[:3]]
        return f"Several important pieces are under pressure: your {_human_list(targets)}. Look for a move that solves more than one problem at once."

    captured = last.get('captured_piece')
    if captured is not None:
        return (
            f"The opponent just captured your {_piece_name(captured)} on {_square(last.get('captured_square'))}. "
            'Check whether the best response is a recapture, a stronger counter-threat, or a simplifying move.'
        )
    return None


def _concept_prompt(concept_keys: list[str]) -> Optional[str]:
    prompts = {
        'mate_defense': 'Your king is facing a mating threat. Identify the forcing idea first and find the move that stops it.',
        'threat_awareness': 'The opponent has a concrete threat. Identify exactly what becomes vulnerable if you make a slow move.',
        'loose_piece_awareness': 'One of your valuable pieces is tactically loose. Find a move that protects it, removes the attacker, or creates a concrete counter-threat.',
        'dont_hang_pieces': 'Before moving, check whether your piece can be captured for free on its destination square.',
        'lost_material': 'Consider what material the game move loses and whether a tactical defense or alternative avoids the loss.',
        'capture_loose_piece': 'Look for an enemy piece you can already capture without an effective recapture.',
        'defensive_resource': 'This position needs an active defensive resource, not a passive waiting move. Look for checks, trades, or counter-threats.',
        'fork': 'Look for a move that attacks two important targets at the same time.',
        'pin': 'The alignment of a valuable piece and the piece behind it matters here. Look for a move that exploits that geometry.',
        'skewer': 'A forcing line can move a valuable front piece and expose the piece behind it.',
        'removal_of_defender': 'A key target is protected by one important defender. Consider whether removing that defender changes the position.',
        'overloaded_defender': 'One defender is doing too many jobs. Look for a move that forces it to abandon one responsibility.',
        'simplification': 'A favorable exchange can reduce the opponent’s tactical chances. Consider whether trading pieces solves the immediate problem.',
        'counterattack': 'You are under pressure, but you may not need to retreat. Look for a forcing counter-threat.',
        'attack_building': 'The opponent’s position can be put under immediate pressure. Look for a forcing move that keeps the initiative.',
        'piece_coordination': 'Your pieces can work together more effectively. Look for a move that improves both pressure and protection.',
        'piece_activity': 'One of your pieces can become much more useful on a better square. Find the move that improves its scope.',
        'passed_pawn': 'The pawn race is the central issue. Decide whether creating or advancing a passed pawn is urgent.',
        'king_activity': 'In this simplified position, the king is a fighting piece. Look for the most active king move.',
        'opposition_zugzwang': 'King placement and spare tempi decide this ending. Look for the move that takes the opposition or forces a concession.',
        'calculation': 'Start with checks, captures, and direct threats. Compare the opponent’s best reply before committing.',
    }
    for key in concept_keys:
        if key in prompts:
            return prompts[key]
    return None


def _specific_solution_sentence(board: chess.Board, best: chess.Move, features: dict, last: dict, concept_keys: list[str], best_san: str, category: str = '', mate_before: Optional[int] = None) -> str:
    moving_piece = features['moving_piece']
    captured_piece = features['captured_piece']
    after = features['after']
    source = _square(best.from_square)
    destination = _square(best.to_square)

    if features['checkmate']:
        if 'back_rank_mate' in concept_keys and concept_keys[0] == 'back_rank_mate':
            return f'{best_san} is a back-rank checkmate. The king is trapped behind its own defenses, with no legal escape or block.'
        return f'{best_san} is checkmate: the king has no legal escape, capture, or blocking response.'

    # The engine stored a mate score, but did not store the full PV. Refer to
    # the confirmed forcing result, not an invented line of moves.
    if category == 'missed_checkmate' and mate_before is not None and mate_before > 0:
        return mate_explanation(best_san, None, mate_in=mate_before, verified=True)
    if category == 'allowed_checkmate' and concept_keys and concept_keys[0] == 'mate_defense':
        return f'{best_san} stops the mating threat.'

    # Lead with the actual primary tactical mechanism before generic captures,
    # piece movement or a check that happens to accompany the main idea.
    primary = concept_keys[0] if concept_keys else ''
    if primary == 'fork' and len(features['new_targets']) >= 2:
        targets = [_target_phrase(after, sq) for sq, _ in features['new_targets'][:2]]
        return f'{best_san} creates a double attack on the opponent’s {_human_list(targets)}.'
    if primary == 'pin':
        return f'{best_san} creates or exploits a pin, restricting a piece that cannot move without exposing a more valuable target.'
    if primary == 'skewer':
        return f'{best_san} creates a skewer: the front target must move and expose the piece behind it.'
    if primary == 'discovered_attack':
        return f'{best_san} uncovers an attack from another piece; the moved piece is not the source of the discovered threat.'

    if features['queen_exchange']:
        attacked = [(sq, pc) for sq, pc in (last.get('newly_attacked') or last.get('attacked_now') or []) if _piece_value(pc) >= 3]
        if attacked:
            targets = [_target_phrase(board, sq) for sq, _ in attacked[:3]]
            return f'{best_san} trades queens, removing the opponent’s queen and resolving the pressure on your {_human_list(targets)}.'
        return f'{best_san} trades queens, reducing the tactical danger and simplifying the position.'

    if features['capture'] and captured_piece is not None:
        # The sampled reply is often a straightforward recapture. Recognize
        # an exchange before claiming this capture wins material or builds a
        # lasting attack from a piece that immediately leaves the board.
        reply = features.get('principal_reply')
        if reply is not None and reply.get('recaptures'):
            balanced = (moving_piece is not None and
                        abs(_piece_value(moving_piece) - _piece_value(captured_piece)) <= 1)
            if balanced:
                return (f'{best_san} trades your {_piece_name(moving_piece)} for the '
                        f'opponent’s {_piece_name(captured_piece)}.')
            return (f'{best_san} takes the {_piece_name(captured_piece)}, but the opponent '
                    f'can recapture your {_piece_name(moving_piece)}.')
        last_move = last.get('move')
        if last_move is not None and best.to_square == last_move.to_square:
            return f'{best_san} removes the {_piece_name(captured_piece)} that just created the threat, immediately neutralizing the opponent’s last move.'
        if _piece_value(captured_piece) >= 3 and features['to_safe']:
            return f'{best_san} captures the {_piece_name(captured_piece)} on {destination} without an immediate recapture of the moving piece.'
        if _piece_value(captured_piece) >= 3:
            return f'{best_san} captures the {_piece_name(captured_piece)} on {destination}.'
        return f'{best_san} takes the {_piece_name(captured_piece)} on {destination}.'

    if features['from_attacked'] and features['to_safe']:
        targets = features['new_targets']
        if targets:
            target_sq, target_piece = targets[0]
            return (
                f'{best_san} moves the {_piece_name(moving_piece)} out of danger from {source} to {destination} '
                f'and immediately attacks the opponent’s {_piece_name(target_piece)} on {_square(target_sq)}.'
            )
        return f'{best_san} moves the threatened {_piece_name(moving_piece)} from {source} to the safer square {destination} without conceding the position.'

    if features['check']:
        targets = [(sq, pc) for sq, pc in features['new_targets'] if pc.piece_type != chess.KING]
        if targets:
            sq, piece = targets[0]
            return f'{best_san} gives check and simultaneously attacks the {_piece_name(piece)} on {_square(sq)}, forcing the opponent to respond.'
        return f'{best_san} gives check, taking the initiative and forcing the opponent to answer before carrying out another plan.'

    if 'fork' in concept_keys and len(features['new_targets']) >= 2:
        targets = [_target_phrase(after, sq) for sq, _ in features['new_targets'][:2]]
        return f'{best_san} creates a double attack on the opponent’s {_human_list(targets)}, so both threats cannot be answered at once.'

    if concept_keys and concept_keys[0] == 'pin':
        return f'{best_san} creates or exploits a pin, restricting a defender because moving it would expose a more valuable piece or the king.'
    if concept_keys and concept_keys[0] == 'skewer':
        return f'{best_san} creates a skewer: the front target must move, exposing the valuable piece behind it.'
    if concept_keys and concept_keys[0] == 'removal_of_defender':
        return f'{best_san} removes a key defender, leaving the remaining target unable to rely on its previous protection.'
    if concept_keys and concept_keys[0] == 'overloaded_defender':
        return f'{best_san} exploits an overloaded defender that cannot protect all of its important targets at once.'

    if features['newly_defended']:
        defended = [_target_phrase(after, sq) for sq in features['newly_defended'][:2]]
        targets = features['new_targets']
        if targets:
            sq, pc = targets[0]
            return (
                f'{best_san} improves coordination: the {_piece_name(moving_piece)} on {destination} protects your {_human_list(defended)} '
                f'while adding pressure to the opponent’s {_piece_name(pc)} on {_square(sq)}.'
            )
        return f'{best_san} improves coordination by placing the {_piece_name(moving_piece)} on {destination}, where it adds protection to your {_human_list(defended)}.'

    if features['new_targets']:
        sq, piece = features['new_targets'][0]
        return f'{best_san} repositions the {_piece_name(moving_piece)} to {destination}, where it creates direct pressure on the opponent’s {_piece_name(piece)} on {_square(sq)}.'

    concept_fallback = {
        'simplification': f'{best_san} reduces the tactical complexity, making the resulting position easier to defend or convert.',
        'mate_defense': f'{best_san} addresses the mating threat before the opponent can continue the attack.',
        'defensive_resource': f'{best_san} is the active defensive resource that keeps the position playable.',
        'counterattack': f'{best_san} answers the opponent’s threat with a forcing counter-threat instead of a passive retreat.',
        'attack_building': f'{best_san} increases the pressure and keeps the initiative with your pieces moving toward active squares.',
        'king_activity': f'{best_san} activates the king on {destination}, where it can directly influence the endgame.',
        'opposition_zugzwang': f'{best_san} improves the king geometry and uses tempo to force the opposing king into a worse placement.',
        'passed_pawn': f'{best_san} improves the pawn race by creating or advancing the passed pawn.',
        'piece_activity': f'{best_san} moves the {_piece_name(moving_piece)} from {source} to {destination}, increasing its useful influence over the position.',
        'piece_coordination': f'{best_san} improves how your pieces support one another and contest the key squares.',
        'king_safety': f'{best_san} addresses the immediate king-safety problem before pursuing a slower plan.',
        'calculation': f'{best_san} is the accurate move because it survives the opponent’s forcing replies while the game move does not.',
    }
    for key in concept_keys:
        if key in concept_fallback:
            return concept_fallback[key]

    return f'{best_san} moves the {_piece_name(moving_piece)} to {destination}. Review which squares it now attacks or defends compared with the game move.'


def _observable_fallback(board: chess.Board, best: chess.Move, played: Optional[chess.Move], best_san: str) -> str:
    """Use actual squares and changing control, not qualitative engine praise."""
    piece = board.piece_at(best.from_square)
    if not piece:
        return f'{best_san} is the recommended move.'
    before = set(board.attacks(best.from_square))
    after = board.copy(stack=False)
    after.push(best)
    new_square_piece = after.piece_at(best.to_square)
    after_control = set(after.attacks(best.to_square)) if new_square_piece else set()
    newly = after_control - before
    central = [sq for sq in newly if chess.square_file(sq) in (2, 3, 4, 5)
               and chess.square_rank(sq) in (2, 3, 4, 5)]
    if central:
        sq = chess.square_name(sorted(central)[0])
        return (f'{best_san} moves the {chess.piece_name(piece.piece_type)} to '
                f'{chess.square_name(best.to_square)}, adding control of {sq}. '
                'This is a concrete change in the squares your piece influences.')
    if piece.piece_type == chess.PAWN:
        return (f'{best_san} advances the pawn to {chess.square_name(best.to_square)}, '
                'changing which squares it controls and which pawn exchanges are available.')
    if piece.piece_type == chess.KING:
        return (f'{best_san} moves the king to {chess.square_name(best.to_square)}, '
                'changing its access to nearby squares.')
    if newly:
        sq = chess.square_name(sorted(newly)[0])
        return (f'{best_san} puts the {chess.piece_name(piece.piece_type)} on '
                f'{chess.square_name(best.to_square)}, where it newly controls {sq}.')
    alternative = board.san(played) if played and played in board.legal_moves else 'the game move'
    return (f'{best_san} keeps the {chess.piece_name(piece.piece_type)} on '
            f'{chess.square_name(best.to_square)} instead of {alternative}.')


def generate_coaching_text(
    *,
    fen: str,
    previous_fen: Optional[str],
    opponent_move_uci: Optional[str],
    opponent_move_san: Optional[str],
    played_move_uci: Optional[str],
    played_move_san: Optional[str],
    best_move_uci: str,
    best_move_san: Optional[str],
    category: str,
    labels: Optional[Iterable] = None,
    mate_before: Optional[int] = None,
    best_pv_uci=None,
    played_pv_uci=None,
    alternative_pvs_json=None,
    eval_before_cp=None,
    eval_after_cp=None,
    critical_events_json=None,
    explanatory_lines_json=None,
) -> tuple[str, str]:
    """Generate a concrete pre-solve coaching prompt and post-solve explanation."""
    board = chess.Board(fen)
    concept_keys = _concept_keys(labels)
    last = _last_move_features(board, previous_fen, opponent_move_uci)
    best = _safe_move(board, best_move_uci)
    played = _safe_move(board, played_move_uci)
    context = (inspect_response(board, best, played, previous_fen, opponent_move_uci)
               if best is not None else None)

    # ---------- spoiler-conscious prompt ----------
    if board.is_check():
        prompt = 'Your king is in check. Find a legal response that neutralizes the check without giving up more than necessary.'
    else:
        # Mate threats take priority over loose-piece geometry. A threat is
        # established by a legal mate-in-one after an unanswered (null) turn;
        # this does not mean the mate is forced against all defenses.
        immediate_mate_threat = unanswered_mate_threat(board)
        if immediate_mate_threat:
            prompt = ('The opponent threatens checkmate on the next move if you '
                      'ignore the threat. Look for a defense, forcing check, or counterattack.')
        # Only explain an opponent threat as newly created when the preceding
        # board state demonstrates it; older pressure may just be incidental.
        if not immediate_mate_threat and context and context.get('last_discovered_lines') and \
                context['last_discovered_lines'][0]['kind'] == 'discovered_attack':
            line = context['last_discovered_lines'][0]
            prompt = (f'The last move revealed an attack on your '
                      f'{line["target_piece"]} on {chess.square_name(line["target_square"])}. '
                      'Find the best response.')
        elif not immediate_mate_threat and context and context['new_loose']:
            sq = context['new_loose'][0]
            prompt = f'The last move left your {piece_description(board, sq)} newly attacked and undefended. How should you respond?'
        elif not immediate_mate_threat and context and context['new_pressure']:
            sq = context['new_pressure'][0]
            prompt = f'The last move added pressure to your {piece_description(board, sq)}. Decide whether you must defend, trade, or counterattack.'
        elif not immediate_mate_threat and context and context['new_pins_on_us']:
            sq = context['new_pins_on_us'][0]
            prompt = (f'The opponent’s last move pinned your {piece_description(board, sq)}. '
                      'Check which captures and defenses are still legal before deciding how to respond.')
        elif not immediate_mate_threat and context and context['new_pins_on_them']:
            prompt = ('The opponent’s last move has left a piece pinned to its king. '
                      'Look for a forcing move that takes advantage of the restricted defense.')
        else:
            if not immediate_mate_threat:
                prompt = None
        if prompt is None:
            if category == 'allowed_checkmate':
                prompt = 'The opponent has a direct mating threat. Identify the threat and find the move that stops it now.'
            elif category == 'missed_checkmate':
                prompt = 'The opposing king is vulnerable. Calculate every forcing check before considering a quieter move.'
            elif category == 'threw_away_win':
                prompt = 'You are winning, but the position contains a tactical danger. Find the move that keeps the win without allowing counterplay.'
            elif category in {'blundered_draw', 'blundered_into_loss'}:
                prompt = 'The position is still defensible. Identify the opponent’s concrete threat and find the resource that keeps you in the game.'
            elif category in {'squandered_advantage', 'blundered_win'}:
                prompt = 'You have the better position. Find the move that keeps the pressure or converts it into something concrete.'
            elif category == 'excellent_move':
                prompt = 'You found an unusually strong move here in the game. Reconstruct the idea: what move stands out from the natural alternatives?'
            elif category == 'brilliant_move':
                prompt = 'You found a highly unique or creative move here. Look beyond the obvious choices and reconstruct the move that made the position work.'
            elif category == 'opposition_opportunity':
                prompt = 'The researched opponent has just made a consequential mistake. Find the strongest way to exploit it before the opportunity disappears.'
            else:
                prompt = _concept_prompt(concept_keys)
        if prompt is None:
            prompt = 'Identify the most urgent tactical fact on the board: what is attacked, what is loose, and what forcing move changes the position immediately?'

    # ---------- post-solve explanation ----------
    # Select ONE reason rooted at the decision, then (only if informative)
    # give the contrast with the move played. Learning-motif priorities and
    # engine-provenance boilerplate must never leak into user-facing prose.
    best_san = best_move_san or best_move_uci
    played_label = played_move_san or played_move_uci
    if best is None:
        return prompt, 'The saved best move is no longer legal in this position; refresh the game metadata.'

    # Primary explanation is a comparison of *two* actual saved variations,
    # including piece identity, recaptures, direct mate threats, and whether
    # threatened material is lost in both lines. This prevents one-ply motifs
    # from claiming that a counterattack saves an inevitably lost pawn.
    factual = decision_facts(board, best, played, best_pv_uci, played_pv_uci,
                             alternative_pvs_json, eval_before_cp, eval_after_cp)
    # A legal king move may both resolve check *and* activate the king in an
    # endgame. Don't discard a substantiated causal finding merely because
    # the original position starts in check; preserve forcing mate evidence.
    # Rank consequences before composing prose. A direct reply, a later
    # demonstrated loss, and positional consequences are NOT equally strong
    # evidence. This semantic layer speaks first when it can explain the
    # evaluation with a specific, supported cause. Legacy reasoning is the
    # conservative fallback for unusual motifs and older metadata.
    semantic = causal_coaching(
        board, best, played, best_pv_uci, played_pv_uci,
        alternative_pvs_json, eval_before_cp, eval_after_cp,
        category, mate_before, facts=factual)
    if semantic and (not board.is_check() or semantic['evidence_level'] >= 2):
        return prompt, semantic['text']
    features = _best_move_features(board, best)
    comparison = comparative_insight(board, best, played, best_pv_uci, played_pv_uci)
    diagnostic = decisive_contrast(board, best, played, best_pv_uci, played_pv_uci,
                                   alternative_pvs_json, category, eval_before_cp)
    critical = decode_critical_evidence(critical_events_json)
    # Live coaching, older databases, and new metadata refresh all use the
    # same causal evidence even when no persisted annotation is available.
    if critical is None:
        critical = critical_decision_evidence(board, best, played, best_pv_uci,
            played_pv_uci, eval_before_cp, eval_after_cp,
            alternatives=alternative_pvs_json, explanatory_lines=explanatory_lines_json)
    critical_text = critical_explanation(critical)
    events = comparison['best'].get('events') or []
    line_mate = bool(events and events[-1]['ours'] and events[-1]['mate'])
    ending = events[-1]['san'] if line_mate else None
    verified_mate = (category == 'missed_checkmate' and
                     isinstance(mate_before, int) and mate_before > 0)
    mate_defense = category == 'allowed_checkmate' and 'mate_defense' in concept_keys

    if features['checkmate'] or verified_mate or mate_defense or line_mate:
        # The checked mate score is the only proof of a *forced* continuation;
        # a sampled mating PV on its own is merely illustrative.
        text = mate_explanation(
            best_san, played_label,
            mate_in=mate_before if verified_mate else None,
            final_move=ending if not features['checkmate'] else None,
            immediate=features['checkmate'], threatened_mate=mate_defense,
            verified=verified_mate,
        )
        # A pin may explain an apparent defense; keep it because it answers a
        # genuinely different question, not because 'Pin' ranked second.
        if context and context.get('pin_capture_refutations'):
            detail = context['pin_capture_refutations'][0]['evidence']
            if detail:
                text += ' ' + detail
        if context and context.get('discovered_reply_checks') and not context.get('pin_capture_refutations'):
            rebuttal = next((d['evidence'] for d in context['discovered_reply_checks']
                             if d['kind'] == 'illegal_capture_during_discovered_check'), None)
            if rebuttal:
                # A concrete answer to 'why can't that piece take mine?' is
                # worth more than a boilerplate 'missed the opportunity'.
                text = mate_explanation(best_san, None, mate_in=mate_before if verified_mate else None,
                                        final_move=ending if not features['checkmate'] else None,
                                        immediate=features['checkmate'], threatened_mate=mate_defense,
                                        verified=verified_mate)
                text = concise([text, rebuttal])
        if context and context.get('discovered_unique_lines'):
            revealed_check = next((d for d in context['discovered_unique_lines']
                                   if d['kind'] == 'discovered_check'), None)
            if revealed_check and not context.get('pin_capture_refutations'):
                text = concise([text, f'The check comes from your '
                                f'{revealed_check["revealed_piece"]} on '
                                f'{chess.square_name(revealed_check["attacker_square"])}.'])
        if diagnostic and diagnostic['kind'] in {'material', 'fork'} and \
                diagnostic['text'].lower() not in text.lower():
            text = concise([text, diagnostic['text']])
        return prompt, text

    # A legal move made WHILE IN CHECK must first be explained as an
    # evasion. It is misleading to describe an interposition as newly
    # pressuring a piece when the tactical point is to block the checking ray
    # or offer a balanced exchange of the attacking and blocking pieces.
    # The context detector also captures an uncovered countercheck, if any.
    evasion = context.get('check_evasion') if context else None
    if evasion:
        facts = [evasion['evidence']]
        if diagnostic and diagnostic['kind'] in {'fork', 'material', 'mate'}:
            # The purpose of a king move is often *which danger it avoids*,
            # not merely that it satisfies the obligation to answer check.
            facts.append(diagnostic['text'])
        uncovered = next((d for d in context.get('discovered_unique_lines', [])
                          if d['kind'] == 'discovered_check'), None)
        if uncovered:
            facts.append('It also uncovers check from your '
                         f'{uncovered["revealed_piece"]} on '
                         f'{chess.square_name(uncovered["attacker_square"])}.')
        return prompt, concise(facts)

    discovery = (context.get('discovered_unique_lines') or [None])[0] if context else None
    discovery_replies = context.get('discovered_reply_checks') or [] if context else []
    demonstrated_reply = next((item for item in discovery_replies if item['kind']
                               in {'illegal_capture_during_discovered_check',
                                   'legal_capture_allows_followup'}), None)
    discovery_lead = ''
    if discovery:
        revealer = (f'your {discovery["revealed_piece"]} on '
                    f'{chess.square_name(discovery["attacker_square"])}')
        if discovery['kind'] == 'discovered_check':
            discovery_lead = f'{best_san} uncovers check from {revealer}.'
        else:
            discovery_lead = (f'{best_san} uncovers {revealer}’s attack on the '
                              f'opponent’s {discovery["target_piece"]} on '
                              f'{chess.square_name(discovery["target_square"])}.')
    # Counterfactual captures are helpful only when validated against the
    # position AFTER the recommendation, not inferred from bare geometry.
    if discovery_lead and demonstrated_reply:
        detail = demonstrated_reply['evidence']
        return prompt, concise([discovery_lead, detail])

    # Distinguish an immediately relevant board fact from an incidental
    # positional pattern found farther down an engine continuation. First
    # explain a directly missed capture/defense, then what the recommended
    # root move *actually does*, and only then less local PV changes.
    rooted = immediate_decision(board, best, played, context)
    root_effect = root_move_impact(board, best, played, best_pv_uci)
    # A demonstrated early loss takes priority over the fork, pressure, or
    # positional pattern seen later in that *same* inferior continuation.
    if diagnostic and diagnostic['kind'] == 'mate':
        return prompt, diagnostic['text']
    if critical_text:
        return prompt, critical_text
    if rooted:
        if diagnostic and diagnostic['kind'] in {'fork', 'material'}:
            return prompt, concise([rooted['explanation'], diagnostic['text']])
        return prompt, rooted['explanation']
    if diagnostic and diagnostic['kind'] == 'fork' and not (
            root_effect and root_effect['kind'] in {'capture', 'exchange', 'contested_capture'}):
        return prompt, diagnostic['text']
    if root_effect and root_effect['kind'] in {
            'capture', 'exchange', 'contested_capture', 'defense', 'block_attack',
            'passed_pawn', 'attack', 'castle', 'check'}:
        # A captured piece is a more local fact than downstream pressure, but
        # an evidenced knight fork or loss may explain the move's true value.
        additional = diagnostic['text'] if diagnostic and diagnostic['kind'] in {
            'material', 'fork'} else ''
        if additional and additional != root_effect['text']:
            return prompt, concise([root_effect['text'], additional])
        return prompt, root_effect['text']

    # A concrete missed defense is more instructive than a long line about
    # pressure elsewhere on the board.  It identifies both candidate moves.
    if context and context.get('played_counterfactual'):
        lead = context['played_counterfactual']['evidence']
    else:
        lead = ''

    # Prefer a verified two-branch outcome over a motif label or an
    # incidental change in square control.  Material, pawn and king-safety
    # explanations already use directly compared continuation states.
    if not lead and root_effect:
        lead = root_effect['text']
    if not lead and diagnostic:
        lead = diagnostic['text']
    if not lead and comparison.get('narrative'):
        lead = polish_comparison(comparison['narrative'], best=best_san,
                                 played=played_label or '')
    if not lead and discovery_lead:
        lead = discovery_lead
    if not lead and context and context.get('response_reason'):
        lead = f'{best_san} {context["response_reason"]}.'
    if not lead and concept_keys and concept_keys[0] == 'fork':
        fork = fork_evidence(board, best, best_pv_uci)
        if fork and fork.get('strong'):
            targets = [_target_phrase(features['after'], sq) for sq, _ in fork['targets'][:2]]
            lead = f'{best_san} forks the opponent’s {_human_list(targets)}.'
    if not lead and (features['capture'] or features['check'] or features['queen_exchange']):
        # We describe captures and checks as facts; a capture is not
        # automatically a material gain or a sacrifice.
        legal_line = legal_pv(board, best_pv_uci, first_move=best)
        if len(legal_line) >= 2:
            after = board.copy(stack=False)
            after.push(best)
            features['principal_reply'] = {'recaptures': (
                after.is_capture(legal_line[1]) and
                legal_line[1].to_square == best.to_square)}
        lead = _specific_solution_sentence(board, best, features, last, [],
                                           best_san, category, mate_before)
    if not lead and context and context.get('pin_capture_refutations'):
        lead = f'{best_san} works because {context["pin_capture_refutations"][0]["evidence"][0].lower() + context["pin_capture_refutations"][0]["evidence"][1:]}'
    if not lead:
        # Avoid the old tautological fallback such as 'e6 places a pawn on
        # e6'.  If the saved evidence is too short, say exactly what must be
        # compared instead of inventing tactical pressure.
        lead = (f'{best_san} is preferred to {played_label}, but the saved '
                'continuations do not yet establish a concrete reason.'
                if played_label and played_label != best_san else
                f'{best_san} is the recommended move; a deeper comparison is '
                'needed to establish the specific benefit.')

    parts = [lead]
    # Add a *different* point only if the first point didn't already explain
    # why an apparently natural legal/illegal reply fails.
    if context:
        if context.get('pin_capture_refutations') and 'cannot capture' not in lead:
            parts.append(context['pin_capture_refutations'][0]['evidence'])
        elif context.get('legal_reply_traps') and 'checkmate' not in lead and '#' not in lead:
            parts.append(context['legal_reply_traps'][0]['evidence'])

    # Describe the played move by name; don't append evaluation labels like
    # 'major blunder' or repeat a material gain already contrasted above.
    if (played_label and played_label != best_san and
            played_label not in ' '.join(parts) and
            not (context and context.get('pin_capture_refutations') and len(parts) > 1)):
        if context and context.get('played_ignores') and context.get('best_neutralizes'):
            overlap = set(context['played_ignores']) & set(context['best_neutralizes'])
            if overlap:
                square = sorted(overlap)[0]
                piece = board.piece_at(square)
                if piece:
                    parts.append(f'In the game, {played_label} left your '
                                 f'{_piece_name(piece)} on {_square(square)} hanging.')
        elif category in {'missed_checkmate', 'allowed_checkmate'}:
            pass  # handled above
        elif category in {'excellent_move', 'brilliant_move'}:
            pass  # user played the same or similarly strong response
        elif len(parts) == 1 and 'fork' in lead.lower() and \
                'in the game' not in lead.lower():
            parts.append(f'In the game, {played_label} misses that fork.')
        # No generic 'missed this idea' sentence: the game-move contrast must
        # be evidenced, not filler added solely to fill a second sentence.

    return prompt, concise(parts)

