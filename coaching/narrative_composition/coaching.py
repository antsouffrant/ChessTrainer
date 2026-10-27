"""The v35 public coaching-copy interface.

Pre-solve guidance comes from board context; post-solve explanation comes
from the six-stage decision-finding pipeline. Historical v34 prose remains in
the SQLite model snapshots/feedback ledger, not in the active code path.
"""
from __future__ import annotations

from coaching.coaching_refresh.version import COACHING_VERSION
from coaching.board_context.presolve_prompt import prompt_for_position
from coaching.narrative_composition.decision_pipeline import coach_decision
from coaching.board_context.decision_evidence import branch_evidence


def generate_coaching_text(**kwargs) -> tuple[str, str]:
    best_uci = kwargs['best_move_uci']
    best_san = kwargs.get('best_move_san') or best_uci
    motif_key = getattr(kwargs.get('taxonomy_path'), 'motif_key', None) or ''
    prompt = prompt_for_position(
        fen=kwargs.get('fen', ''), category=kwargs.get('category', ''), motif_key=motif_key,
        previous_fen=kwargs.get('previous_fen'),opponent_move_uci=kwargs.get('opponent_move_uci'),
        best_move_uci=best_uci,played_move_uci=kwargs.get('played_move_uci'))
    row = dict(kwargs, motif_key=motif_key)
    attempt = {'move_uci': best_uci, 'move_san': best_san, 'correct': 1}
    summary = coach_decision(row, attempt, correct=True,
                             branch=branch_evidence(row, best_uci, attempt),
                             motif_key=motif_key)
    return prompt, summary['text']
