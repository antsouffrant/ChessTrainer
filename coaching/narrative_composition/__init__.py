"""Stage 4 — narration: solving explanations, learning cards and session recap.

This stage owns user-visible chess prose. It must not quietly rewrite board
facts, alter motif classifications or write immutable feedback history.
Interactive free-form coach helpers are grouped here but remain independent
from the deterministic post-solve narration path.
"""


def explain_position(**kwargs):
    from .coaching import generate_coaching_text
    return generate_coaching_text(**kwargs)


def explain_continuation(row, attempt, best_san, *, saved_explanation=''):
    from .continuation_coach import explain_attempt
    return explain_attempt(row, attempt, best_san, saved_explanation=saved_explanation)
