"""Evidence-weighted relevance for the *decision*, not the entire board.

A motif is useful when it connects the previous move (context), the
immediate problem (prompt), and the chosen response.  An incidental tactic
several moves down a sampled PV is intentionally weaker evidence.  This is a
pure scorer: it never substitutes chess geometry or engine evaluation.
"""
from __future__ import annotations

# A threat may be answered by a different kind of move. These are *related*
# concepts, not claims that an attack or a defensive technique occurred.
PROMPT_RELATIONS = {
    'threat_awareness': {'defensive_resource', 'counterattack', 'simplification',
                         'loose_piece_awareness', 'king_safety'},
    'loose_piece_awareness': {'defensive_resource', 'loose_piece_awareness',
                              'counterattack', 'simplification'},
    'king_safety': {'mate_defense', 'king_safety', 'defensive_resource',
                    'simplification', 'counterattack'},
    'pin': {'pin', 'mating_net', 'tactical_combination'},
}


def select_relevant_primary(labels, context, *, original_choice=None,
                            forced_choice=None, immediate_choice=None,
                            pv_choice=None, pv_ply=None):
    """Return (primary motif key, per-motif relevance) from verified evidence.

    Context and prompt alone cannot establish a motif. Its best-move response,
    a near-term supported continuation, or an immediate rooted tactic must
    confirm it. Scores measure relevance *within this set of candidate labels*,
    not an absolute probability of correctness.
    """
    keys = {label.key for label in labels}
    if forced_choice in keys:
        return forced_choice, {forced_choice: 1.0}

    context_keys = set(context.get('context_motifs') or [])
    prompt_keys = set(context.get('prompt_motifs') or [])
    response_keys = set(context.get('response_motifs') or [])
    verified_pin = bool(context.get('pin_capture_refutations'))
    discovered_unique = bool(context.get('discovered_unique_lines'))
    discovered_reply = bool(context.get('discovered_reply_checks'))
    discovered_check = any(d.get('kind') == 'discovered_check'
                           for d in context.get('discovered_unique_lines') or [])
    shared_threat = set(context.get('played_ignores') or []) & set(context.get('best_neutralizes') or [])
    played_failed = bool(shared_threat)
    immediate_recapture = bool(context.get('best_recaptures'))
    threat_removed = bool(context.get('best_takes_last_piece') and context.get('new_pressure'))

    near_pv = pv_ply is None or 1 <= pv_ply <= 4
    scores = {}
    for label in labels:
        key = label.key
        if key == 'calculation':
            continue
        immediate = key == immediate_choice
        response = key in response_keys
        pv_supported = key == pv_choice and near_pv
        contrast = (played_failed and key in {'loose_piece_awareness',
                    'threat_awareness', 'defensive_resource', 'counterattack',
                    'simplification', 'king_safety'})
        if key == 'pin' and verified_pin:
            response = True
            contrast = True  # illegal apparent capture is a concrete refutation
        if key == 'discovered_attack':
            # A revelation that the played move also creates cannot explain
            # the evaluation difference. Only differential evidence counts.
            # Quiet geometric discoveries remain supporting evidence until
            # an opponent reply or near-term continuation demonstrates their
            # effect. Discovered *checks* force an immediate king response.
            response = discovered_unique and (discovered_check or discovered_reply)
            contrast = discovered_unique and discovered_reply
            if not discovered_unique:
                immediate = False
                pv_supported = False
        # A label seen only in the predecessor or far along a PV does not own a
        # lesson until its connection to this decision is independently shown.
        if not (response or immediate or pv_supported or contrast):
            continue
        score = 0.0
        if key in context_keys:
            score += 0.12
        if key in prompt_keys:
            score += 0.19
        if any(key in PROMPT_RELATIONS.get(prompt, ()) for prompt in prompt_keys):
            score += 0.10
        if response:
            score += 0.35
        if immediate:
            score += 0.27
        if pv_supported:
            score += 0.23 if pv_ply is None else 0.23 * max(0.20, 1 - (pv_ply - 1) / 5)
        if contrast:
            score += 0.28
        # Same-square causation is stronger than lexical similarity: the
        # recommended answer and the inferior move treat the identical
        # newly threatened piece differently.
        if shared_threat and key in {'loose_piece_awareness',
                'threat_awareness', 'defensive_resource', 'counterattack'}:
            score += 0.18
        if immediate_recapture and key in {'missed_capture', 'simplification'}:
            score += 0.19
        if threat_removed and key in {'defensive_resource', 'missed_capture'}:
            score += 0.18
        if key == original_choice:
            score += 0.055  # only a tiebreak; never rescue an unsupported label
        # Confidence is a weak tiebreaker, not a substitute for causal evidence.
        score += min(0.09, max(0.0, getattr(label, 'confidence', 0.0)) * 0.09)
        scores[key] = round(score, 4)

    if scores:
        # A response supported by the board but not by the opponent's last
        # move can still be relevant (e.g., a quiet move that wins material).
        winner = max(scores, key=lambda key: scores[key])
        if scores[winner] >= 0.30:
            return winner, scores
    return 'calculation', scores
