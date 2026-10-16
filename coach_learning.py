"""Adaptive-coach routes grounded in the shared puzzle explanation engine.

Classification parses the *request*, not the board. A motif is only presented
as demonstrated when a candidate engine line also passes the motif detector.
"""
from __future__ import annotations

import json
import re

import chess

from coaching import generate_coaching_text
from engine_service import evaluate_fen, evaluate_move_quality, evaluate_multipv
from learning import CONCEPT_CATALOG, classify_learning_concepts

WORKFLOW_VERSION = 'adaptive-coach-workflow-v1'

MOTIF_ALIASES = {
    'fork': ['fork', 'double attack', 'double attacks'],
    'pin': ['pin', 'pinned piece', 'pinned'],
    'discovered_attack': ['discovered attack', 'discovered check'],
    'mating_net': ['mating net', 'checkmate', 'mating attack', 'forced mate'],
    'mate_defense': ['stop mate', 'defend mate', 'mate defense'],
    'hanging_piece': ['new threat', 'attack loose piece'],
    'capture_loose_piece': ['free piece', 'undefended target', 'loose material'],
    'dont_hang_pieces': ['hanging piece', 'moving en prise', 'blunder'],
    'lost_material': ['lost material', 'material loss'],
    'loose_piece_awareness': ['hanging piece', 'loose piece', 'undefended piece'],
    'missed_capture': ['win material', 'winning material'],
    'removal_of_defender': ['remove the defender', 'removal of defender'],
    'overloaded_defender': ['overloaded defender', 'overload'],
    'deflection': ['deflection', 'distraction'],
    'passed_pawn': ['passed pawn'],
    'pawn_structure': ['pawn structure', 'doubled pawn', 'isolated pawn'],
    'simplification': ['simplification', 'exchange pieces', 'trading pieces'],
    'counterattack': ['counterattack', 'counter attack'],
    'king_safety': ['king safety'],
    'piece_activity': ['piece activity'],
    'piece_coordination': ['piece coordination'],
    'space_advantage': ['space advantage'],
    'opposition_zugzwang': ['zugzwang', 'opposition'],
    'skewer': ['skewer'],
    'promotion_tactic': ['promotion', 'promote'],
    'pawn_break': ['pawn break'],
    'king_activity': ['king activity'],
    'piece_development': ['development', 'develop pieces'],
    'trapped_piece': ['trapped piece'],
    'defensive_resource': ['defensive resource'],
    'tactical_combination': ['tactical combination', 'combination'],
}
NAMES = {item['key']: item['name'] for item in CONCEPT_CATALOG}
for item in CONCEPT_CATALOG:
    MOTIF_ALIASES.setdefault(item['key'], []).append(item['name'].lower())

GENERAL_QUESTIONS = re.compile(
    r'\b(explain|explanation|understand|why (?:is|was|does|did) (?:this|that|the best|stockfish|the engine)|'
    r'what(?:\s+is|\s+was|\s+am|\s+are) (?:the )?(?:point|idea|lesson|reason)|'
    r'help me|walk me through|break it down|what did i miss|more detail|why|confused|not sure why)\b', re.I)
MOTIF_REQUEST = re.compile(r'\b(show|find|demonstrate|illustrate|teach|explore|learn|try|use|look for|about|how|why|what|explain|understand|example|lesson|motif)\b', re.I)


def requested_motif(text: str) -> str | None:
    text = str(text or '').lower()
    if not MOTIF_REQUEST.search(text):
        return None
    matches = []
    for key, aliases in MOTIF_ALIASES.items():
        for alias in aliases:
            if re.search(r'(?<!\w)' + re.escape(alias.lower()) + r'(?!\w)', text):
                matches.append((len(alias), key))
    # First prefer more specific phrases, then the original taxonomy order.
    return max(matches)[1] if matches else None



def find_requested_motif(conn, text: str) -> str | None:
    """Recognize built-in as well as user-promoted personal lesson names."""
    known = requested_motif(text)
    if known or not MOTIF_REQUEST.search(text or ''):
        return known
    words = str(text or '').lower()
    try:
        rows = conn.execute("""SELECT key, name, aliases_json FROM learning_concepts
                              WHERE status IN ('candidate', 'personal', 'promoted', 'seeded')""").fetchall()
    except Exception:
        return None
    matches = []
    for row in rows:
        phrases = [str(row['name']).lower()]
        try:
            phrases.extend(str(alias).lower() for alias in json.loads(row['aliases_json'] or '[]')
                           if isinstance(alias, str))
        except (ValueError, TypeError):
            pass
        for phrase in phrases:
            if len(phrase) >= 4 and re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', words):
                matches.append((len(phrase), row['key']))
    return max(matches)[1] if matches else None


def wants_general_explanation(text: str) -> bool:
    return bool(GENERAL_QUESTIONS.search(text or ''))


def _read(row, name, default=None):
    try:
        value = row[name]
        return value if value is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def _json_pv(raw):
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or '[]')
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def shared_move_explanation(board: chess.Board, candidate: chess.Move, best: dict,
                            candidate_eval: dict, *, position_row=None) -> str:
    """Explain the two branches from the same root via the app's canonical model."""
    best_uci = best.get('best_move_uci') or (best.get('pv_uci') or [None])[0]
    if not best_uci:
        return ''
    best_move = chess.Move.from_uci(best_uci)
    if best_move not in board.legal_moves:
        return ''
    same_root = _read(position_row, 'fen') == board.fen()
    gap = int(best.get('eval_cp') or 0) - int(candidate_eval.get('eval_cp') or 0)
    mate_best = best.get('mate')
    mate_other = candidate_eval.get('mate')
    category = ('missed_checkmate' if mate_best is not None and mate_best > 0
                and not (mate_other is not None and mate_other > 0)
                else 'major_blunder' if gap >= 150 else 'excellent_move')
    _, explanation = generate_coaching_text(
        fen=board.fen(),
        previous_fen=_read(position_row, 'previous_fen') if same_root else None,
        opponent_move_uci=_read(position_row, 'opponent_move_uci') if same_root else None,
        opponent_move_san=_read(position_row, 'opponent_move_san') if same_root else None,
        played_move_uci=candidate.uci(), played_move_san=board.san(candidate),
        best_move_uci=best_move.uci(), best_move_san=board.san(best_move),
        category=category,
        mate_before=mate_best if category == 'missed_checkmate' else None,
        best_pv_uci=best.get('pv_uci') or (_json_pv(_read(position_row, 'best_pv_uci')) if same_root else []),
        played_pv_uci=candidate_eval.get('pv_uci') or [],
    )
    return explanation or ''


def explain_general(position_row, displayed_fen: str, solved: bool) -> dict:
    # Do not reveal the precomputed best move before solving the puzzle.
    if not solved:
        text = _read(position_row, 'coach_prompt') or 'Start by identifying what the last move threatened, then look for checks, captures, and defenses.'
        return {'reply': text, 'verdict': 'supported', 'evidence': {'spoiler_safe': True},
                'intent': 'general_explanation'}
    if displayed_fen == _read(position_row, 'fen'):
        explanation = _read(position_row, 'coach_explanation') or ''
        if explanation:
            return {'reply': explanation, 'verdict': 'supported', 'evidence': {'source': 'saved_explanation'},
                    'intent': 'general_explanation'}
    board = chess.Board(displayed_fen)
    best = evaluate_fen(board.fen(), board.turn)
    if best.get('best_move_san'):
        return {'reply': f"From this position, {best['best_move_san']} is Stockfish's leading candidate. Ask about a specific reply or variation and I can compare it with the alternatives.",
                'verdict': 'supported', 'evidence': {'source': 'live_engine'}, 'intent': 'general_explanation'}
    return {'reply': 'What changed after the last move? I can examine a specific continuation or learning motif with you.',
            'verdict': 'uncertain', 'intent': 'general_explanation', 'evidence': {}}


def probe_motif(position_row, board: chess.Board, motif_key: str, solved: bool, conn=None) -> dict:
    label = NAMES.get(motif_key, motif_key.replace('_', ' ').title())
    adaptive_detector = None
    if conn is not None and motif_key not in NAMES:
        row = conn.execute('SELECT name, description, detector_json FROM learning_concepts WHERE key=?',
                           (motif_key,)).fetchone()
        if row:
            label = row['name']
            try:
                adaptive_detector = json.loads(row['detector_json'] or 'null')
            except (ValueError, TypeError):
                adaptive_detector = None
    if not solved:
        item = next((item for item in CONCEPT_CATALOG if item['key'] == motif_key), {})
        return {'reply': f"Look for {label.lower()} here: {item.get('description', 'check how the pieces and threats interact')} I'll test concrete candidate moves after the puzzle is solved.",
                'verdict': 'pending', 'evidence': {'spoiler_safe': True}, 'intent': 'learning_motif'}
    candidates = evaluate_multipv(board.fen(), board.turn, 6)
    if not candidates:
        return {'reply': f'I could not obtain a Stockfish line to test {label.lower()} here.',
                'verdict': 'uncertain', 'evidence': {}, 'intent': 'learning_motif'}
    top_cp = int(candidates[0].get('eval_cp') or 0)
    matched = []
    for candidate in candidates:
        try:
            move = chess.Move.from_uci(candidate['move_uci'])
            if move not in board.legal_moves:
                continue
            labels = classify_learning_concepts(
                board, move, move, 'excellent_move', 0,
                best_pv_uci=candidate.get('pv_uci') or [],
                previous_fen=_read(position_row, 'previous_fen') if board.fen() == _read(position_row, 'fen') else None,
                opponent_move_uci=_read(position_row, 'opponent_move_uci') if board.fen() == _read(position_row, 'fen') else None)
            specific = next((item for item in labels if item.key == motif_key and item.confidence >= 0.70), None)
            if specific is None and adaptive_detector:
                # Import lazily to avoid the circular dependency between the
                # conversation interpreter and personal motif definitions.
                from adaptive_coach import _adaptive_detector_match
                confidence, reason = _adaptive_detector_match(board, move, board.turn, adaptive_detector)
                if confidence >= 0.70:
                    from types import SimpleNamespace
                    specific = SimpleNamespace(key=motif_key, confidence=confidence, evidence=reason)
            if specific:
                loss = max(0, top_cp - int(candidate.get('eval_cp') or 0))
                # Move needs to be reasonably sound, not merely an illustrative but losing trick.
                if loss <= 180:
                    matched.append((specific.confidence - loss / 1000, candidate, specific))
        except (ValueError, KeyError):
            continue
    if not matched:
        return {'reply': f"None of Stockfish's top {len(candidates)} candidate lines clearly demonstrates {label.lower()} in this position. That does not mean the motif is impossible; I would not force the label onto an unrelated move.",
                'verdict': 'uncertain', 'intent': 'learning_motif',
                'evidence': {'candidates_checked': len(candidates), 'motif_key': motif_key}}
    _, chosen, evidence = max(matched, key=lambda item: item[0])
    move = chess.Move.from_uci(chosen['move_uci'])
    best = evaluate_fen(board.fen(), board.turn)
    # Stockfish's top root is the benchmark; the chosen motif move is what we test.
    candidate_eval = evaluate_move_quality(board.fen(), move.uci(), board.turn)
    story = shared_move_explanation(board, move, best, candidate_eval, position_row=position_row)
    line = chosen.get('pv_san') or []
    evidence_text = str(evidence.evidence or '').strip().rstrip('.')
    if evidence_text.lower().startswith(str(chosen['move_san']).lower()):
        prefix = evidence_text + '.'
    else:
        prefix = f"Consider {chosen['move_san']} for {label.lower()}: {evidence_text}."
    # Only include the actual continuation when it reveals an idea that is not
    # obvious in the first move. A raw SAN dump is not an explanation.
    if chosen['move_uci'] == best.get('best_move_uci') and board.fen() == _read(position_row, 'fen'):
        user_uci = _read(position_row, 'played_move_uci')
        try:
            user_move = chess.Move.from_uci(user_uci)
            if user_move in board.legal_moves and user_move != move:
                _, comparison = generate_coaching_text(
                    fen=board.fen(), previous_fen=_read(position_row, 'previous_fen'),
                    opponent_move_uci=_read(position_row, 'opponent_move_uci'),
                    opponent_move_san=_read(position_row, 'opponent_move_san'),
                    played_move_uci=user_move.uci(), played_move_san=board.san(user_move),
                    best_move_uci=move.uci(), best_move_san=board.san(move),
                    category=_read(position_row, 'category', 'major_blunder'),
                    best_pv_uci=chosen.get('pv_uci') or [],
                    played_pv_uci=_json_pv(_read(position_row, 'played_pv_uci')))
                if comparison and comparison.lower() not in prefix.lower():
                    prefix += ' ' + comparison
        except (ValueError, TypeError):
            pass
    elif story and chosen['move_uci'] != best.get('best_move_uci'):
        prefix += f' Stockfish prefers a different first move: {story}'
    return {'reply': prefix, 'verdict': 'supported', 'intent': 'learning_motif',
            'evidence': {'motif_key': motif_key, 'move_uci': move.uci(), 'pv_uci': chosen.get('pv_uci') or [],
                         'eval_cp': candidate_eval.get('eval_cp'), 'best_cp': best.get('eval_cp'),
                         'motif_confidence': evidence.confidence},
            'analysis_context': {'move_uci': move.uci(), 'move_san': board.san(move),
                                 'resulting_fen': (lambda b: (b.push(move), b.fen())[1])(board.copy(stack=False))}}
