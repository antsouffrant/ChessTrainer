"""Stockfish-assisted proactive coaching for *already selected* training positions.

Root scores/PVs from Analyze remain authoritative; this pass probes conditional
opponent replies and stores decision-grounded hypotheses for the coach. Engine
lines illustrate credible continuations, not proofs that all defenses fail.
"""
from __future__ import annotations

import json
import hashlib
import chess
import chess.engine
from explanatory_evidence import position_context, board_events
from continuation_refutations import scan_branch

PROACTIVE_VERSION = 1
PROACTIVE_CACHE_SCHEMA = 2  # v90: tie probe reuse to the coaching rule set


def coaching_probe_cache_key(row, settings, engine_name=''):
    """Fingerprint all inputs affecting a bounded Stockfish coaching probe.

    Cached evidence is reusable only for the exact position, candidate lines,
    engine identity and search configuration. Old JSON without this key is
    intentionally recalculated once and then becomes cacheable.
    """
    def field(key):
        try:
            return row[key]
        except (KeyError, IndexError):
            return None

    # A previous ruleset's probe may have different narrative and motif
    # selection semantics, even when its Stockfish depth is unchanged.
    from coaching import COACHING_VERSION
    inputs = {
        'probe_version': PROACTIVE_VERSION,
        'cache_schema': PROACTIVE_CACHE_SCHEMA,
        'coaching_version': COACHING_VERSION,
        'engine': str(engine_name or ''),
        'fen': field('fen'),
        'best_move_uci': field('best_move_uci'),
        'played_move_uci': field('played_move_uci'),
        'eval_before_cp': field('eval_before_cp'),
        'eval_after_cp': field('eval_after_cp'),
        'alternatives': field('alternative_pvs_json'),
        'seconds': float(settings.get('coaching_probe_seconds', 1.2)),
        'multipv': int(settings.get('coaching_probe_variations', 2)),
        'depth': int(settings.get('coaching_probe_depth', 14)),
        'mate_score': int(settings.get('mate_score_cp', 100000)),
        'threads': int(settings.get('analysis_engine_threads', 2)),
        'hash_mb': int(settings.get('analysis_engine_hash_mb', 128)),
    }
    payload = json.dumps(inputs, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def reusable_coaching_probe(row, settings, engine_name=''):
    """Reuse only versioned evidence from an identical completed probe."""
    try:
        raw = row['proactive_coach_json']
    except (KeyError, IndexError):
        return None
    data = decode_probes(raw)
    from coaching import COACHING_VERSION
    if (data and data.get('coaching_version') == COACHING_VERSION
            and data.get('cache_key') == coaching_probe_cache_key(row, settings, engine_name)):
        return data
    return None


def decode_probes(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    from coaching import COACHING_VERSION
    return raw if (isinstance(raw, dict) and raw.get('version') == PROACTIVE_VERSION
                   and raw.get('coaching_version') == COACHING_VERSION
                   and isinstance(raw.get('branches'), list)) else None


# Root-level strategic context is observation only: it proposes questions for
# engine testing, not a tactical/strategic conclusion in its own right.
MATERIAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
            chess.ROOK: 5, chess.QUEEN: 9}


def strategic_context(board):
    """Material, pawn structure, kings and phase in both player perspectives."""
    result = {}
    for name, color in (('training_side', board.turn), ('opponent', not board.turn)):
        counts = {chess.piece_name(kind): len(board.pieces(kind, color))
                  for kind in MATERIAL}
        value = sum(MATERIAL[kind] * len(board.pieces(kind, color)) for kind in MATERIAL)
        nonpawn = sum(MATERIAL[kind] * len(board.pieces(kind, color))
                      for kind in MATERIAL if kind != chess.PAWN)
        pawns_by_file = [len([sq for sq in board.pieces(chess.PAWN, color)
                              if chess.square_file(sq) == file]) for file in range(8)]
        doubled = [chess.FILE_NAMES[file] for file, n in enumerate(pawns_by_file) if n >= 2]
        isolated = [chess.FILE_NAMES[file] for file, n in enumerate(pawns_by_file)
                    if n and not (file > 0 and pawns_by_file[file - 1]
                                  or file < 7 and pawns_by_file[file + 1])]
        passed = []
        for sq in board.pieces(chess.PAWN, color):
            file, rank = chess.square_file(sq), chess.square_rank(sq)
            if not any(abs(chess.square_file(other) - file) <= 1 and
                       (chess.square_rank(other) > rank if color else
                        chess.square_rank(other) < rank)
                       for other in board.pieces(chess.PAWN, not color)):
                passed.append(chess.square_name(sq))
        king = board.king(color)
        center_dist = (min(abs(chess.square_file(king) - file) + abs(chess.square_rank(king) - rank)
                           for file in (3, 4) for rank in (3, 4)) if king is not None else None)
        result[name] = {'counts': counts, 'material': value,
                        'nonpawn_material': nonpawn,
                        'pawn_structure': {'doubled_files': doubled,
                                           'isolated_files': isolated,
                                           'passed_pawns': passed},
                        'king_center_distance': center_dist}
    combined_nonpawn = sum(result[side]['nonpawn_material'] for side in result)
    result['phase'] = ('endgame' if combined_nonpawn <= 15
                       else 'middlegame' if combined_nonpawn <= 45 else 'opening_or_middlegame')
    result['material_balance'] = (result['training_side']['material'] -
                                  result['opponent']['material'])
    return result


def _alternate(row, best):
    """Positive examples compare the correct game move against a saved runner-up."""
    raw = row['alternative_pvs_json']
    try:
        options = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, dict) and option.get('move_uci') != best.uci():
            try:
                return chess.Move.from_uci(option['move_uci'])
            except (KeyError, TypeError, ValueError):
                pass
    return None


def _engine_replies(engine, board, root, *, seconds, multipv, depth, mate_score):
    after = board.copy(stack=False)
    after.push(root)
    if after.is_game_over():
        return []
    limit = chess.engine.Limit(time=max(0.05, seconds), depth=depth or None)
    # Probe from the position AFTER a known root move, so all candidate replies
    # are legal replies to that move, not unrelated alternatives at the root.
    infos = engine.analyse(after, limit, multipv=min(multipv, after.legal_moves.count()))
    if isinstance(infos, dict):
        infos = [infos]
    result = []
    for info in infos:
        pv = list(info.get('pv') or [])
        replay = after.copy(stack=False)
        legal = []
        for move in pv[:9]:
            if move not in replay.legal_moves:
                break
            legal.append(move)
            replay.push(move)
        if not legal:
            continue
        score = info.get('score')
        pov = score.pov(board.turn) if score is not None else None
        cp = pov.score(mate_score=mate_score) if pov is not None else None
        result.append({
            'pv_uci': [root.uci()] + [m.uci() for m in legal],
            'reply_san': after.san(legal[0]),
            'eval_cp': int(cp) if cp is not None else None,
            'mate': pov.mate() if pov is not None else None,
            'depth': info.get('depth'),
        })
    return result


def _best_finding(board, branches, root_loss):
    """Select only demonstrated short-range refutations, never bare geometry.

    Geometric attacks and remote events may be retained as context, but do not
    displace a user-approved simple capture/exchange by themselves.
    """
    if root_loss is None or root_loss < 90:
        return None
    available = []
    for branch in branches:
        for candidate in branch.get('lines', []):
            try:
                move = chess.Move.from_uci(branch['root_uci'])
                findings = scan_branch(board, move, candidate['pv_uci'],
                                       branch=branch['role'], max_threat_ply=2)
            except (ValueError, TypeError, KeyError):
                continue
            for finding in findings:
                if finding.ply > 2 or finding.motif not in {
                    'fork', 'skewer', 'discovered_attack', 'removal_of_defender',
                }:
                    continue
                # A sampled response shows a real opportunity, not a forced
                # win. For negative training, the refutation of the game move
                # is generally most directly connected to the lesson.
                rank = (0 if finding.branch == 'played' else 1, finding.ply)
                available.append((rank, finding))
    if not available:
        return None
    _, finding = min(available, key=lambda entry: entry[0])
    return {'motif': finding.motif, 'role': finding.branch, 'ply': finding.ply,
            'text': finding.text, 'kind': 'demonstrated_refutation'}


def probe_training_position(engine, row, settings):
    """Observe -> hypothesize -> Stockfish-test -> select an evidenced cause.

    No database modifications; safe to execute outside a write transaction.
    Settings apply to this extra coaching pass only, not the cached Analyze
    score, training position, or puzzle acceptance logic.
    """
    board = chess.Board(row['fen'])
    best = chess.Move.from_uci(row['best_move_uci'])
    played = chess.Move.from_uci(row['played_move_uci']) if row['played_move_uci'] else None
    if best not in board.legal_moves:
        raise ValueError('Saved recommended move is illegal at the training position')
    if played not in board.legal_moves:
        played = None
    comparison = played if played and played != best else _alternate(row, best)
    if comparison not in board.legal_moves:
        comparison = None
    candidates = [('best', best)] + ([('played', comparison)] if comparison else [])
    budget = float(settings.get('coaching_probe_seconds', 1.2)) / len(candidates)
    multipv = max(1, min(3, int(settings.get('coaching_probe_variations', 2))))
    depth = max(1, int(settings.get('coaching_probe_depth', 14)))
    mate_score = int(settings.get('mate_score_cp', 100000))
    root_loss = None
    if row['eval_before_cp'] is not None and row['eval_after_cp'] is not None and played != best:
        root_loss = max(0, row['eval_before_cp'] - row['eval_after_cp'])
    elif comparison:
        # Saved alternatives are evaluated during Analyze, not by this probe.
        try:
            alternatives = json.loads(row['alternative_pvs_json'] or '[]')
            root_loss = next((max(0, row['eval_before_cp'] - a['eval_cp'])
                              for a in alternatives if a.get('move_uci') == comparison.uci()
                              and row['eval_before_cp'] is not None and a.get('eval_cp') is not None), None)
        except (ValueError, TypeError):
            pass
    branches = []
    for role, root in candidates:
        replies = _engine_replies(engine, board, root, seconds=budget,
                                  multipv=multipv, depth=depth, mate_score=mate_score)
        first = replies[0] if replies else None
        branches.append({
            'role': role, 'root_uci': root.uci(), 'root_san': board.san(root),
            'observations': board_events(board, root,
                                         first['pv_uci'] if first else [root.uci()]),
            'lines': replies,
        })
    engine_name = getattr(engine, 'id', {}) or {}
    engine_name = engine_name.get('name', '') if isinstance(engine_name, dict) else str(engine_name)
    from coaching import COACHING_VERSION
    return {'version': PROACTIVE_VERSION, 'coaching_version': COACHING_VERSION,
            'cache_key': coaching_probe_cache_key(row, settings, engine_name), 'root_fen': board.fen(),
            'context': position_context(board),
            'strategic_context': strategic_context(board),
            'root_loss_cp': root_loss,
            'branches': branches, 'selection': _best_finding(board, branches, root_loss),
            'method': 'independent_reply_multipv',
            'limits': {'seconds_per_position': float(settings.get('coaching_probe_seconds', 1.2)),
                       'multipv': multipv, 'max_depth': depth}}


def prefer_evidenced_primary(board, labels, raw):
    """Shared classifier bridge for refresh, Analyze and offline replay.

    Only broad/fallback lessons are eligible; the prose selector uses the same
    persisted causal probe. Do not confuse tactical geometry with a verified
    primary motif or change an already specific approved classification.
    """
    data = decode_probes(raw)
    if not data or data.get('root_fen') != board.fen():
        return labels
    finding = data.get('selection')
    if not finding or finding.get('kind') != 'demonstrated_refutation':
        return labels
    from learning import LearningLabel, CONCEPTS
    from motif_hierarchy import BROAD_FALLBACKS, ancestors
    key = finding.get('motif')
    if key not in CONCEPTS:
        return labels
    current = next((x.key for x in labels if x.is_primary), None)
    if current is not None and current not in BROAD_FALLBACKS and current not in ancestors(key):
        return labels
    match = next((x for x in labels if x.key == key), None)
    if match is None:
        match = LearningLabel(key, 0.79, finding.get('text') or '')
        labels.append(match)
    for label in labels:
        label.is_primary = label.key == key
    return labels


def trusted_probe_explanation(board, best, played, raw, existing_text):
    """Prefer new evidence only when the existing sentence is generic.

    This conservative gate protects already-successful concise explanations.
    A selected refutation must describe the current root decision; speculative
    or merely geometrical alternatives are not promoted.
    """
    data = decode_probes(raw)
    if not data or data.get('root_fen') != board.fen() or not data.get('selection'):
        return None
    selection = data['selection']
    if selection.get('kind') != 'demonstrated_refutation':
        return None
    generic = ('simplif', 'deliberate material investment', 'analyzed continuation',
               'takes a pawn', 'captures a pawn', 'the stronger move')
    if not any(term in str(existing_text or '').lower() for term in generic):
        return None
    # The tactical explanation is a different, stronger lesson only if its
    # rooted branch belongs to one of the same user decision's two candidates.
    roots = {(branch.get('role'), branch.get('root_uci')) for branch in data['branches']}
    if ('best', best.uci()) not in roots:
        return None
    if selection.get('role') == 'played' and played is not None and ('played', played.uci()) not in roots:
        return None
    return selection.get('text')
