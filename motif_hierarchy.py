"""Curriculum ontology and evidence-aware choice of primary motifs.

Edges point from a specific teaching idea to a broader *learning theme*.
They express pedagogical relationships, not logically necessary chess facts:
a fork can be the concrete way to exploit a threat, but merely detecting
an attack is never evidence of a fork. A node only competes when a separate
chess detector has produced a supported observation.

Keep this independent of python-chess so we can test ontology integrity and
ranking even where the engine dependencies are unavailable.
"""
from __future__ import annotations

from functools import lru_cache

ONTOLOGY_VERSION = '1.0'
# Narrow concept -> broader contexts/fallbacks. Multiple parents are valid.
MOTIF_PARENTS = {
    'back_rank_mate': ('mating_net', 'mate_threat'),
    'mating_net': ('mate_threat', 'attack_building'),
    'mate_threat': ('attack_building',),
    'mate_defense': ('king_safety', 'threat_awareness', 'defensive_resource'),
    'fork': ('tactical_combination', 'threat_awareness', 'attack_building'),
    'skewer': ('tactical_combination', 'threat_awareness'),
    'pin': ('tactical_combination', 'piece_coordination'),
    'discovered_attack': ('tactical_combination', 'attack_building'),
    'deflection': ('tactical_combination',),
    'removal_of_defender': ('tactical_combination', 'threat_awareness'),
    'overloaded_defender': ('tactical_combination',),
    'trapped_piece': ('tactical_combination', 'threat_awareness'),
    'exchange_sacrifice': ('material_sacrifice', 'tactical_combination'),
    'material_sacrifice': ('tactical_combination',),
    'capture_loose_piece': ('missed_capture', 'threat_awareness'),
    'hanging_piece': ('missed_capture', 'attack_building'),
    'dont_hang_pieces': ('lost_material', 'threat_awareness'),
    'loose_piece_awareness': ('threat_awareness', 'defensive_resource'),
    'lost_material': ('threat_awareness', 'defensive_resource'),
    'counterattack': ('defensive_resource', 'attack_building'),
    'simplification': ('defensive_resource', 'exchange'),
    'pawn_structure': ('piece_coordination',),
    'pawn_break': ('pawn_structure', 'space_advantage'),
    'piece_development': ('piece_activity',),
    'king_activity': ('piece_activity',),
    'passed_pawn': ('pawn_structure',),
    'opposition_zugzwang': ('king_activity', 'endgame_precision'),
    'endgame_precision': ('threat_awareness',),
    'piece_coordination': ('piece_activity',),
    'attack_building': ('piece_activity',),
    'tactical_combination': ('calculation',),
    'threat_awareness': ('calculation',),
    'defensive_resource': ('calculation',),
}

# Neutral, broad labels should yield to a specific demonstrated reason, not
# to any geometrically plausible motif that happens to be on the board.
BROAD_FALLBACKS = frozenset({
    'defensive_resource', 'threat_awareness', 'attack_building',
    'piece_activity', 'piece_coordination', 'tactical_combination',
    'calculation', 'king_safety', 'missed_capture', 'lost_material',
})


@lru_cache(maxsize=None)
def ancestors(key):
    result = set()
    for parent in MOTIF_PARENTS.get(key, ()):
        if parent == key:
            raise ValueError('cyclic motif hierarchy')
        result.add(parent)
        result.update(ancestors(parent))
    return frozenset(result)


def validate_ontology(concept_keys):
    keys = set(concept_keys)
    missing = {k for k, parents in MOTIF_PARENTS.items() for k in (k, *parents) if k not in keys}
    if missing:
        raise ValueError(f'Unknown motif keys in hierarchy: {sorted(missing)}')
    for key in MOTIF_PARENTS:
        if key in ancestors(key):
            raise ValueError(f'Cycle in motif hierarchy at {key}')
    return True


def choose_specific(primary, supported, *, protected=()):
    """Prefer verified descendants of generic primary labels.

    `supported` contains ONLY separately verified observations. Each value is
    (evidence_strength 0..1, distance_in_plies), not catalogue priority.
    Proximity wins ties; a distant candidate cannot displace a supported
    immediate finding just because its motif has a specific name.
    """
    if not primary or primary in protected or primary not in BROAD_FALLBACKS:
        return primary
    candidates = []
    for key, (strength, ply) in supported.items():
        if key == primary or ply > 3 or strength < 0.72:
            continue
        # Only descendants of the current parent, or directly verified
        # concrete moves replacing a neutral fallback, can displace it.
        if primary not in ancestors(key) and primary != 'defensive_resource':
            continue
        if key in BROAD_FALLBACKS:
            continue
        candidates.append((strength - 0.09 * ply, -ply, len(ancestors(key)), key))
    return max(candidates)[-1] if candidates else primary
