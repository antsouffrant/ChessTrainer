from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Optional

import chess
import requests

from app_settings import get_settings
from coaching.narrative_composition.coach_reasoner import reason_about_message, COACH_REASONER_VERSION

ADAPTIVE_COACH_VERSION = 'adaptive-coach-v2.6-temporal-context'
ADAPTIVE_CLASSIFIER_VERSION = 'adaptive-concepts-v2.0'

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100,
}

# These are deliberately broader than the seeded taxonomy.  They are useful
# examples of concepts a player can teach the app through conversation.
CONCEPT_TEMPLATES = {
    'open_file_control': {
        'name': 'Control Open Files', 'family': 'Strategy',
        'description': 'Use rooks and queens to occupy or dominate open files.',
        'priority': 61, 'aliases': ['open file', 'file control', 'control the file', 'rook file'],
        'detector': {'type': 'open_file_control'},
    },
    'opposite_colored_bishops': {
        'name': 'Opposite-Colored Bishops', 'family': 'Endgames',
        'description': 'Adjust plans to the attacking and drawing features of opposite-colored bishops.',
        'priority': 54, 'aliases': ['opposite colored bishops', 'opposite-coloured bishops', 'opposite bishops'],
        'detector': {'type': 'opposite_colored_bishops'},
    },
    'central_space': {
        'name': 'Control the Center', 'family': 'Strategy',
        'description': 'Use central space and control to restrict the opponent and improve piece activity.',
        'priority': 59, 'aliases': ['central space', 'center control', 'centre control', 'control the center', 'space advantage'],
        'detector': {'type': 'central_space'},
    },
    'square_clearance': {
        'name': 'Clear Key Squares', 'family': 'Strategy',
        'description': 'Vacate or open an important square so another piece can use it.',
        'priority': 58, 'aliases': ['clear a square', 'open a square', 'vacate a square', 'square clearance'],
        'detector': {'type': 'square_clearance'},
    },
    'king_route': {
        'name': 'Create a King Route', 'family': 'Endgames',
        'description': 'Clear safe squares and routes that let the king become more active.',
        'priority': 63, 'aliases': ['king route', 'path for the king', 'square for the king', 'king path'],
        'detector': {'type': 'king_route'},
    },
    'long_diagonal': {
        'name': 'Use the Long Diagonal', 'family': 'Strategy',
        'description': 'Open and control diagonals so bishops and queens can influence both wings.',
        'priority': 55, 'aliases': ['long diagonal', 'open diagonal', 'diagonal control'],
        'detector': {'type': 'long_diagonal'},
    },
    'outpost': {
        'name': 'Use an Outpost', 'family': 'Strategy',
        'description': 'Place a piece on a stable advanced square that enemy pawns cannot easily challenge.',
        'priority': 57, 'aliases': ['outpost', 'strong square', 'protected square'],
        'detector': {'type': 'outpost'},
    },
    'bishop_pair': {
        'name': 'Use the Bishop Pair', 'family': 'Strategy',
        'description': 'Preserve and activate two bishops when open lines make their combined range valuable.',
        'priority': 52, 'aliases': ['bishop pair', 'two bishops'],
        'detector': {'type': 'bishop_pair'},
    },
}

BUILTIN_ALIAS_MAP = {
    'fork': 'fork', 'double attack': 'fork', 'pin': 'pin', 'skewer': 'skewer',
    'remove defender': 'removal_of_defender', 'removal of defender': 'removal_of_defender',
    'overloaded defender': 'overloaded_defender', 'loose piece': 'loose_piece_awareness',
    'passed pawn': 'passed_pawn', 'king activity': 'king_activity', 'activate king': 'king_activity',
    'zugzwang': 'opposition_zugzwang', 'opposition': 'opposition_zugzwang',
    'simplify': 'simplification', 'simplification': 'simplification', 'queen trade': 'simplification',
    'counterattack': 'counterattack', 'counter attack': 'counterattack', 'king safety': 'king_safety',
    'threat': 'threat_awareness', 'mating threat': 'mate_defense', 'mate threat': 'mate_defense',
    'piece activity': 'piece_activity', 'development': 'piece_development', 'pawn break': 'pawn_break',
    'coordination': 'piece_coordination', 'attack': 'attack_building',
}

@dataclass
class ParsedClaim:
    claim_type: str
    raw_claim: str
    subject: Optional[str] = None
    object: Optional[str] = None
    square: Optional[str] = None
    file: Optional[str] = None
    candidate_template: Optional[str] = None
    existing_concept: Optional[str] = None
    confidence: float = 0.7

@dataclass
class ValidationResult:
    verdict: str
    confidence: float
    explanation: str
    evidence: dict
    concept_key: Optional[str] = None


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').lower()
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[^a-z0-9\-\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _piece_name(piece: Optional[chess.Piece]) -> str:
    if not piece:
        return 'piece'
    return chess.piece_name(piece.piece_type)


def _center_control(board: chess.Board, color: chess.Color) -> int:
    center = (chess.D4, chess.E4, chess.D5, chess.E5)
    return sum(1 for sq in center if board.is_attacked_by(color, sq))


def _space_score(board: chess.Board, color: chess.Color) -> int:
    score = 0
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        rank = chess.square_rank(sq)
        if (color == chess.WHITE and rank >= 3) or (color == chess.BLACK and rank <= 4):
            score += 1
    return score + _center_control(board, color)


def _open_files(board: chess.Board) -> set[str]:
    files = set()
    for file_index in range(8):
        if not any(chess.square_file(sq) == file_index for sq in board.pieces(chess.PAWN, chess.WHITE)) \
           and not any(chess.square_file(sq) == file_index for sq in board.pieces(chess.PAWN, chess.BLACK)):
            files.add(chr(97 + file_index))
    return files


def _heavy_file_control(board: chess.Board, color: chess.Color, file_name: Optional[str] = None) -> tuple[int, list[str]]:
    open_files = _open_files(board)
    score = 0
    details = []
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        f = chr(97 + chess.square_file(sq))
        if file_name and f != file_name:
            continue
        if f in open_files:
            score += 2
            details.append(f'{_piece_name(piece)} on {chess.square_name(sq)} occupies the open {f}-file')
        controlled = sum(1 for target in board.attacks(sq) if chess.square_file(target) == chess.square_file(sq))
        if controlled >= 3:
            score += 1
    return score, details


def _bishop_square_color(square: int) -> int:
    return (chess.square_file(square) + chess.square_rank(square)) % 2


def _opposite_colored_bishops(board: chess.Board) -> bool:
    white = list(board.pieces(chess.BISHOP, chess.WHITE))
    black = list(board.pieces(chess.BISHOP, chess.BLACK))
    if not white or not black:
        return False
    return any(_bishop_square_color(w) != _bishop_square_color(b) for w in white for b in black)


def _king_safe_access(board: chess.Board, color: chess.Color, square: int) -> bool:
    king = board.king(color)
    if king is None:
        return False
    piece = board.piece_at(square)
    if piece and piece.color == color:
        return False
    return not board.is_attacked_by(not color, square)


def _king_mobility(board: chess.Board, color: chess.Color) -> int:
    king = board.king(color)
    if king is None:
        return 0
    return sum(1 for sq in chess.SQUARES if chess.square_distance(king, sq) == 1 and _king_safe_access(board, color, sq))


def _ray_mobility(board: chess.Board, square: int) -> int:
    piece = board.piece_at(square)
    if not piece or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return 0
    return len(board.attacks(square))


def _material_count(board: chess.Board) -> int:
    return sum(PIECE_VALUES[p.piece_type] for p in board.piece_map().values() if p.piece_type != chess.KING)


def _resolve_move(board: chess.Board, uci: Optional[str]) -> Optional[chess.Move]:
    if not uci:
        return None
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def move_effects(board: chess.Board, move: chess.Move, side: chess.Color) -> dict:
    before = board.copy(stack=False)
    moved_piece = before.piece_at(move.from_square)
    captured = before.piece_at(move.to_square)
    before_open = _open_files(before)
    before_space = _space_score(before, side)
    before_center = _center_control(before, side)
    before_king_mob = _king_mobility(before, side)
    before_material = _material_count(before)
    before_ray = _ray_mobility(before, move.from_square)
    from_attacked = before.is_attacked_by(not side, move.from_square)
    from_defenders = len(before.attackers(side, move.from_square))

    after = before.copy(stack=False)
    after.push(move)
    after_open = _open_files(after)
    after_space = _space_score(after, side)
    after_center = _center_control(after, side)
    after_king_mob = _king_mobility(after, side)
    after_material = _material_count(after)
    after_ray = _ray_mobility(after, move.to_square)
    to_attacked = after.is_attacked_by(not side, move.to_square)
    to_defenders = len(after.attackers(side, move.to_square))

    target_attacks = []
    for sq in after.attacks(move.to_square):
        p = after.piece_at(sq)
        if p and p.color != side:
            target_attacks.append({'square': chess.square_name(sq), 'piece': _piece_name(p), 'value': PIECE_VALUES[p.piece_type]})

    newly_defended = []
    for sq in after.attacks(move.to_square):
        p = after.piece_at(sq)
        if p and p.color == side and not before.is_attacked_by(side, sq):
            newly_defended.append({'square': chess.square_name(sq), 'piece': _piece_name(p)})

    return {
        'move': move.uci(), 'from': chess.square_name(move.from_square), 'to': chess.square_name(move.to_square),
        'moving_piece': _piece_name(moved_piece), 'captured_piece': _piece_name(captured) if captured else None,
        'capture': before.is_capture(move), 'check': after.is_check(), 'checkmate': after.is_checkmate(),
        'open_files_before': sorted(before_open), 'open_files_after': sorted(after_open),
        'new_open_files': sorted(after_open - before_open),
        'center_control_delta': after_center - before_center,
        'space_delta': after_space - before_space,
        'king_mobility_delta': after_king_mob - before_king_mob,
        'material_delta': after_material - before_material,
        'ray_mobility_delta': after_ray - before_ray,
        'from_attacked': from_attacked, 'to_safe': not to_attacked,
        'defender_delta': to_defenders - from_defenders,
        'targets': target_attacks, 'newly_defended': newly_defended,
        'after_fen': after.fen(),
    }


def _intent(text: str) -> str:
    t = _norm(text)
    if any(p in t for p in ('what if', 'suppose', 'if black', 'if white', 'responded with', 'responds with')):
        return 'what_if'
    if any(p in t for p in ('why', 'explain', 'what is the idea', 'what does this do')):
        return 'explain_move'
    if any(p in t for p in ('is this', 'isnt this', 'does this', 'would this', 'i thought', 'i think', 'because', 'about the')):
        return 'validate_claim'
    return 'discuss_position'


def _extract_square(text: str) -> Optional[str]:
    m = re.search(r'\b([a-h][1-8])\b', text.lower())
    return m.group(1) if m else None


def _extract_file(text: str) -> Optional[str]:
    m = re.search(r'\b([a-h])(?:-|\s*)file\b', text.lower())
    return m.group(1) if m else None


def _match_builtin(text: str) -> Optional[str]:
    t = _norm(text)
    for alias, key in sorted(BUILTIN_ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if alias in t:
            return key
    return None


def _match_template(text: str) -> Optional[str]:
    t = _norm(text)
    patterns = [
        ('opposite_colored_bishops', ('opposite colored bishop', 'opposite-colored bishop', 'opposite colour bishop', 'opposite-coloured bishop', 'opposite bishop')),
        ('open_file_control', ('open file', 'control the file', 'control a file', 'controlling a file', 'file control', 'rook file')),
        ('central_space', ('central space', 'center control', 'centre control', 'control the center', 'space advantage')),
        ('king_route', ('for my king', 'for the king', 'king route', 'path for the king', 'king path')),
        ('square_clearance', ('open up a square', 'opening up a square', 'opens a square', 'open a square', 'clear the square', 'clears the square', 'vacate')),
        ('long_diagonal', ('long diagonal', 'open diagonal', 'diagonal control')),
        ('outpost', ('outpost', 'strong square')),
        ('bishop_pair', ('bishop pair', 'two bishops')),
    ]
    for key, terms in patterns:
        if any(term in t for term in terms):
            return key
    return None


def parse_message_rules(text: str) -> tuple[str, list[ParsedClaim]]:
    t = _norm(text)
    intent = _intent(text)
    claims: list[ParsedClaim] = []
    square = _extract_square(text)
    file_name = _extract_file(text)

    builtin = _match_builtin(text)
    template = _match_template(text)
    if template is None and file_name and 'file' in t and ('open' in t or 'control' in t or 'controlling' in t):
        template = 'open_file_control'

    if 'attack' in t or 'threat' in t:
        claims.append(ParsedClaim('attack_or_threat', text, square=square, existing_concept=builtin, confidence=.76))
    if any(term in t for term in ('defend', 'protect', 'defense', 'defence', 'save the')):
        claims.append(ParsedClaim('defense', text, square=square, existing_concept=builtin, confidence=.78))
    if any(term in t for term in ('trade', 'exchange', 'simplif')):
        claims.append(ParsedClaim('simplification', text, existing_concept='simplification', confidence=.85))
    if template == 'open_file_control':
        claims.append(ParsedClaim('file_control', text, file=file_name, candidate_template=template, confidence=.9))
    elif template == 'opposite_colored_bishops':
        claims.append(ParsedClaim('opposite_colored_bishops', text, candidate_template=template, confidence=.95))
    elif template == 'central_space':
        claims.append(ParsedClaim('central_space', text, candidate_template=template, confidence=.88))
    elif template in ('square_clearance', 'king_route'):
        claims.append(ParsedClaim('square_clearance', text, square=square, candidate_template=template, confidence=.88))
    elif template == 'long_diagonal':
        claims.append(ParsedClaim('long_diagonal', text, candidate_template=template, confidence=.85))
    elif template == 'outpost':
        claims.append(ParsedClaim('outpost', text, square=square, candidate_template=template, confidence=.85))
    elif template == 'bishop_pair':
        claims.append(ParsedClaim('bishop_pair', text, candidate_template=template, confidence=.9))

    if builtin and not any(c.existing_concept == builtin for c in claims):
        claims.append(ParsedClaim('concept_hypothesis', text, existing_concept=builtin, confidence=.82))

    if not claims:
        # A generic claim remains useful conversationally but is deliberately not
        # eligible to create a concept until it becomes testable.
        claims.append(ParsedClaim('general_hypothesis', text, square=square, confidence=.45))

    return intent, claims[:4]


def _parse_ollama(text: str, settings: dict) -> Optional[tuple[str, list[ParsedClaim]]]:
    if not settings.get('adaptive_coach_use_ollama'):
        return None
    base = str(settings.get('ollama_base_url') or 'http://127.0.0.1:11434').rstrip('/')
    model = str(settings.get('ollama_model') or 'qwen2.5:7b')
    schema_prompt = '''You parse chess-coaching user text into JSON only. Return {"intent":...,"claims":[...]}. Intents: validate_claim, explain_move, what_if, discuss_position. Claim types: file_control, opposite_colored_bishops, central_space, square_clearance, simplification, attack_or_threat, defense, long_diagonal, outpost, bishop_pair, concept_hypothesis, general_hypothesis. candidate_template, when applicable, must be one of: open_file_control, opposite_colored_bishops, central_space, square_clearance, king_route, long_diagonal, outpost, bishop_pair. Each claim can include square (a1-h8), file (a-h), candidate_template, existing_concept. Never decide whether a claim is true; only parse it.'''
    payload = {
        'model': model,
        'stream': False,
        'format': 'json',
        'messages': [
            {'role': 'system', 'content': schema_prompt},
            {'role': 'user', 'content': text},
        ],
        'options': {'temperature': 0.0},
    }
    try:
        response = requests.post(f'{base}/api/chat', json=payload, timeout=12)
        response.raise_for_status()
        raw = response.json()['message']['content']
        data = json.loads(raw)
        claims = []
        for item in data.get('claims', [])[:4]:
            claims.append(ParsedClaim(
                claim_type=str(item.get('claim_type') or 'general_hypothesis'),
                raw_claim=text,
                subject=item.get('subject'), object=item.get('object'),
                square=item.get('square'), file=item.get('file'),
                candidate_template=item.get('candidate_template'),
                existing_concept=item.get('existing_concept'),
                confidence=.82,
            ))
        return str(data.get('intent') or _intent(text)), claims or parse_message_rules(text)[1]
    except Exception:
        return None


def parse_coach_message(text: str, settings: dict) -> tuple[str, list[ParsedClaim], str]:
    ollama = _parse_ollama(text, settings)
    if ollama:
        return ollama[0], ollama[1], 'ollama'
    intent, claims = parse_message_rules(text)
    return intent, claims, 'rules'


def _solution_effects(position_row) -> tuple[chess.Board, chess.Color, Optional[chess.Move], dict]:
    board = chess.Board(position_row['fen'])
    side = chess.WHITE if str(position_row['user_color']).lower() == 'white' else chess.BLACK
    move = _resolve_move(board, position_row['best_move_uci'])
    effects = move_effects(board, move, side) if move else {}
    return board, side, move, effects


def _validate_builtin_claim(conn, position_id: int, key: str) -> ValidationResult:
    row = conn.execute('''
        SELECT pc.confidence, pc.evidence, lc.name
        FROM position_concepts pc JOIN learning_concepts lc ON lc.key = pc.concept_key
        WHERE pc.position_id = ? AND pc.concept_key = ?
    ''', (position_id, key)).fetchone()
    if row:
        return ValidationResult('confirmed', min(.98, float(row['confidence']) + .05),
                                f"Yes. This position is already tagged as {row['name']}: {row['evidence']}",
                                {'existing_label': key}, key)
    concept = conn.execute('SELECT name FROM learning_concepts WHERE key = ?', (key,)).fetchone()
    name = concept['name'] if concept else key.replace('_', ' ')
    return ValidationResult('uncertain', .48,
                            f"{name} is a reasonable idea to consider, but the current classifier does not find strong enough board evidence to make it the main explanation here.",
                            {'existing_label': key, 'matched': False}, key)


def validate_claim(conn, position_row, claim: ParsedClaim) -> ValidationResult:
    board, side, best, fx = _solution_effects(position_row)
    if claim.existing_concept:
        return _validate_builtin_claim(conn, position_row['id'], claim.existing_concept)
    if best is None:
        return ValidationResult('uncertain', .2, 'The saved engine move is no longer legal in this position, so I cannot verify that claim safely.', {})

    after = chess.Board(fx['after_fen'])
    ctype = claim.claim_type

    if ctype == 'file_control':
        before_score, before_details = _heavy_file_control(board, side, claim.file)
        after_score, after_details = _heavy_file_control(after, side, claim.file)
        delta = after_score - before_score
        if delta > 0 or (claim.file and claim.file in fx['new_open_files']):
            file_text = f"the {claim.file}-file" if claim.file else 'an open file'
            return ValidationResult('confirmed', .9,
                f"Yes. The move improves your control of {file_text}. " + (after_details[0] if after_details else 'A heavy piece gains useful access to that file.'),
                {'before_score': before_score, 'after_score': after_score, 'file': claim.file, 'new_open_files': fx['new_open_files']})
        if after_score > 0:
            return ValidationResult('partial', .68, 'The file is strategically relevant, but the solution does not materially increase your control of it; it is a supporting feature rather than the main reason the move works.',
                                    {'before_score': before_score, 'after_score': after_score, 'file': claim.file})
        return ValidationResult('refuted', .86, 'I do not find meaningful open-file control created by the solution move in this position. The move is working for a different tactical or positional reason.',
                                {'before_score': before_score, 'after_score': after_score, 'file': claim.file})

    if ctype == 'opposite_colored_bishops':
        present = _opposite_colored_bishops(board)
        if present:
            return ValidationResult('confirmed', .97, 'Yes. The remaining bishops operate on opposite color complexes, so attacking chances, king exposure, and drawish endgame tendencies should be evaluated through that lens.', {'present': True})
        return ValidationResult('refuted', .98, 'No. This board does not currently contain opposite-colored bishops in the relevant sense.', {'present': False})

    if ctype == 'central_space':
        before_space = _space_score(board, side)
        after_space = _space_score(after, side)
        delta = after_space - before_space
        if delta > 0 or fx['center_control_delta'] > 0:
            return ValidationResult('confirmed', .88, f"Yes. The move improves central influence: center control changes by {fx['center_control_delta']:+d} and the space score by {delta:+d}.",
                                    {'space_before': before_space, 'space_after': after_space, 'center_delta': fx['center_control_delta']})
        return ValidationResult('partial' if after_space >= before_space else 'refuted', .68,
                                'Central space is relevant to the position, but the engine move does not gain measurable central control compared with the current board.',
                                {'space_before': before_space, 'space_after': after_space, 'center_delta': fx['center_control_delta']})

    if ctype == 'square_clearance':
        square_name = claim.square
        if square_name:
            sq = chess.parse_square(square_name)
            was_occupied = board.piece_at(sq) is not None
            now_occupied = after.piece_at(sq) is not None
            king_access = _king_safe_access(after, side, sq)
            if was_occupied and not now_occupied and king_access:
                return ValidationResult('confirmed', .95, f"Yes. The move clears {square_name}, and that square is safe enough to become available to your king. That is a concrete secondary purpose of the move.",
                                        {'square': square_name, 'was_occupied': True, 'now_occupied': False, 'king_access': True})
            if not now_occupied and king_access:
                return ValidationResult('partial', .72, f"{square_name} is available and safe for the king after the move, but it was not strictly the move that cleared it. Your strategic interpretation is relevant, but not uniquely caused by the solution.",
                                        {'square': square_name, 'king_access': True})
            return ValidationResult('refuted', .85, f"The solution does not make {square_name} a safe usable square for your king, so that specific explanation is not supported by the board.",
                                    {'square': square_name, 'king_access': king_access, 'now_occupied': now_occupied})
        if fx['king_mobility_delta'] > 0:
            return ValidationResult('confirmed', .82, f"Yes. The move increases your king's safe mobility by {fx['king_mobility_delta']} square(s), which supports the idea of clearing access for the king.", {'king_mobility_delta': fx['king_mobility_delta']})
        return ValidationResult('uncertain', .48, 'I need a specific square or route to test the clearance idea precisely. I do not see a general increase in king mobility from the solution move.', {'king_mobility_delta': fx['king_mobility_delta']})

    if ctype == 'simplification':
        if fx['capture'] and (fx['captured_piece'] == 'queen' or fx['material_delta'] < 0):
            return ValidationResult('confirmed', .9, f"Yes. The solution simplifies immediately by exchanging material{', including the queen' if fx['captured_piece'] == 'queen' else ''}. That reduction in complexity is a real part of why the move is practical.", fx)
        return ValidationResult('partial', .6, 'The resulting line may simplify later, but the solution move itself does not produce a major immediate simplification.', fx)

    if ctype == 'attack_or_threat':
        strong_targets = [t for t in fx['targets'] if t['value'] >= 3]
        if fx['check'] or strong_targets:
            details = 'gives check' if fx['check'] else f"attacks the {strong_targets[0]['piece']} on {strong_targets[0]['square']}"
            return ValidationResult('confirmed', .9, f"Yes. The solution {details}, so the attacking idea is concrete rather than merely positional.", fx)
        return ValidationResult('refuted', .76, 'The solution does not create a direct check or attack on a valuable target. Its value is more positional or defensive.', fx)

    if ctype == 'defense':
        if fx['from_attacked'] and fx['to_safe']:
            return ValidationResult('confirmed', .94, f"Yes. The {fx['moving_piece']} begins under attack and the solution moves it to safety while preserving the position.", fx)
        if fx['defender_delta'] > 0 or fx['newly_defended']:
            return ValidationResult('confirmed', .86, 'Yes. The move increases defensive coverage and improves how your pieces protect one another.', fx)
        return ValidationResult('partial', .56, 'The move may help defensively through tactics or simplification, but it does not directly add measurable protection to the moved piece or a nearby target.', fx)

    if ctype == 'long_diagonal':
        if fx['moving_piece'] in ('bishop', 'queen') and fx['ray_mobility_delta'] >= 2:
            return ValidationResult('confirmed', .86, f"Yes. The {fx['moving_piece']} gains {fx['ray_mobility_delta']} additional attacked squares, which is a concrete increase in diagonal/line activity.", fx)
        return ValidationResult('refuted', .72, 'The solution does not materially increase bishop/queen ray activity, so long-diagonal control is not strongly supported here.', fx)

    if ctype == 'bishop_pair':
        has_pair = len(board.pieces(chess.BISHOP, side)) >= 2
        return ValidationResult('confirmed' if has_pair else 'refuted', .95,
                                'Yes. You have the bishop pair in this position, so preserving and activating both bishops is meaningful.' if has_pair else 'No. You do not currently have two bishops, so the bishop-pair concept does not apply.',
                                {'has_bishop_pair': has_pair})

    if ctype == 'outpost':
        dest = best.to_square
        piece = after.piece_at(dest)
        enemy_pawn_attack = after.is_attacked_by(not side, dest) and any(
            p.piece_type == chess.PAWN and p.color != side and dest in after.attacks(sq)
            for sq, p in after.piece_map().items()
        )
        advanced = chess.square_rank(dest) >= 4 if side == chess.WHITE else chess.square_rank(dest) <= 3
        if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and advanced and not enemy_pawn_attack:
            return ValidationResult('confirmed', .84, f"Yes. The {fx['moving_piece']} lands on {chess.square_name(dest)}, an advanced square that enemy pawns cannot readily chase away.", fx)
        return ValidationResult('refuted', .7, 'The destination does not satisfy the main structural features of an outpost in this position.', fx)

    return ValidationResult('uncertain', .38,
        'That is a plausible chess idea, but I cannot reduce it to a board test confidently enough yet. I will keep it as conversation context rather than teaching it as a new learning motif.', fx)


def _slug(text: str) -> str:
    value = re.sub(r'[^a-z0-9]+', '_', _norm(text)).strip('_')
    return value[:48] or 'concept'


def _candidate_key(account_id: int, template_key: str) -> str:
    return f'adaptive_{account_id}_{_slug(template_key)}'


def _existing_concept_for_template(conn, account_id: int, template_key: str):
    template = CONCEPT_TEMPLATES.get(template_key)
    if not template:
        return None
    aliases = {_norm(a) for a in template['aliases']} | {_norm(template['name'])}
    rows = conn.execute('''
        SELECT * FROM learning_concepts
        WHERE account_id IS NULL OR account_id = ?
    ''', (account_id,)).fetchall()
    for row in rows:
        names = {_norm(row['name']), _norm(row['description'])}
        try:
            names |= {_norm(a) for a in json.loads(row['aliases_json'] or '[]')}
        except Exception:
            pass
        if aliases & names:
            return row
    return None


def ensure_candidate_concept(conn, account_id: int, template_key: str, claim_id: int, validation: ValidationResult):
    template = CONCEPT_TEMPLATES.get(template_key)
    if not template or validation.verdict not in ('confirmed', 'partial'):
        return None
    existing = _existing_concept_for_template(conn, account_id, template_key)
    if existing:
        return existing['key']
    key = _candidate_key(account_id, template_key)
    base_score = .30 * validation.confidence + .20 * 1.0 + .20 * .85 + .15 * 1.0 + .15 * .95
    conn.execute('''
        INSERT INTO learning_concepts(
            key, name, family, description, priority, source, status, account_id,
            aliases_json, detector_json, concept_score, evidence_count, validated_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'user', 'candidate', ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            concept_score = MAX(learning_concepts.concept_score, excluded.concept_score),
            evidence_count = learning_concepts.evidence_count + 1,
            validated_count = learning_concepts.validated_count + excluded.validated_count,
            updated_at = CURRENT_TIMESTAMP
    ''', (
        key, template['name'], template['family'], template['description'], template['priority'],
        account_id, json.dumps(template['aliases']), json.dumps(template['detector']),
        round(base_score, 4), 1 if validation.verdict == 'confirmed' else 0,
    ))
    return key


def _adaptive_detector_match(board: chess.Board, best: chess.Move, side: chess.Color, detector: dict) -> tuple[float, str]:
    dtype = detector.get('type')
    fx = move_effects(board, best, side)
    after = chess.Board(fx['after_fen'])
    if dtype == 'open_file_control':
        before_score, _ = _heavy_file_control(board, side)
        after_score, details = _heavy_file_control(after, side)
        if after_score > before_score:
            return .88, details[0] if details else 'The solution improves heavy-piece control of an open file.'
    elif dtype == 'opposite_colored_bishops' and _opposite_colored_bishops(board):
        return .9, 'The position contains bishops operating on opposite color complexes.'
    elif dtype == 'central_space' and (fx['center_control_delta'] > 0 or fx['space_delta'] > 0):
        return .82, f"The solution changes central control by {fx['center_control_delta']:+d} and space by {fx['space_delta']:+d}."
    elif dtype == 'square_clearance':
        if fx['king_mobility_delta'] > 0 or fx['new_open_files']:
            return .76, 'The move clears access and increases useful mobility/lines for another piece.'
    elif dtype == 'king_route' and fx['king_mobility_delta'] > 0:
        return .86, f"The move increases safe king mobility by {fx['king_mobility_delta']} square(s)."
    elif dtype == 'long_diagonal' and fx['moving_piece'] in ('bishop', 'queen') and fx['ray_mobility_delta'] >= 2:
        return .82, f"The {fx['moving_piece']} gains {fx['ray_mobility_delta']} squares of ray mobility."
    elif dtype == 'outpost':
        dest = best.to_square
        piece = after.piece_at(dest)
        if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP):
            advanced = chess.square_rank(dest) >= 4 if side == chess.WHITE else chess.square_rank(dest) <= 3
            enemy_pawn_can_challenge = any(
                p.color != side and p.piece_type == chess.PAWN and dest in after.attacks(sq)
                for sq, p in after.piece_map().items()
            )
            if advanced and not enemy_pawn_can_challenge:
                return .8, f"The {chess.piece_name(piece.piece_type)} reaches a stable advanced square on {chess.square_name(dest)}."
    elif dtype == 'bishop_pair' and len(board.pieces(chess.BISHOP, side)) >= 2:
        return .78, 'The side to move has two bishops, making bishop-pair considerations relevant.'
    return 0.0, ''


def apply_adaptive_concepts_to_position(conn, position_id: int, account_id: Optional[int] = None) -> int:
    row = conn.execute('''
        SELECT tp.*, j.account_id FROM training_positions tp
        JOIN analysis_jobs j ON j.id = tp.job_id WHERE tp.id = ?
    ''', (position_id,)).fetchone()
    if not row:
        return 0
    account_id = account_id or row['account_id']
    try:
        board = chess.Board(row['fen'])
        best = chess.Move.from_uci(row['best_move_uci'])
        if best not in board.legal_moves:
            return 0
    except Exception:
        return 0
    side = chess.WHITE if row['user_color'] == 'white' else chess.BLACK
    concepts = conn.execute('''
        SELECT * FROM learning_concepts
        WHERE account_id = ? AND source <> 'built_in'
          AND status IN ('candidate', 'personal', 'promoted')
          AND detector_json IS NOT NULL
    ''', (account_id,)).fetchall()
    added = 0
    for concept in concepts:
        try:
            detector = json.loads(concept['detector_json'])
        except Exception:
            continue
        confidence, evidence = _adaptive_detector_match(board, best, side, detector)
        if confidence < .66:
            continue
        conn.execute('''
            INSERT INTO position_concepts(position_id, concept_key, confidence, is_primary, evidence, classifier_version)
            VALUES (?, ?, ?, 0, ?, ?)
            ON CONFLICT(position_id, concept_key) DO UPDATE SET
              confidence = excluded.confidence, evidence = excluded.evidence,
              classifier_version = excluded.classifier_version
        ''', (position_id, concept['key'], confidence, evidence, ADAPTIVE_CLASSIFIER_VERSION))
        added += 1
    if added:
        _refresh_concept_statuses(conn, account_id)
    return added


def _refresh_concept_statuses(conn, account_id: int):
    settings = get_settings(conn)
    min_games = int(settings.get('adaptive_concept_min_games', 2))
    min_claims = int(settings.get('adaptive_concept_min_verified_claims', 1))
    threshold = float(settings.get('adaptive_concept_promotion_score', .68))
    concepts = conn.execute('''
        SELECT * FROM learning_concepts
        WHERE account_id = ? AND source <> 'built_in'
    ''', (account_id,)).fetchall()
    for concept in concepts:
        stats = conn.execute('''
            SELECT COUNT(DISTINCT COALESCE(tp.game_id, 'position:' || tp.id)) AS games,
                   COUNT(DISTINCT tp.id) AS positions
            FROM position_concepts pc
            JOIN training_positions tp ON tp.id = pc.position_id
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE pc.concept_key = ? AND j.account_id = ?
        ''', (concept['key'], account_id)).fetchone()
        claim_stats = conn.execute('''
            SELECT COUNT(*) AS n FROM coach_claims
            WHERE account_id = ? AND concept_key = ? AND verdict = 'confirmed'
        ''', (account_id, concept['key'])).fetchone()
        games = int(stats['games'] or 0)
        positions = int(stats['positions'] or 0)
        claims = int(claim_stats['n'] or 0)
        recurrence = min(1.0, games / max(1, min_games))
        score = min(1.0, .55 * float(concept['concept_score'] or .5) + .30 * recurrence + .15 * min(1.0, claims / max(1, min_claims)))
        status = concept['status']
        if games >= min_games and claims >= min_claims and score >= threshold:
            status = 'personal'
        conn.execute('''
            UPDATE learning_concepts SET distinct_games = ?, evidence_count = MAX(evidence_count, ?),
                validated_count = MAX(validated_count, ?), concept_score = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE key = ?
        ''', (games, positions, claims, round(score, 4), status, concept['key']))


def rescan_concept_across_account(conn, account_id: int, concept_key: str) -> dict:
    concept = conn.execute('SELECT * FROM learning_concepts WHERE key = ?', (concept_key,)).fetchone()
    if not concept or not concept['detector_json']:
        return {'positions': 0, 'games': 0, 'status': concept['status'] if concept else None}
    rows = conn.execute('''
        SELECT tp.id FROM training_positions tp JOIN analysis_jobs j ON j.id = tp.job_id
        WHERE j.account_id = ?
    ''', (account_id,)).fetchall()
    for row in rows:
        apply_adaptive_concepts_to_position(conn, row['id'], account_id)
    _refresh_concept_statuses(conn, account_id)
    stats = conn.execute('''
        SELECT lc.name, lc.status, lc.concept_score,
               COUNT(DISTINCT tp.id) AS positions,
               COUNT(DISTINCT COALESCE(tp.game_id, 'position:' || tp.id)) AS games
        FROM learning_concepts lc
        LEFT JOIN position_concepts pc ON pc.concept_key = lc.key
        LEFT JOIN training_positions tp ON tp.id = pc.position_id
        LEFT JOIN analysis_jobs j ON j.id = tp.job_id AND j.account_id = ?
        WHERE lc.key = ? GROUP BY lc.key
    ''', (account_id, concept_key)).fetchone()
    return dict(stats) if stats else {'positions': 0, 'games': 0, 'status': concept['status']}


def get_or_create_thread(conn, position_id: int, account_id: int) -> int:
    row = conn.execute('SELECT id FROM coach_threads WHERE position_id = ? AND account_id = ?', (position_id, account_id)).fetchone()
    if row:
        return row['id']
    cur = conn.execute('INSERT INTO coach_threads(account_id, position_id) VALUES (?, ?)', (account_id, position_id))
    return cur.lastrowid


def coach_history(conn, position_id: int, account_id: int) -> list[dict]:
    thread = conn.execute('SELECT id FROM coach_threads WHERE position_id = ? AND account_id = ?', (position_id, account_id)).fetchone()
    if not thread:
        return []
    rows = conn.execute('''
        SELECT cm.id, cm.role, cm.content, cm.structured_json, cm.created_at,
               cm.generation_version, cmf.rating AS feedback_rating, cmf.suggested_text AS feedback_suggested_text
        FROM coach_messages cm
        LEFT JOIN coach_message_feedback cmf ON cmf.message_id = cm.id
        WHERE cm.thread_id = ?
        ORDER BY cm.id
    ''', (thread['id'],)).fetchall()
    return [dict(r) for r in rows]


def _concept_note(conn, concept_key: Optional[str]) -> Optional[str]:
    if not concept_key:
        return None
    row = conn.execute('SELECT name, status, distinct_games FROM learning_concepts WHERE key = ?', (concept_key,)).fetchone()
    if not row:
        return None
    if row['status'] == 'candidate':
        return f"I saved this as a candidate concept: {row['name']}. I will test it against your other positions and future analysis passes."
    if row['status'] in ('personal', 'promoted'):
        return f"This has become a personal learning motif: {row['name']} ({row['distinct_games'] or 0} games matched)."
    return f"This maps to the existing learning motif: {row['name']}."


def handle_coach_message(conn, position_row, text: str, displayed_fen: Optional[str] = None, dialogue_context: Optional[dict] = None) -> dict:
    account_id = position_row['account_id']
    settings = get_settings(conn)
    thread_id = get_or_create_thread(conn, position_row['id'], account_id)
    conn.commit()

    context_fen = displayed_fen or position_row['fen']
    try:
        chess.Board(context_fen)
    except Exception:
        context_fen = position_row['fen']

    reasoned = reason_about_message(
        conn, thread_id, position_row, text, context_fen, settings,
        dialogue_context=dialogue_context or {},
    )
    if reasoned is not None:
        structured_user = {
            'intent': reasoned.get('intent'),
            'interpretation': reasoned.get('interpretation'),
            'parser': reasoned.get('parser') or COACH_REASONER_VERSION,
            'displayed_fen': context_fen,
            'dialogue_context': dialogue_context or {},
            'temporal_context': reasoned.get('temporal_context') or {},
        }
        user_cur = conn.execute(
            "INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?, 'user', ?, ?)",
            (thread_id, text, json.dumps(structured_user)),
        )
        verdict = reasoned.get('verdict') or 'uncertain'
        confidence = float(reasoned.get('confidence') or .5)
        evidence = reasoned.get('evidence') or {}
        interpretation = reasoned.get('interpretation') or {}
        move_san = interpretation.get('move_san')
        move_uci = interpretation.get('move_uci')
        claims = reasoned.get('claims') or []

        # Persist the reconstructed utterance as an auditable conversational
        # claim.  Individual causal claims are kept inside structured_json so
        # later versions can learn from successful/failed interpretations.
        conn.execute(
            """
            INSERT INTO coach_claims(thread_id, message_id, position_id, account_id, intent, claim_type,
                subject, object, square, file, raw_claim, verdict, confidence, explanation, structured_json)
            VALUES (?, ?, ?, ?, ?, 'conversation_hypothesis', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id, user_cur.lastrowid, position_row['id'], account_id,
                reasoned.get('intent'), move_san, move_uci, None, None, text, verdict, confidence,
                reasoned['reply'],
                json.dumps({
                    'interpretation': interpretation,
                    'claims': claims,
                    'evidence': evidence,
                    'analysis_context': reasoned.get('analysis_context') or {},
                    'displayed_fen': context_fen,
                    'reasoner_version': COACH_REASONER_VERSION,
                }),
            ),
        )
        assistant_structured = {
            'intent': reasoned.get('intent'),
            'grounded': True,
            'reasoner_version': COACH_REASONER_VERSION,
            'claims': claims or [{
                'verdict': verdict,
                'confidence': confidence,
                'claim_type': 'conversation_hypothesis',
            }],
            'analysis_context': reasoned.get('analysis_context') or {},
            'interpretation': interpretation,
        }
        assistant_cur = conn.execute(
            "INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?, 'assistant', ?, ?)",
            (thread_id, reasoned['reply'], json.dumps(assistant_structured)),
        )
        conn.execute('UPDATE coach_threads SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (thread_id,))
        conn.execute('UPDATE coach_messages SET generation_version=? WHERE id=?',
                     (position_row['coaching_version'], assistant_cur.lastrowid))
        conn.commit()
        return {
            'reply': reasoned['reply'],
            'claims': assistant_structured['claims'],
            'concept_updates': [],
            'parser': reasoned.get('parser') or COACH_REASONER_VERSION,
            'message_id': assistant_cur.lastrowid,
        }

    intent, claims, parser = parse_coach_message(text, settings)
    user_cur = conn.execute(
        "INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?, 'user', ?, ?)",
        (thread_id, text, json.dumps({
            'intent': intent,
            'claims': [asdict(c) for c in claims],
            'parser': parser,
            'displayed_fen': context_fen,
            'dialogue_context': dialogue_context or {},
        })),
    )
    user_message_id = user_cur.lastrowid

    session_solved = bool(position_row['learned']) or bool((dialogue_context or {}).get('session_solved'))
    if not session_solved:
        response = (
            'That is a useful hypothesis. I can test it fully after you solve the position; '
            'for now, use it as a lens and compare whether your candidate move improves that '
            'feature without creating a new tactical problem.'
        )
        for claim in claims:
            conn.execute(
                """
                INSERT INTO coach_claims(thread_id, message_id, position_id, account_id, intent, claim_type,
                    subject, object, square, file, raw_claim, verdict, confidence, explanation, structured_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    thread_id, user_message_id, position_row['id'], account_id, intent, claim.claim_type,
                    claim.subject, claim.object, claim.square, claim.file, claim.raw_claim, claim.confidence,
                    response, json.dumps(asdict(claim)),
                ),
            )
        assistant_cur = conn.execute(
            "INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?, 'assistant', ?, ?)",
            (thread_id, response, json.dumps({'spoiler_safe': True})),
        )
        conn.execute('UPDATE coach_messages SET generation_version=? WHERE id=?',
                     (position_row['coaching_version'], assistant_cur.lastrowid))
        conn.commit()
        return {'reply': response, 'claims': [], 'concept_updates': [], 'message_id': assistant_cur.lastrowid}

    results = []
    concept_updates = []
    sentences = []
    for claim in claims:
        validation = validate_claim(conn, position_row, claim)
        concept_key = validation.concept_key
        if not concept_key and claim.candidate_template and validation.verdict in ('confirmed', 'partial'):
            claim_cur = conn.execute(
                """
                INSERT INTO coach_claims(thread_id, message_id, position_id, account_id, intent, claim_type,
                    subject, object, square, file, raw_claim, verdict, confidence, explanation, structured_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id, user_message_id, position_row['id'], account_id, intent, claim.claim_type,
                    claim.subject, claim.object, claim.square, claim.file, claim.raw_claim, validation.verdict,
                    validation.confidence, validation.explanation,
                    json.dumps({'claim': asdict(claim), 'validation': validation.evidence}),
                ),
            )
            concept_key = ensure_candidate_concept(
                conn, account_id, claim.candidate_template, claim_cur.lastrowid, validation
            )
            if concept_key:
                conn.execute('UPDATE coach_claims SET concept_key = ? WHERE id = ?', (concept_key, claim_cur.lastrowid))
                conn.execute(
                    """
                    INSERT INTO concept_evidence(concept_key, account_id, position_id, claim_id, verdict, confidence, evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        concept_key, account_id, position_row['id'], claim_cur.lastrowid,
                        validation.verdict, validation.confidence, json.dumps(validation.evidence),
                    ),
                )
                stats = rescan_concept_across_account(conn, account_id, concept_key)
                concept_updates.append({'concept_key': concept_key, **stats})
        else:
            claim_cur = conn.execute(
                """
                INSERT INTO coach_claims(thread_id, message_id, position_id, account_id, intent, claim_type,
                    subject, object, square, file, raw_claim, verdict, confidence, explanation, concept_key, structured_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id, user_message_id, position_row['id'], account_id, intent, claim.claim_type,
                    claim.subject, claim.object, claim.square, claim.file, claim.raw_claim, validation.verdict,
                    validation.confidence, validation.explanation, concept_key,
                    json.dumps({'claim': asdict(claim), 'validation': validation.evidence}),
                ),
            )
            if concept_key:
                conn.execute(
                    """
                    INSERT INTO concept_evidence(concept_key, account_id, position_id, claim_id, verdict, confidence, evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        concept_key, account_id, position_row['id'], claim_cur.lastrowid,
                        validation.verdict, validation.confidence, json.dumps(validation.evidence),
                    ),
                )
        sentences.append(validation.explanation)
        note = _concept_note(conn, concept_key)
        if note and note not in sentences:
            sentences.append(note)
        results.append({
            'claim': asdict(claim), 'verdict': validation.verdict,
            'confidence': validation.confidence, 'explanation': validation.explanation,
            'concept_key': concept_key,
        })

    response = ' '.join(dict.fromkeys(sentences))
    assistant_cur = conn.execute(
        "INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?, 'assistant', ?, ?)",
        (thread_id, response, json.dumps({'intent': intent, 'claims': results, 'concept_updates': concept_updates})),
    )
    conn.execute('UPDATE coach_threads SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (thread_id,))
    conn.execute('UPDATE coach_messages SET generation_version=? WHERE id=?',
                 (position_row['coaching_version'], assistant_cur.lastrowid))
    conn.commit()
    return {
        'reply': response, 'claims': results, 'concept_updates': concept_updates,
        'parser': parser, 'message_id': assistant_cur.lastrowid,
    }

