from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess

from position_context import inspect_response
from immediate_decision import immediate_decision
from decision_context import decision_facts
from semantic_coaching import evidence_findings
from causal_selection import primary_causal_finding, finding_score
from loose_piece_provenance import differential_loss_motif, confirmed_differential_loss
from motif_relevance import select_relevant_primary
from motif_hierarchy import choose_specific, validate_ontology
from pv_reasoning import fork_evidence, legal_pv, comparative_insight

CLASSIFIER_VERSION = '2.8-shared-causal-selection'

# A deliberately compact curriculum: these are common, teachable amateur
# failure modes that we can identify with reasonably explainable board rules.
# The classifier is multi-label; one concept is selected as primary.
CONCEPT_CATALOG = [
    {'key': 'back_rank_mate', 'name': 'Back-Rank Mate', 'family': 'Tactics', 'description': 'Spot mating chances against a king trapped behind its own pawns.', 'priority': 100},
    {'key': 'mate_threat', 'name': 'Threaten Mate', 'family': 'Tactics', 'description': 'Create an immediate mating threat that the opponent must answer, without confusing a threat with forced mate.', 'priority': 94},
    {'key': 'mating_net', 'name': 'Mating Net', 'family': 'Tactics', 'description': 'Restrict the king and turn forcing checks into a mating sequence.', 'priority': 96},
    {'key': 'tactical_combination', 'name': 'Tactical Combination', 'family': 'Tactics', 'description': 'Calculate a sequence whose tactical payoff emerges only after the opponent replies.', 'priority': 91},
    {'key': 'fork', 'name': 'Double Attack', 'family': 'Tactics', 'description': 'Create two important threats with one move.', 'priority': 92},
    {'key': 'pin', 'name': 'Pin', 'family': 'Tactics', 'description': 'Exploit a piece that cannot move without exposing something more valuable.', 'priority': 91},
    {'key': 'skewer', 'name': 'Skewer', 'family': 'Tactics', 'description': 'Force a valuable piece away to expose the target behind it.', 'priority': 90},
    {'key': 'discovered_attack', 'name': 'Discovered Attack', 'family': 'Tactics', 'description': 'Move one piece to uncover an attack from another.', 'priority': 89},
    {'key': 'deflection', 'name': 'Distraction / Deflection', 'family': 'Tactics', 'description': 'Draw a defender away so its former target becomes vulnerable in the continuation.', 'priority': 89},
    {'key': 'removal_of_defender', 'name': 'Remove the Defender', 'family': 'Tactics', 'description': 'Eliminate a key defender so another target becomes vulnerable.', 'priority': 88},
    {'key': 'overloaded_defender', 'name': 'Overload', 'family': 'Tactics', 'description': 'Exploit a defender that is responsible for too many jobs.', 'priority': 87},
    {'key': 'trapped_piece', 'name': 'Trap a Piece', 'family': 'Tactics', 'description': 'Restrict a valuable piece until it has no safe escape.', 'priority': 86},
    {'key': 'material_sacrifice', 'name': 'Sacrifice Material', 'family': 'Tactics', 'description': 'Intentionally concede material for a verified tactical or positional opportunity.', 'priority': 93},
    {'key': 'exchange_sacrifice', 'name': 'Exchange Sacrifice', 'family': 'Tactics', 'description': 'Give a rook for a bishop or knight to gain compensation.', 'priority': 94},
    {'key': 'exchange', 'name': 'Piece Exchange', 'family': 'Tactics', 'description': 'Recognize captures and recaptures, and distinguish favorable trades from winning a free piece.', 'priority': 82},
    {'key': 'hanging_piece', 'name': 'Attack Loose Pieces', 'family': 'Tactics', 'description': 'Create a new threat against enemy material and realize it in a near-term continuation.', 'priority': 84},
    {'key': 'capture_loose_piece', 'name': 'Capture Loose Pieces', 'family': 'Tactics', 'description': 'Notice and capture an already-undefended enemy piece in the training position.', 'priority': 88},
    {'key': 'dont_hang_pieces', 'name': "Don't Hang Pieces", 'family': 'Defense', 'description': 'Avoid moving a piece onto an undefended square where the opponent can win it.', 'priority': 96},
    {'key': 'lost_material', 'name': 'Lost Material', 'family': 'Defense', 'description': 'Recognize the direct material cost of the game move without mislabeling it as a pre-existing loose piece.', 'priority': 86},
    {'key': 'missed_capture', 'name': 'Win Material', 'family': 'Tactics', 'description': 'Take a favorable capture before choosing a quieter move.', 'priority': 78},
    {'key': 'promotion_tactic', 'name': 'Promotion', 'family': 'Tactics', 'description': 'Use forcing pawn advances and promotion threats to decide the position.', 'priority': 85},
    {'key': 'attack_building', 'name': 'Build the Attack', 'family': 'Tactics', 'description': 'Create forcing threats that keep the opponent reacting.', 'priority': 74},
    {'key': 'counterattack', 'name': 'Counterattack', 'family': 'Tactics', 'description': 'Answer an opponent threat by creating an equal or stronger threat of your own.', 'priority': 75},
    {'key': 'simplification', 'name': 'Simplify', 'family': 'Strategy', 'description': 'Trade pieces when exchanges reduce danger or make an advantage easier to convert.', 'priority': 73},
    {'key': 'king_safety', 'name': 'King Safety', 'family': 'Defense', 'description': 'Address direct king danger before pursuing slower plans.', 'priority': 72},
    {'key': 'mate_defense', 'name': 'Stop the Mate', 'family': 'Defense', 'description': 'Recognize and neutralize a mating threat immediately.', 'priority': 99},
    {'key': 'threat_awareness', 'name': 'See the Threat', 'family': 'Defense', 'description': 'Identify what the opponent is threatening before you choose a move.', 'priority': 94},
    {'key': 'loose_piece_awareness', 'name': 'Protect Loose Pieces', 'family': 'Defense', 'description': 'Save a piece that was already loose in the training position and whose loss the better move prevents.', 'priority': 93},
    {'key': 'defensive_resource', 'name': 'Defensive Resource', 'family': 'Defense', 'description': 'Find active or simplifying moves that keep a difficult position playable.', 'priority': 80},
    {'key': 'piece_development', 'name': 'Develop Pieces', 'family': 'Strategy', 'description': 'Bring minor pieces into the game efficiently instead of losing opening tempi.', 'priority': 58},
    {'key': 'pawn_structure', 'name': 'Pawn Structure', 'family': 'Strategy', 'description': 'Create an identifiable weakness such as doubled or isolated pawns, or avoid one yourself.', 'priority': 66},
    {'key': 'space_advantage', 'name': 'Space Advantage', 'family': 'Strategy', 'description': 'Gain sustainable control of squares in the opponent’s territory.', 'priority': 54},
    {'key': 'pawn_break', 'name': 'Pawn Break', 'family': 'Strategy', 'description': 'Challenge the pawn structure at the right moment to open useful lines.', 'priority': 64},
    {'key': 'piece_activity', 'name': 'Improve Activity', 'family': 'Strategy', 'description': 'Place pieces on squares where they influence more of the position.', 'priority': 55},
    {'key': 'piece_coordination', 'name': 'Coordinate Pieces', 'family': 'Strategy', 'description': 'Improve how your pieces defend one another and combine on key squares.', 'priority': 57},
    {'key': 'passed_pawn', 'name': 'Passed Pawn', 'family': 'Endgames', 'description': 'Create, support, or advance a passed pawn when it becomes the main plan.', 'priority': 70},
    {'key': 'king_activity', 'name': 'Activate the King', 'family': 'Endgames', 'description': 'Use the king as an active fighting piece once the position simplifies.', 'priority': 68},
    {'key': 'endgame_precision', 'name': 'Endgame Conversion', 'family': 'Endgames', 'description': 'Find a move that preserves a tablebase-verified win or draw, rather than allowing the result to slip.', 'priority': 98},
    {'key': 'opposition_zugzwang', 'name': 'Opposition & Zugzwang', 'family': 'Endgames', 'description': 'Use king opposition and spare tempi to force the opponent backward.', 'priority': 76},
    {'key': 'calculation', 'name': 'Forcing-Move Scan', 'family': 'Calculation', 'description': 'Check forcing moves and calculate one move deeper before committing.', 'priority': 20},
]

CONCEPTS = {item['key']: item for item in CONCEPT_CATALOG}
validate_ontology(CONCEPTS)

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}


@dataclass
class LearningLabel:
    key: str
    confidence: float
    evidence: str
    is_primary: bool = False


def _piece_value(piece: Optional[chess.Piece]) -> int:
    return PIECE_VALUES.get(piece.piece_type, 0) if piece else 0


def _is_endgame(board: chess.Board) -> bool:
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    non_pawn_material = 0
    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        non_pawn_material += PIECE_VALUES[piece_type] * (
            len(board.pieces(piece_type, chess.WHITE)) + len(board.pieces(piece_type, chess.BLACK))
        )
    return queens == 0 or non_pawn_material <= 16


def _pinned_squares(board: chess.Board, color: chess.Color) -> set[int]:
    return {
        square
        for square in chess.SQUARES
        if (piece := board.piece_at(square)) is not None
        and piece.color == color
        and piece.piece_type != chess.KING
        and board.is_pinned(color, square)
    }


def _square_distance(a: int, b: int) -> int:
    return max(abs(chess.square_file(a) - chess.square_file(b)), abs(chess.square_rank(a) - chess.square_rank(b)))


def _center_distance(square: int) -> float:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    return min(
        abs(file - 3.5) + abs(rank - 3.5),
        7.0,
    )


def _is_passed_pawn(board: chess.Board, square: int, color: chess.Color) -> bool:
    if board.piece_type_at(square) != chess.PAWN:
        return False

    file = chess.square_file(square)
    rank = chess.square_rank(square)
    enemy = not color
    for enemy_square in board.pieces(chess.PAWN, enemy):
        enemy_file = chess.square_file(enemy_square)
        enemy_rank = chess.square_rank(enemy_square)
        if abs(enemy_file - file) > 1:
            continue
        if color == chess.WHITE and enemy_rank > rank:
            return False
        if color == chess.BLACK and enemy_rank < rank:
            return False
    return True


def _skewer_target(after: chess.Board, attacker_square: int, victim_color: chess.Color) -> Optional[chess.Piece]:
    attacker = after.piece_at(attacker_square)
    king_square = after.king(victim_color)
    if attacker is None or king_square is None or attacker.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        return None

    af, ar = chess.square_file(attacker_square), chess.square_rank(attacker_square)
    kf, kr = chess.square_file(king_square), chess.square_rank(king_square)
    df, dr = kf - af, kr - ar

    if df == 0:
        step_f, step_r = 0, 1 if dr > 0 else -1
    elif dr == 0:
        step_f, step_r = 1 if df > 0 else -1, 0
    elif abs(df) == abs(dr):
        step_f, step_r = (1 if df > 0 else -1), (1 if dr > 0 else -1)
    else:
        return None

    # The attacker must actually attack the king for this to be a skewer line.
    if king_square not in after.attacks(attacker_square):
        return None

    f, r = kf + step_f, kr + step_r
    while 0 <= f <= 7 and 0 <= r <= 7:
        square = chess.square(f, r)
        piece = after.piece_at(square)
        if piece is not None:
            if piece.color == victim_color and piece.piece_type != chess.KING and _piece_value(piece) >= 3:
                return piece
            return None
        f += step_f
        r += step_r
    return None


def _important_targets(board: chess.Board, attacker_square: int, victim_color: chess.Color) -> list[tuple[int, chess.Piece]]:
    targets = []
    for square in board.attacks(attacker_square):
        piece = board.piece_at(square)
        if piece and piece.color == victim_color and (piece.piece_type == chess.KING or _piece_value(piece) >= 3):
            targets.append((square, piece))
    return targets


def classify_learning_concepts(
    board: chess.Board,
    played_move: chess.Move,
    best_move: chess.Move,
    category: str,
    centipawn_loss: int,
    mate_before: Optional[int] = None,
    previous_fen: Optional[str] = None,
    opponent_move_uci: Optional[str] = None,
    best_pv_uci=None,
    played_pv_uci=None,
) -> list[LearningLabel]:
    """Return explainable multi-label learning motifs for a confirmed mistake.

    These rules intentionally bias toward precision. If no concrete motif is
    recognized, the position falls back to a calculation/process lesson.
    """
    side = board.turn
    opponent = not side
    context = inspect_response(board, best_move, played_move, previous_fen, opponent_move_uci)
    root_evidence = immediate_decision(board, best_move, played_move, context)
    line = legal_pv(board, best_pv_uci, first_move=best_move)
    fork = fork_evidence(board, best_move, best_pv_uci)
    variation = comparative_insight(board, best_move, played_move, best_pv_uci, played_pv_uci)
    decision = decision_facts(board, best_move, played_move, best_pv_uci, played_pv_uci)
    labels: dict[str, LearningLabel] = {}

    def add(key: str, confidence: float, evidence: str):
        confidence = max(0.0, min(1.0, float(confidence)))
        existing = labels.get(key)
        if existing is None or confidence > existing.confidence:
            labels[key] = LearningLabel(key=key, confidence=confidence, evidence=evidence)

    best_piece = board.piece_at(best_move.from_square)
    captured_piece = board.piece_at(best_move.to_square)
    best_is_capture = board.is_capture(best_move)
    best_is_castling = board.is_castling(best_move)
    before_pins = _pinned_squares(board, opponent)
    before_attack_count = len(board.attacks(best_move.from_square)) if best_piece else 0

    try:
        best_san = board.san(best_move)
    except Exception:
        best_san = best_move.uci()

    after = board.copy(stack=False)
    after.push(best_move)
    exchanged_at_root = bool(len(line) >= 2 and best_is_capture
        and after.is_capture(line[1]) and line[1].to_square == best_move.to_square)
    balanced_exchange = bool(exchanged_at_root and best_piece and captured_piece
        and abs(_piece_value(best_piece) - _piece_value(captured_piece)) <= 1)
    moved_piece = after.piece_at(best_move.to_square)
    opponent_king = after.king(opponent)

    played_after = board.copy(stack=False)
    try:
        played_after.push(played_move)
    except Exception:
        played_after = None

    own_valuable_under_attack = [
        square for square, piece in board.piece_map().items()
        if piece.color == side
        and piece.piece_type != chess.KING
        and _piece_value(piece) >= 3
        and board.is_attacked_by(opponent, square)
    ]
    before_defended_by_mover = set()
    if best_piece is not None:
        for square in board.attacks(best_move.from_square):
            piece = board.piece_at(square)
            if piece is not None and piece.color == side and piece.piece_type != chess.KING:
                before_defended_by_mover.add(square)
    after_defended_by_mover = set()
    if moved_piece is not None:
        for square in after.attacks(best_move.to_square):
            piece = after.piece_at(square)
            if piece is not None and piece.color == side and piece.piece_type != chess.KING:
                after_defended_by_mover.add(square)

    # Mating patterns.
    if after.is_checkmate():
        king_rank = chess.square_rank(opponent_king) if opponent_king is not None else -1
        back_rank = 0 if opponent == chess.WHITE else 7
        # Being *on* the back rank is not enough: many mates on g8/h8
        # are not back-rank patterns. Require own pawns blocking nearby
        # escape files before teaching this motif as the primary concept.
        forward_rank = back_rank + (1 if opponent == chess.WHITE else -1)
        king_file = chess.square_file(opponent_king) if opponent_king is not None else -1
        blocking_pawns = sum(
            1 for file in range(max(0, king_file - 1), min(7, king_file + 1) + 1)
            if (pawn := after.piece_at(chess.square(file, forward_rank))) is not None
            and pawn.color == opponent and pawn.piece_type == chess.PAWN
        ) if king_file >= 0 else 0
        if king_rank == back_rank and blocking_pawns >= 2:
            add('back_rank_mate', 0.99, f'{best_san} gives mate while the king is restricted by its own pawns on the rank in front of it.')
        add('mating_net', 0.99, f'{best_san} is an immediate checkmate.')
    elif category == 'missed_checkmate' or (mate_before is not None and mate_before > 0):
        add('mating_net', 0.96, 'Stockfish found a forced mating sequence that the game move missed.')

    # Defensive/outcome-oriented lessons.  These complement the tactical
    # solution motifs above by explaining why the user's actual move failed.
    if category == 'allowed_checkmate':
        add('mate_defense', 0.99, 'The played move allowed a forced mate; the best move was needed to stop the mating threat.')
        add('threat_awareness', 0.94, 'The opponent had an immediate mating threat that required attention.')
        add('king_safety', 0.95, 'King safety was the decisive constraint in the position.')
    elif category in {'threw_away_win', 'blundered_draw', 'blundered_into_loss'}:
        add('threat_awareness', 0.89, 'The played move changed a non-losing position into a clearly losing one.')
        add('defensive_resource', 0.82, f'{best_san} was an important resource for preserving the position.')
    elif category == 'major_blunder':
        add('threat_awareness', 0.74, 'A large one-move evaluation drop suggests an opponent resource was missed.')

    # Do not label a hanging piece merely because it is attacked and
    # undefended. Its actual loss, versus the better branch, must be proven
    # in a near-term legal continuation (see decision and semantic evidence).

    # Promotion and passed-pawn themes.
    if best_piece and best_piece.piece_type == chess.PAWN:
        if best_move.promotion:
            add('promotion_tactic', 0.98, f'{best_san} promotes a pawn.')
        elif _is_passed_pawn(after, best_move.to_square, side):
            rank = chess.square_rank(best_move.to_square)
            progress = rank if side == chess.WHITE else 7 - rank
            add('passed_pawn', 0.78 if progress >= 5 else 0.65, f'{best_san} creates or advances a passed pawn.')

        enemy_pawn_targets = [
            square for square in after.attacks(best_move.to_square)
            if (piece := after.piece_at(square)) is not None and piece.color == opponent and piece.piece_type == chess.PAWN
        ]
        if enemy_pawn_targets and not best_is_capture:
            add('pawn_break', 0.73, f'{best_san} challenges the opponent pawn structure.')

    # Forks and double attacks by the moved piece.
    if moved_piece is not None and not board.is_check():
        important = _important_targets(after, best_move.to_square, opponent)
        if len(important) >= 2:
            names = ', '.join(chess.piece_name(piece.piece_type) for _, piece in important[:3])
            add('fork', 0.94, f'{best_san} attacks multiple important targets ({names}).')

    # Broader attacking/defending ideas that are useful for the coaching layer.
    important_after = _important_targets(after, best_move.to_square, opponent) if moved_piece is not None else []
    if after.is_check() and not after.is_checkmate():
        add('attack_building', 0.76, f'{best_san} creates a forcing check and keeps the initiative.')
    elif len(important_after) >= 1 and not best_is_capture and not board.is_check():
        target_names = ', '.join(chess.piece_name(piece.piece_type) for _, piece in important_after[:2])
        add('attack_building', 0.63, f'{best_san} creates direct pressure on {target_names}.')

    if not board.is_check() and own_valuable_under_attack and (after.is_check() or important_after):
        add('counterattack', 0.70, f'{best_san} answers existing pressure by creating an immediate threat of its own.')

    newly_defended = after_defended_by_mover - before_defended_by_mover
    if len(newly_defended) >= 2:
        squares = ', '.join(chess.square_name(square) for square in sorted(newly_defended)[:3])
        add('piece_coordination', 0.68, f'{best_san} improves coordination by adding protection to pieces on {squares}.')

    # Pins created by the best move.
    after_pins = _pinned_squares(after, opponent)
    newly_pinned = after_pins - before_pins
    relevant_pins = newly_pinned.intersection(context['pin_relevant'])
    if relevant_pins:
        squares = ', '.join(chess.square_name(square) for square in sorted(relevant_pins))
        add('pin', 0.78, f'{best_san} newly pins an already vulnerable valuable piece on {squares}.')

    # A pinned defender may APPEAR able to capture the solution piece, but
    # such a capture is impossible because it exposes its own king.  Legal
    # engine continuations omit that answer entirely, so use board-verified
    # pseudo-legal geometry as supporting evidence instead of relying on PVs.
    # This also recognizes exploitation of an EXISTING pin (not only one
    # created by the best move).  Mere pins without an actual blocked capture
    # remain background context and cannot own a lesson.
    pin_refutations = context['pin_capture_refutations']
    if pin_refutations:
        add('pin', 0.97, pin_refutations[0]['evidence'])

    # Skewer: a sliding best move checks the king with valuable material behind it.
    if after.is_check() and _skewer_target(after, best_move.to_square, opponent) is not None:
        add('skewer', 0.92, f'{best_san} checks the king along a line with another valuable piece behind it.')

    # Revealed rays from a different, stationary slider establish discovered
    # attacks on valuable pieces, not only discovered checks. A move that
    # reveals the SAME attack as the played move does not explain why it wins.
    discoveries = context['discovered_unique_lines']
    if discoveries:
        discovery = discoveries[0]
        checking = discovery['kind'] == 'discovered_check'
        reliable_reply = any(d['kind'] in {'illegal_capture_during_discovered_check',
                                         'legal_capture_allows_followup'}
                             for d in context['discovered_reply_checks'])
        confidence = 0.97 if checking else (0.92 if reliable_reply else 0.79)
        add('discovered_attack', confidence, f'{best_san}: {discovery["evidence"]}')

    # Captures that remove defenders or simply win loose material.
    if best_is_capture and captured_piece is not None:
        defended_important = []
        for square in board.attacks(best_move.to_square):
            piece = board.piece_at(square)
            if piece and piece.color == opponent and (piece.piece_type == chess.KING or _piece_value(piece) >= 3):
                defended_important.append((square, piece))

        if len(defended_important) >= 2:
            add('overloaded_defender', 0.84, f'{best_san} removes a piece that was defending several important targets.')
        elif defended_important:
            add('removal_of_defender', 0.82, f'{best_san} removes a defender of another important target.')

        captured_value = _piece_value(captured_piece)
        destination_defended = after.is_attacked_by(opponent, best_move.to_square)
        if (
            best_piece is not None
            and best_piece.piece_type == chess.QUEEN
            and captured_piece.piece_type == chess.QUEEN
        ):
            add('simplification', 0.96, f'{best_san} offers or completes a queen exchange, sharply reducing tactical danger.')
        elif captured_value >= 5 and destination_defended and category in {
            'squandered_advantage', 'blundered_win', 'blundered_draw',
            'blundered_into_loss', 'threw_away_win', 'major_blunder'
        }:
            add('simplification', 0.72, f'{best_san} trades a major piece and simplifies a tactically sensitive position.')
        if captured_value >= 1 and not destination_defended:
            add('capture_loose_piece', 0.90 if captured_value >= 3 else 0.78,
                f'{best_san} captures material already available in the training position without an immediate legal recapture.')
        if captured_value >= 3:
            add('missed_capture', 0.76, f'{best_san} wins material immediately.')

    # Trapped target: the best move attacks a valuable piece with almost no legal exits.
    if moved_piece is not None:
        for square, target in _important_targets(after, best_move.to_square, opponent):
            if target.piece_type == chess.KING:
                continue
            legal_escapes = [move for move in after.legal_moves if move.from_square == square]
            if len(legal_escapes) <= 1:
                add('trapped_piece', 0.82, f'{best_san} attacks a valuable piece with almost no legal escape squares.')
                break

    # King safety and development.
    if best_is_castling:
        add('king_safety', 0.98, f'{best_san} castles and improves king safety.')
    elif board.is_check():
        add('king_safety', 0.88, 'The position requires an accurate response to a direct attack on the king.')
        evasion = context.get('check_evasion')
        if evasion:
            add(evasion['motif'], 0.98, evasion['evidence'])

    if best_piece and best_piece.piece_type in (chess.KNIGHT, chess.BISHOP) and board.fullmove_number <= 12:
        start_rank = 0 if side == chess.WHITE else 7
        if chess.square_rank(best_move.from_square) == start_rank and chess.square_rank(best_move.to_square) != start_rank:
            add('piece_development', 0.76, f'{best_san} develops a minor piece from its starting rank.')

    # Quiet activity gains for pieces that substantially increase their scope.
    if best_piece and best_piece.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) and not best_is_capture and not after.is_check():
        after_attack_count = len(after.attacks(best_move.to_square))
        center_gain = _center_distance(best_move.from_square) - _center_distance(best_move.to_square)
        if after_attack_count >= before_attack_count + 3 or center_gain >= 2:
            add('piece_activity', 0.61, f'{best_san} substantially improves the piece\'s activity.')

    # Endgame king technique and direct opposition.
    if _is_endgame(board) and best_piece and best_piece.piece_type == chess.KING:
        add('king_activity', 0.82, f'{best_san} activates the king in a simplified position.')
        own_king = after.king(side)
        enemy_king = after.king(opponent)
        if own_king is not None and enemy_king is not None:
            same_file = chess.square_file(own_king) == chess.square_file(enemy_king)
            same_rank = chess.square_rank(own_king) == chess.square_rank(enemy_king)
            if (same_file or same_rank) and _square_distance(own_king, enemy_king) == 2:
                add('opposition_zugzwang', 0.91, f'{best_san} establishes direct king opposition.')
            elif len(board.piece_map()) <= 6 and not best_is_capture and not after.is_check():
                add('opposition_zugzwang', 0.58, 'The simplified position is tempo-sensitive and the best move is a quiet king move.')

    # New direct, differentiated context: an offensive threat is not a
    # defensive save; an exchange is not an outright material win. Never
    # select Protect Loose Pieces when even the engine-preferred line loses
    # the exact same root piece.
    context_primary = None
    if decision:
        if decision['shared_loss'] and not decision['truly_saved']:
            labels.pop('loose_piece_awareness', None)
            if root_evidence and root_evidence['motif'] == 'loose_piece_awareness':
                root_evidence = None
        if (decision['opponent_mate_bad'] and not decision['opponent_mate_good']
                and played_move != best_move):
            add('mate_defense', 0.99,
                f'The game move allows {decision["opponent_mate_bad"][0]} checkmate immediately; {best_san} does not.')
            context_primary = 'mate_defense'
        elif (decision['our_mate_good'] and not decision['our_mate_bad']):
            add('mate_threat', 0.97,
                f'{best_san} threatens {decision["our_mate_good"][0]} next turn if unanswered.')
            context_primary = 'mate_threat'
        elif (decision['shared_loss'] and decision['new_targets']):
            threat = decision['new_targets'][0]
            add('counterattack', 0.96,
                f'{best_san} counterattacks the {threat["piece"]} on {threat["square"]}; '
                'the original threatened material is lost in both saved lines.')
            context_primary = 'counterattack'
        elif (decision['truly_saved'] and decision.get('bad') and
                any(c['ply'] <= 2 and not c['by_solver'] and
                    c['root_square'] == decision['truly_saved'][0]['square']
                    for c in decision['bad']['captures'])):
            saved = decision['truly_saved'][0]
            add('loose_piece_awareness', 0.97,
                f'{best_san} keeps the attacked {saved["piece"]} from {saved["square"]} '
                'through the compared continuation.')
            context_primary = 'loose_piece_awareness'
        elif (decision['good']['exchanges']
                and decision['good']['exchanges'][0]['first']['ply'] == 0):
            exchange = decision['good']['exchanges'][0]
            diff = exchange['recapture']['value'] - exchange['first']['value']
            if diff >= 2:
                motif = ('exchange_sacrifice' if exchange['recapture']['value'] == 5
                         and exchange['first']['value'] == 3 else 'material_sacrifice')
                add(motif, 0.97, f'{best_san} deliberately gives up more material than it takes.')
            elif abs(diff) <= 1:
                motif = 'simplification'
                add(motif, 0.84, f'{best_san} makes an even exchange of material.')
            else:
                motif = 'missed_capture'
            context_primary = motif
        else:
            # A *new* attack on a loose enemy target can be a motif only when
            # the good PV realizes the capture promptly, and the inferior line
            # misses that material. Mere geometry or an undefended target is
            # insufficient evidence for an attacking lesson.
            bad_captured = {c['root_square'] for c in decision['bad']['captures']
                            if c['by_solver']} if decision.get('bad') else set()
            for target in decision['new_targets']:
                if not target['loose'] or target['square'] in bad_captured:
                    continue
                if any(c['by_solver'] and c['root_square'] == target['square']
                       and 1 <= c['ply'] <= 2
                       for c in decision['good']['captures']):
                    add('hanging_piece', 0.92,
                        f'{best_san} attacks the opponent’s undefended {target["piece"]} '
                        f'on {target["square"]}; the continuation realizes the capture.')
                    context_primary = 'hanging_piece'
                    break

    # Keep process-level guidance out of the specific motif taxonomy.

    # A discovered check constrains the reply even when the moved piece is
    # captured. A quieter line attack is less clearly causal if the moved
    # piece is immediately exchanged and no actual follow-up is demonstrated.
    if exchanged_at_root and 'discovered_attack' in labels and not any(
        d['kind'] == 'discovered_check' for d in discoveries) and not any(
        d['kind'] == 'legal_capture_allows_followup'
        for d in context['discovered_reply_checks']):
        labels.pop('discovered_attack', None)

    # A piece recaptured on the next ply no longer attacks or pins anything.
    # Suppress fleeting geometrical labels, which would be misleading even as
    # secondary learning motifs for this position.
    if exchanged_at_root:
        for transient in ('fork', 'pin', 'attack_building', 'counterattack',
                          'trapped_piece', 'piece_activity', 'missed_capture'):
            if transient == 'pin' and pin_refutations:
                continue  # A verified illegal capture is not transient geometry.
            labels.pop(transient, None)
        if balanced_exchange and not variation['motif']:
            add('simplification', 0.88,
                f'{best_san} initiates a piece exchange; look at which threat the trade removes.')

    # The lesson's owner must come from a reason for THIS reply, not the most
    # conspicuous geometrical pattern somewhere on the board. Forced results
    # override this prioritization; otherwise trust only verified response
    # evidence (opponent move -> changed threat -> answer), with calculation as
    # a deliberately honest fallback when the continuation is unavailable.
    forced_primary = None
    if category == 'allowed_checkmate' and 'mate_defense' in labels:
        forced_primary = 'mate_defense'
    elif after.is_checkmate() or (mate_before is not None and mate_before > 0):
        if after.is_checkmate() and 'back_rank_mate' in labels:
            forced_primary = 'back_rank_mate'
        elif 'mating_net' in labels:
            forced_primary = 'mating_net'

    # Check evasion is a legal necessity. An interposition offering a verified
    # equal-value exchange is not an enduring attack on the checking piece.
    # Preserve a distinctive newly revealed *check* as immediate tactical
    # evidence, but otherwise place direct check defense ahead of geometry.
    check_evasion = context.get('check_evasion')

    # Explain the decisive move, not merely the context or an existing shape.
    # A genuine checking fork is forcing in one move; a quieter double attack
    # needs a safe attacker AND supporting actions in the stored PV.
    concrete_primary = None
    if fork and fork['strong'] and not exchanged_at_root:
        names = ' and '.join(f'{chess.piece_name(pc.piece_type)} on {chess.square_name(sq)}'
                             for sq, pc in fork['targets'][:2])
        add('fork', 0.98 if fork['line_supported'] else 0.94,
            f'{best_san} attacks {names} simultaneously' +
            ('; the engine continuation illustrates the tactic.' if fork['line_supported']
             else ' while giving check.' if fork['check_fork']
             else '; both valuable targets are exposed.'))
        concrete_primary = 'fork'
    elif (discoveries and discoveries[0]['kind'] == 'discovered_check'
          and not exchanged_at_root):
        concrete_primary = 'discovered_attack'
    elif pin_refutations and not exchanged_at_root:
        concrete_primary = 'pin'
    elif 'skewer' in labels and after.is_check():
        concrete_primary = 'skewer'
    elif ('discovered_attack' in labels and discoveries
          and any(d['kind'] == 'legal_capture_allows_followup'
                  for d in context['discovered_reply_checks'])):
        concrete_primary = 'discovered_attack'
    elif 'promotion_tactic' in labels:
        concrete_primary = 'promotion_tactic'
    elif 'capture_loose_piece' in labels and context['best_takes_loose']:
        concrete_primary = 'capture_loose_piece'
    elif 'counterattack' in labels and context['new_pressure'] and (after.is_check() or fork and fork['line_supported']):
        concrete_primary = 'counterattack'
    elif 'attack_building' in labels and after.is_check() and len(line) >= 3:
        concrete_primary = 'attack_building'
    elif (not exchanged_at_root and 'missed_capture' in labels
          and context['best_capture'] and context['best_takes_last_piece']):
        concrete_primary = 'missed_capture'
    elif ('missed_capture' in labels and best_is_capture and captured_piece
          and _piece_value(captured_piece) >= 3
          and not after.is_attacked_by(opponent, best_move.to_square)
          and not context['best_takes_loose']):
        concrete_primary = 'missed_capture'
    if check_evasion and not any(d['kind'] == 'discovered_check' for d in discoveries):
        concrete_primary = check_evasion['motif']

    contextual_primary = context['primary_key']
    if contextual_primary and contextual_primary not in labels and contextual_primary in CONCEPTS:
        add(contextual_primary, 0.91, context['primary_evidence'] or
            'The correct reply directly addresses the position’s concrete requirements.')

    # A continuation can prove a delayed payoff that one-move geometry misses.
    # Preserve immediate mate defense and directly demonstrated first-move
    # tactics; otherwise let the PV's concrete result resolve the bucket.
    pv_primary = variation['motif']
    if pv_primary and pv_primary in CONCEPTS:
        add(pv_primary, 0.96, variation['narrative'] or
            'The saved engine line demonstrates the later tactical payoff.')
    immediate_primary = concrete_primary if concrete_primary not in {'attack_building', 'counterattack'} else None
    if exchanged_at_root and immediate_primary in {'fork', 'pin', 'trapped_piece', 'missed_capture'}:
        immediate_primary = None
    chosen = (forced_primary or immediate_primary or pv_primary
              or (None if exchanged_at_root and concrete_primary in
                  {'fork', 'pin', 'attack_building', 'counterattack', 'missed_capture'}
                  else concrete_primary)
              or (None if exchanged_at_root and contextual_primary == 'missed_capture'
                  else contextual_primary))
    if exchanged_at_root and chosen is None:
        chosen = 'simplification' if balanced_exchange else 'calculation'
        add(chosen, 0.75, 'The recapture determines the material outcome; avoid labeling a temporary threat as a lasting attack.')
    if not chosen:
        # Forcing-Move Scan only applies where there is a concrete forcing
        # option at the root: a legal check, a capture, or an existing check.
        forcing = (board.is_check() or board.is_capture(best_move)
                   or board.gives_check(best_move)
                   or (played_move is not None and played_move in board.legal_moves and
                       (board.is_capture(played_move) or board.gives_check(played_move))))
        if forcing:
            chosen = 'calculation'
            add(chosen, 0.64, 'Compare immediate checks, captures, and replies.')

    # Root facts that distinguish these two actual moves are higher-confidence
    # learning material than a tactical pattern appearing many plies later.
    # Verified mate and check defense remain higher-priority forced obligations.
    root_primary = None
    if root_evidence and not forced_primary and not check_evasion:
        root_primary = root_evidence['motif']
        add(root_primary, root_evidence['strength'], root_evidence['explanation'])

    # Rank supported motifs by their proximity to THIS decision rather than
    # simply by the strength of their geometry or curriculum priority. The
    # opponent's previous move (context), the current problem (prompt), the
    # actual response, and the contrast with the played alternative all count.
    # A motif appearing only late in a sampled PV cannot become primary.
    pv_ply = variation.get('motif_ply')
    relevance_choice, relevance_scores = select_relevant_primary(
        list(labels.values()), context, original_choice=chosen,
        forced_choice=forced_primary, immediate_choice=(root_primary or immediate_primary or concrete_primary
        or ('simplification' if exchanged_at_root and balanced_exchange else None)
        or ('king_safety' if best_is_castling else None)),
        pv_choice=pv_primary, pv_ply=pv_ply)
    if relevance_choice == 'calculation' and relevance_choice not in labels:
        add('calculation', 0.65,
            'Other detected motifs are not established as relevant to the current decision.')
    if relevance_choice in labels:
        chosen = relevance_choice
    # The scorer cannot infer reliability from a geometry label alone: a
    # legally verified root capture or a missed immediate defense should own
    # the lesson even if a sampled PV contains a more exotic later tactic.
    if root_primary and root_primary in labels:
        chosen = root_primary
    # A demonstrable, position-specific distinction overrides a merely
    # geometric label or a temporary attack in a sampled PV.
    if context_primary and context_primary in labels and not forced_primary and not check_evasion:
        chosen = context_primary
    # Explanation and primary motif should describe the SAME causal event.
    # Only explicit threats / saved-line results may override the older
    # geometry-based motif; do not turn a weak positional hypothesis into
    # an asserted cause. Keep specific mating and immediate tactical labels.
    causal, _ = evidence_findings(
        board, best_move, played_move, best_pv_uci, played_pv_uci,
        category=category, mate_before=mate_before, facts=decision)
    if causal and not forced_primary and not check_evasion:
        cause = causal[0]
        if (cause.confidence >= 2 and cause.impact >= 78 and
                cause.key in {'counterattack', 'mate_allowed', 'mate_threat',
                              'material_loss', 'clean_capture', 'exchange_loss',
                              'material_sacrifice', 'exchange_sacrifice',
                              'double_attack', 'pawn_sacrifice_plan',
                              'capture_mate_trap', 'queen_trade_castling', 'line_refutation'} and
                cause.motif in CONCEPTS):
            # A demonstrated fork or discovered check is more instructive
            # than a generic material-loss label for that same sequence.
            specific = chosen in {'fork', 'skewer', 'discovered_attack', 'pin'}
            if not (cause.key == 'material_loss' and specific and cause.impact < 105):
                add(cause.motif, 0.96, cause.assessment)
                chosen = cause.motif
    # Broad labels must be supported by near-root, differential evidence,
    # not incidental threats or an undefended square on the board.
    # Root-side pieces can be hanging BEFORE the move or become hanging
    # because the played move puts them directly on an attacked square. In
    # both cases, require a legal near-term capture differential across PVs.
    verified_defense = bool(decision and decision.get('bad') and (
        (decision['truly_saved'] and any(
            c['ply'] <= 2 and not c['by_solver']
            and c['root_square'] in {x['square'] for x in decision['truly_saved']}
            for c in decision['bad']['captures'])) or
        (any(c['ply'] == 1 and not c['by_solver']
             and c['root_square'] == chess.square_name(played_move.from_square)
             for c in decision['bad']['captures'])
         and played_after is not None
         and played_after.is_attacked_by(opponent, played_move.to_square)
         and not played_after.is_attacked_by(side, played_move.to_square)
         and len(decision['good']['steps']) > 1
         and chess.square_name(played_move.from_square) not in {
             c['root_square'] for c in decision['good']['captures']
             if not c['by_solver']})
    ))
    verified_attack = bool(decision and decision.get('bad') and any(
        target['loose'] and target['square'] not in {
            c['root_square'] for c in decision['bad']['captures'] if c['by_solver']}
        and any(c['by_solver'] and c['root_square'] == target['square']
                and 1 <= c['ply'] <= 2 for c in decision['good']['captures'])
        for target in decision['new_targets']))
    if verified_defense and causal and causal[0].key == 'material_loss' and causal[0].horizon == 1:
        # Only a pre-existing loose piece can be 'protected'. A piece moved
        # into danger or newly exposed by the mistake needs a different lesson.
        captured = confirmed_differential_loss(board, decision)
        if captured and differential_loss_motif(board, played_move, captured) == 'loose_piece_awareness':
            add('loose_piece_awareness', 0.97, causal[0].assessment)
    # This check runs AFTER all relevance/semantic overrides. It prevents a
    # newly hung mover being mislabeled as a piece that was already loose.
    witnessed = confirmed_differential_loss(board, decision)
    if witnessed and played_move != best_move and not forced_primary:
        provenance = differential_loss_motif(board, played_move, witnessed)
        if provenance == 'loose_piece_awareness':
            add(provenance, 0.98, 'The piece was already loose before the game move; the better choice saves it.')
        elif provenance == 'dont_hang_pieces':
            add(provenance, 0.99, 'The game move places its own piece en prise, and the continuation shows the capture.')
            labels.pop('loose_piece_awareness', None)
        else:
            add(provenance, 0.96, 'The game move allows a material loss not present in the better continuation.')
            labels.pop('loose_piece_awareness', None)
        if chosen in {'loose_piece_awareness', 'hanging_piece', 'lost_material',
                      'dont_hang_pieces', 'calculation', 'threat_awareness', 'tactical_combination'}:
            chosen = provenance
    if not verified_defense and (not witnessed or differential_loss_motif(board, played_move, witnessed) != 'loose_piece_awareness'):
        labels.pop('loose_piece_awareness', None)
    if not verified_attack:
        labels.pop('hanging_piece', None)
    # A free root capture is *not* an attack that the answer creates. The
    # loose enemy piece was available before either candidate move.
    if root_evidence and root_evidence.get('kind') == 'free_capture':
        add('capture_loose_piece', 0.99, root_evidence['explanation'])
        if not forced_primary:
            chosen = 'capture_loose_piece'
    if chosen not in labels:
        chosen = next((key for key in ('mate_defense', 'exchange_sacrifice',
             'material_sacrifice', 'simplification', 'missed_capture',
             'tactical_combination', 'fork', 'counterattack') if key in labels), None)
    if chosen == 'calculation':
        # Process labels are fallback, never preferred over a relevant
        # recognized chess mechanism. A bare label with no response or root
        # evidence cannot displace one with a substantial relevance score.
        supported = [(k, score) for k, score in relevance_scores.items()
                     if k in labels and k not in {'calculation'}
                     and score >= 0.30]
        if supported:
            chosen = max(supported, key=lambda item: item[1])[0]
    # An exact endgame verdict takes precedence over heuristic motifs.
    from endgame_evidence import exact_move_contrast
    exact = exact_move_contrast(board, best_move, played_move) if played_move else None
    if exact:
        add('endgame_precision', 1.0,
            f'Syzygy confirms {best_san} preserves a {exact["best"]}, whereas the game move leads to a {exact["played"]}.')
        chosen = 'endgame_precision'
    if chosen in {'calculation', None}:
        forcing = (board.is_check() or board.is_capture(best_move)
                   or board.gives_check(best_move)
                   or (played_move is not None and played_move in board.legal_moves
                       and (board.is_capture(played_move) or board.gives_check(played_move))))
        specific = [(k, relevance_scores.get(k, 0.0)) for k in labels
                    if k != 'calculation']
        if specific and (not forcing or max(score for _, score in specific) >= 0.30):
            chosen = max(specific, key=lambda entry: (entry[1], labels[entry[0]].confidence))[0]
        elif forcing:
            chosen = 'calculation'
            add('calculation', 0.60, 'Examine the forcing moves available in this position.')
        else:
            moving = board.piece_at(best_move.from_square)
            if _is_endgame(board) and moving and moving.piece_type == chess.KING:
                chosen = 'king_activity'
                note = 'Compare the king’s activity and reachable squares in this endgame.'
            elif moving and moving.piece_type == chess.PAWN:
                chosen = 'pawn_structure'
                note = 'Compare how the pawn moves change the pawn structure and available squares.'
            elif moving and moving.piece_type == chess.KING:
                chosen = 'king_safety'
                note = 'Compare king safety and available escape squares.'
            else:
                chosen = 'piece_activity'
                note = 'Compare the pieces’ active squares and influence after each move.'
            add(chosen, 0.56, note)
        if chosen != 'calculation':
            labels.pop('calculation', None)
    if not labels:
        chosen = 'piece_activity'
        add(chosen, 0.52, 'Compare useful squares and activity rather than assuming a forcing tactic.')
    # A broad learning theme can describe the position yet obscure the
    # decisive mechanism. Promote only independently supported, near-root
    # findings; do not use catalogue priorities as proof of a tactic.
    supported = {}
    for finding in (causal or []):
        if (finding.motif in labels and finding.confidence >= 2
                and finding.horizon <= 3 and finding.impact >= 75):
            strength = min(1.0, finding.confidence / 3 * 0.6 + finding.impact / 130 * 0.4)
            prev = supported.get(finding.motif, (0, 10))
            if strength > prev[0]:
                supported[finding.motif] = (strength, finding.horizon)
    # An immediate confirmed tactic is stronger than incidental PV geometry.
    for key in (root_primary, immediate_primary):
        if key in labels and labels[key].confidence >= 0.90:
            supported[key] = (max(labels[key].confidence, supported.get(key, (0, 0))[0]), 0)
    chosen = choose_specific(chosen, supported,
                             protected={'mate_defense', 'back_rank_mate',
                                        'mating_net', 'endgame_precision'})
    # Final alignment: explanations and primary motifs must describe the
    # same verified *cause*, not merely nearby board features. This uses the
    # same ranked findings as causal_coaching; a later generic metadata pass
    # may no longer silently overwrite a demonstrated mechanism. Forced mate,
    # tablebase verdicts, and confirmed piece provenance remain protected.
    leading_cause = primary_causal_finding(causal or [])
    meaningful_evasion = (not check_evasion or (
        leading_cause is not None and leading_cause.horizon == 0
        and leading_cause.confidence >= 2
        and leading_cause.motif in {'king_activity', 'capture_loose_piece',
                                    'removal_of_defender', 'fork', 'pin',
                                    'material_sacrifice', 'exchange_sacrifice'}))
    if (leading_cause is not None and not forced_primary and meaningful_evasion
            and chosen != 'endgame_precision' and leading_cause.motif in CONCEPTS
            and finding_score(leading_cause) >= 72 and leading_cause.horizon <= 2):
        provenance_protected = bool(witnessed and chosen in {
            'loose_piece_awareness', 'dont_hang_pieces', 'lost_material'
        } and leading_cause.key not in {'material_loss', 'line_refutation'})
        capture_protected = bool(root_evidence and root_evidence.get('kind') == 'free_capture'
                                 and leading_cause.key not in {'clean_capture', 'line_refutation'})
        if not provenance_protected and not capture_protected:
            add(leading_cause.motif,
                min(0.99, 0.76 + 0.07 * leading_cause.confidence),
                leading_cause.assessment)
            chosen = leading_cause.motif
    ordered = sorted(labels.values(), key=lambda label: (
        label.key != chosen, -relevance_scores.get(label.key, 0.0),
        -label.confidence, -CONCEPTS[label.key]['priority']))
    ordered[0].is_primary = True
    return ordered
