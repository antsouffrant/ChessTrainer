from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Optional

import chess
import requests

from engine_service import evaluate_fen, evaluate_move_quality, evaluate_multipv

COACH_REASONER_VERSION = 'coach-reasoner-v3.0-unified-explanation'

from coach_learning import (find_requested_motif, wants_general_explanation, explain_general,
                            probe_motif, shared_move_explanation)

PIECE_WORDS = {
    'pawn': chess.PAWN, 'pawns': chess.PAWN,
    'knight': chess.KNIGHT, 'knights': chess.KNIGHT, 'horse': chess.KNIGHT, 'horses': chess.KNIGHT,
    'bishop': chess.BISHOP, 'bishops': chess.BISHOP,
    'rook': chess.ROOK, 'rooks': chess.ROOK, 'castle': chess.ROOK,
    'queen': chess.QUEEN, 'queens': chess.QUEEN,
    'king': chess.KING, 'kings': chess.KING,
}

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}

QUESTION_MARKERS = (
    'what if', 'what about', 'how about', 'why not', 'could i', 'could we', 'can i', 'should i',
    'could black', 'could white', 'can black', 'can white', 'should black', 'should white',
    'instead', 'then', 'after that', 'first', 'would', 'isn\'t', 'doesn\'t', 'don\'t', 'do i',
)

THREAT_MARKERS = (
    'what is the threat', "what's the threat", 'what are they threatening', 'what is black threatening',
    'what is white threatening', 'what am i threatened by', 'what is he threatening', 'what is she threatening',
)

PLAN_MARKERS = (
    'what is the plan', "what's the plan", 'what should i do', 'what am i trying to do',
    'what is the idea', "what's the idea", 'what should my plan be', 'how should i play this',
)

CLAIM_MARKERS = (
    'i think', 'i thought', 'because', 'the point is', 'the idea is', 'this opens', 'this gives',
    'this blocks', 'this defends', 'this attacks', 'this wins', 'this loses', 'this trades',
    'this controls', 'this clears', 'this creates', 'this stops', 'this prevents',
)


@dataclass
class MoveHypothesis:
    move_uci: str
    move_san: str
    score: float
    reasons: list[str]


@dataclass
class Interpretation:
    intent: str
    confidence: float
    context_fen: str
    context_source: str
    move_uci: Optional[str] = None
    move_san: Optional[str] = None
    candidates: Optional[list[dict]] = None
    claims: Optional[list[dict]] = None
    clarification: Optional[str] = None
    parser: str = 'contextual-rules'
    variation_uci: Optional[list[str]] = None
    variation_san: Optional[list[str]] = None


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKD', text or '').lower()
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('…', '...').replace('–', '-').replace('—', '-')
    return re.sub(r'\s+', ' ', text).strip()


def _strip_san_suffix(san: str) -> str:
    return re.sub(r'[+#]+$', '', san or '')


def _piece_type_from_text(text: str) -> Optional[int]:
    t = _norm(text)
    for word, piece_type in PIECE_WORDS.items():
        if re.search(rf'\b{re.escape(word)}\b', t):
            return piece_type
    return None


def _moving_piece_type_from_text(text: str) -> Optional[int]:
    t = _norm(text)
    piece_alt = '(pawn|knight|horse|bishop|rook|castle|queen|king)'
    patterns = [
        rf'\b(?:my|our|the|a|his|her|their)?\s*{piece_alt}\s+(?:to|onto|on|takes?|captures?|blocks?|moves?|goes?|comes?|defends?|attacks?|trades?|checks?)\b',
        rf'\bwith\s+(?:my|our|the|a)?\s*{piece_alt}\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, t)
        if m:
            return PIECE_WORDS.get(m.group(1))
    # If a piece noun is only the object of "take the pawn", it is the
    # target, not the moving piece. Otherwise a lone piece noun is useful.
    target = re.search(rf'\b(?:take|takes|taking|capture|captures|capturing|win|wins|winning|trade|exchange)\s+(?:off\s+)?(?:the\s+)?{piece_alt}\b', t)
    nouns = re.findall(rf'\b{piece_alt}\b', t)
    if target and len(nouns) == 1:
        return None
    return PIECE_WORDS.get(nouns[0]) if nouns else None


def _target_piece_type(text: str) -> Optional[int]:
    t = _norm(text)
    m = re.search(r'\b(?:take|takes|taking|capture|captures|capturing|win|wins|winning|trade|exchange)\s+(?:off\s+)?(?:the\s+)?(pawn|knight|horse|bishop|rook|castle|queen|king)\b', t)
    return PIECE_WORDS.get(m.group(1)) if m else None


def _squares(text: str) -> list[str]:
    return re.findall(r'(?<![a-z0-9])([a-h][1-8])(?![a-z0-9])', _norm(text))




def _move_destination_square(text: str, squares: list[str]) -> Optional[str]:
    t = _norm(text)
    # Squares appearing in a causal clause ("gives my king f2", "opens e4")
    # describe the claimed consequence, not necessarily the move destination.
    explicit = re.search(r'\b(?:to|onto|into|on)\s+([a-h][1-8])\b', t)
    if explicit:
        return explicit.group(1)
    if len(squares) == 1:
        sq = squares[0]
        causal = re.search(rf'\b(?:open|opens|clear|clears|vacate|vacates|give|gives|access|control|controls|defend|defends|attack|attacks)\b[^.?!]{{0,32}}\b{sq}\b', t)
        if causal:
            return None
        return sq
    return None


def _move_source_square(text: str) -> Optional[str]:
    m = re.search(r'\bfrom\s+([a-h][1-8])\b', _norm(text))
    return m.group(1) if m else None


def _capture_target_square(text: str) -> Optional[str]:
    t = _norm(text)
    m = re.search(r'\b(?:pawn|knight|horse|bishop|rook|queen)\s+(?:on|at)\s+([a-h][1-8])\b', t)
    return m.group(1) if m else None

def _explicit_side(text: str) -> Optional[str]:
    t = _norm(text)
    if re.search(r'\bblack\b', t):
        return 'black'
    if re.search(r'\bwhite\b', t):
        return 'white'
    if re.search(r'\b(?:opponent|they|them|their|he|him|his|she|her)\b', t):
        return 'opponent'
    if re.search(r'\b(?:i|me|my|we|our)\b', t):
        return 'self'
    return None


def _action(text: str) -> Optional[str]:
    t = _norm(text)
    tests = [
        ('capture', r'\b(?:take|takes|taking|capture|captures|capturing|grab|win|wins)\b'),
        ('block', r'\b(?:block|blocks|blocking|interpose|interposes)\b'),
        ('trade', r'\b(?:trade|trades|exchange|exchanges|swap|swaps)\b'),
        ('defend', r'\b(?:defend|defends|protect|protects|cover|covers)\b'),
        ('attack', r'\b(?:attack|attacks|pressure|pressures|target|targets)\b'),
        ('push', r'\b(?:push|pushes|advance|advances)\b'),
        ('move', r'\b(?:move|moves|go|goes|come|comes|jump|jumps|retreat|retreats)\b'),
    ]
    for label, pattern in tests:
        if re.search(pattern, t):
            return label
    return None


def _conversation_state(conn, thread_id: int) -> dict:
    rows = conn.execute(
        '''SELECT cm.role, cm.content, cm.structured_json, cmf.rating AS feedback_rating
           FROM coach_messages cm
           LEFT JOIN coach_message_feedback cmf ON cmf.message_id = cm.id
           WHERE cm.thread_id = ?
           ORDER BY cm.id DESC LIMIT 12''',
        (thread_id,),
    ).fetchall()
    state = {
        'recent_text': [],
        'feedback_examples': [],
        'last_move_uci': None,
        'last_move_san': None,
        'last_resulting_fen': None,
        'last_reply_uci': None,
        'last_reply_san': None,
        'last_after_reply_fen': None,
        'referenced_squares': [],
    }
    for row in rows:
        state['recent_text'].append({'role': row['role'], 'content': row['content']})
        if row['role'] == 'assistant' and row['feedback_rating'] in (-1, 1):
            state['feedback_examples'].append({
                'rating': int(row['feedback_rating']),
                'response': row['content'][:1200],
            })
        try:
            data = json.loads(row['structured_json'] or '{}')
        except Exception:
            continue
        analysis_context = data.get('analysis_context') or {}
        if not state['last_move_uci'] and analysis_context.get('move_uci'):
            state['last_move_uci'] = analysis_context.get('move_uci')
            state['last_move_san'] = analysis_context.get('move_san')
            state['last_resulting_fen'] = analysis_context.get('resulting_fen')
            state['last_reply_uci'] = analysis_context.get('critical_reply_uci')
            state['last_reply_san'] = analysis_context.get('critical_reply_san')
            state['last_after_reply_fen'] = analysis_context.get('after_reply_fen')
            state['referenced_squares'] = list(analysis_context.get('referenced_squares') or [])
    state['recent_text'].reverse()
    state['feedback_examples'].reverse()
    return state


def _choose_context_fen(displayed_fen: str, text: str, state: dict, user_color: str) -> tuple[str, str]:
    """Use the board on screen unless the user clearly refers to a prior hypothetical reply."""
    t = _norm(text)
    board = chess.Board(displayed_fen)
    user_side = chess.WHITE if str(user_color).lower() == 'white' else chess.BLACK
    explicit = _explicit_side(text)

    # Follow-up language such as "what if he checks first?" usually refers to
    # the position after the candidate move discussed immediately before it.
    follow_up = any(marker in t for marker in ('then', 'after that', 'afterwards', 'what if he', 'what if she', 'what if they', 'he can', 'she can', 'they can', 'respond', 'reply'))
    if explicit == 'opponent' and state.get('last_resulting_fen'):
        try:
            branch = chess.Board(state['last_resulting_fen'])
            if branch.turn == (not user_side):
                return branch.fen(), 'previous_hypothesis'
        except Exception:
            pass
    if follow_up and state.get('last_resulting_fen'):
        try:
            return chess.Board(state['last_resulting_fen']).fen(), 'previous_hypothesis'
        except Exception:
            pass
    return board.fen(), 'displayed_board'


def _legal_descriptors(board: chess.Board) -> list[dict]:
    items = []
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        target = board.piece_at(move.to_square)
        san = board.san(move)
        after = board.copy(stack=False)
        after.push(move)
        items.append({
            'uci': move.uci(),
            'san': san,
            'san_plain': _strip_san_suffix(san),
            'piece': chess.piece_name(piece.piece_type) if piece else None,
            'piece_type': piece.piece_type if piece else None,
            'from': chess.square_name(move.from_square),
            'to': chess.square_name(move.to_square),
            'capture': board.is_capture(move),
            'captured_piece': chess.piece_name(target.piece_type) if target else ('pawn' if board.is_en_passant(move) else None),
            'check': after.is_check(),
            'mate': after.is_checkmate(),
            'castle': board.is_castling(move),
        })
    return items


def _exact_move_tokens(text: str) -> list[str]:
    cleaned = (text or '').replace('0-0-0', 'O-O-O').replace('0-0', 'O-O')
    pattern = r'(?<![A-Za-z0-9])(?:O-O-O|O-O|[KQRBN](?:[a-h]|[1-8])?x?[a-h][1-8](?:=[QRBN])?[+#]?|[a-h]x[a-h][1-8](?:=[QRBN])?[+#]?|[a-h][1-8](?:=[QRBN])?[+#]?|[a-h][1-8][a-h][1-8][qrbn]?)(?![A-Za-z0-9])'
    return re.findall(pattern, cleaned)


def _variation_from_text(board: chess.Board, text: str) -> tuple[list[str], list[str]]:
    tokens = _exact_move_tokens(text)
    if len(tokens) < 2:
        return [], []
    replay = board.copy(stack=False)
    ucis = []
    sans = []
    for token in tokens:
        move = None
        # UCI first.
        try:
            candidate = chess.Move.from_uci(token.lower())
            if candidate in replay.legal_moves:
                move = candidate
        except Exception:
            pass
        if move is None:
            try:
                move = replay.parse_san(token)
            except Exception:
                break
        sans.append(replay.san(move))
        ucis.append(move.uci())
        replay.push(move)
    return (ucis, sans) if len(ucis) >= 2 else ([], [])


def _score_move_hypotheses(board: chess.Board, text: str, state: dict) -> list[MoveHypothesis]:
    t = _norm(text)
    descriptors = _legal_descriptors(board)
    scores: dict[str, MoveHypothesis] = {}

    def add(item: dict, score: float, reason: str):
        current = scores.get(item['uci'])
        if current is None:
            scores[item['uci']] = MoveHypothesis(item['uci'], item['san'], score, [reason])
        else:
            current.score += score
            current.reasons.append(reason)

    # Exact SAN/UCI is strongest evidence. A bare "d6" should naturally map
    # to SAN d6 before it is treated as merely a destination square.
    piece_type = _moving_piece_type_from_text(text)
    tokens = _exact_move_tokens(text)
    for token in tokens:
        token_plain = _strip_san_suffix(token)
        bare_square = bool(re.fullmatch(r'[a-h][1-8]', token_plain))
        for item in descriptors:
            if token.lower() == item['uci'].lower():
                add(item, 10.0, 'explicit UCI')
            if token_plain == item['san_plain']:
                # In natural language, "knight to c3" contains the square c3,
                # but that must not be mistaken for the pawn move c3. Likewise
                # "taking the pawn gives my king f2" uses f2 as a claimed
                # consequence, not as the proposed pawn move f2.
                if bare_square and piece_type is not None and piece_type != chess.PAWN:
                    continue
                if bare_square and _move_destination_square(text, [token_plain]) is None:
                    continue
                add(item, 9.5, 'exact SAN')

    target_type = _target_piece_type(text)
    squares = _squares(text)
    destination = _move_destination_square(text, squares)
    source = _move_source_square(text)
    capture_target_square = _capture_target_square(text)
    action = _action(text)

    for item in descriptors:
        score = 0.0
        reasons = []
        if piece_type is not None:
            if item['piece_type'] == piece_type:
                score += 3.2
                reasons.append('piece noun')
            else:
                continue
        if destination:
            if item['to'] == destination:
                score += 4.0
                reasons.append('destination square')
            elif tokens:
                # Exact SAN token may contain another square (source disambiguation).
                pass
            else:
                continue
        if source and item['from'] == source:
            score += 2.5
            reasons.append('source square')
        if target_type is not None:
            if item['capture'] and item['captured_piece'] == chess.piece_name(target_type):
                score += 4.0
                reasons.append('captured piece')
                if capture_target_square:
                    if item['to'] == capture_target_square:
                        score += 3.0
                        reasons.append('captured piece square')
                    else:
                        continue
            else:
                continue
        if action == 'capture':
            if item['capture']:
                score += 2.0
                reasons.append('capture verb')
            else:
                continue
        if action == 'block':
            score += 0.8
            reasons.append('block verb')
            try:
                blocks = _line_blocked_by_move(board, chess.Move.from_uci(item['uci']), board.turn)
            except Exception:
                blocks = []
            if blocks:
                score += 4.0
                reasons.append('actually blocks a sliding line')
        if action == 'trade' and item['capture']:
            score += 1.0
            reasons.append('trade verb')
        if action == 'push' and item['piece_type'] == chess.PAWN:
            score += 1.2
            reasons.append('pawn push verb')
        if action == 'attack':
            score += 0.4
        if item['check'] and re.search(r'\b(?:check|checks|checking)\b', t):
            score += 4.0
            reasons.append('checking move')
        if item['mate'] and re.search(r'\b(?:mate|checkmate)\b', t):
            score += 5.0
            reasons.append('mating move')
        if item['castle'] and re.search(r'\b(?:castle|castling)\b', t):
            score += 5.0
            reasons.append('castling')
        if score > 0:
            add(item, score, ', '.join(reasons) or 'natural description')

    # Pronouns in follow-up questions can refer to the move we just discussed.
    if state.get('last_move_uci') and re.search(r'\b(?:that move|it|that|same move)\b', t):
        for item in descriptors:
            if item['uci'] == state['last_move_uci']:
                add(item, 3.0, 'conversation reference')

    # "Take it" can resolve to a unique legal capture, especially in a
    # continuing thread. We do not force it if several captures remain.
    if re.search(r'\b(?:take|capture)\s+it\b', t):
        captures = [item for item in descriptors if item['capture']]
        referenced = state.get('referenced_squares') or []
        if referenced:
            target_sq = referenced[-1]
            matching = [item for item in captures if item['to'] == target_sq]
            if len(matching) == 1:
                add(matching[0], 6.0, 'capture of previously referenced square')
        if len(captures) == 1:
            add(captures[0], 4.0, 'unique legal capture')

    ranked = sorted(scores.values(), key=lambda x: (-x.score, x.move_san))
    return ranked


def _claims_from_text(text: str, move_san: Optional[str] = None) -> list[dict]:
    t = _norm(text)
    claims = []
    squares = _squares(text)

    def add(kind: str, proposition: str, square: Optional[str] = None, confidence: float = 0.78):
        claims.append({
            'type': kind,
            'proposition': proposition,
            'square': square,
            'move_san': move_san,
            'confidence': confidence,
        })

    if re.search(r'\b(?:block|interpose)\b', t):
        add('blocks_line', 'the move blocks an attacking line', squares[-1] if squares else None, .88)
    if re.search(r'\b(?:open|opens|clear|clears|vacate|vacates|give|gives)\b', t) and squares:
        if 'king' in t:
            add('king_square_access', f'the move makes {squares[-1]} available or useful to the king', squares[-1], .9)
        else:
            add('square_clearance', f'the move clears or opens {squares[-1]}', squares[-1], .82)
    if re.search(r'\b(?:open file|opens? the [a-h]-file|control(?:s|ling)? the [a-h]-file|file control)\b', t):
        file_match = re.search(r'\b([a-h])-file\b', t)
        add('file_control', 'the move improves control of an open or semi-open file', file_match.group(1) if file_match else None, .82)
    if re.search(r'\b(?:center|centre|central|space)\b', t):
        add('central_control', 'the move improves central control or space', None, .78)
    if re.search(r'\b(?:defend|protect|save)\b', t):
        add('defense', 'the move adds a meaningful defense', squares[-1] if squares else None, .76)
    if re.search(r'\b(?:attack|threaten|pressure|target)\b', t):
        add('threat', 'the move creates or increases a concrete threat', squares[-1] if squares else None, .76)
    if re.search(r'\b(?:trade|exchange|simplif)\b', t):
        add('simplification', 'the move usefully simplifies the position', None, .78)
    if re.search(r'\b(?:win|wins|winning)\s+(?:a\s+)?(?:piece|pawn|queen|rook|bishop|knight|material)\b', t):
        add('wins_material', 'the move wins material', None, .86)
    if re.search(r'\b(?:passed pawn|passer)\b', t):
        add('passed_pawn', 'the move advances or supports a passed pawn', None, .82)
    if re.search(r'\b(?:pin|pins|pinned|pinning)\b', t):
        target = None
        for piece_name in ('queen', 'rook', 'bishop', 'knight', 'pawn'):
            if re.search(rf'\b{piece_name}\b', t):
                target = piece_name
                break
        proposition = f'the {target} is pinned or can be pinned in the referenced position' if target else 'an opposing piece is pinned in the referenced position'
        claims.append({
            'type': 'pin',
            'proposition': proposition,
            'square': squares[-1] if squares else None,
            'target_piece': target,
            'move_san': move_san,
            'confidence': .9,
        })
    return claims


def _intent_from_text(text: str, hypotheses: list[MoveHypothesis]) -> str:
    t = _norm(text)
    if any(marker in t for marker in THREAT_MARKERS):
        return 'identify_threat'
    if any(marker in t for marker in PLAN_MARKERS):
        return 'identify_plan'
    if re.search(r'\b(?:compare|versus| vs |better than|worse than|instead of)\b', f' {t} ') and len(hypotheses) >= 2:
        return 'compare_moves'
    if hypotheses:
        if 'why not' in t:
            return 'why_not_move'
        return 'analyze_move'
    if any(marker in t for marker in CLAIM_MARKERS):
        return 'validate_claim'
    return 'none'


def _position_packet(board: chess.Board, text: str, state: dict, hypotheses: list[MoveHypothesis], temporal_context: Optional[dict] = None) -> dict:
    legal = _legal_descriptors(board)
    return {
        'fen': board.fen(),
        'side_to_move': 'white' if board.turn else 'black',
        'user_text': text,
        'candidate_interpretations': [asdict(h) for h in hypotheses[:8]],
        'legal_moves': [
            {'uci': x['uci'], 'san': x['san'], 'piece': x['piece'], 'from': x['from'], 'to': x['to'], 'capture': x['capture'], 'check': x['check']}
            for x in legal
        ],
        'recent_conversation': state.get('recent_text', [])[-6:],
        'learner_feedback_examples': state.get('feedback_examples', [])[-6:],
        'temporal_context': temporal_context or {},
    }


def _ollama_interpret(text: str, board: chess.Board, state: dict, hypotheses: list[MoveHypothesis], settings: dict, temporal_context: Optional[dict] = None) -> Optional[dict]:
    if not settings.get('adaptive_coach_use_ollama'):
        return None
    base = str(settings.get('ollama_base_url') or 'http://127.0.0.1:11434').rstrip('/')
    model = str(settings.get('ollama_model') or 'qwen2.5:7b')
    packet = _position_packet(board, text, state, hypotheses, temporal_context)
    system = '''You are the semantic interpreter for a chess coaching application. Reconstruct what the player means; do not evaluate chess quality. You receive the exact position, legal moves, scored candidate interpretations, recent conversation, and possibly examples of prior coach replies that this learner liked (+1) or disliked (-1). Use feedback only to understand preferred conversational framing; never treat it as chess truth. temporal_context tells you whether the learner is referring to the original puzzle position, the solving move, or a later winning-line continuation. Respect that time reference: retrospective phrases such as 'I realized' can describe what was already true in the puzzle, while 'once/after/then I can...' usually describes a later continuation. Return JSON only with keys: intent, move_uci, confidence, clarification, claims. intent must be one of analyze_move, compare_moves, identify_threat, identify_plan, validate_claim, clarify, none. move_uci must be null or exactly one UCI move from legal_moves. If the user wording is genuinely ambiguous, use intent=clarify and write a short chess-specific clarification. claims is a list of factual propositions with type and proposition; do not decide whether they are true. Never invent an illegal move.'''
    try:
        response = requests.post(
            f'{base}/api/chat',
            json={
                'model': model,
                'stream': False,
                'format': 'json',
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': json.dumps(packet)},
                ],
                'options': {'temperature': 0.0},
            },
            timeout=15,
        )
        response.raise_for_status()
        data = json.loads(response.json()['message']['content'])
        legal_uci = {m.uci() for m in board.legal_moves}
        move_uci = data.get('move_uci')
        if move_uci and move_uci not in legal_uci:
            move_uci = None
        return {
            'intent': str(data.get('intent') or 'none'),
            'move_uci': move_uci,
            'confidence': max(0.0, min(1.0, float(data.get('confidence') or .5))),
            'clarification': data.get('clarification'),
            'claims': data.get('claims') if isinstance(data.get('claims'), list) else [],
            'parser': f'ollama:{model}',
        }
    except Exception:
        return None


def interpret_message(conn, thread_id: int, displayed_fen: str, text: str, user_color: str, settings: dict, temporal_context: Optional[dict] = None) -> Interpretation:
    state = _conversation_state(conn, thread_id)
    if temporal_context and temporal_context.get('context_fen'):
        context_fen = temporal_context['context_fen']
        context_source = temporal_context.get('context_source') or 'temporal_context'
    else:
        context_fen, context_source = _choose_context_fen(displayed_fen, text, state, user_color)
    board = chess.Board(context_fen)
    hypotheses = _score_move_hypotheses(board, text, state)
    rule_intent = _intent_from_text(text, hypotheses)
    variation_uci, variation_san = _variation_from_text(board, text)
    if variation_uci and any(marker in _norm(text) for marker in ('what if', 'then', 'after', 'line', 'variation')):
        return Interpretation(
            intent='analyze_variation', confidence=.97, context_fen=context_fen, context_source=context_source,
            move_uci=variation_uci[0], move_san=variation_san[0],
            candidates=[asdict(h) for h in hypotheses[:5]], claims=_claims_from_text(text, variation_san[0]),
            parser='exact-variation-resolution', variation_uci=variation_uci, variation_san=variation_san,
        )

    # Exact/near-exact chess notation is reliable enough to bypass a model.
    if hypotheses and hypotheses[0].score >= 9.0:
        top = hypotheses[0]
        second = hypotheses[1].score if len(hypotheses) > 1 else -1
        if top.score - second >= 2.0:
            return Interpretation(
                intent=rule_intent if rule_intent != 'none' else 'analyze_move',
                confidence=.98,
                context_fen=context_fen,
                context_source=context_source,
                move_uci=top.move_uci,
                move_san=top.move_san,
                candidates=[asdict(h) for h in hypotheses[:5]],
                claims=_claims_from_text(text, top.move_san),
                parser='exact-board-resolution',
            )

    llm = _ollama_interpret(text, board, state, hypotheses, settings, temporal_context)
    if llm:
        move_san = None
        if llm.get('move_uci'):
            move = chess.Move.from_uci(llm['move_uci'])
            move_san = board.san(move)
        claims = list(llm.get('claims') or [])
        # Preserve deterministic chess-language claims (especially temporal
        # ideas such as pins) even when the semantic model returns a broader
        # paraphrase. The model interprets language; it does not erase concrete
        # propositions that the board validator knows how to test.
        for rule_claim in _claims_from_text(text, move_san):
            if not any(item.get('type') == rule_claim.get('type') and item.get('proposition') == rule_claim.get('proposition') for item in claims if isinstance(item, dict)):
                claims.append(rule_claim)
        if llm['intent'] == 'clarify':
            return Interpretation(
                intent='clarify', confidence=llm['confidence'], context_fen=context_fen,
                context_source=context_source, move_uci=llm.get('move_uci'), move_san=move_san,
                candidates=[asdict(h) for h in hypotheses[:5]], claims=claims,
                clarification=llm.get('clarification'), parser=llm['parser'],
            )
        if llm['intent'] != 'none':
            return Interpretation(
                intent=llm['intent'], confidence=llm['confidence'], context_fen=context_fen,
                context_source=context_source, move_uci=llm.get('move_uci'), move_san=move_san,
                candidates=[asdict(h) for h in hypotheses[:5]], claims=claims, parser=llm['parser'],
            )

    if rule_intent in ('identify_threat', 'identify_plan'):
        return Interpretation(
            intent=rule_intent, confidence=.9, context_fen=context_fen, context_source=context_source,
            candidates=[asdict(h) for h in hypotheses[:5]], claims=_claims_from_text(text), parser='contextual-rules',
        )

    if rule_intent == 'compare_moves' and len(hypotheses) >= 2:
        return Interpretation(
            intent='compare_moves', confidence=.9, context_fen=context_fen, context_source=context_source,
            candidates=[asdict(h) for h in hypotheses[:4]], claims=_claims_from_text(text), parser='contextual-rules',
        )

    if hypotheses:
        top = hypotheses[0]
        second = hypotheses[1].score if len(hypotheses) > 1 else -1
        # A bare SAN-like move such as "d6" often produces a decisive score.
        if top.score >= 4.0 and (top.score - second >= 2.0 or len(hypotheses) == 1):
            confidence = min(.95, .58 + top.score / 20.0)
            return Interpretation(
                intent=rule_intent if rule_intent != 'none' else 'analyze_move', confidence=confidence,
                context_fen=context_fen, context_source=context_source, move_uci=top.move_uci, move_san=top.move_san,
                candidates=[asdict(h) for h in hypotheses[:5]], claims=_claims_from_text(text, top.move_san),
                parser='contextual-rules',
            )
        # If the board itself cannot distinguish the reference, ask a useful clarification.
        options = ', '.join(h.move_san for h in hypotheses[:4])
        return Interpretation(
            intent='clarify', confidence=.62, context_fen=context_fen, context_source=context_source,
            candidates=[asdict(h) for h in hypotheses[:5]], claims=_claims_from_text(text),
            clarification=f'I can read that a couple of ways in this position: {options}. Which move do you mean?',
            parser='contextual-rules',
        )

    claims = _claims_from_text(text)
    if claims:
        return Interpretation(
            intent='validate_claim', confidence=.72, context_fen=context_fen, context_source=context_source,
            candidates=[], claims=claims, parser='contextual-rules',
        )

    return Interpretation(
        intent='none', confidence=.25, context_fen=context_fen, context_source=context_source,
        candidates=[], claims=[], parser='contextual-rules',
    )


def _material_score(board: chess.Board, color: chess.Color) -> int:
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        if piece_type == chess.KING:
            continue
        total += value * len(board.pieces(piece_type, color))
        total -= value * len(board.pieces(piece_type, not color))
    return total


def _hanging_pieces(board: chess.Board, color: chess.Color) -> list[tuple[int, chess.Piece]]:
    result = []
    for sq, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        attackers = board.attackers(not color, sq)
        defenders = board.attackers(color, sq)
        if attackers and not defenders:
            result.append((sq, piece))
    return result


def _open_files(board: chess.Board) -> set[str]:
    result = set()
    for f in range(8):
        pawns = [sq for sq in board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK) if chess.square_file(sq) == f]
        if not pawns:
            result.add(chr(ord('a') + f))
    return result


def _semi_open_files(board: chess.Board, color: chess.Color) -> set[str]:
    result = set()
    own = board.pieces(chess.PAWN, color)
    enemy = board.pieces(chess.PAWN, not color)
    for f in range(8):
        own_here = any(chess.square_file(sq) == f for sq in own)
        enemy_here = any(chess.square_file(sq) == f for sq in enemy)
        if not own_here and enemy_here:
            result.add(chr(ord('a') + f))
    return result


def _center_control(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.attackers(color, sq)) for sq in (chess.D4, chess.E4, chess.D5, chess.E5))


def _king_ring_pressure(board: chess.Board, victim_color: chess.Color) -> int:
    king = board.king(victim_color)
    if king is None:
        return 0
    ring = [sq for sq in chess.SQUARES if chess.square_distance(king, sq) <= 1]
    return sum(len(board.attackers(not victim_color, sq)) for sq in ring)


def _feature_snapshot(board: chess.Board, mover: chess.Color) -> dict:
    return {
        'material': _material_score(board, mover),
        'own_hanging': [(chess.square_name(sq), chess.piece_name(p.piece_type)) for sq, p in _hanging_pieces(board, mover)],
        'enemy_hanging': [(chess.square_name(sq), chess.piece_name(p.piece_type)) for sq, p in _hanging_pieces(board, not mover)],
        'open_files': sorted(_open_files(board)),
        'semi_open_files': sorted(_semi_open_files(board, mover)),
        'center_control': _center_control(board, mover),
        'enemy_king_pressure': _king_ring_pressure(board, not mover),
        'own_king_pressure': _king_ring_pressure(board, mover),
        'in_check': board.is_check(),
    }


def _piece_attack_targets(board: chess.Board, square: int, color: chess.Color) -> list[tuple[int, chess.Piece]]:
    targets = []
    for sq in board.attacks(square):
        p = board.piece_at(sq)
        if p and p.color != color and p.piece_type != chess.KING:
            targets.append((sq, p))
    return sorted(targets, key=lambda x: PIECE_VALUES.get(x[1].piece_type, 0), reverse=True)


def _line_blocked_by_move(before: chess.Board, move: chess.Move, mover: chess.Color) -> list[str]:
    after = before.copy(stack=False)
    after.push(move)
    messages = []
    for target_sq, target_piece in before.piece_map().items():
        if target_piece.color != mover:
            continue
        before_attackers = set(before.attackers(not mover, target_sq))
        after_attackers = set(after.attackers(not mover, target_sq))
        for attacker_sq in before_attackers - after_attackers:
            attacker = before.piece_at(attacker_sq)
            if attacker and attacker.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                messages.append(
                    f"blocks the {chess.piece_name(attacker.piece_type)} on {chess.square_name(attacker_sq)} from attacking the {chess.piece_name(target_piece.piece_type)} on {chess.square_name(target_sq)}"
                )
    return messages


def _move_consequences(board: chess.Board, move: chess.Move, mover: chess.Color) -> dict:
    piece = board.piece_at(move.from_square)
    target = board.piece_at(move.to_square)
    san = board.san(move)
    before = _feature_snapshot(board, mover)
    from_attacked = board.is_attacked_by(not mover, move.from_square)
    before_open = _open_files(board)
    blocks = _line_blocked_by_move(board, move, mover)

    after = board.copy(stack=False)
    after.push(move)
    after_features = _feature_snapshot(after, mover)
    targets = _piece_attack_targets(after, move.to_square, mover)
    new_open = sorted(_open_files(after) - before_open)

    facts = []
    if board.is_capture(move):
        captured_name = chess.piece_name(target.piece_type) if target else 'pawn'
        facts.append(f'captures the {captured_name} on {chess.square_name(move.to_square)}')
    if after.is_checkmate():
        facts.append('gives checkmate')
    elif after.is_check():
        facts.append('gives check')
    if blocks:
        facts.extend(blocks[:2])
    if from_attacked and not after.is_attacked_by(not mover, move.to_square) and piece:
        facts.append(f'moves the attacked {chess.piece_name(piece.piece_type)} to safety')
    if targets:
        top_targets = ', '.join(f"{chess.piece_name(p.piece_type)} on {chess.square_name(sq)}" for sq, p in targets[:2])
        facts.append(f'creates pressure on {top_targets}')
    if new_open:
        facts.append(f"opens the {'/'.join(new_open)}-file" if len(new_open) == 1 else f"opens the {', '.join(new_open)} files")
    if after_features['center_control'] > before['center_control']:
        facts.append('increases central control')
    if after_features['enemy_king_pressure'] > before['enemy_king_pressure']:
        facts.append('increases pressure around the enemy king')
    if after_features['own_king_pressure'] < before['own_king_pressure']:
        facts.append('reduces pressure around your king')

    return {
        'san': san,
        'uci': move.uci(),
        'piece': chess.piece_name(piece.piece_type) if piece else None,
        'from': chess.square_name(move.from_square),
        'to': chess.square_name(move.to_square),
        'facts': facts,
        'before': before,
        'after': after_features,
        'resulting_fen': after.fen(),
    }


def _critical_reply(candidate_info: dict, after_candidate: chess.Board, mover: chess.Color) -> dict:
    pv_uci = list(candidate_info.get('pv_uci') or [])
    pv_san = list(candidate_info.get('pv_san') or [])
    if len(pv_uci) < 2:
        return {'uci': None, 'san': None, 'facts': [], 'after_reply_fen': None}
    try:
        reply = chess.Move.from_uci(pv_uci[1])
    except Exception:
        return {'uci': None, 'san': None, 'facts': [], 'after_reply_fen': None}
    if reply not in after_candidate.legal_moves:
        return {'uci': None, 'san': None, 'facts': [], 'after_reply_fen': None}
    reply_effects = _move_consequences(after_candidate, reply, not mover)
    after_reply = after_candidate.copy(stack=False)
    after_reply.push(reply)
    return {
        'uci': reply.uci(),
        'san': pv_san[1] if len(pv_san) > 1 else after_candidate.san(reply),
        'facts': reply_effects['facts'],
        'after_reply_fen': after_reply.fen(),
        'material_after_reply': _material_score(after_reply, mover),
        'own_hanging_after_reply': [(chess.square_name(sq), chess.piece_name(p.piece_type)) for sq, p in _hanging_pieces(after_reply, mover)],
    }


def _grade_gap(best: dict, candidate: dict) -> tuple[str, str]:
    best_mate = best.get('mate')
    cand_mate = candidate.get('mate')
    if best_mate is not None and best_mate > 0 and not (cand_mate is not None and cand_mate > 0):
        return 'refuted', 'it gives up a forced mating continuation'
    gap = max(0, int(best.get('eval_cp') or 0) - int(candidate.get('eval_cp') or 0))
    if gap <= 30:
        return 'supported', 'the engine considers it essentially best'
    if gap <= 80:
        return 'supported', 'the engine considers it a strong alternative'
    if gap <= 160:
        return 'plausible_but_secondary', 'the idea is playable but less precise than the best continuation'
    if gap <= 300:
        return 'mostly_refuted', 'the idea is understandable, but the concrete reply costs enough to matter'
    return 'refuted', 'the concrete continuation makes the move substantially worse than the best choice'


def _natural_join(items: list[str]) -> str:
    items = [x.strip().rstrip('.') for x in items if x and x.strip()]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f'{items[0]} and {items[1]}'
    return ', '.join(items[:-1]) + f', and {items[-1]}'


def _validate_claims_for_move(claims: list[dict], before: chess.Board, move: chess.Move, after: chess.Board, candidate_info: dict) -> list[dict]:
    results = []
    mover = before.turn
    for claim in claims or []:
        kind = claim.get('type')
        square_name = claim.get('square')
        verdict = 'uncertain'
        explanation = 'I can see the idea, but I do not have a clean board test for it yet.'

        if kind == 'blocks_line':
            blocks = _line_blocked_by_move(before, move, mover)
            verdict = 'supported' if blocks else 'refuted'
            explanation = blocks[0].capitalize() + '.' if blocks else 'The move reaches the square you mentioned, but it does not actually cut off a major rook, bishop, or queen line.'
        elif kind in ('king_square_access', 'square_clearance') and square_name:
            try:
                sq = chess.parse_square(square_name)
                occupied_before = before.piece_at(sq)
                occupied_after = after.piece_at(sq)
                if occupied_before and occupied_before.color == mover and occupied_after is None:
                    verdict = 'supported'
                    explanation = f'Yes—the move vacates {square_name}.'
                elif occupied_after is None:
                    verdict = 'supported'
                    explanation = f'{square_name} is open after the move.'
                else:
                    verdict = 'refuted'
                    explanation = f'{square_name} is still occupied after the move.'
                if kind == 'king_square_access' and verdict == 'supported':
                    king = after.king(mover)
                    safe = not after.is_attacked_by(not mover, sq)
                    if king is not None:
                        if chess.square_distance(king, sq) == 1 and safe:
                            explanation += ' Your king could legally use that square on a later move if the turn sequence allows it.'
                        elif safe:
                            explanation += ' It is safe at the moment, although it is not an immediate king move from the current king square.'
                        else:
                            explanation += ' However, the opponent currently controls that square, so access is not yet practically available.'
            except Exception:
                pass
        elif kind == 'wins_material':
            pv = list(candidate_info.get('pv_uci') or [])[:5]
            replay = before.copy(stack=False)
            start = _material_score(replay, mover)
            for uci in pv:
                try:
                    m = chess.Move.from_uci(uci)
                except Exception:
                    break
                if m not in replay.legal_moves:
                    break
                replay.push(m)
            end = _material_score(replay, mover)
            if end > start:
                verdict = 'supported'
                explanation = f'Yes. In the engine continuation, the line improves your material balance by about {end - start} point(s).'
            else:
                verdict = 'refuted'
                explanation = 'I do not see a material gain surviving the opponent’s best response.'
        elif kind == 'central_control':
            before_score = _center_control(before, mover)
            after_score = _center_control(after, mover)
            verdict = 'supported' if after_score > before_score else ('plausible_but_secondary' if after_score == before_score else 'refuted')
            explanation = 'The move increases your direct control of the four central squares.' if after_score > before_score else 'The move does not increase direct central-square control; any central benefit is more indirect.'
        elif kind == 'file_control':
            square_or_file = square_name
            file_name = square_or_file if square_or_file and len(square_or_file) == 1 else None
            after_open = _open_files(after)
            after_semi = _semi_open_files(after, mover)
            if file_name and file_name in after_open | after_semi:
                verdict = 'supported'
                explanation = f'Yes. The {file_name}-file is available as an open or semi-open file after the move.'
            else:
                verdict = 'plausible_but_secondary'
                explanation = 'File activity may be part of the position, but this move does not itself create a clear new open-file advantage.'
        elif kind == 'defense':
            before_hanging = set(_feature_snapshot(before, mover)['own_hanging'])
            after_hanging = set(_feature_snapshot(after, mover)['own_hanging'])
            if len(after_hanging) < len(before_hanging):
                verdict = 'supported'
                explanation = 'Yes. The move removes at least one of your previously undefended attacked pieces from immediate danger.'
            else:
                verdict = 'uncertain'
                explanation = 'The move may defend something, but it does not clearly reduce the set of hanging pieces.'
        elif kind == 'threat':
            effects = _move_consequences(before, move, mover)
            threatening = [fact for fact in effects['facts'] if 'pressure on' in fact or 'gives check' in fact]
            verdict = 'supported' if threatening else 'uncertain'
            explanation = threatening[0].capitalize() + '.' if threatening else 'The move is not immediately forcing; any threat is positional rather than a direct check or attack on material.'
        elif kind == 'simplification':
            verdict = 'supported' if before.is_capture(move) else 'uncertain'
            explanation = 'The move starts a concrete exchange sequence.' if before.is_capture(move) else 'The move may aim for simplification, but it does not force an exchange immediately.'

        results.append({**claim, 'verdict': verdict, 'explanation': explanation})
    return results


def _best_move_contrast(board: chess.Board, candidate_move: chess.Move, best_info: dict, mover: chess.Color) -> Optional[str]:
    best_uci = best_info.get('best_move_uci')
    if not best_uci or best_uci == candidate_move.uci():
        return None
    try:
        best_move = chess.Move.from_uci(best_uci)
    except Exception:
        return None
    if best_move not in board.legal_moves:
        return None
    candidate_fx = _move_consequences(board, candidate_move, mover)
    best_fx = _move_consequences(board, best_move, mover)
    best_facts = best_fx['facts'][:2]
    cand_facts = candidate_fx['facts'][:2]
    best_san = board.san(best_move)
    if best_facts and cand_facts:
        return f"By contrast, {best_san} {_natural_join(best_facts)}; that is the concrete advantage your move has to compete with."
    if best_facts:
        return f"The stronger alternative is {best_san}, which {_natural_join(best_facts)}."
    return f"The engine prefers {best_san}, but the important comparison is the resulting position rather than the notation itself."


def _reply_sentence(reply: dict, mover: chess.Color, material_before: int) -> Optional[str]:
    if not reply.get('san'):
        return None
    facts = list(reply.get('facts') or [])
    material_after = reply.get('material_after_reply')
    if material_after is not None and material_after < material_before:
        loss = material_before - material_after
        facts.append(f'leaves you about {loss} material point(s) worse than before the sequence')
    if facts:
        return f"The move I would test first against your idea is {reply['san']}: it {_natural_join(facts[:3])}."
    return f"The opponent’s most testing response is {reply['san']}; that is the reply your idea has to survive."


def _dialogue_temporal_scope(text: str, dialogue_context: Optional[dict]) -> str:
    t = _norm(text)
    if not dialogue_context:
        return 'displayed'
    continuation_markers = (
        'once ', 'after ', 'then ', 'next ', 'later ', 'continuation', 'moves out of check',
        'move out of check', 'gets out of check', 'responds', 'replies', 'after he', 'after she',
        'after they', 'after the opponent', 'can pin', 'could pin', 'then i can', 'then we can',
    )
    if any(marker in t for marker in continuation_markers):
        return 'continuation'
    solution_markers = (
        'winning move', 'solving move', 'move i played', 'move we played', 'when i played',
        'i did realize', 'i realized', 'i noticed', 'i saw that', 'was pinned', 'were pinned',
        'before i moved', 'in the puzzle', 'in that position',
    )
    if any(marker in t for marker in solution_markers):
        return 'puzzle_position'
    if dialogue_context.get('stage') == 'analysis_continuation':
        return 'displayed_continuation'
    if dialogue_context.get('stage') == 'post_solution':
        return 'post_solution'
    return 'displayed'


def _safe_fen(value: Optional[str], fallback: str) -> str:
    try:
        return chess.Board(value or fallback).fen()
    except Exception:
        return chess.Board(fallback).fen()


def _temporal_context_for_message(position_row, text: str, displayed_fen: str, dialogue_context: Optional[dict]) -> dict:
    ctx = dict(dialogue_context or {})
    puzzle_fen = _safe_fen(ctx.get('puzzle_fen') or position_row['fen'], position_row['fen'])
    displayed = _safe_fen(displayed_fen, puzzle_fen)
    scope = _dialogue_temporal_scope(text, ctx)
    result = {
        'scope': scope,
        'context_fen': displayed,
        'context_source': 'displayed_board',
        'puzzle_fen': puzzle_fen,
        'solving_move_uci': ctx.get('solving_move_uci') or (position_row['best_move_uci'] if position_row['learned'] else None),
        'solving_move_san': ctx.get('solving_move_san') or (position_row['best_move_san'] if position_row['learned'] else None),
        'solving_fen': ctx.get('solving_fen'),
        'continuation_reply_uci': None,
        'continuation_reply_san': None,
        'continuation_pv_uci': [],
        'continuation_pv_san': [],
    }

    if scope == 'puzzle_position':
        result['context_fen'] = puzzle_fen
        result['context_source'] = 'puzzle_position_before_solving_move'
        return result

    if scope == 'displayed_continuation':
        result['context_fen'] = displayed
        result['context_source'] = 'user_analysis_continuation'
        return result

    if scope == 'post_solution' and ctx.get('solving_fen'):
        result['context_fen'] = _safe_fen(ctx.get('solving_fen'), displayed)
        result['context_source'] = 'position_after_solving_move'
        return result

    if scope == 'continuation' and result['solving_move_uci']:
        user_side = chess.WHITE if str(position_row['user_color']).lower() == 'white' else chess.BLACK
        try:
            info = evaluate_move_quality(puzzle_fen, result['solving_move_uci'], user_side)
            pv_uci = list(info.get('pv_uci') or [])
            pv_san = list(info.get('pv_san') or [])
            result['continuation_pv_uci'] = pv_uci
            result['continuation_pv_san'] = pv_san
            replay = chess.Board(puzzle_fen)
            # The PV normally begins with the solving move. Advance through the
            # opponent's first reply so future-tense claims are tested at the
            # point where the learner says their next idea becomes available.
            if pv_uci:
                first = chess.Move.from_uci(pv_uci[0])
                if first in replay.legal_moves:
                    replay.push(first)
            if len(pv_uci) > 1:
                reply = chess.Move.from_uci(pv_uci[1])
                if reply in replay.legal_moves:
                    result['continuation_reply_uci'] = reply.uci()
                    result['continuation_reply_san'] = replay.san(reply)
                    replay.push(reply)
                    result['context_fen'] = replay.fen()
                    result['context_source'] = 'after_opponent_reply_in_winning_line'
                    return result
            result['context_fen'] = replay.fen()
            result['context_source'] = 'after_solving_move_in_winning_line'
            return result
        except Exception:
            pass

    return result


def _pinned_piece_descriptions(board: chess.Board, color: chess.Color, target_piece: Optional[str] = None) -> list[str]:
    descriptions = []
    target_type = PIECE_WORDS.get(target_piece) if target_piece else None
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        if target_type is not None and piece.piece_type != target_type:
            continue
        try:
            if board.is_pinned(color, square):
                descriptions.append(f"{chess.piece_name(piece.piece_type)} on {chess.square_name(square)}")
        except Exception:
            continue
    return descriptions


def _legal_moves_creating_pin(board: chess.Board, mover: chess.Color, target_piece: Optional[str]) -> list[tuple[chess.Move, str]]:
    enemy = not mover
    matches = []
    for move in list(board.legal_moves):
        if board.turn != mover:
            break
        after = board.copy(stack=False)
        san = board.san(move)
        after.push(move)
        pinned = _pinned_piece_descriptions(after, enemy, target_piece)
        if pinned:
            matches.append((move, f"{san} pins the {pinned[0]} to the king"))
    return matches


def _analyze_temporal_claim(interp: Interpretation, position_row, temporal_context: dict) -> Optional[dict]:
    claims = list(interp.claims or [])
    pin_claims = [claim for claim in claims if claim.get('type') == 'pin']
    if not pin_claims:
        return None
    board = chess.Board(interp.context_fen)
    user_side = chess.WHITE if str(position_row['user_color']).lower() == 'white' else chess.BLACK
    enemy = not user_side
    claim = pin_claims[0]
    target_piece = claim.get('target_piece')
    scope = temporal_context.get('scope') or 'displayed'

    if scope in ('puzzle_position', 'post_solution', 'displayed'):
        pinned = _pinned_piece_descriptions(board, enemy, target_piece)
        if pinned:
            where = 'in the original puzzle position' if scope == 'puzzle_position' else 'in the position you are referring to'
            reply = f"Yes—that observation is concrete. The opponent's {pinned[0]} is absolutely pinned to the king {where}, so it cannot legally move off the pin line."
            if scope == 'puzzle_position':
                reply += ' That is exactly the kind of pre-existing constraint that can make the winning move work, so it is useful to separate it from a tactic created only after your move.'
            return {
                'reply': reply,
                'verdict': 'supported',
                'confidence': .94,
                'claims': [{**claim, 'verdict': 'supported', 'explanation': reply}],
                'analysis_context': {
                    'temporal_scope': scope,
                    'context_source': temporal_context.get('context_source'),
                    'referenced_squares': [item.split()[-1] for item in pinned],
                },
                'evidence': {'pinned_pieces': pinned, 'context_fen': board.fen()},
            }
        reply = "I do not find an absolute pin on the opponent's piece in the position you are referring to. You may be noticing a tactical restriction or a relative pin instead, but I would not label it an absolute pin from the board geometry alone."
        return {
            'reply': reply, 'verdict': 'mostly_refuted', 'confidence': .86,
            'claims': [{**claim, 'verdict': 'mostly_refuted', 'explanation': reply}],
            'analysis_context': {'temporal_scope': scope, 'context_source': temporal_context.get('context_source')},
            'evidence': {'pinned_pieces': [], 'context_fen': board.fen()},
        }

    if scope in ('continuation', 'displayed_continuation'):
        if board.turn != user_side:
            return {
                'reply': 'I understand this as a claim about your next move in the continuation, but the reconstructed line still has the opponent to move. I would rather not guess which reply you mean.',
                'verdict': 'ambiguous', 'confidence': .68, 'claims': claims,
                'analysis_context': {'temporal_scope': scope, 'context_source': temporal_context.get('context_source')},
                'evidence': {'context_fen': board.fen()},
            }
        pin_moves = _legal_moves_creating_pin(board, user_side, target_piece)
        if pin_moves:
            # Prefer an engine-favored pinning move if more than one exists.
            ranked = []
            for move, description in pin_moves[:8]:
                try:
                    info = evaluate_move_quality(board.fen(), move.uci(), user_side)
                    ranked.append((int(info.get('eval_cp') or 0), move, description))
                except Exception:
                    ranked.append((-999999, move, description))
            ranked.sort(key=lambda item: item[0], reverse=True)
            _, move, description = ranked[0]
            lead = ''
            if temporal_context.get('continuation_reply_san'):
                lead = f"After {temporal_context['continuation_reply_san']}, "
            reply = f"Yes—your continuation claim is real. {lead}{description}. That means the pin is not a feature of the original puzzle position; it becomes available one move later after the opponent's reply."
            return {
                'reply': reply, 'verdict': 'supported', 'confidence': .93,
                'claims': [{**claim, 'verdict': 'supported', 'explanation': reply}],
                'analysis_context': {
                    'temporal_scope': scope,
                    'context_source': temporal_context.get('context_source'),
                    'move_uci': move.uci(), 'move_san': board.san(move),
                    'resulting_fen': (lambda b, m: (b.push(m), b.fen())[1])(board.copy(stack=False), move),
                    'critical_reply_uci': temporal_context.get('continuation_reply_uci'),
                    'critical_reply_san': temporal_context.get('continuation_reply_san'),
                },
                'evidence': {
                    'pin_moves': [{'uci': m.uci(), 'san': board.san(m), 'description': d} for m, d in pin_moves],
                    'continuation_pv_uci': temporal_context.get('continuation_pv_uci') or [],
                    'continuation_pv_san': temporal_context.get('continuation_pv_san') or [],
                    'context_fen': board.fen(),
                },
            }
        reply = "I can reconstruct the continuation you mean, but I do not find a legal move there that creates an absolute pin on the referenced piece. The idea may still be a skewer, discovered attack, or relative pin, so I would not call it disproven beyond the absolute-pin claim."
        return {
            'reply': reply, 'verdict': 'mostly_refuted', 'confidence': .82, 'claims': claims,
            'analysis_context': {'temporal_scope': scope, 'context_source': temporal_context.get('context_source')},
            'evidence': {'pin_moves': [], 'context_fen': board.fen()},
        }
    return None


def analyze_interpretation(interp: Interpretation, user_color: str, allow_best_move: bool) -> dict:
    board = chess.Board(interp.context_fen)
    user_side = chess.WHITE if str(user_color).lower() == 'white' else chess.BLACK

    if interp.intent == 'clarify':
        return {
            'reply': interp.clarification or 'I can see more than one reasonable interpretation. Which move do you mean?',
            'verdict': 'ambiguous',
            'confidence': interp.confidence,
            'claims': [],
            'analysis_context': {'referenced_squares': _squares(interp.clarification or '')},
        }

    if interp.intent == 'identify_threat':
        return _analyze_threat(board, user_side, allow_best_move, interp)
    if interp.intent == 'identify_plan':
        return _analyze_plan(board, user_side, allow_best_move, interp)
    if interp.intent == 'compare_moves':
        return _analyze_comparison(board, interp, allow_best_move)
    if interp.intent == 'analyze_variation':
        return _analyze_variation(board, interp, allow_best_move)
    if interp.intent == 'validate_claim' and not interp.move_uci:
        return {
            'reply': 'I understand the strategic claim, but I need the move or concrete continuation you are connecting it to before I can test whether it is actually causal in this position.',
            'verdict': 'ambiguous',
            'confidence': interp.confidence,
            'claims': interp.claims or [],
            'analysis_context': {},
        }
    if not interp.move_uci:
        return {
            'reply': 'I understand that you are asking about the position, but I cannot yet identify the concrete move or claim well enough to analyze it without guessing. Try naming the piece, destination square, or continuation you have in mind.',
            'verdict': 'ambiguous',
            'confidence': interp.confidence,
            'claims': [],
            'analysis_context': {},
        }

    move = chess.Move.from_uci(interp.move_uci)
    if move not in board.legal_moves:
        return {
            'reply': f'I interpreted your idea as {interp.move_san or interp.move_uci}, but that move is not legal on the board currently displayed.',
            'verdict': 'refuted', 'confidence': interp.confidence, 'claims': interp.claims or [], 'analysis_context': {},
        }

    mover = board.turn
    san = board.san(move)
    best = evaluate_fen(board.fen(), mover)
    candidate = evaluate_move_quality(board.fen(), move.uci(), mover)
    verdict, engine_summary = _grade_gap(best, candidate)
    candidate_fx = _move_consequences(board, move, mover)
    after_candidate = board.copy(stack=False)
    after_candidate.push(move)
    critical = _critical_reply(candidate, after_candidate, mover)
    claims = _validate_claims_for_move(interp.claims or [], board, move, after_candidate, candidate)

    facts = candidate_fx['facts'][:3]
    direct = {
        'supported': f'Yes—{san} is a serious move here.',
        'plausible_but_secondary': f'{san} is a reasonable idea, but it is not quite the most precise continuation.',
        'mostly_refuted': f'I understand the idea behind {san}, but there is a concrete problem with the timing.',
        'refuted': f'{san} looks natural, but the position contains a concrete reason it falls short.',
    }.get(verdict, f'{san} is worth examining.')

    paragraphs = [direct]
    if facts:
        paragraphs.append(f"What your move accomplishes is that it {_natural_join(facts)}.")

    reply_sentence = _reply_sentence(critical, mover, candidate_fx['before']['material'])
    if reply_sentence:
        paragraphs.append(reply_sentence)

    # Explain the user's explicit causal claim separately from move quality.
    for result in claims[:2]:
        prefix = {
            'supported': 'Your specific idea is real:',
            'refuted': 'That specific part is not quite right:',
            'plausible_but_secondary': 'That is a secondary factor:',
            'uncertain': 'I would be cautious about that part:',
        }.get(result['verdict'], 'On that claim:')
        paragraphs.append(f"{prefix} {result['explanation']}")

    if allow_best_move:
        contrast = _best_move_contrast(board, move, best, mover)
        if contrast and best.get('best_move_uci') != move.uci():
            paragraphs.append(contrast)

    # Finish with a coaching takeaway rather than an evaluation dump.
    if verdict in ('mostly_refuted', 'refuted') and critical.get('san'):
        takeaway = f"The coaching takeaway is to test {san} against the opponent’s most forcing reply—{critical['san']}—before judging the positional idea. {engine_summary.capitalize()}."
    elif verdict == 'supported':
        takeaway = f"So your candidate survives the concrete test. {engine_summary.capitalize()}."
    else:
        takeaway = f"The idea has merit, but the comparison is about precision: {engine_summary}."
    paragraphs.append(takeaway)

    referenced = [candidate_fx['from'], candidate_fx['to']]
    referenced.extend(_squares(' '.join(x.get('explanation', '') for x in claims)))
    analysis_context = {
        'move_uci': move.uci(),
        'move_san': san,
        'resulting_fen': candidate_fx['resulting_fen'],
        'critical_reply_uci': critical.get('uci'),
        'critical_reply_san': critical.get('san'),
        'after_reply_fen': critical.get('after_reply_fen'),
        'referenced_squares': list(dict.fromkeys(referenced)),
        'engine_verdict': verdict,
        'parser': interp.parser,
        'context_source': interp.context_source,
    }
    return {
        'reply': '\n\n'.join(paragraphs),
        'verdict': verdict,
        'confidence': interp.confidence,
        'claims': claims,
        'analysis_context': analysis_context,
        'evidence': {
            'candidate': candidate,
            'candidate_effects': candidate_fx,
            'critical_reply': critical,
            'best_move_uci': best.get('best_move_uci') if allow_best_move else None,
            'best_move_san': best.get('best_move_san') if allow_best_move else None,
        },
    }


def _analyze_comparison(board: chess.Board, interp: Interpretation, allow_best_move: bool) -> dict:
    candidates = list(interp.candidates or [])
    legal = []
    seen = set()
    for item in candidates:
        uci = item.get('move_uci') or item.get('uci')
        if not uci or uci in seen:
            continue
        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            continue
        if move in board.legal_moves:
            legal.append(move)
            seen.add(uci)
        if len(legal) >= 2:
            break
    if len(legal) < 2:
        return {'reply': 'I can compare the moves, but I need two concrete legal candidates.', 'verdict': 'ambiguous', 'confidence': .55, 'claims': [], 'analysis_context': {}}
    mover = board.turn
    analyses = []
    for move in legal[:2]:
        info = evaluate_move_quality(board.fen(), move.uci(), mover)
        fx = _move_consequences(board, move, mover)
        after = board.copy(stack=False); after.push(move)
        reply = _critical_reply(info, after, mover)
        analyses.append((move, info, fx, reply))
    analyses.sort(key=lambda x: int(x[1].get('eval_cp') or 0), reverse=True)
    better, worse = analyses[0], analyses[1]
    better_san, worse_san = board.san(better[0]), board.san(worse[0])
    gap = int(better[1].get('eval_cp') or 0) - int(worse[1].get('eval_cp') or 0)
    parts = [f'Between {better_san} and {worse_san}, I prefer {better_san}.']
    if better[2]['facts']:
        parts.append(f"{better_san} {_natural_join(better[2]['facts'][:2])}.")
    if worse[3].get('san'):
        sentence = _reply_sentence(worse[3], mover, worse[2]['before']['material'])
        if sentence:
            parts.append(f"The practical problem with {worse_san} is clearer after the reply: {sentence}")
    if gap <= 60:
        parts.append('The difference is small, so this is more about move-order and precision than a fundamentally different plan.')
        verdict = 'supported'
    elif gap <= 180:
        parts.append('The difference is meaningful but not catastrophic: both ideas are playable, while the first one handles the concrete demands of the position more cleanly.')
        verdict = 'plausible_but_secondary'
    else:
        parts.append('The difference is large enough that the concrete continuation, not just style, separates the two moves.')
        verdict = 'mostly_refuted'
    return {
        'reply': '\n\n'.join(parts), 'verdict': verdict, 'confidence': interp.confidence, 'claims': [],
        'analysis_context': {'move_uci': better[0].uci(), 'move_san': better_san, 'resulting_fen': better[2]['resulting_fen'], 'referenced_squares': [better[2]['from'], better[2]['to'], worse[2]['from'], worse[2]['to']]},
        'evidence': {'moves': [{'uci': x[0].uci(), 'san': board.san(x[0]), 'eval_cp': x[1].get('eval_cp')} for x in analyses]},
    }


def _analyze_variation(board: chess.Board, interp: Interpretation, allow_best_move: bool) -> dict:
    ucis = list(interp.variation_uci or [])
    sans = list(interp.variation_san or [])
    if len(ucis) < 2:
        return {'reply': 'I understand that as a line, but I cannot reconstruct enough legal moves to test it.', 'verdict': 'ambiguous', 'confidence': .55, 'claims': [], 'analysis_context': {}}
    replay = board.copy(stack=False)
    origin_side = replay.turn
    story = []
    for index, uci in enumerate(ucis):
        move = chess.Move.from_uci(uci)
        if move not in replay.legal_moves:
            return {'reply': f'The line stops at move {index + 1}: {uci} is not legal from the position reached so far.', 'verdict': 'refuted', 'confidence': interp.confidence, 'claims': [], 'analysis_context': {}}
        fx = _move_consequences(replay, move, replay.turn)
        if fx['facts']:
            story.append(f"{replay.san(move)} {_natural_join(fx['facts'][:2])}")
        replay.push(move)
    final_eval = evaluate_fen(replay.fen(), origin_side)
    first_info = evaluate_move_quality(board.fen(), ucis[0], origin_side)
    best = evaluate_fen(board.fen(), origin_side)
    verdict, summary = _grade_gap(best, first_info)
    parts = [f"Yes—I can test that line: {' '.join(sans)}."]
    if story:
        parts.append('The important changes are: ' + '; '.join(story[:4]) + '.')
    if final_eval.get('mate') is not None:
        mate = final_eval['mate']
        parts.append(f"At the end of your line, the position has a forced mate {'for your side' if mate > 0 else 'against your side'}, so the sequence is tactically decisive.")
    else:
        parts.append(f"The first move is best judged by whether the whole line survives the opponent's replies; {summary}.")
    first_board = chess.Board(interp.context_fen)
    first_move = chess.Move.from_uci(ucis[0])
    first_board.push(first_move)
    return {
        'reply': '\n\n'.join(parts), 'verdict': verdict, 'confidence': interp.confidence, 'claims': [],
        'analysis_context': {'move_uci': ucis[0], 'move_san': sans[0], 'resulting_fen': first_board.fen(), 'after_reply_fen': replay.fen(), 'referenced_squares': _squares(' '.join(sans))},
        'evidence': {'variation_uci': ucis, 'variation_san': sans, 'final_eval': final_eval},
    }


def _analyze_threat(board: chess.Board, user_side: chess.Color, allow_best_move: bool, interp: Interpretation) -> dict:
    # A threat question is most useful when framed around forcing candidate moves.
    multipv = evaluate_multipv(board.fen(), board.turn, 4)
    forcing = []
    for info in multipv:
        try:
            move = chess.Move.from_uci(info['move_uci'])
        except Exception:
            continue
        if move not in board.legal_moves:
            continue
        fx = _move_consequences(board, move, board.turn)
        if any(('check' in fact or 'captures' in fact or 'pressure on' in fact) for fact in fx['facts']):
            forcing.append((info, fx))
    if forcing:
        info, fx = forcing[0]
        reply = f"The most immediate thing to notice is {info['move_san']}: it {_natural_join(fx['facts'][:2])}."
        if len(forcing) > 1:
            reply += f" Another forcing candidate is {forcing[1][0]['move_san']}."
    else:
        top = multipv[0] if multipv else None
        reply = f"I do not see a single forcing tactical threat dominating the position. The strongest continuation begins with {top['move_san']}, so the position is more about improving the pieces than answering one immediate blow." if top else 'I do not see a single forcing tactical threat dominating the position.'
    return {
        'reply': reply,
        'verdict': 'supported',
        'confidence': .86,
        'claims': [],
        'analysis_context': {'parser': interp.parser, 'context_source': interp.context_source},
        'evidence': {'multipv': multipv},
    }


def _analyze_plan(board: chess.Board, user_side: chess.Color, allow_best_move: bool, interp: Interpretation) -> dict:
    multipv = evaluate_multipv(board.fen(), board.turn, 4)
    if not multipv:
        return {'reply': 'I cannot get enough engine evidence to identify a concrete plan right now.', 'verdict': 'uncertain', 'confidence': .5, 'claims': [], 'analysis_context': {}}
    stories = []
    for info in multipv[:3]:
        try:
            move = chess.Move.from_uci(info['move_uci'])
        except Exception:
            continue
        if move not in board.legal_moves:
            continue
        fx = _move_consequences(board, move, board.turn)
        stories.append((info['move_san'], fx['facts']))
    first_san, first_facts = stories[0] if stories else (multipv[0]['move_san'], [])
    if first_facts:
        reply = f"I would start with {first_san}, because it {_natural_join(first_facts[:2])}."
    else:
        reply = f"I would start with {first_san}. It is not a forcing move, so the plan is positional rather than tactical."
    if len(stories) >= 2 and stories[1][1]:
        reply += f" The fact that {stories[1][0]} is also strong and {_natural_join(stories[1][1][:1])} suggests the broader plan is to improve that same part of the position rather than chase a one-move tactic."
    return {
        'reply': reply,
        'verdict': 'supported',
        'confidence': .82,
        'claims': [],
        'analysis_context': {'parser': interp.parser, 'context_source': interp.context_source},
        'evidence': {'multipv': multipv},
    }



def _ollama_personalize_reply(reply: str, user_text: str, state: dict, settings: dict) -> str:
    """Use explicit learner ratings only to adapt coaching presentation.

    The deterministic/engine-grounded reply remains the factual substrate. The
    model is prohibited from adding chess facts, moves, evaluations, or claims.
    """
    examples = list(state.get('feedback_examples') or [])[-6:]
    if not examples or not settings.get('adaptive_coach_use_ollama'):
        return reply
    base = str(settings.get('ollama_base_url') or 'http://127.0.0.1:11434').rstrip('/')
    model = str(settings.get('ollama_model') or 'qwen2.5:7b')
    prompt = {
        'player_message': user_text,
        'grounded_response': reply,
        'learner_feedback_examples': examples,
    }
    system = '''You are the presentation layer for a chess coach. Rewrite the grounded_response so it better matches this learner's demonstrated preferences from prior thumbs-up (+1) and thumbs-down (-1) examples. You may change clarity, structure, emphasis, tone, and level of detail only. Do NOT add, remove, reverse, or invent chess facts, moves, evaluations, tactical claims, causal claims, or verdicts. Do not mention the ratings. If the feedback does not imply a clear presentation preference, return the grounded_response unchanged. Return plain text only.'''
    try:
        response = requests.post(
            f'{base}/api/chat',
            json={
                'model': model,
                'stream': False,
                'messages': [
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': json.dumps(prompt)},
                ],
                'options': {'temperature': 0.15},
            },
            timeout=15,
        )
        response.raise_for_status()
        polished = str(response.json()['message']['content']).strip()
        return polished or reply
    except Exception:
        return reply


def reason_about_message(conn, thread_id: int, position_row, text: str, displayed_fen: str, settings: dict, dialogue_context: Optional[dict] = None) -> Optional[dict]:
    dialogue_context = dialogue_context or {}
    session_solved = bool(position_row['learned']) or bool(dialogue_context.get('session_solved'))
    temporal_context = _temporal_context_for_message(position_row, text, displayed_fen, dialogue_context)
    try:
        interp = interpret_message(
            conn, thread_id, displayed_fen, text, position_row['user_color'], settings,
            temporal_context=temporal_context,
        )
    except Exception:
        return None

    # The three conversation routes all share the same board position:
    # general understanding, concrete move/variation, or motif exploration.
    # A well-identified move takes precedence over a mere mention of a motif.
    motif_key = find_requested_motif(conn, text)
    concrete = interp.intent in ('analyze_move', 'why_not_move', 'analyze_variation', 'compare_moves')
    temporal_claim = _analyze_temporal_claim(interp, position_row, temporal_context)
    if temporal_claim is not None:
        result = temporal_claim
    elif not concrete and motif_key:
        result = probe_motif(position_row, chess.Board(interp.context_fen), motif_key, session_solved, conn=conn)
        interp.intent = 'learning_motif'
    elif not concrete and wants_general_explanation(text) and interp.intent not in ('identify_threat', 'identify_plan'):
        result = explain_general(position_row, interp.context_fen, session_solved)
        interp.intent = 'general_explanation'
    else:
        if interp.intent == 'none' or (interp.intent == 'validate_claim' and not interp.move_uci):
            return None
        result = analyze_interpretation(interp, position_row['user_color'], session_solved)
        # A move-specific question must use the same comparative explanation
        # system as a solved training puzzle. Before solving, preserve the
        # established no-spoilers candidate-move feedback.
        if session_solved and interp.move_uci and interp.intent in ('analyze_move', 'why_not_move', 'analyze_variation'):
            board = chess.Board(interp.context_fen)
            try:
                candidate = chess.Move.from_uci(interp.move_uci)
                if candidate in board.legal_moves:
                    best = evaluate_fen(board.fen(), board.turn)
                    played = evaluate_move_quality(board.fen(), candidate.uci(), board.turn)
                    explanation = shared_move_explanation(board, candidate, best, played, position_row=position_row)
                    if explanation:
                        if interp.intent == 'analyze_variation' and interp.variation_san:
                            # Evaluate the exact proposed continuation as well as
                            # contrasting its first decision with the engine line.
                            sequence = ' '.join(interp.variation_san[:6])
                            end_board = board.copy(stack=False)
                            for uci in interp.variation_uci or []:
                                line_move = chess.Move.from_uci(uci)
                                if line_move not in end_board.legal_moves:
                                    break
                                end_board.push(line_move)
                            final = (result.get('evidence') or {}).get('final_eval') or {}
                            if end_board.is_checkmate():
                                outcome = 'That continuation ends in checkmate.'
                            elif final.get('mate') is not None:
                                outcome = ('Stockfish sees a forced mate for the side that started this line.'
                                           if final['mate'] > 0 else
                                           'Stockfish sees a forced mate against the side that started this line.')
                            else:
                                score = float(final.get('eval_cp') or 0) / 100
                                outcome = f'At the end of your line, Stockfish evaluates the position at {score:+.2f} pawns for the side that started it.'
                            result['reply'] = f"Your line {sequence}: {outcome} {explanation}"
                        else:
                            result['reply'] = explanation
                        result.setdefault('evidence', {})['shared_explanation_engine'] = True
            except (ValueError, KeyError):
                pass

    state = _conversation_state(conn, thread_id)
    personalized_reply = _ollama_personalize_reply(result['reply'], text, state, settings)
    analysis_context = result.get('analysis_context') or {}
    analysis_context.setdefault('temporal_scope', temporal_context.get('scope'))
    analysis_context.setdefault('context_source', temporal_context.get('context_source'))
    return {
        'reply': personalized_reply,
        'verdict': result.get('verdict') or 'uncertain',
        'confidence': float(result.get('confidence') or interp.confidence),
        'claims': result.get('claims') or [],
        'evidence': result.get('evidence') or {},
        'analysis_context': analysis_context,
        'interpretation': asdict(interp),
        'parser': interp.parser,
        'intent': interp.intent,
        'temporal_context': temporal_context,
    }

