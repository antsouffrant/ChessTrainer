from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import chess.pgn
import requests

from db import connect
from app_settings import DEFAULT_SETTINGS, analysis_signature, settings_from_snapshot
from coaching import COACHING_VERSION, generate_coaching_text
from learning import CLASSIFIER_VERSION, LearningLabel, classify_learning_concepts
from adaptive_coach import apply_adaptive_concepts_to_position
from pv_reasoning import encode_pv
from critical_moments import critical_decision_evidence
from explanatory_evidence import explanation_variations

# Compatibility aliases for older imports. Runtime analysis uses the persisted
# settings snapshot attached to each analysis job.
STOCKFISH_DIR = Path(DEFAULT_SETTINGS['stockfish_dir'])
MATE_SCORE_CP = int(DEFAULT_SETTINGS['mate_score_cp'])
MIN_CPL_CP = int(DEFAULT_SETTINGS['min_cpl_cp'])
WINNING_CP = int(DEFAULT_SETTINGS['winning_cp'])
EQUAL_CP = int(DEFAULT_SETTINGS['equal_cp'])
LOSS_CP = int(DEFAULT_SETTINGS['loss_cp'])
PLAYABLE_CP = int(DEFAULT_SETTINGS['playable_cp'])
SCREEN_PLAYABLE_CP = int(DEFAULT_SETTINGS['screen_playable_cp'])
SCREEN_MIN_CPL_CP = int(DEFAULT_SETTINGS['screen_min_cpl_cp'])
DISTINCT_PLY_GAP = int(DEFAULT_SETTINGS['distinct_ply_gap'])
MAX_POSITIONS_PER_GAME = int(DEFAULT_SETTINGS['max_positions_per_game'])
MAX_DEEP_CANDIDATES_PER_GAME = int(DEFAULT_SETTINGS['max_deep_candidates_per_game'])
MIN_SCREEN_SEARCH_SECONDS = float(DEFAULT_SETTINGS['min_screen_search_seconds'])
MAX_SCREEN_SEARCH_SECONDS = float(DEFAULT_SETTINGS['max_screen_search_seconds'])
DIFFICULTY_VERSION = 'heuristic-v3-choice-complexity'
ANALYSIS_VERSION = 'analysis-v1.7-context-probed-explanations'
DEFAULT_MAX_PASSES = int(DEFAULT_SETTINGS['max_passes'])
SCREEN_DEPTH_STEP = int(DEFAULT_SETTINGS['screen_depth_step'])
DEEP_DEPTH_STEP = int(DEFAULT_SETTINGS['deep_depth_step'])
ENGINE_RESTART_RETRIES = int(DEFAULT_SETTINGS['engine_restart_retries'])
from process_runtime import PROCESS_LOCK
_ANALYSIS_LOCK = threading.Lock()


@dataclass
class EvalResult:
    cp: int
    mate: Optional[int]
    best_move: Optional[chess.Move]
    depth: Optional[int]
    second_best_cp: Optional[int] = None
    pv_uci: tuple[str, ...] = ()
    alternatives: tuple[dict, ...] = ()


def find_stockfish(settings=None) -> Path:
    settings = settings or DEFAULT_SETTINGS
    stockfish_dir = Path(settings.get('stockfish_dir', DEFAULT_SETTINGS['stockfish_dir']))
    if not stockfish_dir.exists():
        raise FileNotFoundError(f'Expected Stockfish folder at {stockfish_dir}.')

    candidates = []
    for path in stockfish_dir.rglob('*'):
        if not path.is_file() or not path.name.lower().startswith('stockfish'):
            continue
        if sys.platform == 'win32':
            if path.suffix.lower() == '.exe':
                candidates.append(path)
        elif os.access(path, os.X_OK):
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError('No Stockfish executable found inside stockfish/.')

    candidates.sort(key=lambda p: (len(p.relative_to(stockfish_dir).parts), len(p.name)))
    return candidates[0].resolve()


def date_range_to_ms(name: str) -> int:
    days = {'week': 7, 'month': 30, '90days': 90, 'year': 365}.get(name, 30)
    start = datetime.now(timezone.utc) - timedelta(days=days)
    return int(start.timestamp() * 1000)


def pass_depths(base_screen_depth: int, base_deep_depth: int, pass_number: int, settings=None) -> tuple[int, int]:
    """Return monotonically increasing Stockfish depth caps for a refinement pass.

    Time budgets remain fixed so each pass stays bounded; deeper passes can use
    more of that budget because the earlier depth cap no longer stops the search.
    """
    settings = settings or DEFAULT_SETTINGS
    offset = max(0, int(pass_number) - 1)
    return (
        max(1, int(base_screen_depth)) + int(settings['screen_depth_step']) * offset,
        max(1, int(base_deep_depth)) + int(settings['deep_depth_step']) * offset,
    )


def player_color(game: chess.pgn.Game, username: str) -> Optional[chess.Color]:
    white = game.headers.get('White', '')
    black = game.headers.get('Black', '')
    if white.casefold() == username.casefold():
        return chess.WHITE
    if black.casefold() == username.casefold():
        return chess.BLACK
    return None


def evaluate(engine, board, pov, seconds, root_move: Optional[chess.Move] = None, depth: Optional[int] = None, settings=None) -> EvalResult:
    kwargs = {}
    if root_move is not None:
        kwargs['root_moves'] = [root_move]

    seconds = max(0.005, float(seconds))
    limit = chess.engine.Limit(time=seconds, depth=depth) if depth else chess.engine.Limit(time=seconds)
    info = engine.analyse(board, limit, **kwargs)
    score = info['score'].pov(pov)
    settings = settings or DEFAULT_SETTINGS
    cp = score.score(mate_score=int(settings['mate_score_cp']))
    pv = info.get('pv', [])
    return EvalResult(
        cp=int(cp if cp is not None else 0),
        mate=score.mate(),
        best_move=pv[0] if pv else None,
        depth=info.get('depth'),
        pv_uci=tuple(m.uci() for m in pv[:12]),
    )


def evaluate_top_moves(engine, board, pov, seconds, multipv=2, depth: Optional[int] = None, settings=None) -> EvalResult:
    """Evaluate the position and retain the runner-up score for difficulty estimation."""
    seconds = max(0.005, float(seconds))
    limit = chess.engine.Limit(time=seconds, depth=depth) if depth else chess.engine.Limit(time=seconds)
    infos = engine.analyse(board, limit, multipv=max(2, multipv))
    if not isinstance(infos, list):
        infos = [infos]
    first = infos[0]
    score = first['score'].pov(pov)
    settings = settings or DEFAULT_SETTINGS
    cp = score.score(mate_score=int(settings['mate_score_cp']))
    pv = first.get('pv', [])

    second_cp = None
    alternatives = []
    for info in infos[1:3]:
        other_pv = info.get('pv', [])
        if not other_pv:
            continue
        other_score = info['score'].pov(pov)
        other_cp = other_score.score(mate_score=int(settings['mate_score_cp']))
        alternatives.append({'move_uci': other_pv[0].uci(),
                             'pv_uci': [m.uci() for m in other_pv[:12]],
                             'eval_cp': int(other_cp) if other_cp is not None else None,
                             'mate': other_score.mate(),
                             'depth': info.get('depth')})
    if len(infos) > 1:
        second_score = infos[1]['score'].pov(pov)
        raw_second = second_score.score(mate_score=int(settings['mate_score_cp']))
        if raw_second is not None:
            second_cp = int(raw_second)

    return EvalResult(
        cp=int(cp if cp is not None else 0),
        mate=score.mate(),
        best_move=pv[0] if pv else None,
        depth=first.get('depth'),
        second_best_cp=second_cp,
        alternatives=tuple(alternatives),
        pv_uci=tuple(m.uci() for m in pv[:12]),
    )


def estimate_puzzle_difficulty(board, best_move, before, category=None):
    """Estimate ordering difficulty, NOT a validated human puzzle Elo.

    Uses decision load (plausible forcing candidates), directness of the tactic,
    king-in-check constraint, mate distance and engine move alternatives. This
    model is intentionally versioned so older cached positions can be rescored
    without rerunning Stockfish; actual rating calibration requires solve data.
    """
    if best_move not in board.legal_moves:
        return 50.0, 1500
    legal = list(board.legal_moves)
    legal_count = len(legal)
    forcing = sum(1 for move in legal if board.is_capture(move) or board.gives_check(move) or move.promotion)
    is_check = board.gives_check(best_move)
    is_capture = board.is_capture(best_move)
    is_promotion = bool(best_move.promotion)
    is_quiet = not (is_check or is_capture or is_promotion)
    after = board.copy(stack=False)
    after.push(best_move)
    immediate_mate = after.is_checkmate()

    score = 28.0
    score += min(17.0, max(0, legal_count - 8) * .55)
    # Several plausible forcing choices mean that the solver must distinguish
    # them. One forced legal response should almost never be a difficult puzzle.
    score += min(13.0, max(0, forcing - 1) * 2.6)
    if legal_count <= 2:
        score -= 23.0
    elif legal_count <= 5:
        score -= 12.0
    if board.is_check():
        score -= 7.0
    if immediate_mate:
        score -= 17.0
    elif before.mate is not None and before.mate > 0:
        score += min(20.0, max(0, abs(before.mate) - 1) * 4.0)
        if not is_check:
            score += 7.0  # Quiet first move in a forced mating sequence.
    elif is_check:
        score -= 4.0
    if is_promotion:
        score -= 9.0
    elif is_capture:
        score -= 4.0
    elif is_quiet:
        score += 11.0
    if before.second_best_cp is not None:
        gap = max(0, before.cp - before.second_best_cp)
        if gap < 45:
            score += 8.0  # Alternatives are hard to distinguish.
        elif gap > 450:
            score -= 4.0
    if category in {'allowed_checkmate', 'missed_checkmate'} and not immediate_mate:
        score += 5.0
    score = max(0.0, min(100.0, score))
    rating = int(round((600.0 + score * 19.5) / 25.0) * 25)
    return round(score, 1), max(600, min(2550, rating))


def centipawn_loss(before, after):
    return max(0, before.cp - after.cp)


def classify(before, after, settings=None):
    """Classify the practical consequence of the user's move.

    Scores are always from the user's point of view.  The categories are
    intentionally outcome-oriented so that conversion mistakes and defensive
    blunders can coexist in the same training curriculum.
    """
    settings = settings or DEFAULT_SETTINGS
    min_cpl_cp = int(settings['min_cpl_cp'])
    winning_cp = int(settings['winning_cp'])
    equal_cp = int(settings['equal_cp'])
    loss_cp = int(settings['loss_cp'])
    playable_cp = int(settings['playable_cp'])
    major_blunder_cpl_cp = int(settings['major_blunder_cpl_cp'])

    # The most severe defensive error: a move turns a non-mated position into
    # a forced mate for the opponent.
    if after.mate is not None and after.mate < 0 and not (before.mate is not None and before.mate < 0):
        return 'allowed_checkmate'

    # The mirror image: a forced mate for the user was available but lost.
    if before.mate is not None and before.mate > 0 and not (after.mate is not None and after.mate > 0):
        return 'missed_checkmate'

    cpl = centipawn_loss(before, after)
    if cpl < min_cpl_cp:
        return None

    # Winning -> losing is more serious than merely failing to convert.
    if before.cp >= winning_cp and after.cp <= loss_cp:
        return 'threw_away_win'

    # Roughly drawable/playable -> clearly losing.
    if abs(before.cp) <= equal_cp and after.cp <= loss_cp:
        return 'blundered_draw'

    # Slightly better/slightly worse, but still playable -> clearly losing.
    if before.cp > loss_cp and after.cp <= loss_cp:
        return 'blundered_into_loss'

    # Winning -> no longer winning, but not outright losing.
    if before.cp >= winning_cp and after.cp < winning_cp:
        return 'squandered_advantage'

    # A large error that leaves a winning position winning.
    if before.cp >= winning_cp and after.cp >= winning_cp:
        return 'blundered_win'

    # Catch substantial one-move errors from otherwise playable positions even
    # when they do not cross one of the simple outcome thresholds above.
    if before.cp >= playable_cp and cpl >= major_blunder_cpl_cp:
        return 'major_blunder'

    return None


def count_user_turns(game, user_color):
    board = game.board()
    count = 0
    for move in game.mainline_moves():
        if board.turn == user_color:
            count += 1
        board.push(move)
    return max(1, count)


def screen_game(engine, game, username, screen_seconds, screen_depth, settings=None):
    """Screen one game for the learning modes attached to this job.

    Mistake/opposition discovery looks for consequential errors. Reinforcement
    discovery only promotes engine-best moves that are already unusually unique
    at shallow depth, preventing routine winning moves from flooding the queue.
    """
    settings = settings or DEFAULT_SETTINGS
    target_color = player_color(game, username)
    if target_color is None:
        return []

    modes = set(settings.get('_job_learning_modes') or ['mistakes'])
    source_type = settings.get('_source_type', 'self')
    if source_type == 'opposition':
        modes = {'opposition'}

    positive_enabled = source_type == 'self' and bool(modes & {'excellent', 'brilliant'})
    mistake_enabled = source_type == 'opposition' or bool(modes & {'mistakes', 'blunders'})

    board = game.board()
    nodes = list(game.mainline())
    moves = [node.move for node in nodes]
    candidates = []
    previous_fen = None
    opponent_move_uci = None
    opponent_move_san = None
    user_turns_remaining = count_user_turns(game, target_color)
    deadline = time.monotonic() + max(0.5, float(screen_seconds))

    for ply, node in enumerate(nodes, start=1):
        move = node.move
        move_nags = set(getattr(node, 'nags', set()) or set())
        # Standard PGN NAGs: $1 = ! (good), $3 = !! (brilliant).
        annotation_quality = 'brilliant' if 3 in move_nags else ('excellent' if 1 in move_nags else None)
        if board.turn == target_color:
            remaining_budget = max(0.01, deadline - time.monotonic())
            per_search = remaining_budget / max(1.0, user_turns_remaining * 1.35)
            per_search = min(float(settings['max_screen_search_seconds']), max(float(settings['min_screen_search_seconds']), per_search))

            if positive_enabled:
                before = evaluate_top_moves(engine, board, target_color, per_search, multipv=2, depth=screen_depth, settings=settings)
            else:
                before = evaluate(engine, board, target_color, per_search, depth=screen_depth, settings=settings)

            base = {
                'ply': ply,
                'fen': board.fen(),
                'played_move_uci': move.uci(),
                'annotation_quality': annotation_quality,
                'player_rating': game.headers.get('WhiteElo' if target_color == chess.WHITE else 'BlackElo', ''),
                'previous_fen': previous_fen,
                'opponent_move_uci': opponent_move_uci,
                'opponent_move_san': opponent_move_san,
                'user_color': target_color,
            }

            if mistake_enabled and before.best_move is not None and move != before.best_move:
                worth_checking = (
                    (before.mate is not None and before.mate > 0)
                    or before.cp >= int(settings['screen_playable_cp'])
                )
                if worth_checking:
                    remaining_budget = max(0.005, deadline - time.monotonic())
                    follow_up = min(per_search * 0.7, remaining_budget / max(1.0, user_turns_remaining))
                    follow_up = max(0.01, follow_up)
                    after = evaluate(engine, board, target_color, follow_up, root_move=move, depth=screen_depth, settings=settings)
                    screen_category = classify(before, after, settings)
                    if screen_category is not None or centipawn_loss(before, after) >= int(settings['screen_min_cpl_cp']):
                        if screen_category is None:
                            screen_category = 'major_blunder'
                        candidate = {
                            **base,
                            'candidate_kind': 'opposition' if source_type == 'opposition' else 'mistake',
                            'screen_category': screen_category,
                            'screen_cpl': centipawn_loss(before, after),
                        }
                        if source_type == 'opposition' and ply < len(moves):
                            candidate['actual_reply_uci'] = moves[ply].uci()
                        candidates.append(candidate)

            if positive_enabled and before.best_move is not None and move == before.best_move:
                second = before.second_best_cp
                gap = max(0, before.cp - second) if second is not None else 0
                selected_thresholds = []
                if 'excellent' in modes:
                    selected_thresholds.append(max(20, int(settings['excellent_uniqueness_cp']) // 2))
                if 'brilliant' in modes:
                    selected_thresholds.append(max(35, int(settings['brilliant_uniqueness_cp']) // 2))
                shallow_gap = min(selected_thresholds) if selected_thresholds else 999999
                easy_win = before.cp >= int(settings['positive_easy_win_cp'])
                exceptional = gap >= max(shallow_gap, int(settings['brilliant_uniqueness_cp']) // 2)
                annotated_match = (annotation_quality == 'brilliant' and 'brilliant' in modes) or (annotation_quality == 'excellent' and bool(modes & {'excellent', 'brilliant'}))
                if annotated_match or (gap >= shallow_gap and (not easy_win or exceptional)):
                    candidates.append({
                        **base,
                        'candidate_kind': 'reinforcement',
                        'screen_category': 'reinforcement_candidate',
                        'screen_cpl': 0,
                        'screen_uniqueness_cp': gap,
                    })

            user_turns_remaining = max(0, user_turns_remaining - 1)
        else:
            previous_fen = board.fen()
            opponent_move_uci = move.uci()
            opponent_move_san = board.san(move)

        board.push(move)

    return candidates

def choose_deep_candidates(candidates, settings=None):
    """Select expensive confirmations with separate mistake/reinforcement quotas."""
    if not candidates:
        return []
    settings = settings or DEFAULT_SETTINGS

    priority = {
        'allowed_checkmate': 7,
        'threw_away_win': 6,
        'missed_checkmate': 5,
        'blundered_draw': 4,
        'blundered_into_loss': 4,
        'squandered_advantage': 3,
        'major_blunder': 2,
        'blundered_win': 1,
    }
    mistakes = [c for c in candidates if c.get('candidate_kind') != 'reinforcement']
    reinforcement = [c for c in candidates if c.get('candidate_kind') == 'reinforcement']

    mistakes.sort(key=lambda c: (-priority.get(c.get('screen_category'), 0), -c.get('screen_cpl', 0)))
    kept_mistakes = []
    for candidate in mistakes:
        redundant = any(
            candidate.get('screen_category') == existing.get('screen_category')
            and abs(candidate['ply'] - existing['ply']) < int(settings['distinct_ply_gap'])
            for existing in kept_mistakes
        )
        if not redundant:
            kept_mistakes.append(candidate)
        if len(kept_mistakes) >= int(settings['max_deep_candidates_per_game']):
            break

    reinforcement.sort(key=lambda c: (-int(c.get('screen_uniqueness_cp') or 0), c['ply']))
    kept_reinforcement = []
    for candidate in reinforcement:
        if any(abs(candidate['ply'] - existing['ply']) < int(settings['distinct_ply_gap']) for existing in kept_reinforcement):
            continue
        kept_reinforcement.append(candidate)
        if len(kept_reinforcement) >= int(settings['max_reinforcement_candidates_per_game']):
            break

    return sorted(kept_mistakes + kept_reinforcement, key=lambda c: c['ply'])

def _piece_value_for_sacrifice(piece):
    if piece is None:
        return 0
    return {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}.get(piece.piece_type, 0)


def _looks_sacrificial(board: chess.Board, move: chess.Move) -> bool:
    moving = board.piece_at(move.from_square)
    captured = board.piece_at(move.to_square)
    if moving is None:
        return False
    invested = _piece_value_for_sacrifice(moving) - _piece_value_for_sacrifice(captured)
    after = board.copy(stack=False)
    after.push(move)
    exposed = after.is_attacked_by(after.turn, move.to_square)
    return exposed and invested >= 2


def confirm_candidate(engine, candidate, deep_seconds, deep_depth, settings=None):
    """Deep-confirm a mistake, reinforcement move, or opposition opportunity."""
    settings = settings or DEFAULT_SETTINGS
    board = chess.Board(candidate['fen'])
    move = chess.Move.from_uci(candidate['played_move_uci'])
    target_color = candidate['user_color']
    kind = candidate.get('candidate_kind', 'mistake')
    modes = set(settings.get('_job_learning_modes') or ['mistakes'])
    total = max(1.0, float(deep_seconds))

    if kind == 'reinforcement':
        before = evaluate_top_moves(engine, board, target_color, total * 0.72, multipv=3, depth=deep_depth, settings=settings)
        if before.best_move is None or move != before.best_move or before.second_best_cp is None:
            return None
        gap = max(0, before.cp - before.second_best_cp)
        sacrifice = _looks_sacrificial(board, move)
        easy_win = before.cp >= int(settings['positive_easy_win_cp'])
        brilliant_threshold = int(settings['brilliant_uniqueness_cp'])
        excellent_threshold = int(settings['excellent_uniqueness_cp'])

        annotation_quality = candidate.get('annotation_quality')
        forced_mate = before.mate is not None and before.mate > 0
        learning_mode = None
        category = None

        # If an annotated PGN explicitly supplies ! or !!, preserve that human-facing
        # label after Stockfish verifies the move is still the best move here. This is
        # the strongest signal and keeps annotated/imported games backwards compatible.
        if annotation_quality == 'brilliant' and 'brilliant' in modes:
            learning_mode = 'brilliant'
            category = 'brilliant_move'
        elif annotation_quality == 'excellent' and 'excellent' in modes:
            learning_mode = 'excellent'
            category = 'excellent_move'

        # Bulk Lichess exports do not reliably carry literate glyphs, so use a
        # conservative NAG-style fallback. A forced mate is reinforcement-worthy
        # but is not called brilliant merely because it is forced. Unannotated
        # brilliance requires a real sacrifice plus a substantial uniqueness gap.
        if learning_mode is None and 'brilliant' in modes:
            brilliant_enough = sacrifice and gap >= brilliant_threshold
            if brilliant_enough and (not easy_win or gap >= brilliant_threshold * 2):
                learning_mode = 'brilliant'
                category = 'brilliant_move'
        if learning_mode is None and 'excellent' in modes:
            excellent_enough = gap >= excellent_threshold or forced_mate
            if excellent_enough and (not easy_win or forced_mate or sacrifice or gap >= brilliant_threshold):
                learning_mode = 'excellent'
                category = 'excellent_move'
        if learning_mode is None:
            return None

        after = evaluate(engine, board, target_color, total * 0.28, root_move=move, depth=deep_depth, settings=settings)
        difficulty_score, estimated_rating = estimate_puzzle_difficulty(board, move, before, category)
        try:
            player_rating = int(candidate.get('player_rating') or 0)
        except (ValueError, TypeError):
            player_rating = 0
        rating_surprise = estimated_rating - player_rating if player_rating > 0 else None
        # Engine strength is necessary, but the player's demonstrated level matters too.
        # Explicit verified human !/!! annotations keep priority for compatibility.
        if not annotation_quality and rating_surprise is not None:
            if learning_mode == 'brilliant' and rating_surprise < 450:
                learning_mode = 'excellent' if 'excellent' in modes and rating_surprise >= 200 else None
            elif learning_mode == 'excellent' and rating_surprise < 200:
                learning_mode = None
        if learning_mode is None:
            return None
        category = 'brilliant_move' if learning_mode == 'brilliant' else 'excellent_move'
        return {
            **candidate,
            'board': board,
            'played_move': move,
            'before': before,
            'after': after,
            'category': category,
            'learning_mode': learning_mode,
            'uniqueness_cp': gap,
            'is_sacrifice': sacrifice,
            'difficulty_score': difficulty_score,
            'estimated_rating': estimated_rating,
            'rating_surprise': rating_surprise,
            'player_rating': player_rating,
        }

    if kind == 'opposition':
        # First verify that the researched player's move is actually a meaningful
        # mistake; then flip the puzzle to the board after the mistake so the
        # learner practices the punishment from the opponent's perspective.
        before = evaluate_top_moves(engine, board, target_color, total * 0.40, multipv=3, depth=deep_depth, settings=settings)
        if before.best_move is None or move == before.best_move:
            return None
        bad_after = evaluate(engine, board, target_color, total * 0.20, root_move=move, depth=deep_depth, settings=settings)
        target_category = classify(before, bad_after, settings)
        if target_category is None:
            return None

        target_move_san = board.san(move)
        exploit_board = board.copy(stack=False)
        exploit_board.push(move)
        exploiter = exploit_board.turn
        exploit = evaluate_top_moves(engine, exploit_board, exploiter, total * 0.25, multipv=3, depth=deep_depth, settings=settings)
        if exploit.best_move is None:
            return None

        actual_reply = None
        actual_reply_uci = candidate.get('actual_reply_uci')
        if actual_reply_uci:
            try:
                possible = chess.Move.from_uci(actual_reply_uci)
                if possible in exploit_board.legal_moves:
                    actual_reply = possible
            except ValueError:
                pass
        played_reply = actual_reply or exploit.best_move
        if played_reply == exploit.best_move:
            response_eval = EvalResult(
                cp=exploit.cp, mate=exploit.mate, best_move=exploit.best_move,
                depth=exploit.depth, second_best_cp=exploit.second_best_cp, pv_uci=exploit.pv_uci,
            )
        else:
            response_eval = evaluate(engine, exploit_board, exploiter, max(0.05, total * 0.15), root_move=played_reply, depth=deep_depth, settings=settings)

        difficulty_score, estimated_rating = estimate_puzzle_difficulty(
            exploit_board, exploit.best_move, exploit, 'opposition_opportunity'
        )
        return {
            **candidate,
            'ply': int(candidate.get('ply') or 0) + 1,
            'board': exploit_board,
            'played_move': played_reply,
            'played_move_uci': played_reply.uci(),
            'before': exploit,
            'after': response_eval,
            'category': 'opposition_opportunity',
            'learning_mode': 'opposition',
            'user_color': exploiter,
            'previous_fen': candidate['fen'],
            'opponent_move_uci': move.uci(),
            'opponent_move_san': target_move_san,
            'target_mistake_category': target_category,
            'difficulty_score': difficulty_score,
            'estimated_rating': estimated_rating,
        }

    before = evaluate_top_moves(engine, board, target_color, total * 0.58, multipv=3, depth=deep_depth, settings=settings)
    if before.best_move is None or move == before.best_move:
        return None
    after = evaluate(engine, board, target_color, total * 0.42, root_move=move, depth=deep_depth, settings=settings)
    category = classify(before, after, settings)
    if category is None:
        return None
    difficulty_score, estimated_rating = estimate_puzzle_difficulty(board, before.best_move, before, category)
    if not (modes & {'mistakes', 'blunders'}):
        return None
    actual_mode = 'mistakes' if category in {'allowed_checkmate', 'threw_away_win', 'blundered_draw', 'blundered_into_loss', 'major_blunder', 'blundered_win'} else 'blunders'
    # Legacy lists with only 'mistakes' retain their original combined coverage.
    if actual_mode not in modes and not (actual_mode == 'blunders' and modes == {'mistakes'}):
        return None
    return {
        **candidate,
        'board': board,
        'played_move': move,
        'before': before,
        'after': after,
        'category': category,
        'learning_mode': ('mistakes' if category in {'allowed_checkmate', 'threw_away_win', 'blundered_draw', 'blundered_into_loss', 'major_blunder', 'blundered_win'} else 'blunders'),
        'difficulty_score': difficulty_score,
        'estimated_rating': estimated_rating,
    }

def choose_distinct_positions(confirmed, settings=None):
    if not confirmed:
        return []
    settings = settings or DEFAULT_SETTINGS
    priority = {
        'allowed_checkmate': 7, 'threw_away_win': 6, 'missed_checkmate': 5,
        'blundered_draw': 4, 'blundered_into_loss': 4, 'squandered_advantage': 3,
        'major_blunder': 2, 'blundered_win': 1,
    }

    mistake_like = [c for c in confirmed if c.get('learning_mode') in {'mistakes', 'blunders', 'opposition'}]
    reinforcement = [c for c in confirmed if c.get('learning_mode') in {'excellent', 'brilliant'}]

    mistake_like.sort(key=lambda c: (-priority.get(c['category'], 0), -centipawn_loss(c['before'], c['after'])))
    kept_base = []
    base_cap = int(settings['max_positions_per_game'])
    if mistake_like and all(c.get('learning_mode') == 'opposition' for c in mistake_like):
        base_cap = min(base_cap, int(settings.get('max_opposition_positions_per_game', 2)))
    for candidate in mistake_like:
        redundant = any(
            candidate['category'] == existing['category']
            and abs(candidate['ply'] - existing['ply']) < int(settings['distinct_ply_gap'])
            for existing in kept_base
        )
        if not redundant:
            kept_base.append(candidate)
        if len(kept_base) >= base_cap:
            break

    reinforcement.sort(key=lambda c: (
        0 if c.get('learning_mode') == 'brilliant' else 1,
        -int(c.get('uniqueness_cp') or 0), c['ply']
    ))
    kept_positive = []
    for candidate in reinforcement:
        if any(abs(candidate['ply'] - existing['ply']) < int(settings['distinct_ply_gap']) for existing in kept_positive):
            continue
        kept_positive.append(candidate)
        if len(kept_positive) >= int(settings['max_reinforcement_positions_per_game']):
            break

    return sorted(kept_base + kept_positive, key=lambda c: c['ply'])

def stable_game_id(game, game_pgn=None):
    # Prefer provider IDs; fall back to a deterministic hash for imported PGNs.
    site = (game.headers.get('Site') or '').strip()
    if site:
        token = site.rstrip('/').split('/')[-1].split('#')[0].split('?')[0]
        if token and token not in {'?', '-'}:
            return token

    for key in ('GameId', 'GameID', 'ID'):
        value = (game.headers.get(key) or '').strip()
        if value:
            return value

    if game_pgn is None:
        game_pgn = export_game_pgn(game)
    digest = hashlib.sha1(game_pgn.encode('utf-8', errors='replace')).hexdigest()[:20]
    return f'imported-{digest}'


def copy_cached_positions(conn, account_id, game_id, source_job_id, target_job_id, target_modes=None):
    """Copy a previously analyzed game's current training set into a new job.

    The unique key makes this idempotent across refinement passes. Learned state
    and solve history are preserved, while lesson labels are refreshed using the
    current classifier.
    """
    if not source_job_id or int(source_job_id) == int(target_job_id):
        return 0

    source_rows = conn.execute("""
        SELECT tp.*
        FROM training_positions tp
        JOIN analysis_jobs j ON j.id = tp.job_id
        WHERE tp.job_id = ? AND j.account_id = ? AND tp.game_id = ?
        ORDER BY tp.id
    """, (source_job_id, account_id, game_id)).fetchall()

    # Preserve candidate reporting only for modes carried into the target list.
    allowed_modes = set(target_modes or ['mistakes'])
    mode_placeholders = ','.join('?' for _ in allowed_modes)
    if allowed_modes:
        conn.execute(f'''
            INSERT INTO analysis_candidates(job_id, game_id, ply, first_pass, last_pass, learning_mode)
            SELECT ?, game_id, ply, first_pass, last_pass, learning_mode
            FROM analysis_candidates
            WHERE job_id = ? AND game_id = ? AND learning_mode IN ({mode_placeholders})
            ON CONFLICT(job_id, game_id, ply) DO UPDATE SET
                first_pass = MIN(first_pass, excluded.first_pass),
                last_pass = MAX(last_pass, excluded.last_pass),
                learning_mode = excluded.learning_mode
        ''', (target_job_id, source_job_id, game_id, *sorted(allowed_modes)))

    copied = 0
    for row in source_rows:
        row_mode = row['learning_mode'] if 'learning_mode' in row.keys() and row['learning_mode'] else 'mistakes'
        if row_mode not in allowed_modes:
            continue
        cur = conn.execute("""
            INSERT OR IGNORE INTO training_positions (
                job_id, game_id, site, game_date, opponent, category, learning_mode, fen,
                previous_fen, opponent_move_uci, opponent_move_san,
                user_color, move_number, mistake_ply, game_pgn,
                played_move_uci, played_move_san, best_move_uci, best_move_san,
                eval_before_cp, eval_after_cp, mate_before, mate_after,
                centipawn_loss, difficulty_score, estimated_rating, difficulty_version,
                best_pv_uci, played_pv_uci, alternative_pvs_json, critical_events_json, explanatory_lines_json, proactive_coach_json, analysis_pass, analysis_screen_depth, analysis_deep_depth,
                learned, attempts, correct_attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            target_job_id, row['game_id'], row['site'], row['game_date'], row['opponent'],
            row['category'], row_mode, row['fen'], row['previous_fen'], row['opponent_move_uci'],
            row['opponent_move_san'], row['user_color'], row['move_number'], row['mistake_ply'],
            row['game_pgn'], row['played_move_uci'], row['played_move_san'],
            row['best_move_uci'], row['best_move_san'], row['eval_before_cp'],
            row['eval_after_cp'], row['mate_before'], row['mate_after'], row['centipawn_loss'],
            row['difficulty_score'], row['estimated_rating'], row['difficulty_version'],
            row['best_pv_uci'], row['played_pv_uci'], row['alternative_pvs_json'], row['critical_events_json'], row['explanatory_lines_json'], row['proactive_coach_json'], row['analysis_pass'], row['analysis_screen_depth'], row['analysis_deep_depth'],
            row['learned'], row['attempts'], row['correct_attempts'],
        ))
        if cur.rowcount <= 0:
            continue

        new_position_id = cur.lastrowid
        _refresh_position_labels(conn, new_position_id, row)
        copied += 1

    return copied


def _refresh_position_labels(conn, position_id, row_or_values, *, regenerate_copy=True):
    """Replace labels and coaching text for one position using current rules."""
    try:
        fen = row_or_values['fen']
        played_uci = row_or_values['played_move_uci']
        best_uci = row_or_values['best_move_uci']
        category = row_or_values['category']
        cpl = row_or_values['centipawn_loss'] or 0
        mate_before = row_or_values['mate_before']
        board = chess.Board(fen)
        played = chess.Move.from_uci(played_uci)
        best = chess.Move.from_uci(best_uci)
        labels = classify_learning_concepts(
            board=board,
            played_move=played,
            best_move=best,
            category=category,
            centipawn_loss=cpl,
            mate_before=mate_before,
            previous_fen=row_or_values['previous_fen'],
            opponent_move_uci=row_or_values['opponent_move_uci'],
            best_pv_uci=row_or_values['best_pv_uci'],
            played_pv_uci=row_or_values['played_pv_uci'],
        )
    except (ValueError, TypeError, KeyError):
        return

    # When the saved played-line reply *actually wins a piece* shortly after
    # the wrong decision, that loss is a better primary learning lesson than
    # incidental later geometry (e.g. Qxd4 also happens to fork two targets).
    try:
        from learning import LearningLabel
        from critical_moments import decode_critical_evidence
        evidence = decode_critical_evidence(row_or_values['critical_events_json'])
        if (evidence and evidence.get('kind')
                and evidence.get('critical_ply') is not None
                and evidence['critical_ply'] <= 3
                and (evidence.get('root_loss_cp') or 0) >= 90
                and category not in ('missed_checkmate', 'allowed_checkmate')
                and not board.is_capture(best)):
            # Only an observed, decision-distinguishing realization may own
            # the primary motif. Incidental geometric labels stay secondary.
            new_key = evidence.get('motif')
            from learning import CONCEPTS
            if new_key in CONCEPTS:
                from motif_hierarchy import BROAD_FALLBACKS, ancestors
                current_primary = next((x.key for x in labels if x.is_primary), None)
                # Do not undo the hierarchy-selected, concrete primary motif
                # just because a generic material loss is annotated later.
                can_override = (current_primary is None or
                    current_primary in BROAD_FALLBACKS or
                    current_primary in ancestors(new_key))
                if not can_override:
                    new_key = None
            if new_key in CONCEPTS:
                current = next((label for label in labels if label.key == new_key), None)
                if current is None:
                    from coaching_language import game_continuation
                    wording = (game_continuation(evidence.get('played_move'),
                               evidence.get('critical_move'), 'win material',
                               ply=evidence.get('critical_ply') or 2)
                               if evidence['kind'] == 'material_loss' else evidence.get('text', ''))
                    current = LearningLabel(new_key, 0.95, wording)
                    labels.append(current)
                for label in labels:
                    label.is_primary = label.key == new_key
    except (ValueError, TypeError, KeyError, AttributeError):
        pass

    # The same evidence-selection policy is applied by the offline benchmark
    # and the live proactive coaching pass.
    try:
        from proactive_coaching import prefer_evidenced_primary
        probe_json = (row_or_values['proactive_coach_json']
                      if 'proactive_coach_json' in row_or_values.keys() else None)
        labels = prefer_evidenced_primary(board, labels, probe_json)
    except (TypeError, ValueError, KeyError, AttributeError):
        pass

    from coaching_taxonomy import normalize_learning_labels
    king_evasion = (board.is_check() and best in board.legal_moves
                    and board.piece_at(best.from_square) is not None
                    and board.piece_at(best.from_square).piece_type == chess.KING
                    and not board.is_capture(best))
    labels = normalize_learning_labels(labels, row_or_values,
                                       is_in_check=board.is_check(),
                                       best_is_king_evasion=king_evasion)

    conn.execute('DELETE FROM position_concepts WHERE position_id = ?', (position_id,))
    for label in labels:
        conn.execute("""
            INSERT OR REPLACE INTO position_concepts (
                position_id, concept_key, confidence, is_primary, evidence, classifier_version
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            position_id, label.key, label.confidence,
            1 if label.is_primary else 0, label.evidence, CLASSIFIER_VERSION,
        ))

    teaching_path = None
    # Store the teaching hierarchy separately from the flat detector labels.
    # The primary lesson key stays stable for Coach votes, progress and tiles.
    try:
        from coaching_taxonomy import save_taxonomy
        from decision_context import decision_facts
        from loose_piece_provenance import confirmed_differential_loss
        # The context can be defensive even when the *move itself* attacks:
        # a fork may be the correct counterattack to avert a material loss.
        differential = decision_facts(
            board, best, played,
            row_or_values['best_pv_uci'], row_or_values['played_pv_uci'],
            row_or_values['alternative_pvs_json'],
            row_or_values['eval_before_cp'], row_or_values['eval_after_cp'])
        verified_save = confirmed_differential_loss(board, differential) is not None
        teaching_path = save_taxonomy(conn, position_id, row_or_values,
                      next((x.key for x in labels if x.is_primary), labels[0].key),
                      confidence=next((x.confidence for x in labels if x.is_primary), .65),
                      is_in_check=board.is_check(),
                      root_best_is_check=board.gives_check(best) if best in board.legal_moves else False,
                      best_move_saves_material=verified_save,
                      strategic_sacrifice=(
                          verified_save and not board.gives_check(best)
                          and next((x.key for x in labels if x.is_primary), '') == 'material_sacrifice'))
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        pass

    # Personal concepts learned through coach conversations are declarative
    # detectors. Apply them every time a position is inserted/refreshed so the
    # next analysis pass can populate new lesson playlists automatically.
    try:
        apply_adaptive_concepts_to_position(conn, position_id)
    except Exception:
        pass

    if not regenerate_copy:
        return

    try:
        prompt, explanation = generate_coaching_text(
            fen=fen,
            previous_fen=row_or_values['previous_fen'],
            opponent_move_uci=row_or_values['opponent_move_uci'],
            opponent_move_san=row_or_values['opponent_move_san'],
            played_move_uci=played_uci,
            played_move_san=row_or_values['played_move_san'],
            best_move_uci=best_uci,
            best_move_san=row_or_values['best_move_san'],
            category=category,
            labels=labels,
            taxonomy_path=teaching_path,
            mate_before=row_or_values['mate_before'],
            best_pv_uci=row_or_values['best_pv_uci'],
            played_pv_uci=row_or_values['played_pv_uci'],
            alternative_pvs_json=row_or_values['alternative_pvs_json'],
            eval_before_cp=row_or_values['eval_before_cp'],
            eval_after_cp=row_or_values['eval_after_cp'],
            critical_events_json=row_or_values['critical_events_json'],
            explanatory_lines_json=row_or_values['explanatory_lines_json'],
            proactive_coach_json=(row_or_values['proactive_coach_json']
                                  if 'proactive_coach_json' in row_or_values.keys() else None),
        )
        conn.execute(
            'UPDATE training_positions SET coach_prompt = ?, coach_explanation = ?, coaching_version = ? WHERE id = ?',
            (prompt, explanation, COACHING_VERSION, position_id),
        )
    except (ValueError, TypeError, KeyError):
        pass


def cache_analyzed_game(
    conn, account_id, game_id, game, game_pgn, source_job_id,
    screen_depth, deep_depth, analysis_pass, settings_signature,
    source_type='self', source_username=None,
):
    """Record the deepest completed analysis for an account/game pair."""
    site = game.headers.get('Site', '')
    game_date = game.headers.get('UTCDate') or game.headers.get('Date')
    conn.execute("""
        INSERT INTO analyzed_games (
            account_id, game_id, site, game_date, game_pgn,
            source_job_id, analysis_version, max_screen_depth, max_deep_depth,
            analysis_pass, settings_signature, source_type, source_username, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(account_id, game_id) DO UPDATE SET
            site = excluded.site,
            game_date = excluded.game_date,
            game_pgn = excluded.game_pgn,
            source_job_id = excluded.source_job_id,
            max_screen_depth = CASE
                WHEN analyzed_games.analysis_version = excluded.analysis_version
                     AND COALESCE(analyzed_games.settings_signature, '') = COALESCE(excluded.settings_signature, '')
                THEN MAX(analyzed_games.max_screen_depth, excluded.max_screen_depth)
                ELSE excluded.max_screen_depth
            END,
            max_deep_depth = CASE
                WHEN analyzed_games.analysis_version = excluded.analysis_version
                     AND COALESCE(analyzed_games.settings_signature, '') = COALESCE(excluded.settings_signature, '')
                THEN MAX(analyzed_games.max_deep_depth, excluded.max_deep_depth)
                ELSE excluded.max_deep_depth
            END,
            analysis_pass = CASE
                WHEN analyzed_games.analysis_version = excluded.analysis_version
                     AND COALESCE(analyzed_games.settings_signature, '') = COALESCE(excluded.settings_signature, '')
                THEN MAX(analyzed_games.analysis_pass, excluded.analysis_pass)
                ELSE excluded.analysis_pass
            END,
            analysis_version = excluded.analysis_version,
            settings_signature = excluded.settings_signature,
            source_type = excluded.source_type,
            source_username = excluded.source_username,
            completed_at = CURRENT_TIMESTAMP
    """, (
        account_id, game_id, site, game_date, game_pgn,
        source_job_id, ANALYSIS_VERSION, int(screen_depth), int(deep_depth), int(analysis_pass), settings_signature,
        source_type, source_username,
    ))


def repoint_cache_to_job(conn, account_id, game_id, job_id):
    """Point an already-sufficient cache at the newest copied job without lowering depth."""
    conn.execute("""
        UPDATE analyzed_games
        SET source_job_id = ?, completed_at = CURRENT_TIMESTAMP
        WHERE account_id = ? AND game_id = ?
    """, (job_id, account_id, game_id))


def export_game_pgn(game):
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return game.accept(exporter)


def upsert_position(conn, job_id, game, game_pgn, candidate, analysis_pass, screen_depth, deep_depth):
    """Insert a new puzzle or refresh an existing puzzle with deeper analysis.

    Solve history is intentionally never overwritten by a deeper engine pass.
    """
    board = candidate['board']
    played_move = candidate['played_move']
    before = candidate['before']
    after = candidate['after']
    user_color = candidate['user_color']
    best = before.best_move
    if best is None:
        return False

    site = game.headers.get('Site', '')
    game_id = stable_game_id(game, game_pgn)
    opponent = game.headers.get('Black') if user_color == chess.WHITE else game.headers.get('White')
    game_date = game.headers.get('UTCDate') or game.headers.get('Date')
    fen = board.fen()
    played_uci = played_move.uci()

    existing = conn.execute("""
        SELECT id FROM training_positions
        WHERE job_id = ? AND game_id = ? AND fen = ? AND played_move_uci = ?
    """, (job_id, game_id, fen, played_uci)).fetchone()

    analytical_values = {
        'site': site,
        'game_date': game_date,
        'opponent': opponent,
        'category': candidate['category'],
        'learning_mode': candidate.get('learning_mode', 'mistakes'),
        'fen': fen,
        'previous_fen': candidate['previous_fen'],
        'opponent_move_uci': candidate['opponent_move_uci'],
        'opponent_move_san': candidate['opponent_move_san'],
        'user_color': 'white' if user_color == chess.WHITE else 'black',
        'move_number': board.fullmove_number,
        'mistake_ply': candidate['ply'],
        'game_pgn': game_pgn,
        'played_move_uci': played_uci,
        'played_move_san': board.san(played_move),
        'best_move_uci': best.uci(),
        'best_move_san': board.san(best),
        'eval_before_cp': before.cp,
        'eval_after_cp': after.cp,
        'mate_before': before.mate,
        'mate_after': after.mate,
        'centipawn_loss': centipawn_loss(before, after),
        'difficulty_score': candidate.get('difficulty_score'),
        'estimated_rating': candidate.get('estimated_rating'),
        'difficulty_version': DIFFICULTY_VERSION,
        'best_pv_uci': encode_pv(before.pv_uci),
        'played_pv_uci': encode_pv(after.pv_uci),
        'alternative_pvs_json': json.dumps(list(before.alternatives)) if before.alternatives else None,
        'analysis_pass': int(analysis_pass),
        'analysis_screen_depth': int(screen_depth),
        'analysis_deep_depth': int(deep_depth),
    }

    analytical_values['proactive_coach_json'] = (json.dumps(candidate['proactive_probe'])
        if candidate.get('proactive_probe') else None)

    # Structured chess-context observations from the best, game and verified
    # contrast lines. Only the optional third reply requires another engine
    # query; refresh reconstructs all existing lines without Stockfish.
    explanation_lines = explanation_variations(
        board, best, played_move, before.pv_uci, after.pv_uci,
        best_cp=before.cp, played_cp=after.cp, best_mate=before.mate,
        played_mate=after.mate, alternatives=list(before.alternatives),
        probe=candidate.get('explanation_probe'),
        coaching_probes=candidate.get('proactive_probe'))
    analytical_values['explanatory_lines_json'] = json.dumps(explanation_lines)
    # The root evaluation gap belongs to the decision; an observed event
    # illustrates how a sampled continuation realizes that disadvantage.
    critical = critical_decision_evidence(board, best, played_move,
        analytical_values['best_pv_uci'], analytical_values['played_pv_uci'],
        before.cp, after.cp, alternatives=list(before.alternatives),
        explanatory_lines=explanation_lines)
    analytical_values['critical_events_json'] = json.dumps(critical)

    if existing is not None:
        position_id = existing['id']
        conn.execute("""
            UPDATE training_positions SET
                site = ?, game_date = ?, opponent = ?, category = ?, learning_mode = ?,
                previous_fen = ?, opponent_move_uci = ?, opponent_move_san = ?,
                user_color = ?, move_number = ?, mistake_ply = ?, game_pgn = ?,
                played_move_san = ?, best_move_uci = ?, best_move_san = ?,
                eval_before_cp = ?, eval_after_cp = ?, mate_before = ?, mate_after = ?,
                centipawn_loss = ?, difficulty_score = ?, estimated_rating = ?,
                difficulty_version = ?, best_pv_uci = ?, played_pv_uci = ?, alternative_pvs_json = ?, critical_events_json = ?, explanatory_lines_json = ?, proactive_coach_json = ?,
                analysis_pass = ?, analysis_screen_depth = ?,
                analysis_deep_depth = ?
            WHERE id = ?
        """, (
            analytical_values['site'], analytical_values['game_date'], analytical_values['opponent'],
            analytical_values['category'], analytical_values['learning_mode'], analytical_values['previous_fen'],
            analytical_values['opponent_move_uci'], analytical_values['opponent_move_san'],
            analytical_values['user_color'], analytical_values['move_number'],
            analytical_values['mistake_ply'], analytical_values['game_pgn'],
            analytical_values['played_move_san'], analytical_values['best_move_uci'],
            analytical_values['best_move_san'], analytical_values['eval_before_cp'],
            analytical_values['eval_after_cp'], analytical_values['mate_before'],
            analytical_values['mate_after'], analytical_values['centipawn_loss'],
            analytical_values['difficulty_score'], analytical_values['estimated_rating'],
                analytical_values['difficulty_version'], analytical_values['best_pv_uci'],
                analytical_values['played_pv_uci'], analytical_values['alternative_pvs_json'], analytical_values['critical_events_json'], analytical_values['explanatory_lines_json'], analytical_values['proactive_coach_json'], analytical_values['analysis_pass'],
            analytical_values['analysis_screen_depth'], analytical_values['analysis_deep_depth'],
            position_id,
        ))
        _refresh_position_labels(conn, position_id, analytical_values)
        return False

    cur = conn.execute("""
        INSERT INTO training_positions (
            job_id, game_id, site, game_date, opponent, category, learning_mode, fen,
            previous_fen, opponent_move_uci, opponent_move_san,
            user_color, move_number, mistake_ply, game_pgn,
            played_move_uci, played_move_san, best_move_uci, best_move_san,
            eval_before_cp, eval_after_cp, mate_before, mate_after,
            centipawn_loss, difficulty_score, estimated_rating, difficulty_version,
            best_pv_uci, played_pv_uci, alternative_pvs_json, critical_events_json, explanatory_lines_json, proactive_coach_json, analysis_pass, analysis_screen_depth, analysis_deep_depth
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id, game_id, analytical_values['site'], analytical_values['game_date'],
        analytical_values['opponent'], analytical_values['category'], analytical_values['learning_mode'], analytical_values['fen'],
        analytical_values['previous_fen'], analytical_values['opponent_move_uci'],
        analytical_values['opponent_move_san'], analytical_values['user_color'],
        analytical_values['move_number'], analytical_values['mistake_ply'], analytical_values['game_pgn'],
        analytical_values['played_move_uci'], analytical_values['played_move_san'],
        analytical_values['best_move_uci'], analytical_values['best_move_san'],
        analytical_values['eval_before_cp'], analytical_values['eval_after_cp'],
        analytical_values['mate_before'], analytical_values['mate_after'],
        analytical_values['centipawn_loss'], analytical_values['difficulty_score'],
        analytical_values['estimated_rating'], analytical_values['difficulty_version'],
        analytical_values['best_pv_uci'], analytical_values['played_pv_uci'],
        analytical_values['alternative_pvs_json'], analytical_values['critical_events_json'], analytical_values['explanatory_lines_json'], analytical_values['proactive_coach_json'], analytical_values['analysis_pass'], analytical_values['analysis_screen_depth'],
        analytical_values['analysis_deep_depth'],
    ))
    position_id = cur.lastrowid
    _refresh_position_labels(conn, position_id, analytical_values)
    return True


def batch_path_for_job(username: str, job_id: int) -> Path:
    batch_dir = Path('data/batches')
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_dir / f'job_{job_id}_{username}.pgn'


def download_game_batch(username: str, params: dict, headers: dict, job_id: int) -> Path:
    batch_path = batch_path_for_job(username, job_id)
    temp_path = batch_path.with_suffix('.pgn.part')
    url = f'https://lichess.org/api/games/user/{username}'

    with requests.get(url, params=params, headers=headers, stream=True, timeout=(15, 300)) as response:
        if response.status_code == 429:
            raise RuntimeError('Lichess rate limit reached. Try again after at least one minute.')
        response.raise_for_status()
        with temp_path.open('wb') as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    temp_path.replace(batch_path)
    return batch_path


def count_games_in_batch(batch_path: Path) -> int:
    count = 0
    with batch_path.open('r', encoding='utf-8', errors='replace') as pgn:
        for line in pgn:
            if line.startswith('[Event '):
                count += 1
    return count


def run_analysis_job(job_id: int):
    # Serialize background Stockfish work in the local prototype. Imported
    # databases can contain several stale jobs; one engine-heavy job at a time
    # is both faster and more reliable on a desktop machine.
    with PROCESS_LOCK:
        with _ANALYSIS_LOCK:
            return _run_analysis_job(job_id)


def _run_analysis_job(job_id: int):
    conn = connect()
    engine = None
    claimed_running = False
    try:
        row = conn.execute("""
            SELECT j.*, a.username
            FROM analysis_jobs j
            JOIN accounts a ON a.id = j.account_id
            WHERE j.id = ?
        """, (job_id,)).fetchone()
        if row is None:
            return
        if row['status'] not in ('queued', 'retrieving', 'running'):
            return

        # Instrument real per-stage work rather than estimating from engine settings.
        perf = {'screen_seconds': 0.0, 'deep_seconds': 0.0,
                'reply_seconds': 0.0, 'coaching_seconds': 0.0,
                'metadata_seconds': 0.0, 'cached_games': 0}
        if row['perf_json']:
            try:
                previous = json.loads(row['perf_json'])
                perf.update({k: float(v) if k.endswith('_seconds') else int(v)
                             for k, v in previous.items() if k in perf})
            except (ValueError, TypeError):
                pass

        account_id = row['account_id']
        owner_username = row['username']
        source_type = row['source_type'] if 'source_type' in row.keys() and row['source_type'] else 'self'
        source_username = row['source_username'] if 'source_username' in row.keys() and row['source_username'] else owner_username
        try:
            learning_modes = json.loads(row['learning_modes']) if 'learning_modes' in row.keys() and row['learning_modes'] else ['mistakes']
        except (TypeError, json.JSONDecodeError):
            learning_modes = ['mistakes']
        if source_type == 'opposition':
            learning_modes = ['opposition']
        learning_modes = [m for m in learning_modes if m in {'mistakes', 'blunders', 'excellent', 'brilliant', 'opposition'}]
        if not learning_modes:
            learning_modes = ['mistakes'] if source_type == 'self' else ['opposition']
        settings = settings_from_snapshot(row['settings_json'] if 'settings_json' in row.keys() else None, conn)
        perf_types = json.loads(row['game_types'])
        since_ms = date_range_to_ms(row['date_range'])
        screen_seconds = float(row['screen_seconds'] if 'screen_seconds' in row.keys() else settings['screen_seconds'])
        deep_seconds = float(row['deep_seconds'] if 'deep_seconds' in row.keys() else settings['deep_seconds'])
        base_screen_depth = int(row['screen_depth'] if 'screen_depth' in row.keys() else settings['base_screen_depth'])
        base_deep_depth = int(row['deep_depth'] if 'deep_depth' in row.keys() else settings['base_deep_depth'])
        settings = dict(settings)
        settings.update({
            'screen_seconds': screen_seconds,
            'deep_seconds': deep_seconds,
            'base_screen_depth': base_screen_depth,
            'base_deep_depth': base_deep_depth,
            '_job_learning_modes': learning_modes,
            '_source_type': source_type,
            '_source_username': source_username,
        })
        max_passes = max(1, int(row['max_passes'] if 'max_passes' in row.keys() else settings['max_passes']))
        # Explicit next-pass refinement is allowed even when automatic progressive
        # depths were disabled; setup already stored one pass for such lists.
        settings['max_passes'] = max_passes
        settings_sig = analysis_signature(settings)
        start_pass = max(1, int(row['current_pass'] if 'current_pass' in row.keys() else 1))
        start_pass = min(start_pass, max_passes)

        if not (row['settings_json'] if 'settings_json' in row.keys() else None):
            from app_settings import serialize_settings
            conn.execute('UPDATE analysis_jobs SET settings_json = ? WHERE id = ?', (serialize_settings(settings), job_id))
            conn.commit()

        # Retrieval is a distinct, persisted process initiated at list creation.
        # A resumed analysis must never silently trigger a new Lichess download.
        existing_positions = conn.execute(
            'SELECT COUNT(*) AS n FROM training_positions WHERE job_id = ?',
            (job_id,),
        ).fetchone()['n']

        batch_path = batch_path_for_job(source_username, job_id)
        if not batch_path.exists() or batch_path.stat().st_size == 0:
            raise RuntimeError('Saved PGN batch is missing. Retrieval must complete before analysis can start.')
        retrieval = conn.execute(
            'SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)
        ).fetchone()
        if retrieval is not None and retrieval['status'] != 'complete':
            raise RuntimeError('Game retrieval has not completed for this game list.')

        game_count = count_games_in_batch(batch_path)
        first_screen_depth, first_deep_depth = pass_depths(
            base_screen_depth, base_deep_depth, start_pass, settings
        )
        conn.execute("""
            UPDATE analysis_jobs
            SET status = 'running', error = NULL, games_retrieved = ?,
                positions_found = ?, current_screen_depth = ?, current_deep_depth = ?
            WHERE id = ? AND status IN ('queued', 'retrieving', 'running')
        """, (
            game_count, existing_positions, first_screen_depth, first_deep_depth, job_id,
        ))
        conn.commit()
        if conn.execute('SELECT status FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()['status'] != 'running':
            return
        claimed_running = True

        def safe_quit_engine():
            nonlocal engine
            if engine is None:
                return
            try:
                engine.quit()
            except Exception:
                try:
                    engine.close()
                except Exception:
                    pass
            finally:
                engine = None

        def ensure_engine():
            nonlocal engine
            if engine is not None:
                return engine
            stockfish_path = find_stockfish(settings)
            engine = chess.engine.SimpleEngine.popen_uci(
                str(stockfish_path),
                setpgrp=True,
                timeout=float(settings['engine_start_timeout_seconds']),
            )
            options = {}
            if 'Threads' in engine.options:
                options['Threads'] = max(1, min(int(settings['analysis_engine_threads']), os.cpu_count() or int(settings['analysis_engine_threads'])))
            if 'Hash' in engine.options:
                options['Hash'] = int(settings['analysis_engine_hash_mb'])
            if options:
                engine.configure(options)
            engine.ping()
            return engine

        def engine_retry(operation, label):
            last_error = None
            for attempt in range(int(settings['engine_restart_retries']) + 1):
                try:
                    return operation(ensure_engine())
                except (chess.engine.EngineTerminatedError, chess.engine.EngineError, OSError) as exc:
                    last_error = exc
                    safe_quit_engine()
                    if attempt >= int(settings['engine_restart_retries']):
                        break
            raise RuntimeError(
                f'Stockfish stopped while {label}. It was restarted '
                f"{int(settings['engine_restart_retries'])} times but could not continue: {last_error}"
            ) from last_error

        for pass_number in range(start_pass, max_passes + 1):
            state = conn.execute('''
                SELECT status, checkpoint_pass, checkpoint_game_index,
                       checkpoint_file_offset FROM analysis_jobs WHERE id = ?
            ''', (job_id,)).fetchone()
            if state is None or state['status'] != 'running':
                break

            screen_depth, deep_depth = pass_depths(
                base_screen_depth, base_deep_depth, pass_number, settings
            )
            checkpointed = int(state['checkpoint_pass'] or 0) == pass_number
            game_index = int(state['checkpoint_game_index'] or 0) if checkpointed else 0
            file_offset = int(state['checkpoint_file_offset'] or 0) if checkpointed else 0
            if not checkpointed and pass_number == start_pass:
                # Recover conservatively from an analysis paused by v37 (which
                # advanced games_processed *before* deep confirmation). All but
                # its last counted game are complete when the pass was partial.
                # A full count can belong to the PREVIOUS pass, so never use it
                # to skip work in a newly started pass.
                previous_count = int(row['games_processed'] or 0)
                if 0 < previous_count < game_count and int(row['current_pass'] or 1) == pass_number:
                    game_index = max(0, previous_count - 1)
            # A resumed pass keeps its progress; a *new* pass starts at zero.
            conn.execute("""
                UPDATE analysis_jobs
                SET current_pass = ?, current_screen_depth = ?, current_deep_depth = ?,
                    checkpoint_pass = ?, checkpoint_game_index = ?, checkpoint_file_offset = ?,
                    games_processed = ?, passes_completed = ?, error = NULL
                WHERE id = ? AND status = 'running'
            """, (pass_number, screen_depth, deep_depth, pass_number,
                  game_index, file_offset, game_index, pass_number - 1, job_id))
            conn.commit()

            with batch_path.open('r', encoding='utf-8', errors='replace') as pgn:
                if file_offset:
                    # seek() restores a text-file position saved by tell() on this PGN.
                    pgn.seek(file_offset)
                elif game_index:
                    # Recovery path for a checkpoint whose file offset was lost.
                    for _ in range(game_index):
                        if chess.pgn.read_game(pgn) is None:
                            raise RuntimeError('Saved PGN has changed since analysis was paused.')
                while True:
                    current_status = conn.execute(
                        'SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)
                    ).fetchone()
                    if current_status is None or current_status['status'] != 'running':
                        break

                    game = chess.pgn.read_game(pgn)
                    if game is None:
                        break
                    next_file_offset = pgn.tell()
                    game_pgn = export_game_pgn(game)
                    game_id = stable_game_id(game, game_pgn)
                    cached = conn.execute("""
                        SELECT source_job_id, analysis_version, max_screen_depth,
                               max_deep_depth, analysis_pass, settings_signature,
                               source_type, source_username
                        FROM analyzed_games
                        WHERE account_id = ? AND game_id = ?
                    """, (account_id, game_id)).fetchone()

                    cached_same_source = (
                        cached is not None
                        and (cached['source_type'] or 'self') == source_type
                        and str(cached['source_username'] or owner_username).casefold() == str(source_username).casefold()
                    )
                    copied = 0
                    if cached_same_source and not row['force_reanalysis']:
                        copied = copy_cached_positions(
                            conn, account_id, game_id, cached['source_job_id'], job_id, learning_modes
                        )
                        if copied:
                            conn.execute(
                                'UPDATE analysis_jobs SET positions_found = positions_found + ? WHERE id = ?',
                                (copied, job_id),
                            )
                            conn.commit()

                    cache_is_deep_enough = (
                        not row['force_reanalysis']
                        and cached_same_source
                        and cached['analysis_version'] == ANALYSIS_VERSION
                        and (cached['settings_signature'] or '') == settings_sig
                        and int(cached['max_screen_depth'] or 0) >= screen_depth
                        and int(cached['max_deep_depth'] or 0) >= deep_depth
                    )
                    if cache_is_deep_enough:
                        perf['cached_games'] += 1
                        conn.execute('UPDATE analysis_jobs SET perf_json=? WHERE id=?',
                                     (json.dumps(perf), job_id))
                        repoint_cache_to_job(conn, account_id, game_id, job_id)
                        # The per-game checkpoint and cache changes commit together.
                        game_index += 1
                        conn.execute("""
                            UPDATE analysis_jobs SET checkpoint_game_index=?,
                                checkpoint_file_offset=?, games_processed=?,
                                games_screened=MAX(games_screened, ?)
                            WHERE id=? AND status='running'
                        """, (game_index, next_file_offset, game_index, game_index, job_id))
                        conn.commit()
                        continue

                    screen_started = time.perf_counter()
                    candidates = engine_retry(
                        lambda sf: screen_game(
                            sf, game, source_username, screen_seconds, screen_depth, settings
                        ),
                        f'screening game {game_id} at depth {screen_depth}',
                    )
                    perf['screen_seconds'] += time.perf_counter() - screen_started
                    # Do not advance the resume cursor after screening alone:
                    # this game's deep confirmation must finish first.
                    after_screen_status = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
                    if after_screen_status is None or after_screen_status['status'] != 'running':
                        break

                    confirmed = []
                    deep_candidates = choose_deep_candidates(candidates, settings)
                    for candidate in deep_candidates:
                        candidate_ply = int(candidate.get('ply') or 0)
                        conn.execute('''
                            INSERT INTO analysis_candidates(job_id, game_id, ply, first_pass, last_pass, learning_mode)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(job_id, game_id, ply) DO UPDATE SET
                                first_pass = MIN(first_pass, excluded.first_pass),
                                last_pass = MAX(last_pass, excluded.last_pass),
                                learning_mode = excluded.learning_mode
                        ''', (job_id, game_id, candidate_ply, pass_number, pass_number,
                              'opposition' if candidate.get('candidate_kind') == 'opposition' else
                              ('excellent' if candidate.get('candidate_kind') == 'reinforcement' else 'mistakes')))
                        conn.commit()
                        deep_started = time.perf_counter()
                        result = engine_retry(
                            lambda sf, candidate=candidate: confirm_candidate(
                                sf, candidate, deep_seconds, deep_depth, settings
                            ),
                            f'deep-confirming game {game_id} at depth {deep_depth}',
                        )
                        perf['deep_seconds'] += time.perf_counter() - deep_started
                        if result is not None:
                            # Preserve deep-confirmed work even when a bounded
                            # explanation probe encounters an engine limitation.
                            fraction = max(0.0, min(.5, float(settings.get('explanation_probe_fraction', .18))))
                            if fraction and settings.get('explanation_probe_enabled', True):
                                reply_started = time.perf_counter()
                                try:
                                    result['explanation_probe'] = engine_retry(
                                        lambda sf, result=result: probe_explanatory_replies(
                                            sf, result, max(.05, deep_seconds * fraction),
                                            deep_depth, settings),
                                        f'checking explanatory replies for {game_id}',
                                    )
                                except Exception:
                                    # The explanatory probe is strictly optional.
                                    # It must never discard a confirmed puzzle.
                                    result['explanation_probe'] = None
                                finally:
                                    perf['reply_seconds'] += time.perf_counter() - reply_started
                            confirmed.append(result)
                        mid_status = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
                        if mid_status is None or mid_status['status'] != 'running':
                            break

                    mid_status = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
                    if mid_status is None or mid_status['status'] != 'running':
                        break

                    inserted = 0
                    if confirmed:
                        for candidate in choose_distinct_positions(confirmed, settings):
                            if settings.get('coaching_probe_enabled', True):
                                from proactive_coaching import probe_training_position
                                root = candidate['board']
                                before = candidate['before']
                                comparison = candidate['played_move']
                                args = {'fen': root.fen(),
                                        'best_move_uci': before.best_move.uci(),
                                        'played_move_uci': comparison.uci(),
                                        'eval_before_cp': before.cp,
                                        'eval_after_cp': candidate['after'].cp,
                                        'alternative_pvs_json': json.dumps(list(before.alternatives))}
                                coaching_started = time.perf_counter()
                                try:
                                    candidate['proactive_probe'] = engine_retry(
                                        lambda sf, args=args: probe_training_position(sf, args, settings),
                                        f'coaching training position in {game_id}')
                                except Exception:
                                    # Coaching probes are additional diagnostics;
                                    # never discard an otherwise confirmed puzzle.
                                    candidate['proactive_probe'] = None
                                finally:
                                    perf['coaching_seconds'] += time.perf_counter() - coaching_started
                            metadata_started = time.perf_counter()
                            if upsert_position(
                                conn, job_id, game, game_pgn, candidate,
                                pass_number, screen_depth, deep_depth,
                            ):
                                inserted += 1
                            perf['metadata_seconds'] += time.perf_counter() - metadata_started

                    # Clean games are also cached at this depth. If a deeper pass
                    # later discovers a hidden tactic, it will be added then.
                    cache_analyzed_game(
                        conn, account_id, game_id, game, game_pgn, job_id,
                        screen_depth, deep_depth, pass_number, settings_sig,
                        source_type=source_type, source_username=source_username,
                    )
                    if inserted:
                        conn.execute(
                            'UPDATE analysis_jobs SET positions_found = positions_found + ? WHERE id = ?',
                            (inserted, job_id),
                        )
                    conn.execute('UPDATE analysis_jobs SET perf_json=? WHERE id=?',
                                 (json.dumps(perf, sort_keys=True), job_id))
                    # Finish the game atomically with its cached results and positions.
                    # Pausing mid-game leaves this checkpoint untouched; only that
                    # unfinished game is evaluated again on resume.
                    game_index += 1
                    conn.execute("""
                        UPDATE analysis_jobs SET checkpoint_game_index=?,
                            checkpoint_file_offset=?, games_processed=?,
                            games_screened=MAX(games_screened, ?)
                        WHERE id=? AND status='running'
                    """, (game_index, next_file_offset, game_index, game_index, job_id))
                    conn.commit()

            state = conn.execute(
                'SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)
            ).fetchone()
            if state is None or state['status'] != 'running':
                break

            conn.execute("""
                UPDATE analysis_jobs
                SET passes_completed = ?,
                    current_pass = CASE WHEN ? < max_passes THEN ? ELSE current_pass END,
                    checkpoint_pass = CASE WHEN ? < max_passes THEN ? ELSE checkpoint_pass END,
                    checkpoint_game_index = CASE WHEN ? < max_passes THEN 0 ELSE checkpoint_game_index END,
                    checkpoint_file_offset = CASE WHEN ? < max_passes THEN 0 ELSE checkpoint_file_offset END,
                    games_processed = CASE WHEN ? < max_passes THEN 0 ELSE games_processed END
                WHERE id = ? AND status = 'running'
            """, (
                pass_number, pass_number, pass_number + 1,
                pass_number, pass_number + 1,
                pass_number, pass_number, pass_number, job_id,
            ))
            conn.commit()

        current_status = conn.execute(
            'SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)
        ).fetchone()
        if current_status is not None and current_status['status'] == 'running':
            final_screen_depth, final_deep_depth = pass_depths(
                base_screen_depth, base_deep_depth, max_passes, settings
            )
            conn.execute("""
                UPDATE analysis_jobs
                SET status = 'complete', force_reanalysis = 0, finished_at = CURRENT_TIMESTAMP,
                    passes_completed = max_passes, current_pass = max_passes,
                    current_screen_depth = ?, current_deep_depth = ?
                WHERE id = ? AND status = 'running'
            """, (final_screen_depth, final_deep_depth, job_id))
            conn.commit()

    except Exception as exc:
        # A worker finishing after Pause must never overwrite a newer queued
        # Resume request with an error from the previous attempt.
        where = ("id = ? AND status = 'running'" if claimed_running else
                 "id = ? AND status IN ('queued', 'retrieving', 'running')")
        conn.execute(
            "UPDATE analysis_jobs SET status='error', error=?, finished_at=CURRENT_TIMESTAMP WHERE " + where,
            (str(exc), job_id),
        )
        conn.commit()
    finally:
        if engine is not None:
            try:
                engine.quit()
            except Exception:
                try:
                    engine.close()
                except Exception:
                    pass
        conn.close()


def probe_explanatory_replies(engine, candidate, seconds, depth, settings=None):
    """Bounded, optional second-best *opponent reply* after the played move.

    The best and played PVs are already root-constrained Stockfish results. An
    extra MultiPV probe tests whether an apparent tactical explanation changes
    under another credible reply, without claiming that either line is forced.
    Runs only after deep confirmation and never during page rendering/refresh.
    """
    settings = settings or DEFAULT_SETTINGS
    if not settings.get('explanation_probe_enabled', True):
        return None
    board = candidate.get('board')
    played = candidate.get('played_move')
    before = candidate.get('before')
    after = candidate.get('after')
    if not board or not played or played not in board.legal_moves or played == before.best_move:
        return None
    after_board = board.copy(stack=False)
    after_board.push(played)
    if after_board.is_game_over():
        return None
    seconds = max(0.05, float(seconds))
    limit = chess.engine.Limit(time=seconds, depth=max(1, int(depth) - 2))
    infos = engine.analyse(after_board, limit, multipv=2)
    if not isinstance(infos, list):
        infos = [infos]
    existing = list(after.pv_uci[:2])
    for info in infos:
        pv = info.get('pv') or []
        if not pv or (len(existing) > 1 and pv[0].uci() == existing[1]):
            continue
        score = info['score'].pov(board.turn)
        cp = score.score(mate_score=int(settings['mate_score_cp']))
        return {'pv_uci': [played.uci()] + [m.uci() for m in pv[:11]],
                'eval_cp': int(cp) if cp is not None else None,
                'mate': score.mate(), 'depth': info.get('depth')}
    return None
