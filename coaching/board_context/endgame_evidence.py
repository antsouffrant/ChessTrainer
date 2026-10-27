"""Optional *exact* endgame verdicts via local Syzygy tables.

Stockfish centipawn scores are estimates, not solved endgame proofs. A
Syzygy win/draw/loss verdict is exact for a supported legal <=7-piece board.
Set CHESS_SYZYGY_PATH to a directory containing the requisite table files.
No tablebase files are distributed with the trainer.
"""
from __future__ import annotations
import os
import chess


def exact_outcome(board: chess.Board):
    """Result for side to move: ('win'|'draw'|'loss', raw_wdl), else None."""
    path = os.environ.get('CHESS_SYZYGY_PATH', '').strip()
    if not path or len(board.piece_map()) > 7 or not board.is_valid() or board.castling_rights:
        return None
    try:
        import chess.syzygy
        with chess.syzygy.open_tablebase(path) as table:
            wdl = table.probe_wdl(board)
        # WDL +/-1 denotes a cursed win / blessed loss under the 50-move
        # rule, so avoid calling these a proven win or loss.
        return ('win' if wdl == 2 else 'loss' if wdl == -2 else 'draw', wdl)
    except (OSError, ValueError, KeyError, AssertionError):
        return None


def exact_move_contrast(board: chess.Board, best: chess.Move, played: chess.Move):
    """Compare exact outcomes from mover's perspective, if both can be probed."""
    if best not in board.legal_moves or played not in board.legal_moves:
        return None
    results = []
    for move in (best, played):
        child = board.copy(stack=False)
        child.push(move)
        verdict = exact_outcome(child)
        if verdict is None:
            return None
        # Table is from the *replying* side's perspective.
        results.append(-verdict[1])
    def outcome(wdl):
        return 'win' if wdl == 2 else 'loss' if wdl == -2 else 'draw'
    best_wdl, played_wdl = results
    if best_wdl <= played_wdl:
        return None
    return {'best': outcome(best_wdl), 'played': outcome(played_wdl),
            'source': 'Syzygy', 'exact': True}
