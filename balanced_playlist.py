"""Diverse, randomized ordering of the full training playlist.

A random candidate window favors underrepresented openings and primary motifs
and discourages immediate repeats. Every input position appears exactly once.
Nothing is persisted here: the trainer pins the generated ID order for a session.
"""
from __future__ import annotations

from collections import Counter, deque
import random


def balanced_playlist_order(items, *, rng=None, lookahead=64):
    """Return a fresh balanced shuffle, without removing or duplicating positions.

    Each item can be a dict or a sqlite3.Row and should contain `opening_key`,
    `motif_key`, and `learning_mode`. Unknown values are grouped consistently.
    An injectable RNG makes the algorithm deterministically testable.
    """
    rows = list(items)
    if len(rows) < 2:
        return rows
    if rng is None:
        rng = random.Random()
    pending = list(rows)
    rng.shuffle(pending)
    window = [pending.pop() for _ in range(min(max(1, int(lookahead)), len(rows)))]

    def value(row, field):
        try:
            return str(row[field] or 'unclassified').strip().lower() or 'unclassified'
        except (KeyError, IndexError):
            return 'unclassified'

    fields = ('opening_key', 'motif_key', 'learning_mode')
    weights = (1.0, 1.25, 0.45)
    population = [Counter(value(row, field) for row in rows) for field in fields]
    used = [Counter() for _ in fields]
    recent = deque(maxlen=6)
    ordered = []
    n = len(rows)
    while window:
        step = len(ordered)
        best_index, best_score = None, float('-inf')
        for index, row in enumerate(window):
            keys = tuple(value(row, field) for field in fields)
            score = rng.random() * 0.32
            for dimension, key in enumerate(keys):
                # Bring underrepresented categories closer to their expected
                # cumulative share, rather than exhausting rare groups early.
                expected = (step + 1) * population[dimension][key] / n
                score += weights[dimension] * max(-2.5, min(2.5, expected - used[dimension][key]))
            for distance, former in enumerate(reversed(recent), start=1):
                if keys[0] == former[0]:
                    score -= 1.8 / distance
                if keys[1] == former[1]:
                    score -= 2.1 / distance
                if keys[2] == former[2]:
                    score -= 0.35 / distance
            if score > best_score:
                best_index, best_score = index, score
        chosen = window.pop(best_index)
        keys = tuple(value(chosen, field) for field in fields)
        ordered.append(chosen)
        for dimension, key in enumerate(keys):
            used[dimension][key] += 1
        recent.append(keys)
        if pending:
            window.append(pending.pop())
    return ordered
