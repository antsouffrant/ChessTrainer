"""Versioned coaching paths: context -> optional move type -> canonical motif.

Legacy detector keys are inputs, not the public curriculum.  Converting those
keys is deterministic and deliberately independent of the user's chess engine.
Chess evidence / primary selection is handled by ``normalize_learning_labels``;
context never restricts which tactics and strategies can compete.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

TAXONOMY_VERSION = '3.1-blocking-distinct-motifs'
CONTEXTS = {'attack': 'Attacking Plans', 'defend': 'Defensive Resources'}
MOVE_TYPES = {'tactical': 'Tactical Calculation', 'strategic': 'Strategic Comprehension'}

ATTACK_GENERAL = frozenset({
    'capture_loose_piece', 'hanging_piece', 'piece_coordination',
    'piece_activity', 'pawn_break', 'initiative', 'mate_threat', 'missed_capture',
})
DEFEND_GENERAL = frozenset({
    'dont_hang_pieces', 'loose_piece_awareness', 'mate_defense',
    'lost_material', 'counterattack', 'threat_awareness',
})
TACTICAL = frozenset({
    'mating_net', 'fork', 'pin', 'skewer', 'discovered_attack', 'deflection',
    'removal_of_defender', 'trapped_piece', 'material_sacrifice',
    'promotion_tactic', 'overloaded_defender', 'blocking',
})
STRATEGIC = frozenset({
    'simplification', 'space_advantage', 'king_safety', 'king_activity',
    'opposition_zugzwang', 'vacating_squares', 'passed_pawn', 'pawn_structure',
})

# Old detectors remain available as inputs. Retired curriculum keys stay in
# SQLite for historical feedback, without appearing as new primary lessons.
LEGACY_MOTIF_MAP = {
    'back_rank_mate': 'mating_net',
    'tactical_combination': None,  # too broad to assert a particular tactic
    'exchange_sacrifice': 'material_sacrifice',
    'exchange': 'simplification',
    'piece_development': 'piece_activity',
    'attack_building': 'initiative',
    'defensive_resource': None,  # context, never a primary leaf
    'calculation': None,  # calculation is a process, never an invented tactic
    'endgame_precision': None,  # exact WDL change belongs in the outcome fallback
}

EVALUATION_OUTCOMES = {
    'evaluation_win_to_loss': 'Winning to Losing Position',
    'evaluation_win_to_draw': 'Winning to Drawn Position',
    'evaluation_draw_to_loss': 'Drawn to Losing Position',
    'evaluation_lost_advantage': 'Lost Advantage',
    'evaluation_missed_opportunity': 'Missed Winning Opportunity',
    'evaluation_change': 'Evaluation Swing',
}
CANONICAL_KEYS = ATTACK_GENERAL | DEFEND_GENERAL | TACTICAL | STRATEGIC | frozenset(EVALUATION_OUTCOMES)
RETIRED_KEYS = frozenset(key for key in LEGACY_MOTIF_MAP if key not in CANONICAL_KEYS)
# General themes that may legitimately be taught alone when they have their own
# supported observation. Context labels and detection processes cannot.
WEAK_GENERAL = frozenset({'threat_awareness', 'missed_capture', 'piece_activity', 'initiative', 'lost_material', 'king_safety'})


def canonical_motif_key(key):
    if key in LEGACY_MOTIF_MAP:
        return LEGACY_MOTIF_MAP[key]
    return key


def _read(row, field, default=None):
    try:
        return row[field]
    except (KeyError, TypeError, IndexError):
        return default


def _band(cp, mate):
    if mate is not None:
        return 'win' if int(mate) > 0 else 'loss'
    if cp is None:
        return None
    cp = int(cp)
    return 'win' if cp >= 180 else 'loss' if cp <= -180 else 'draw'


def evaluation_outcome_key(row):
    """Use stored user-POV scores; never infer a tactic from evaluation alone."""
    before = _band(_read(row, 'eval_before_cp'), _read(row, 'mate_before'))
    after = _band(_read(row, 'eval_after_cp'), _read(row, 'mate_after'))
    transitions = {
        ('win', 'loss'): 'evaluation_win_to_loss',
        ('win', 'draw'): 'evaluation_win_to_draw',
        ('draw', 'loss'): 'evaluation_draw_to_loss',
    }
    if (before, after) in transitions:
        return transitions[before, after]
    if before == 'win' and after == 'win':
        return 'evaluation_lost_advantage'
    if before == 'draw' and after == 'draw':
        return 'evaluation_change'
    return 'evaluation_change'


@dataclass
class CanonicalLearningLabel:
    key: str
    confidence: float
    evidence: str
    is_primary: bool = False


def normalize_learning_labels(labels, row):
    """Merge legacy motifs, search *all* supported tactics/strategies.

    Evidence supplied by the existing causal classifier is required. Broad
    fallback labels can be displaced by sufficiently strong, near-term concrete
    candidates regardless of attack/defend context. Never transform a generic
    'tactical combination' into an unsupported named tactic.
    """
    normalized = {}
    for item in labels:
        key = canonical_motif_key(item.key)
        if key not in CANONICAL_KEYS or key in EVALUATION_OUTCOMES:
            continue
        candidate = CanonicalLearningLabel(key, item.confidence, item.evidence, False)
        old = normalized.get(key)
        if old is None or candidate.confidence > old.confidence:
            normalized[key] = candidate
    original_key = next((canonical_motif_key(x.key) for x in labels if x.is_primary), None)
    original = normalized.get(original_key)
    # Only replace a genuinely broad primary when a concrete alternative is
    # independently supported. This retains successful free captures/exchanges.
    primary = original
    if primary is None or primary.key in WEAK_GENERAL:
        specific = [item for item in normalized.values()
                    if item.key in TACTICAL | STRATEGIC
                    and item.confidence >= .76]
        if specific:
            primary = max(specific, key=lambda x: (x.confidence, x.key))
        else:
            # A general attack/defense motif can still be the concrete lesson.
            # Search across both contexts rather than assuming that the first
            # defensive finding limits all subsequent candidates.
            concrete_general = [item for item in normalized.values()
                if item.key in (ATTACK_GENERAL | DEFEND_GENERAL) - WEAK_GENERAL
                and item.confidence >= .78]
            if concrete_general:
                best_general = max(concrete_general, key=lambda x: (x.confidence, x.key))
                if primary is None or best_general.confidence >= primary.confidence + .07:
                    primary = best_general
    if primary is None:
        key = evaluation_outcome_key(row)
        primary = CanonicalLearningLabel(key, .55, 'Saved Stockfish evaluation change; no sufficiently supported motif.')
        normalized[key] = primary
    for item in normalized.values():
        item.is_primary = item.key == primary.key
    return sorted(normalized.values(), key=lambda x: (not x.is_primary, -x.confidence, x.key))


DEFENSIVE_PURPOSE = DEFEND_GENERAL | frozenset({'king_safety'})
ATTACKING_PURPOSE = ATTACK_GENERAL | frozenset({'mating_net', 'material_sacrifice', 'promotion_tactic'})


@dataclass(frozen=True)
class MotifPath:
    context_key: str
    move_type_key: str | None
    motif_key: str
    confidence: float
    evidence: str

    def serialize(self, names=None):
        names = names or {}
        nodes = [{'key': self.context_key, 'name': CONTEXTS[self.context_key], 'level': 'context'}]
        if self.move_type_key:
            nodes.append({'key': self.move_type_key, 'name': MOVE_TYPES[self.move_type_key], 'level': 'move_type'})
        name = names.get(self.motif_key, EVALUATION_OUTCOMES.get(self.motif_key,
                                  self.motif_key.replace('_', ' ').title()))
        nodes.append({'key': self.motif_key, 'name': name, 'level': 'motif'})
        return {'context_key': self.context_key, 'context_name': CONTEXTS[self.context_key],
                'move_type_key': self.move_type_key, 'move_type_name': MOVE_TYPES.get(self.move_type_key),
                'motif_key': self.motif_key, 'motif_name': name, 'confidence': self.confidence,
                'evidence': self.evidence, 'taxonomy_version': TAXONOMY_VERSION, 'levels': nodes}


def assign_taxonomy(primary_key, *, category='', learning_mode='', is_in_check=False,
                    root_best_is_check=False, opponent_reply_wins_material=False,
                    best_move_saves_material=False, strategic_sacrifice=False, confidence=.75):
    key = canonical_motif_key(primary_key)
    if key is None or key not in CANONICAL_KEYS:
        raise ValueError('A canonical learning motif or evaluation outcome is required')
    attack, defend, reasons = 0., 0., []
    if key in ATTACKING_PURPOSE:
        attack += 3
        reasons.append('The supported idea creates an attacking opportunity.')
    if key in DEFENSIVE_PURPOSE:
        defend += 3
        reasons.append('The supported idea answers an opponent threat.')
    if is_in_check:
        defend += 4
        reasons.append('The solver must answer check.')
    if category == 'allowed_checkmate':
        defend += 3
    if category == 'missed_checkmate':
        attack += 3
    if best_move_saves_material and key != 'material_sacrifice':
        defend += 2
        reasons.append('The better move prevents a material loss.')
    if key == 'material_sacrifice' and strategic_sacrifice:
        # A verified defensive investment can preserve the position instead
        # of launching an attacking combination. The sacrificed material is
        # still real, but the strategic objective belongs to defense.
        defend += 6
        reasons.append('The supported material investment preserves the position against a worse continuation.')
    if opponent_reply_wins_material:
        defend += 1
    if root_best_is_check and not is_in_check:
        attack += 1
    # Evaluative errors call for defense when the game move converts an
    # advantage into a draw/loss, even when no particular tactic was found.
    if key.startswith('evaluation_'):
        defend += 2
        reasons.append('The played continuation deteriorates the saved evaluation.')
    if attack == defend == 0:
        attack = 1
        reasons.append('No specific defensive obligation has been established.')
    context = 'defend' if defend > attack else 'attack'
    move_type = ('strategic' if key == 'material_sacrifice' and strategic_sacrifice
                 else 'tactical' if key in TACTICAL
                 else 'strategic' if key in STRATEGIC else None)
    certainty = min(.98, max(.45, float(confidence)))
    if abs(attack - defend) < 2:
        certainty = min(certainty, .68)
    return MotifPath(context, move_type, key, round(certainty, 3), ' '.join(reasons))


def taxonomy_from_rows(row, primary_key, *, confidence=.75):
    key = canonical_motif_key(primary_key)
    if key is None:
        key = evaluation_outcome_key(row)
    return assign_taxonomy(key, category=_read(row, 'category') or '',
                           learning_mode=_read(row, 'learning_mode') or '',
                           confidence=confidence)


def save_taxonomy(conn, position_id, row, primary_key, *, confidence=.75,
                  is_in_check=False, root_best_is_check=False,
                  best_move_saves_material=False, strategic_sacrifice=False):
    key = canonical_motif_key(primary_key) or evaluation_outcome_key(row)
    path = assign_taxonomy(key, category=_read(row, 'category') or '',
                           learning_mode=_read(row, 'learning_mode') or '',
                           confidence=confidence, is_in_check=is_in_check,
                           root_best_is_check=root_best_is_check,
                           best_move_saves_material=best_move_saves_material,
                           strategic_sacrifice=strategic_sacrifice)
    conn.execute('''
        INSERT INTO position_motif_taxonomy
            (position_id, context_key, move_type_key, motif_key, confidence, evidence, taxonomy_version)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(position_id) DO UPDATE SET
            context_key=excluded.context_key, move_type_key=excluded.move_type_key,
            motif_key=excluded.motif_key, confidence=excluded.confidence,
            evidence=excluded.evidence, taxonomy_version=excluded.taxonomy_version,
            updated_at=CURRENT_TIMESTAMP
    ''', (position_id, path.context_key, path.move_type_key, path.motif_key,
          path.confidence, path.evidence, TAXONOMY_VERSION))
    return path


def validate_taxonomy(concept_keys):
    missing = (CANONICAL_KEYS | RETIRED_KEYS) - set(concept_keys)
    if missing:
        raise ValueError(f'Unknown taxonomy concepts: {sorted(missing)}')
    if TACTICAL & STRATEGIC:
        raise ValueError('Tactics and strategies overlap')
    return True
