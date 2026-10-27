"""Stage 4: compose a brief *explanation* or a contrasting *learning* card.

At most two causal sentences. A saved engine PV is available separately on
the board; it is not an acceptable surrogate for a chess lesson.
"""
from __future__ import annotations
import re
from coaching.conceptual_understanding.decision_comparator import DecisionFinding


def _effect(event):
    if not event:
        return ''
    text=' '.join(event.text.rstrip('.').split())
    san=event.san.strip()
    if san and text.startswith(san):
        text=text[len(san):].strip(' ,')
    return text


def _sentence(s):
    s=' '.join(str(s or '').split()).rstrip(' .')
    if not s: return ''
    # Pawn SAN begins with a lowercase file letter (dxe5, e4). Keep it exact.
    if re.match(r'^[a-h](?:x|[1-8])',s):
        return s+'.'
    return s[0].upper()+s[1:]+'.'


def compose_finding(f:DecisionFinding):
    move=f.root_san
    main=f.main_event
    if f.purpose=='explanation':
        if main is None:
            return _sentence(f'{move} is the accepted move, but the saved evidence does not establish its main idea')
        effect=_effect(main)
        if main.ply==0:
            text=_sentence(f'{move} {effect}')
        elif main.ply%2==0:
            text=_sentence(f'{move} sets up {main.san}, which {effect}')
        else:
            # A required defensive reply is an illustration, not a claim
            # that the choice has a unique forced continuation.
            text=_sentence(f'After {move}, the saved line includes {main.san}, which {effect}')
        # A meaningful second sentence needs distinct supported information,
        # not another ply of Stockfish narration.
        support=f.supporting_event
        if support and support.ply==0 and support.kind not in {'check','check_evasion','exchange',main.kind}:
            extra=_effect(support)
            if extra and len(text.split())+len(extra.split())<42:
                text+=' '+_sentence(f'The move also {extra}' if support.ply==0 else
                                     f'The saved follow-up {support.san} {extra}')
        return text
    # Learning speaks about the candidate's failure, never praises a move's
    # surface feature before revealing its refutation.
    if main is None:
        if f.better_event and f.best_san and f.best_san!=move:
            e=f.better_event
            if e.ply==0:
                return _sentence(f'{move} misses {f.best_san}, which {_effect(e)}')
            if e.ply%2==0:
                return _sentence(f'{move} misses {f.best_san}; the saved line uses {e.san}, which {_effect(e)}')
        if f.best_san and f.best_san!=move:
            return _sentence(f'{move} misses the stronger {f.best_san}; the saved variation does not establish a specific refutation')
        return _sentence(f'The saved variation does not establish why {move} is inferior')
    effect=_effect(main)
    reply=main.san or f.opponent_reply or ''
    if main.ply==1:
        text=_sentence(f'{move} allows {reply}, which {effect}')
    else:
        text=_sentence(f'In the saved line after {move}, {reply} {effect}')
    # Contrast answers *what to learn*, without presenting the best move as
    # automatically preventing a tactic unless the comparison proves it.
    if f.best_san and f.best_san!=move and len(text.split())<30:
        text+=f' Compare this with {f.best_san}.'
    return text
