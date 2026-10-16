from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional

import chess
import chess.engine

from app_settings import get_settings
from db import connect



def find_stockfish(settings=None) -> Path:
    settings = settings or get_settings()
    stockfish_dir = Path(settings.get('stockfish_dir', 'stockfish'))
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
        raise FileNotFoundError(f'No Stockfish executable found inside {stockfish_dir}.')
    candidates.sort(key=lambda p: (len(p.relative_to(stockfish_dir).parts), len(p.name)))
    return candidates[0].resolve()

_engine: Optional[chess.engine.SimpleEngine] = None
_engine_lock = threading.Lock()


def _discard_engine():
    global _engine
    if _engine is None:
        return
    try:
        _engine.quit()
    except Exception:
        try:
            _engine.close()
        except Exception:
            pass
    finally:
        _engine = None


def reset_review_engine():
    """Drop the shared review engine so newly saved settings apply immediately."""
    with _engine_lock:
        _discard_engine()


def _engine_instance(settings) -> chess.engine.SimpleEngine:
    global _engine
    if _engine is None:
        _engine = chess.engine.SimpleEngine.popen_uci(
            str(find_stockfish(settings)),
            setpgrp=True,
            timeout=float(settings['engine_start_timeout_seconds']),
        )
        options = {}
        if 'Threads' in _engine.options:
            options['Threads'] = int(settings['review_engine_threads'])
        if 'Hash' in _engine.options:
            options['Hash'] = int(settings['review_engine_hash_mb'])
        if options:
            _engine.configure(options)
        _engine.ping()
    return _engine


def _analyse_with_recovery(board: chess.Board, settings):
    last_error = None
    retries = int(settings['review_engine_retries'])
    for attempt in range(retries + 1):
        try:
            engine = _engine_instance(settings)
            return engine.analyse(
                board,
                chess.engine.Limit(time=float(settings['review_engine_seconds'])),
            )
        except (chess.engine.EngineTerminatedError, chess.engine.EngineError, OSError) as exc:
            last_error = exc
            _discard_engine()
            if attempt >= retries:
                break
    raise RuntimeError(
        f'Stockfish review engine stopped unexpectedly after {retries + 1} attempts: {last_error}'
    ) from last_error


def _analyse_move_with_recovery(board: chess.Board, move: chess.Move, settings):
    """Evaluate one legal root move using the configured short review budget."""
    last_error = None
    retries = int(settings['review_engine_retries'])
    for attempt in range(retries + 1):
        try:
            engine = _engine_instance(settings)
            return engine.analyse(
                board,
                chess.engine.Limit(time=float(settings['review_engine_seconds'])),
                root_moves=[move],
            )
        except (chess.engine.EngineTerminatedError, chess.engine.EngineError, OSError) as exc:
            last_error = exc
            _discard_engine()
            if attempt >= retries:
                break
    raise RuntimeError(
        f'Stockfish move-quality engine stopped unexpectedly after {retries + 1} attempts: {last_error}'
    ) from last_error


def evaluate_move_quality(fen: str, move_uci: str, pov: chess.Color):
    board = chess.Board(fen)
    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError as exc:
        raise ValueError('Invalid UCI move') from exc
    if move not in board.legal_moves:
        raise ValueError('Move is not legal in this position')

    settings = get_settings()
    with _engine_lock:
        info = _analyse_move_with_recovery(board, move, settings)

    score = info['score'].pov(pov)
    cp = score.score(mate_score=int(settings['mate_score_cp']))

    pv = list(info.get('pv') or [])
    pv_uci = [m.uci() for m in pv]
    pv_san = []
    replay = board.copy(stack=False)
    for pv_move in pv:
        try:
            if pv_move not in replay.legal_moves:
                break
            pv_san.append(replay.san(pv_move))
            replay.push(pv_move)
        except Exception:
            break

    resulting = board.copy(stack=False)
    resulting.push(move)
    best_reply_uci = pv_uci[1] if len(pv_uci) > 1 else None
    best_reply_san = pv_san[1] if len(pv_san) > 1 else None

    return {
        'eval_cp': int(cp if cp is not None else 0),
        'mate': score.mate(),
        'depth': info.get('depth'),
        'pv_uci': pv_uci,
        'pv_san': pv_san,
        'best_reply_uci': best_reply_uci,
        'best_reply_san': best_reply_san,
        'resulting_fen': resulting.fen(),
    }


def evaluate_fen(fen: str, pov: chess.Color):
    board = chess.Board(fen)

    with connect() as conn:
        cached = conn.execute(
            'SELECT * FROM engine_eval_cache WHERE fen = ?',
            (fen,),
        ).fetchone()

    settings = get_settings()
    if cached is None:
        with _engine_lock:
            info = _analyse_with_recovery(board, settings)

        score_white = info['score'].pov(chess.WHITE)
        cp_white = score_white.score(mate_score=int(settings['mate_score_cp']))
        pv = info.get('pv', [])
        best_move = pv[0] if pv else None
        best_uci = best_move.uci() if best_move else None
        best_san = board.san(best_move) if best_move else None

        with connect() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO engine_eval_cache (
                    fen, best_move_uci, best_move_san, eval_white_cp, mate_white, depth
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                fen,
                best_uci,
                best_san,
                int(cp_white if cp_white is not None else 0),
                score_white.mate(),
                info.get('depth'),
            ))
            conn.commit()
            cached = conn.execute(
                'SELECT * FROM engine_eval_cache WHERE fen = ?',
                (fen,),
            ).fetchone()

    cp_white = cached['eval_white_cp']
    mate_white = cached['mate_white']
    if pov == chess.WHITE:
        cp = cp_white
        mate = mate_white
    else:
        cp = -cp_white if cp_white is not None else None
        mate = -mate_white if mate_white is not None else None

    return {
        'best_move_uci': cached['best_move_uci'],
        'best_move_san': cached['best_move_san'],
        'eval_cp': cp,
        'mate': mate,
        'depth': cached['depth'],
        'legal_moves': [move.uci() for move in board.legal_moves],
        'turn': 'white' if board.turn == chess.WHITE else 'black',
        'fen': fen,
    }


def evaluate_multipv(fen: str, pov: chess.Color, count: int = 4):
    """Return a small ranked set of engine candidates for conversational coaching.

    This is intentionally uncached: the coach uses it only on demand and the
    configured short review budget keeps the interaction responsive.
    """
    board = chess.Board(fen)
    settings = get_settings()
    count = max(1, min(int(count or 1), 8))
    last_error = None
    with _engine_lock:
        retries = int(settings['review_engine_retries'])
        infos = None
        for attempt in range(retries + 1):
            try:
                engine = _engine_instance(settings)
                infos = engine.analyse(
                    board,
                    chess.engine.Limit(time=float(settings['review_engine_seconds'])),
                    multipv=count,
                )
                break
            except (chess.engine.EngineTerminatedError, chess.engine.EngineError, OSError) as exc:
                last_error = exc
                _discard_engine()
                if attempt >= retries:
                    break
        if infos is None:
            raise RuntimeError(
                f'Stockfish MultiPV engine stopped unexpectedly after {retries + 1} attempts: {last_error}'
            ) from last_error

    if isinstance(infos, dict):
        infos = [infos]
    results = []
    for rank, info in enumerate(infos or [], start=1):
        score = info['score'].pov(pov)
        cp = score.score(mate_score=int(settings['mate_score_cp']))
        pv = list(info.get('pv') or [])
        replay = board.copy(stack=False)
        pv_san = []
        pv_uci = []
        for move in pv:
            if move not in replay.legal_moves:
                break
            pv_uci.append(move.uci())
            pv_san.append(replay.san(move))
            replay.push(move)
        if not pv_uci:
            continue
        results.append({
            'rank': rank,
            'move_uci': pv_uci[0],
            'move_san': pv_san[0],
            'eval_cp': int(cp if cp is not None else 0),
            'mate': score.mate(),
            'depth': info.get('depth'),
            'pv_uci': pv_uci,
            'pv_san': pv_san,
        })
    return results
