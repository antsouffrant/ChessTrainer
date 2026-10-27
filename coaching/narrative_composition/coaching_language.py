"""Shared post-solve wording for demonstrated game consequences.

Keep board evidence in tactical detectors, and language here. A saved PV
shows a possible/best analyzed continuation, not a proof across all replies.
"""
from __future__ import annotations


def game_continuation(played_san, reply_san, outcome, *, ply=1, alternative=False, preceding=()):
    """Explain that a game choice *allows* a demonstrated opponent response."""
    played = str(played_san or 'the move')
    reply = str(reply_san or 'the reply')
    outcome = str(outcome or 'improve the position').rstrip('.')
    if alternative:
        preface = f'The alternative {played}'
    else:
        preface = f'In the game you played {played}'
    if ply == 1:
        return f'{preface}, allowing {reply} to {outcome}.'
    # A sampled engine line demonstrates a possible reply, not inevitability.
    # Name a relevant intermediate move when one was actually saved; never
    # expose the engine's analysis process as the explanation itself.
    middle = [str(move) for move in preceding if move]
    if middle:
        prefix = ', then '.join(middle[:2])
        return f'{preface}. After {prefix}, your opponent can {outcome} with {reply}.'
    return f'{preface}. Your opponent can {outcome} with {reply}.'
