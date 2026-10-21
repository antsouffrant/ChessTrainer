"""Evidence-only checking cycles; sampled continuations are not forced outcomes."""

def verified_check_repetition(board, legal_moves):
    """True only when a *played* legal PV repeats a position 3x amid 3 checks
    from one side. The input board has no earlier PGN history, so this is
    intentionally conservative and cannot invent an earlier repetition.
    """
    if len(legal_moves) < 6:
        return False
    replay=board.copy(stack=False)
    checks=[0,0]
    for ply,move in enumerate(legal_moves):
        if move not in replay.legal_moves:
            return False
        replay.push(move)
        if replay.is_check():checks[ply%2]+=1
        if max(checks)>=3 and replay.is_repetition(3):
            return True
    return False
