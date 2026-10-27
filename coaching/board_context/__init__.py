"""Stage 1 — board context: position evidence, legality and replayable PVs.

Owns observation only. It must not select a lesson, generate coach prose,
write to SQLite or determine whether feedback is correct.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BoardEvidence:
    fen: str
    root_uci: str
    root_san: str
    legal: bool
    continuation_uci: tuple[str, ...]
    continuation_san: tuple[str, ...]
    truncated: bool
    error: Optional[str] = None


def observe(fen: str, root_uci: str, pv_uci=None, *, max_plies=12) -> BoardEvidence:
    """Board-verify a candidate root and every returned continuation ply.

    Does not call the engine or infer tactical significance. Replays only the
    legal prefix and records when the supplied continuation is truncated.
    """
    import json
    import chess
    board = chess.Board(fen)
    try:
        root = chess.Move.from_uci(root_uci)
    except (ValueError, TypeError):
        root = None
    if root not in board.legal_moves:
        return BoardEvidence(fen, str(root_uci), '', False, (), (), False, 'Illegal root move')
    root_san = board.san(root)
    if isinstance(pv_uci, str):
        try:
            pv_uci = json.loads(pv_uci)
        except (ValueError, TypeError):
            pv_uci = []
    pv_uci = pv_uci or [root_uci]
    from .pv_reasoning import legal_pv
    moves = legal_pv(board, pv_uci, first_move=root, max_plies=max_plies)
    if not moves:
        moves = [root]
    replay = board.copy(stack=False)
    sans = []
    for move in moves:
        sans.append(replay.san(move))
        replay.push(move)
    return BoardEvidence(fen, root_uci, root_san, True,
                         tuple(m.uci() for m in moves), tuple(sans),
                         len(pv_uci) > len(moves))
