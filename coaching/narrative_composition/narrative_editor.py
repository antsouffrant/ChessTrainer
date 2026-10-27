"""Human-facing chess coaching language, deliberately separate from motif classification.

The upstream classifiers collect evidence.  This module edits that evidence into
one central takeaway, avoiding labels, repeated outcome claims, and descriptions
of how the engine or classifier arrived at a decision.

This is deliberately pure Python: it can be tested without a chess engine.
"""
from __future__ import annotations

import re


def mate_explanation(best: str, played: str | None, *, mate_in: int | None = None,
                     final_move: str | None = None, immediate: bool = False,
                     threatened_mate: bool = False, verified: bool = False) -> str:
    """Say the mating outcome exactly once and optionally contrast the game move.

    A PV ending in mate is NOT proof of a forced mate without a mating score.
    """
    if immediate:
        lead = f'{best} is checkmate.'
    elif threatened_mate:
        lead = f'{best} stops the mating attack.'
    elif verified and mate_in and mate_in > 0:
        lead = f'{best} forces mate in {mate_in}'
        if final_move:
            lead += f', finishing with {final_move}'
        lead += '.'
    elif final_move:
        lead = f'{best} leads to {final_move} in the analyzed line.'
    else:
        lead = f'{best} is the mating move.'
    if played and played != best:
        if threatened_mate:
            return lead + f' In the game, {played} allowed the attack to continue.'
        if immediate:
            return lead + f' In the game, {played} missed the finish.'
        return lead + f' In the game, {played} missed that opportunity.'
    return lead


def polish_comparison(text: str, *, best: str = '', played: str = '') -> str:
    """Edit existing verified evidence, NOT invent an explanation of its cause."""
    text = ' '.join((text or '').split())
    if not text:
        return ''
    # Where both moves share an initial action, name the actual difference.
    # These rewrites only operate on evidence whose underlying geometry/PV
    # comparison has already been checked by the calling analyzer.
    capture = re.search(
        r'^([\w+#=x-]+) and ([\w+#=x-]+) both capture the opponent’s '
        r'(\w+) on ([a-h][1-8]), but \1 keeps your pawn on ([a-h][1-8]) protected\. '
        r'In the game, \2 leaves that pawn hanging\.$', text)
    if capture:
        engine, actual, victim, target, pawn = capture.groups()
        return (f'Both {engine} and {actual} capture the {victim} on {target}, '
                f'but only {engine} keeps your pawn on {pawn} defended. '
                f'After {actual}, it is hanging.')
    if text.startswith('The best continuation trades off the queens while retaining a material lead.'):
        if best and played:
            return (f'{best} leads to a queen trade while keeping your material advantage. '
                    f'After {played}, the queens stay on the board.')
        return f'{best} trades queens while keeping your material advantage.' if best else text
    if text.startswith('The best continuation advances your passed pawn to '):
        sq = re.search(r'passed pawn to ([a-h][1-8])', text)
        if sq and best:
            return (f'{best} helps your passed pawn reach {sq.group(1)}; '
                    f'the line after {played} does not advance it as far.' if played else
                    f'{best} helps your passed pawn reach {sq.group(1)}.')
    # These prefixes convey provenance rather than chess understanding.
    edits = (
        ('The key payoff comes later: ', 'The follow-up '),
        (' in the analyzed continuation', ''),
        (' in the best-move line', ''),
        ('The analyzed reply ', ''),
        ('In the best continuation, ', 'After ' + best + ', ' if best else 'After the better move, '),
        ('In the played-move continuation, ', 'After ' + played + ', ' if played else 'After the played move, '),
        ('The best continuation ', 'The continuation '),
        ('The stronger continuation ', 'The continuation '),
        ('The best move ', best + ' ' if best else 'The move '),
    )
    for old, new in edits:
        text = text.replace(old, new)
    text = text.replace('The best analyzed continuation ends in checkmate with ', 'The line ends with ')
    # Connect a delayed payoff to the player's ROOT decision rather than
    # sounding as if the follow-up move were itself the recommended answer.
    if best:
        match = re.match(r'(?:The follow-up |After the check, |In the continuation, )'
                         r'([^ ]+) (captures|creates) (.+)', text)
        if match:
            later, verb, rest = match.groups()
            if verb == 'captures':
                text = f'{best} sets up {later}, which captures {rest}'
            else:
                text = f'{best} sets up {later}, which creates {rest}'
        elif text.startswith('The continuation '):
            text = f'After {best}, the continuation ' + text[len('The continuation '):]
    text = text.replace('The distraction makes the later capture possible in the best-move line.', '')
    text = text.replace('providing the material payoff shown at the end of the analyzed line',
                        'leaving a material gain')
    text = text.replace('leaving a better material result than the game continuation',
                        'leaving you ahead in material compared with the played move')
    text = text.replace('This is a concrete change in the squares your piece influences.', '')
    # Defensive phrasing should be plain chess language.
    text = text.replace('under attack and undefended', 'hanging')
    text = re.sub(r'\s+([.,;:])', r'\1', text)
    text = re.sub(r'\.{2,}', '.', text)
    return ' '.join(text.split()).strip()


def concise(parts: list[str], *, max_sentences: int = 2, max_words: int = 75) -> str:
    """Prevent several templates from restating the same result.

    Keep one explanation and at most one nonduplicative follow-up.  Sentence
    boundaries after SAN (e.g., `Bb8`) are not changed.
    """
    output = []
    seen = set()
    mate_already = False
    words = 0
    for raw in parts:
        fact = ' '.join((raw or '').split()).strip()
        if not fact:
            continue
        normalized = re.sub(r'[^a-z0-9]+', ' ', fact.lower()).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        is_mate = bool(re.search(r'\b(mate in \d+|forced mate|checkmate|forces mate)\b|#', fact.lower()))
        if mate_already and is_mate:
            continue
        new_words = len(fact.split())
        if output and (len(output) >= max_sentences or words + new_words > max_words):
            break
        output.append(fact)
        words += new_words
        mate_already |= is_mate
    return ' '.join(output)
