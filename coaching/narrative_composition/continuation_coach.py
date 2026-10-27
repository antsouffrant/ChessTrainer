"""Stage-4 continuation facade; evidence selection belongs to Stage 1."""
from coaching.board_context.decision_evidence import branch_evidence, main_fact as _main_fact


def _effects(ply):
    return [e for e in (ply.get('effects') or []) if isinstance(e,dict)] if isinstance(ply,dict) else []

def _checking_cycle(branch):
    """Classify observed recurring checks; never infer a forced perpetual.

    Threefold uses exact side/castling/en-passant board identities. The
    initial position counts, but hypothetical future Stockfish lines do not.
    Older evidence without per-ply board identities is not proof of a cycle.
    """
    if not isinstance(branch, dict): return None
    plies = branch.get('plies') or []
    start = branch.get('start_fen')
    if not start or len(plies) < 5: return None
    key = lambda fen: tuple(str(fen).split()[:4]) if fen else ()
    seen = {key(start):1}
    checks = [0, 0]
    repeats = False
    threefold = False
    for i, ply in enumerate(plies):
        # Board-event check markers are mover-relative and verified by replay.
        if any(e.get('kind') in ('check','discovered_check')
               for e in _effects(ply)):
            checks[i % 2] += 1
        position = key(ply.get('fen_after'))
        if len(position) != 4: return None
        seen[position] = seen.get(position, 0) + 1
        if seen[position] >= 2: repeats = True
        if seen[position] >= 3: threefold = True
    if max(checks) < 3: return None
    if threefold:
        return ('The saved continuation repeats a position three times during '
                'a series of checks; a draw by threefold repetition can be claimed.')
    if repeats:
        return ('The checking sequence returns to an earlier position, '
                'suggesting a perpetual-check possibility; this saved line '
                'does not establish a forced draw.')
    return ('This line contains a sequence of checks, but no repeated position '
            'has been verified; perpetual check is not established.')




def explain_attempt(row, attempt, best_san, *, saved_explanation=''):
    """Compose a purpose-specific lesson for one legally verified root move."""
    from coaching.board_context.decision_evidence import field
    from coaching.narrative_composition.decision_pipeline import coach_decision
    move=field(attempt, 'move_uci')
    branch=branch_evidence(row,move,attempt)
    # Never re-use previous-model narrative text: it belongs to its original
    # versioned snapshot and must not be presented as a new explanation.
    return coach_decision(row,attempt,correct=bool(field(attempt,'correct')),
                          branch=branch,motif_key=field(row,'motif_key'))
