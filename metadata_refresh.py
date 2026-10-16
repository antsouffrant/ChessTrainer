"""Rebuild derived position metadata from locally saved analysis and PGNs.

This deliberately does not call Lichess or Stockfish. Evaluation scores,
selected positions, PVs, modes, and learning history remain untouched.
"""
from __future__ import annotations

import io
import json

from critical_moments import critical_decision_evidence
from explanatory_evidence import explanation_variations, decode_variations

import chess
import chess.pgn

from analysis import (
    DIFFICULTY_VERSION, EvalResult, _refresh_position_labels,
    estimate_puzzle_difficulty,
)
from openings import classify_pgn, historical_for_position


def _game_context(pgn):
    """Index the game before each played move, including its actual previous move."""
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return None, {}
    board = game.board()
    previous_fen = None
    previous_move = None
    previous_san = None
    result = {}
    for ply, move in enumerate(game.mainline_moves(), start=1):
        if move not in board.legal_moves:
            break
        current_fen = board.fen()
        current_san = board.san(move)
        result[(current_fen, move.uci())] = {
            'previous_fen': previous_fen,
            'opponent_move_uci': previous_move,
            'opponent_move_san': previous_san,
            'played_move_san': current_san,
            'move_number': board.fullmove_number,
            'mistake_ply': ply,
        }
        previous_fen, previous_move, previous_san = current_fen, move.uci(), current_san
        board.push(move)
    return game, result


def refresh_metadata_batch(conn, job_id, after_id=0, batch_size=25):
    """Refresh a bounded portion of one game list. Caller owns the transaction.

    Returns deterministic cursor progress; running the same batch twice is safe.
    Missing or invalid PGNs do not block labels/difficulty from stored FENs.
    """
    batch_size = max(1, min(100, int(batch_size)))
    after_id = max(0, int(after_id))
    total = conn.execute(
        'SELECT COUNT(*) AS n FROM training_positions WHERE job_id = ?', (job_id,)
    ).fetchone()['n']
    rows = conn.execute('''
        SELECT tp.*, COALESCE(NULLIF(tp.game_pgn, ''), ag.game_pgn) AS saved_pgn
        FROM training_positions tp
        JOIN analysis_jobs j ON j.id = tp.job_id
        LEFT JOIN analyzed_games ag ON ag.account_id = j.account_id
            AND ag.game_id = tp.game_id
        WHERE tp.job_id = ? AND tp.id > ?
        ORDER BY tp.id LIMIT ?
    ''', (job_id, after_id, batch_size)).fetchall()

    cache = {}
    refreshed = 0
    failed = 0
    no_pgn = 0
    for row in rows:
        position_id = row['id']
        pgn = row['saved_pgn'] or ''
        try:
            board = chess.Board(row['fen'])
            best_move = chess.Move.from_uci(row['best_move_uci'])
            if best_move not in board.legal_moves:
                failed += 1
                continue

            if pgn:
                game_key = (row['game_id'], pgn)
                if game_key not in cache:
                    opening = classify_pgn(pgn)
                    try:
                        game, history = _game_context(pgn)
                    except (ValueError, TypeError, UnicodeError):
                        game, history = None, {}
                    cache[game_key] = opening, game, history
                opening, game, history = cache[game_key]
                historical = historical_for_position(row['fen'])
                conn.execute('''
                    UPDATE training_positions SET
                        game_pgn = COALESCE(NULLIF(game_pgn, ''), ?),
                        opening_key = ?, opening_name = ?, opening_variation = ?,
                        opening_eco = ?, opening_source = ?, opening_history = ?,
                        historical_match = ?
                    WHERE id = ?
                ''', (pgn, opening['key'], opening['name'], opening['variation'],
                      opening['eco'], opening['source'], opening['history'], historical, position_id))
                original = history.get((row['fen'], row['played_move_uci']))
                if original:
                    # Only reconstruct context when the stored puzzle is an exact
                    # moment in the original game. Opponent-scouting puzzles can
                    # be deliberately positioned one move later, so do not guess.
                    conn.execute('''
                        UPDATE training_positions SET
                            previous_fen = ?, opponent_move_uci = ?, opponent_move_san = ?,
                            played_move_san = ?, move_number = ?, mistake_ply = ?
                        WHERE id = ?
                    ''', (original['previous_fen'], original['opponent_move_uci'],
                          original['opponent_move_san'], original['played_move_san'],
                          original['move_number'], original['mistake_ply'], position_id))
            else:
                no_pgn += 1
                # A PGN-less legacy position can still gain an exact historical
                # match and labels without losing a previously known opening.
                conn.execute('''UPDATE training_positions
                    SET historical_match = ? WHERE id = ?''',
                    (historical_for_position(row['fen']), position_id))

            before = EvalResult(
                cp=int(row['eval_before_cp'] or 0),
                mate=row['mate_before'],
                best_move=best_move,
                depth=None,
            )
            score, rating = estimate_puzzle_difficulty(board, best_move, before, row['category'])
            conn.execute('''UPDATE training_positions
                SET difficulty_score = ?, estimated_rating = ?, difficulty_version = ?
                WHERE id = ?''', (score, rating, DIFFICULTY_VERSION, position_id))

            # Metadata-only reconstruction: uses existing root evaluations and
            # saved PVs, never downloads PGNs or invokes Stockfish.
            try:
                played = chess.Move.from_uci(row['played_move_uci'])
                existing_lines = decode_variations(row['explanatory_lines_json'])
                probe = next((line for line in existing_lines['lines']
                              if line.get('role') == 'tested_reply'), None) if existing_lines else None
                lines = explanation_variations(
                    board, best_move, played, row['best_pv_uci'], row['played_pv_uci'],
                    row['eval_before_cp'], row['eval_after_cp'], row['mate_before'],
                    row['mate_after'], row['alternative_pvs_json'], probe=probe)
                evidence = critical_decision_evidence(
                    board, best_move, played, row['best_pv_uci'], row['played_pv_uci'],
                    row['eval_before_cp'], row['eval_after_cp'],
                    alternatives=row['alternative_pvs_json'], explanatory_lines=lines)
                conn.execute('''UPDATE training_positions
                    SET critical_events_json = ?, explanatory_lines_json = ?
                    WHERE id = ?''', (json.dumps(evidence), json.dumps(lines), position_id))
            except (TypeError, ValueError):
                pass

            # Refresh labels from the newest stored PGN context, PVs, and
            # unchanged engine evaluations; coaching uses those updated labels.
            current = conn.execute('SELECT * FROM training_positions WHERE id = ?', (position_id,)).fetchone()
            _refresh_position_labels(conn, position_id, current)
            refreshed += 1
        except (ValueError, TypeError, KeyError, UnicodeError):
            failed += 1
            continue

    last_id = rows[-1]['id'] if rows else after_id
    more = bool(conn.execute('''SELECT 1 FROM training_positions
        WHERE job_id = ? AND id > ? LIMIT 1''', (job_id, last_id)).fetchone())
    if not more:
        conn.execute('''UPDATE analysis_jobs
            SET metadata_refreshed_at = CURRENT_TIMESTAMP WHERE id = ?''', (job_id,))
    processed = conn.execute('''SELECT COUNT(*) AS n FROM training_positions
        WHERE job_id = ? AND id <= ?''', (job_id, last_id)).fetchone()['n']
    return {
        'total': total, 'processed': processed, 'updated': refreshed,
        'failed': failed, 'without_pgn': no_pgn,
        'next_cursor': last_id if more else None, 'done': not more,
    }
