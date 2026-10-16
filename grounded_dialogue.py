from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Optional

import chess

from engine_service import evaluate_fen, evaluate_move_quality

GROUNDED_DIALOGUE_VERSION = 'grounded-dialogue-v2.2'

PIECE_WORDS = {
    'pawn': chess.PAWN,
    'pawns': chess.PAWN,
    'knight': chess.KNIGHT,
    'knights': chess.KNIGHT,
    'horse': chess.KNIGHT,
    'horses': chess.KNIGHT,
    'bishop': chess.BISHOP,
    'bishops': chess.BISHOP,
    'rook': chess.ROOK,
    'rooks': chess.ROOK,
    'castle': chess.ROOK,
    'queen': chess.QUEEN,
    'queens': chess.QUEEN,
    'king': chess.KING,
    'kings': chess.KING,
}

ACTION_WORDS = {
    'block': ('block', 'blocks', 'blocking', 'interpose', 'interposes'),
    'capture': ('take', 'takes', 'taking', 'capture', 'captures', 'capturing', 'grab', 'wins'),
    'move': ('move', 'moves', 'moving', 'go', 'goes', 'come', 'comes', 'jump', 'jumps', 'retreat', 'retreats'),
    'defend': ('defend', 'defends', 'protect', 'protects', 'cover', 'covers'),
    'attack': ('attack', 'attacks', 'pressure', 'pressures', 'target', 'targets'),
    'trade': ('trade', 'trades', 'exchange', 'exchanges', 'swap', 'swaps'),
    'push': ('push', 'pushes', 'advance', 'advances'),
}

MOVE_QUERY_PHRASES = (
    'what if', 'what about', 'how about', 'why not', 'could i', 'could we', 'could black',
    'could white', 'can i', 'can black', 'can white', 'should i', 'should black', 'should white',
    'instead', 'responds with', 'respond with', 'plays', 'play ', 'try ', 'trying ', 'consider ',
)

THREAT_PHRASES = ('what is the threat', "what's the threat", 'what are they threatening', 'what is black threatening', 'what is white threatening')
PLAN_PHRASES = ('what is the plan', "what's the plan", 'what should the plan', 'what am i trying to do', 'what is the idea')
COMPARE_PHRASES = ('compare', 'better than', 'worse than', 'instead of', 'versus', ' vs ', ' or ')


@dataclass
class MoveResolution:
    intent: str
    raw_text: str
    action: Optional[str]
    piece_type: Optional[int]
    destination: Optional[str]
    source: Optional[str]
    capture_piece_type: Optional[int]
    explicit_side: Optional[str]
    candidate_uci: list[str]
    candidate_san: list[str]
    variation_uci: list[str]
    variation_san: list[str]
    ambiguous: bool
    confidence: float
    parser: str = 'grounded-rules'


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').lower()
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('…', '...')
    return re.sub(r'\s+', ' ', text).strip()


def _piece_word(text: str) -> Optional[int]:
    t = _norm(text)
    # Prefer the first explicit chess-piece noun, not a noun contained in a move token.
    for word, piece_type in PIECE_WORDS.items():
        if re.search(rf'\b{re.escape(word)}\b', t):
            return piece_type
    return None


def _captured_piece_word(text: str) -> Optional[int]:
    t = _norm(text)
    capture_match = re.search(r'\b(?:take|takes|taking|capture|captures|capturing|wins?)\s+(?:the\s+)?(pawn|knight|horse|bishop|rook|castle|queen|king)\b', t)
    if capture_match:
        return PIECE_WORDS.get(capture_match.group(1))
    return None


def _action(text: str) -> Optional[str]:
    t = _norm(text)
    for action, words in ACTION_WORDS.items():
        if any(re.search(rf'\b{re.escape(word)}\b', t) for word in words):
            return action
    return None


def _explicit_side(text: str) -> Optional[str]:
    t = _norm(text)
    if re.search(r'\bblack\b', t):
        return 'black'
    if re.search(r'\bwhite\b', t):
        return 'white'
    if re.search(r'\b(?:opponent|they|them|their|he|she)\b', t):
        return 'opponent'
    if re.search(r'\b(?:i|my|me|we|our)\b', t):
        return 'self'
    return None


def _extract_squares(text: str) -> list[str]:
    return re.findall(r'(?<![a-z0-9])([a-h][1-8])(?![a-z0-9])', text.lower())


def _san_candidates_from_text(board: chess.Board, text: str) -> list[chess.Move]:
    # Pull likely SAN tokens, including common ellipsis notation (...Rc1).
    tokens = _san_tokens(text)
    result: list[chess.Move] = []
    for token in tokens:
        try:
            move = board.parse_san(token)
        except Exception:
            continue
        if move not in result:
            result.append(move)
    return result



def _san_tokens(text: str) -> list[str]:
    cleaned = text.replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
    return re.findall(r'(?<![A-Za-z0-9])(?:O-O-O|O-O|[KQRBN](?:[a-h]|[1-8])?x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h]x?[a-h][1-8](?:=[QRBN])?[+#]?)(?![A-Za-z0-9])', cleaned)


def _san_variation_from_text(board: chess.Board, text: str) -> tuple[list[chess.Move], list[str]]:
    tokens = _san_tokens(text)
    if len(tokens) < 2:
        return [], []
    replay = board.copy(stack=False)
    moves: list[chess.Move] = []
    sans: list[str] = []
    for token in tokens:
        try:
            move = replay.parse_san(token)
        except Exception:
            break
        sans.append(replay.san(move))
        moves.append(move)
        replay.push(move)
    return (moves, sans) if len(moves) >= 2 else ([], [])


def _uci_candidates_from_text(board: chess.Board, text: str) -> list[chess.Move]:
    tokens = re.findall(r'(?<![a-z0-9])([a-h][1-8][a-h][1-8][qrbn]?)(?![a-z0-9])', text.lower())
    moves = []
    for token in tokens:
        try:
            move = chess.Move.from_uci(token)
        except Exception:
            continue
        if move in board.legal_moves and move not in moves:
            moves.append(move)
    return moves


def _match_natural_move(board: chess.Board, text: str) -> tuple[list[chess.Move], dict]:
    t = _norm(text)
    piece_type = _piece_word(t)
    captured_type = _captured_piece_word(t)
    action = _action(t)
    squares = _extract_squares(t)
    destination = squares[-1] if squares else None
    source = squares[-2] if len(squares) >= 2 else None

    # A bare square plus a piece noun is a very common human formulation:
    # "knight blocks on c3", "rook to e1", "queen takes d5".
    candidates = list(board.legal_moves)
    if piece_type is not None:
        candidates = [m for m in candidates if (board.piece_at(m.from_square) and board.piece_at(m.from_square).piece_type == piece_type)]
    if destination:
        dest_sq = chess.parse_square(destination)
        candidates = [m for m in candidates if m.to_square == dest_sq]
    if source:
        source_sq = chess.parse_square(source)
        source_matched = [m for m in candidates if m.from_square == source_sq]
        if source_matched:
            candidates = source_matched
    if action == 'capture' or captured_type is not None:
        capture_moves = [m for m in candidates if board.is_capture(m)]
        if captured_type is not None:
            capture_moves = [m for m in capture_moves if (board.piece_at(m.to_square) and board.piece_at(m.to_square).piece_type == captured_type) or board.is_en_passant(m)]
        candidates = capture_moves

    # If there is no destination, "take the queen" can still be resolved if unique.
    if not destination and captured_type is not None:
        candidates = []
        for move in board.legal_moves:
            if not board.is_capture(move):
                continue
            target = board.piece_at(move.to_square)
            if target and target.piece_type == captured_type:
                if piece_type is None or (board.piece_at(move.from_square) and board.piece_at(move.from_square).piece_type == piece_type):
                    candidates.append(move)

    # Without a useful move constraint, don't pretend all legal moves are candidates.
    constrained = piece_type is not None or destination is not None or captured_type is not None
    if not constrained:
        candidates = []

    return candidates, {
        'piece_type': piece_type,
        'capture_piece_type': captured_type,
        'action': action,
        'destination': destination,
        'source': source,
    }


def _intent(text: str, has_move: bool, move_count: int) -> str:
    t = _norm(text)
    if any(p in t for p in THREAT_PHRASES):
        return 'identify_threat'
    if any(p in t for p in PLAN_PHRASES):
        return 'identify_plan'
    if 'why not' in t and has_move:
        return 'why_not_move'
    if any(p in t for p in COMPARE_PHRASES) and move_count >= 2:
        return 'compare_moves'
    if has_move and any(p in t for p in MOVE_QUERY_PHRASES):
        return 'analyze_move'
    if has_move and ('?' in text or _action(t)):
        return 'analyze_move'
    return 'none'


def parse_grounded_request(text: str, fen: str) -> Optional[MoveResolution]:
    try:
        board = chess.Board(fen)
    except Exception:
        return None

    explicit = _uci_candidates_from_text(board, text)
    san = _san_candidates_from_text(board, text)
    variation_moves, variation_san = _san_variation_from_text(board, text)
    natural, meta = _match_natural_move(board, text)

    candidates: list[chess.Move] = []
    for move in explicit + san + natural:
        if move not in candidates:
            candidates.append(move)

    has_description = bool(meta.get('piece_type') is not None or meta.get('destination') or meta.get('capture_piece_type'))
    if len(variation_moves) >= 2 and any(term in _norm(text) for term in ('what if', 'line', 'then', 'after')):
        intent = 'analyze_variation'
    else:
        intent = _intent(text, bool(candidates) or has_description, len(candidates))
    # Threat/plan questions and explicit-but-illegal move ideas remain grounded.
    if intent == 'none':
        return None

    san_names = []
    for move in candidates:
        try:
            san_names.append(board.san(move))
        except Exception:
            san_names.append(move.uci())

    return MoveResolution(
        intent=intent,
        raw_text=text,
        action=meta.get('action'),
        piece_type=meta.get('piece_type'),
        destination=meta.get('destination'),
        source=meta.get('source'),
        capture_piece_type=meta.get('capture_piece_type'),
        explicit_side=_explicit_side(text),
        candidate_uci=[m.uci() for m in candidates],
        candidate_san=san_names,
        variation_uci=[m.uci() for m in variation_moves],
        variation_san=variation_san,
        ambiguous=len(candidates) > 1 and intent not in ('analyze_variation', 'compare_moves'),
        confidence=.96 if len(candidates) == 1 else (.78 if candidates else .7),
    )


def _fmt_eval(cp: Optional[int], mate: Optional[int], perspective: str = 'your') -> str:
    if mate is not None:
        if mate > 0:
            return f'forced mate in {abs(mate)} for {perspective} side'
        return f'being mated in {abs(mate)} from {perspective} perspective'
    cp = int(cp or 0)
    return f'{cp / 100:+.2f}'


def _move_grade(gap_cp: int, mate_best: Optional[int], mate_candidate: Optional[int]) -> tuple[str, str]:
    if mate_best is not None and mate_best > 0 and not (mate_candidate is not None and mate_candidate > 0):
        return 'refuted', 'It gives up a forced mating continuation.'
    if gap_cp <= 25:
        return 'supported', 'It is essentially as strong as the engine preference.'
    if gap_cp <= 70:
        return 'supported', 'It is very close to the engine preference.'
    if gap_cp <= 150:
        return 'plausible_but_secondary', 'It is playable, but it concedes some of the position compared with the strongest continuation.'
    if gap_cp <= 300:
        return 'mostly_refuted', 'The idea is understandable, but the concrete position punishes it enough to matter.'
    return 'refuted', 'The move loses substantial value compared with the best continuation.'


def _between_square(a: int, b: int, x: int) -> bool:
    af, ar = chess.square_file(a), chess.square_rank(a)
    bf, br = chess.square_file(b), chess.square_rank(b)
    xf, xr = chess.square_file(x), chess.square_rank(x)
    df, dr = bf - af, br - ar
    if not (df == 0 or dr == 0 or abs(df) == abs(dr)):
        return False
    step_f = 0 if df == 0 else (1 if df > 0 else -1)
    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    f, r = af + step_f, ar + step_r
    while (f, r) != (bf, br):
        if (f, r) == (xf, xr):
            return True
        f += step_f
        r += step_r
    return False


def _block_effect(board: chess.Board, move: chess.Move, mover: chess.Color) -> Optional[str]:
    destination = move.to_square
    after = board.copy(stack=False)
    after.push(move)
    enemy = not mover
    for target_sq, target_piece in board.piece_map().items():
        if target_piece.color != mover:
            continue
        before_attackers = board.attackers(enemy, target_sq)
        after_attackers = after.attackers(enemy, target_sq)
        removed = [sq for sq in before_attackers if sq not in after_attackers]
        for attacker_sq in removed:
            attacker = board.piece_at(attacker_sq)
            if not attacker or attacker.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                continue
            if _between_square(attacker_sq, target_sq, destination):
                return f'It really does interpose on the line from the {chess.piece_name(attacker.piece_type)} on {chess.square_name(attacker_sq)} to your {chess.piece_name(target_piece.piece_type)} on {chess.square_name(target_sq)}.'
    return None


def _concrete_effects(board: chess.Board, move: chess.Move, requested_action: Optional[str]) -> list[str]:
    mover = board.turn
    piece = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    from_attacked = board.is_attacked_by(not mover, move.from_square)
    san = board.san(move)
    after = board.copy(stack=False)
    after.push(move)
    to_attacked = after.is_attacked_by(not mover, move.to_square)

    notes: list[str] = []
    if requested_action == 'block':
        block_note = _block_effect(board, move, mover)
        if block_note:
            notes.append(block_note)
        else:
            notes.append('It reaches the square you described, but I do not find a major sliding attack that is actually neutralized by the interposition.')
    if board.is_capture(move):
        if captured:
            notes.append(f'It captures the {chess.piece_name(captured.piece_type)} on {chess.square_name(move.to_square)}.')
        else:
            notes.append('It is a capture.')
    if after.is_checkmate():
        notes.append('It gives checkmate.')
    elif after.is_check():
        notes.append('It gives check, so the opponent must answer the king threat.')
    if from_attacked and not to_attacked and piece:
        notes.append(f'It also moves the attacked {chess.piece_name(piece.piece_type)} to a square where it is not immediately attacked.')

    # New direct targets created by the moved piece.
    targets = []
    for sq in after.attacks(move.to_square):
        target = after.piece_at(sq)
        if target and target.color != mover and target.piece_type != chess.KING:
            targets.append((target.piece_type, sq))
    targets.sort(key=lambda item: {chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9}.get(item[0],0), reverse=True)
    if targets:
        names = [f"{chess.piece_name(pt)} on {chess.square_name(sq)}" for pt, sq in targets[:2]]
        if len(names) == 1:
            notes.append(f'From there it attacks the opponent\'s {names[0]}.')
        else:
            notes.append(f"From there it attacks both the opponent's {names[0]} and {names[1]}.")
    if not notes:
        notes.append(f'{san} is a non-forcing move; to understand it, examine the opponent’s strongest response rather than assuming it creates an immediate tactic.')
    return notes


def _pv_text(info: dict, board: chess.Board) -> str:
    pv_san = info.get('pv_san') or []
    if len(pv_san) <= 1:
        return ''
    continuation = ' '.join(pv_san[1:4])
    return continuation


def analyze_move_request(resolution: MoveResolution, fen: str, user_color: str, allow_best_move: bool) -> dict:
    board = chess.Board(fen)
    user_pov = chess.WHITE if str(user_color).lower() == 'white' else chess.BLACK

    explicit = resolution.explicit_side
    expected = None
    side_label = None
    if explicit in ('white', 'black'):
        expected = chess.WHITE if explicit == 'white' else chess.BLACK
        side_label = explicit.capitalize()
    elif explicit == 'self':
        expected = user_pov
        side_label = 'your side'
    elif explicit == 'opponent':
        expected = not user_pov
        side_label = 'your opponent'
    if expected is not None and board.turn != expected:
        return {
            'handled': True,
            'reply': f"I understand the idea, but it is currently {'White' if board.turn else 'Black'} to move on the board. To analyze {side_label}'s move, first advance the board to that side's turn or describe the preceding move too.",
            'verdict': 'ambiguous',
            'resolution': asdict(resolution),
            'evidence': {'turn_mismatch': True, 'board_turn': 'white' if board.turn else 'black'},
        }

    if resolution.intent == 'analyze_variation' and resolution.variation_uci:
        return analyze_variation(resolution, fen, user_color, allow_best_move)

    if not resolution.candidate_uci:
        if resolution.intent == 'identify_threat':
            return analyze_threat(fen, user_color)
        if resolution.intent == 'identify_plan':
            return analyze_plan(fen, user_color, allow_best_move)
        piece = chess.piece_name(resolution.piece_type) if resolution.piece_type else 'piece'
        dest = f" to {resolution.destination}" if resolution.destination else ''
        reply = f"I understand the idea as {piece}{dest}, but there is no legal move matching that description in the position currently on the board."
        if resolution.explicit_side in ('white', 'black') and resolution.explicit_side != ('white' if board.turn else 'black'):
            reply += f" It is currently {'White' if board.turn else 'Black'} to move, which may be the mismatch."
        return {'handled': True, 'reply': reply, 'verdict': 'refuted', 'resolution': asdict(resolution), 'evidence': {'legal': False}}

    if resolution.ambiguous and resolution.intent != 'compare_moves':
        options = ', '.join(resolution.candidate_san[:4])
        return {
            'handled': True,
            'reply': f"I can map that wording to more than one legal move: {options}. Name the source square or use the move notation and I’ll analyze the one you mean.",
            'verdict': 'ambiguous', 'resolution': asdict(resolution), 'evidence': {'candidates': resolution.candidate_uci},
        }

    if resolution.intent == 'compare_moves' and len(resolution.candidate_uci) >= 2:
        return compare_moves(resolution, fen, user_color, allow_best_move)

    move = chess.Move.from_uci(resolution.candidate_uci[0])
    san = board.san(move)
    best = evaluate_fen(fen, board.turn)
    candidate = evaluate_move_quality(fen, move.uci(), board.turn)
    best_cp = int(best.get('eval_cp') or 0)
    cand_cp = int(candidate.get('eval_cp') or 0)
    gap = max(0, best_cp - cand_cp)
    verdict, grade_text = _move_grade(gap, best.get('mate'), candidate.get('mate'))

    effects = _concrete_effects(board, move, resolution.action)
    continuation = _pv_text(candidate, board)
    candidate_user_cp = cand_cp if board.turn == user_pov else -cand_cp
    candidate_user_mate = candidate.get('mate') if board.turn == user_pov else (-candidate.get('mate') if candidate.get('mate') is not None else None)

    # Ground the explanation in the actual first reply and its board consequences.
    reply_board = board.copy(stack=False)
    reply_board.push(move)
    reply_san = (candidate.get('pv_san') or [])[1:2]
    reply_effects = []
    if reply_san:
        try:
            reply_move = reply_board.parse_san(reply_san[0])
            reply_effects = _concrete_effects(reply_board, reply_move, None)
        except (ValueError, AssertionError):
            pass
    parts = [f"Let's examine {san}."]
    parts.extend(effects)
    if reply_san:
        parts.append(f"The critical reply to examine is {reply_san[0]}.")
        parts.extend(reply_effects[:2])
    if gap <= 60:
        parts.append('The move is competitive with the engine’s leading choice at this search limit; this does not by itself establish a particular strategic purpose.')
    elif gap <= 150:
        parts.append('The idea is playable, but the engine sees a meaningful drawback compared with its leading choice.')
    else:
        parts.append('The engine finds a substantially stronger alternative, so the proposed move needs a closer tactical check.')
    if allow_best_move and best.get('best_move_san') and best.get('best_move_uci') != move.uci():
        parts.append(f"For comparison, Stockfish prefers {best['best_move_san']} (about {gap/100:.2f} pawns stronger at this search limit).")
    if not reply_san:
        parts.append('No reliable principal variation was returned; a deeper search is needed to explain the opponent’s concrete response.')

    return {
        'handled': True,
        'reply': ' '.join(parts),
        'verdict': verdict,
        'resolution': asdict(resolution),
        'evidence': {
            'move_uci': move.uci(), 'move_san': san, 'candidate_eval_cp_side_to_move': cand_cp,
            'best_eval_cp_side_to_move': best_cp, 'gap_cp': gap,
            'candidate_eval_cp_user': candidate_user_cp, 'pv_uci': candidate.get('pv_uci', []),
            'pv_san': candidate.get('pv_san', []), 'best_move_uci': best.get('best_move_uci') if allow_best_move else None,
            'best_move_san': best.get('best_move_san') if allow_best_move else None,
        },
    }



def analyze_variation(resolution: MoveResolution, fen: str, user_color: str, allow_best_move: bool) -> dict:
    board = chess.Board(fen)
    replay = board.copy(stack=False)
    sans = []
    for uci in resolution.variation_uci:
        move = chess.Move.from_uci(uci)
        if move not in replay.legal_moves:
            return {
                'handled': True,
                'reply': f"The line is legal through {' '.join(sans) or 'the starting position'}, but {uci} is not legal at the next step.",
                'verdict': 'refuted', 'resolution': asdict(resolution),
                'evidence': {'legal_prefix': sans, 'illegal_move': uci},
            }
        sans.append(replay.san(move))
        replay.push(move)

    user_pov = chess.WHITE if str(user_color).lower() == 'white' else chess.BLACK
    final_eval = evaluate_fen(replay.fen(), user_pov)
    eval_text = _fmt_eval(final_eval.get('eval_cp'), final_eval.get('mate'), 'your')
    reply = f"The line {' '.join(sans)} is legal. After those moves, the position evaluates around {eval_text} from your perspective."
    if allow_best_move and final_eval.get('best_move_san'):
        reply += f" From that resulting position, Stockfish prefers {final_eval['best_move_san']}."
    elif not allow_best_move:
        reply += ' I will keep the engine preference hidden until the puzzle is solved.'
    return {
        'handled': True, 'reply': reply, 'verdict': 'supported',
        'resolution': asdict(resolution),
        'evidence': {'variation_uci': resolution.variation_uci, 'variation_san': sans,
                     'resulting_fen': replay.fen(), 'eval_cp_user': final_eval.get('eval_cp'),
                     'mate_user': final_eval.get('mate'),
                     'best_move_san': final_eval.get('best_move_san') if allow_best_move else None},
    }


def compare_moves(resolution: MoveResolution, fen: str, user_color: str, allow_best_move: bool) -> dict:
    board = chess.Board(fen)
    rows = []
    for uci in resolution.candidate_uci[:4]:
        move = chess.Move.from_uci(uci)
        info = evaluate_move_quality(fen, uci, board.turn)
        rows.append((int(info.get('eval_cp') or 0), board.san(move), uci, info))
    rows.sort(reverse=True, key=lambda x: x[0])
    best_candidate = rows[0]
    details = [f"{san}: {cp/100:+.2f}" for cp, san, _, _ in rows]
    reply = f"Among the moves you named, {best_candidate[1]} evaluates best for the side to move. " + '; '.join(details) + '.'
    pv = best_candidate[3].get('pv_san') or []
    if len(pv) > 1:
        reply += f" Its main continuation begins {' '.join(pv[1:4])}."
    return {'handled': True, 'reply': reply, 'verdict': 'supported', 'resolution': asdict(resolution), 'evidence': {'moves': details}}


def analyze_threat(fen: str, user_color: str) -> dict:
    board = chess.Board(fen)
    side = board.turn
    enemy = not side
    attacked = []
    for sq, piece in board.piece_map().items():
        if piece.color == side and board.is_attacked_by(enemy, sq):
            defenders = len(board.attackers(side, sq))
            attackers = len(board.attackers(enemy, sq))
            value = {chess.PAWN:1,chess.KNIGHT:3,chess.BISHOP:3,chess.ROOK:5,chess.QUEEN:9,chess.KING:100}.get(piece.piece_type,0)
            attacked.append((value, attackers-defenders, piece, sq))
    attacked.sort(reverse=True, key=lambda x:(x[0],x[1]))
    if board.is_check():
        reply = f"The immediate issue is check: the {'white' if side else 'black'} king must respond before any slower plan matters."
    elif attacked:
        _, _, piece, sq = attacked[0]
        reply = f"The clearest immediate pressure is on the {chess.piece_name(piece.piece_type)} on {chess.square_name(sq)}."
        if len(attacked) > 1:
            _, _, p2, s2 = attacked[1]
            reply += f" The {chess.piece_name(p2.piece_type)} on {chess.square_name(s2)} is also under attack."
    else:
        reply = 'I do not find a simple one-move attack on a valuable piece, so the threat is likely positional or depends on a forcing continuation rather than a currently hanging piece.'
    return {'handled': True, 'reply': reply, 'verdict': 'supported', 'resolution': {'intent':'identify_threat'}, 'evidence': {'attacked': [(chess.piece_name(p.piece_type), chess.square_name(s)) for _,_,p,s in attacked[:4]]}}


def analyze_plan(fen: str, user_color: str, allow_best_move: bool) -> dict:
    board = chess.Board(fen)
    engine = evaluate_fen(fen, board.turn)
    pieces = []
    for sq, piece in board.piece_map().items():
        if piece.color == board.turn and piece.piece_type in (chess.ROOK, chess.QUEEN, chess.BISHOP, chess.KNIGHT):
            mobility = len(board.attacks(sq))
            pieces.append((mobility, chess.piece_name(piece.piece_type), chess.square_name(sq)))
    pieces.sort()
    weak = pieces[0] if pieces else None
    if allow_best_move and engine.get('best_move_san'):
        reply = f"A concrete way to understand the position is to start from {engine['best_move_san']}, Stockfish's preferred move at the current review depth."
        if weak:
            reply += f" More generally, your least mobile major/minor piece is the {weak[1]} on {weak[2]}, so improving piece activity is a useful strategic question to test."
    elif weak:
        reply = f"Without revealing an engine move, a useful planning question is whether you can improve the {weak[1]} on {weak[2]}, currently one of your least mobile pieces, while answering any immediate tactical threats."
    else:
        reply = 'The position is forcing enough that I would prioritize checks, captures, and direct threats before committing to a slower strategic plan.'
    return {'handled': True, 'reply': reply, 'verdict': 'supported', 'resolution': {'intent':'identify_plan'}, 'evidence': {'least_mobile_piece': weak, 'best_move': engine.get('best_move_san') if allow_best_move else None}}
