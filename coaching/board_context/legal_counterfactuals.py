"""Conservative, legality-aware counterfactuals.

The played move is a legal but potentially inferior alternative. For opponent
replies, only make a refutation claim if the actual legal sequence proves it.
In particular, we do NOT invent a Stockfish evaluation for a tempting capture
absent from the principal variation.
"""
from __future__ import annotations

import chess


def verified_legal_reply_traps(board: chess.Board, best_move: chess.Move,
                               max_replies: int = 3) -> list[dict]:
    """Find a legal capture of the answer that loses to *mate in one*.

    This proof needs no engine and does not imply all other legal replies lose.
    Limit the probe to captures of the piece just moved, excluding null results
    and positions where the move already gives checkmate.
    """
    if best_move not in board.legal_moves:
        return []
    best_san = board.san(best_move)
    after = board.copy(stack=False)
    after.push(best_move)
    if after.is_game_over():
        return []
    findings = []
    candidates = [reply for reply in after.legal_moves
                  if after.is_capture(reply) and reply.to_square == best_move.to_square]
    for reply in candidates[:max_replies]:
        reply_san = after.san(reply)
        after_reply = after.copy(stack=False)
        after_reply.push(reply)
        for refutation in after_reply.legal_moves:
            reply_to_refutation = after_reply.copy(stack=False)
            reply_to_refutation.push(refutation)
            if reply_to_refutation.is_checkmate():
                mate_san = after_reply.san(refutation)
                findings.append({
                    'kind': 'legal_capture_mate_in_one', 'reply_uci': reply.uci(),
                    'reply_san': reply_san, 'refutation_uci': refutation.uci(),
                    'refutation_san': mate_san, 'ply': 3,
                    'motif': 'mating_net',
                    'evidence': (f'After {best_san}, {reply_san} is legal but '
                                 f'allows {mate_san}, checkmate.'),
                })
                break
    return findings


def missed_threat_counterfactual(board: chess.Board, best_move: chess.Move,
                                 played_move: chess.Move | None, context: dict) -> dict | None:
    """Board-proven contrast between two legal first moves.

    A missed threat is useful only when the best answer addresses that same
    threatened piece. Avoid the assertion that a capture *will* happen, which
    would require further validated opponent play.
    """
    if (played_move is None or played_move == best_move
            or played_move not in board.legal_moves
            or not context.get('best_neutralizes')):
        return None
    missed = set(context.get('played_ignores') or [])
    rescued = set(context.get('best_neutralizes') or [])
    overlap = sorted(missed & rescued)
    if not overlap:
        return None
    square = overlap[0]
    piece = board.piece_at(square)
    if piece is None:
        return None
    best_san, played_san = board.san(best_move), board.san(played_move)
    name, location = chess.piece_name(piece.piece_type), chess.square_name(square)
    return {
        'kind': 'missed_defense', 'motif': 'loose_piece_awareness', 'ply': 1,
        'evidence': (f'{best_san} deals with the threat to your {name} on {location}; '
                     f'in the game, {played_san} left it hanging.'),
    }
