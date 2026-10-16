"""Legality- and continuation-grounded explanation of the *decision*.

Separate what is visible (a threat, a capture, a proposed exchange) from what
Stockfish actually rates higher. PVs are samples, not proofs of inevitability.
In particular, the best move must never be described as saving a piece that is
also lost in the best-move continuation.
"""
from __future__ import annotations

import json
import chess
from pv_reasoning import legal_pv

CONTEXT_VERSION = 1
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def _name(piece):
    return chess.piece_name(piece.piece_type)


def mate_in_one(board, limit=2):
    """Legal mating moves for the *side to move* (never geometric guesses)."""
    answer = []
    for move in board.legal_moves:
        if not board.gives_check(move):
            continue
        san = board.san(move)
        child = board.copy(stack=False)
        child.push(move)
        if child.is_checkmate():
            answer.append(san)
            if len(answer) == limit:
                break
    return answer


def unanswered_mate_threat(board):
    """Mate in one on the next turn if the opponent makes a null move.

    This is an actionable threat, NOT proof of a forced mate: real moves can
    defend it. Do not use a null move from check or a terminal position.
    """
    if board.is_check() or board.is_game_over():
        return []
    other = board.copy(stack=False)
    other.push(chess.Move.null())
    return mate_in_one(other)


def _capture_square(before, move):
    if not before.is_capture(move):
        return None
    if before.is_en_passant(move):
        return chess.square(chess.square_file(move.to_square),
                            chess.square_rank(move.from_square))
    return move.to_square


def trace_variation(board, raw, first=None, max_plies=10):
    """Keep root-piece identity even when pieces move before being captured."""
    moves = legal_pv(board, raw, first_move=first, max_plies=max_plies)
    track = {sq: sq for sq in board.piece_map()}
    replay = board.copy(stack=False)
    captures, exchanges, steps = [], [], []
    total = 0
    for ply, move in enumerate(moves):
        if move not in replay.legal_moves:
            break
        san, mover = replay.san(move), replay.piece_at(move.from_square)
        capture_sq = _capture_square(replay, move)
        victim = replay.piece_at(capture_sq) if capture_sq is not None else None
        victim_id = track.pop(capture_sq, None) if capture_sq is not None else None
        if victim is not None:
            value = VALUES[victim.piece_type]
            item = {'ply': ply, 'san': san, 'square': chess.square_name(capture_sq),
                    'root_square': chess.square_name(victim_id) if victim_id is not None else None,
                    'piece': _name(victim), 'value': value,
                    'by_solver': replay.turn == board.turn}
            captures.append(item)
            total += value * (1 if item['by_solver'] else -1)
            if len(captures) >= 2:
                prev = captures[-2]
                if (prev['ply'] == ply - 1 and prev['by_solver'] != item['by_solver']
                        and prev['square'] == item['square']):
                    exchanges.append({'first': prev, 'recapture': item,
                                      'balanced': abs(prev['value'] - item['value']) <= 1})
        # Castling relocates two pieces; keep both root identities.
        castle = replay.is_castling(move)
        if castle:
            kingside = chess.square_file(move.to_square) > chess.square_file(move.from_square)
            rank = chess.square_rank(move.from_square)
            rook_from = chess.square(7 if kingside else 0, rank)
            rook_to = chess.square(5 if kingside else 3, rank)
            rook_id = track.pop(rook_from, None)
            if rook_id is not None:
                track[rook_to] = rook_id
        root_id = track.pop(move.from_square, None)
        if root_id is not None:
            track[move.to_square] = root_id
        replay.push(move)
        steps.append({'ply': ply, 'san': san, 'uci': move.uci(),
                      'by_solver': mover.color == board.turn if mover else False,
                      'checkmate': replay.is_checkmate(), 'material_delta': total})
    return {'moves': [s['san'] for s in steps], 'captures': captures,
            'exchanges': exchanges, 'steps': steps, 'material_delta': total,
            'root_remaining': {chess.square_name(x) for x in track.values()}}


def _root_loose(board, color):
    items = []
    for square, piece in board.piece_map().items():
        if piece.color != color or piece.piece_type == chess.KING:
            continue
        if board.is_attacked_by(not color, square) and not board.is_attacked_by(color, square):
            items.append({'square': chess.square_name(square), 'piece': _name(piece),
                          'value': VALUES[piece.piece_type]})
    return sorted(items, key=lambda x: -x['value'])


def _new_targets(board, after, color):
    """Enemy pieces newly attacked by our move (not automatically free)."""
    targets = []
    for square, piece in board.piece_map().items():
        if piece.color == color or piece.piece_type == chess.KING:
            continue
        # Do not track a moved/captured piece at its stale square.
        if after.piece_at(square) != piece:
            continue
        if (after.is_attacked_by(color, square)
                and not board.is_attacked_by(color, square)):
            targets.append({'square': chess.square_name(square), 'piece': _name(piece),
                            'value': VALUES[piece.piece_type],
                            'loose': not after.is_attacked_by(not color, square)})
    return sorted(targets, key=lambda x: (-int(x['loose']), -x['value']))


def _surviving_piece(board, after, root_sq, move, side):
    sq = chess.parse_square(root_sq)
    if sq == move.from_square:
        sq = move.to_square
    piece = after.piece_at(sq)
    if piece is None or piece.color != side:
        return None
    return sq


def _defended(board, after, move, root_sq, side):
    sq = _surviving_piece(board, after, root_sq, move, side)
    if sq is None:
        return False
    return (not after.is_attacked_by(not side, sq)
            or (after.is_attacked_by(side, sq)
                and not board.is_attacked_by(side, chess.parse_square(root_sq))))


def _first_reply(trace):
    return trace['steps'][1]['san'] if len(trace['steps']) >= 2 else None


def decision_facts(board, best, played, best_pv=None, played_pv=None,
                   alternatives=None, best_cp=None, played_cp=None):
    """Branch-aware tactical context. No Stockfish call and no invented lines."""
    if best not in board.legal_moves:
        return None
    positive = played == best
    contrast_role = 'game move'
    contrast_cp = played_cp
    if positive:
        options = alternatives
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except (ValueError, TypeError):
                options = []
        if not isinstance(options, list):
            options = []
        contrast = next((op for op in options if isinstance(op, dict)
                         and op.get('move_uci') and op.get('pv_uci')
                         and op.get('eval_cp') is not None
                         and op['move_uci'] != best.uci()), None)
        if contrast:
            try:
                candidate = chess.Move.from_uci(contrast['move_uci'])
            except (ValueError, TypeError):
                candidate = None
            if candidate in board.legal_moves:
                played, played_pv = candidate, contrast['pv_uci']
                contrast_cp, contrast_role = contrast['eval_cp'], 'tempting alternative'
    if positive and contrast_role != 'tempting alternative':
        # The best game move is not its own inferior counterfactual.
        played, played_pv, contrast_cp = None, None, None
    if played is None or played not in board.legal_moves:
        played = None
    good = trace_variation(board, best_pv, best)
    bad = trace_variation(board, played_pv, played) if played else None
    after_good = board.copy(stack=False)
    after_good.push(best)
    after_bad = board.copy(stack=False) if played else None
    if after_bad:
        after_bad.push(played)
    own_loose = _root_loose(board, board.turn)
    enemy_loose = _root_loose(board, not board.turn)
    # Note: if root side has an immediate mate, that's an opportunity rather than
    # the opponent's threat. Only a null reply checks what the opponent threatened.
    root_opponent_mate = unanswered_mate_threat(board)
    opponent_mate_good = mate_in_one(after_good)
    opponent_mate_bad = mate_in_one(after_bad) if after_bad else []
    our_mate_good = unanswered_mate_threat(after_good)
    our_mate_bad = unanswered_mate_threat(after_bad) if after_bad else []
    lost_good = {c['root_square'] for c in good['captures']
                 if not c['by_solver'] and c['root_square']}
    lost_bad = {c['root_square'] for c in bad['captures']
                if not c['by_solver'] and c['root_square']} if bad else set()
    shared_loss = [x for x in own_loose if x['square'] in lost_good and x['square'] in lost_bad]
    # Same original piece may be moved before it is taken. Only call a loss
    # differential when the good line is at least as long as the bad capture.
    differential_loss = []
    if bad:
        for capture in bad['captures']:
            source = capture['root_square']
            if (not capture['by_solver'] and source and source not in lost_good
                    and len(good['steps']) > capture['ply']):
                differential_loss.append(capture)
    truly_saved = [x for x in own_loose if x['square'] in lost_bad and x['square'] not in lost_good
                   and _defended(board, after_good, best, x['square'], board.turn)
                   and len(good['steps']) > max((c['ply'] for c in bad['captures']
                                                 if c['root_square'] == x['square'] and not c['by_solver']), default=-1)]
    newly_attacked = _new_targets(board, after_good, board.turn)
    return {'version': CONTEXT_VERSION, 'positive': positive,
            'best_san': board.san(best), 'played_san': board.san(played) if played else None,
            'contrast_role': contrast_role, 'best_cp': best_cp,
            'played_cp': contrast_cp, 'own_loose': own_loose,
            'enemy_loose': enemy_loose, 'shared_loss': shared_loss,
            'truly_saved': truly_saved, 'differential_loss': differential_loss, 'new_targets': newly_attacked,
            'root_opponent_mate': root_opponent_mate,
            'opponent_mate_good': opponent_mate_good, 'opponent_mate_bad': opponent_mate_bad,
            'our_mate_good': our_mate_good, 'our_mate_bad': our_mate_bad,
            'good': good, 'bad': bad,
            'best_is_capture': board.is_capture(best),
            'best_capture_piece': _name(board.piece_at(best.to_square))
                if board.piece_at(best.to_square) and board.is_capture(best) else None,
            'best_move_uci': best.uci(), 'played_move_uci': played.uci() if played else None}


def has_decisive_context(board, facts):
    """Use new narrative only when it beats the legacy concrete rule path."""
    if not facts:
        return False
    if facts['shared_loss'] or facts['truly_saved']:
        return True
    if (facts['opponent_mate_bad'] and not facts['opponent_mate_good']) or (
            facts['our_mate_good'] and not facts['our_mate_bad']):
        return True
    if any(x['first']['ply'] <= 2 for x in facts['good']['exchanges']) or (facts['bad'] and any(x['first']['ply'] <= 2 for x in facts['bad']['exchanges'])):
        return True
    # A demonstrated capture/attack in a played continuation differentiates
    # two choices; mere board geometry or single-ply samples do not.
    if facts['bad'] and facts['bad']['captures'] and len(facts['good']['steps']) >= 2:
        loss = next((c for c in facts['bad']['captures'] if not c['by_solver']), None)
        if loss and loss['root_square'] not in {
                c['root_square'] for c in facts['good']['captures'] if not c['by_solver']}:
            return True
    if facts['new_targets'] and facts['bad'] and len(facts['good']['steps']) >= 2:
        return True
    return False


def concrete_explanation(board, facts, category='', mate_before=None, mate_after=None):
    """Decision -> relevant board fact -> sampled realization -> better choice.

    Each clause has its own evidence threshold. Lack of PV is reported as an
    evidentiary limitation rather than filling with a manufactured tactic.
    """
    if not facts:
        return ''
    best, played = facts['best_san'], facts['played_san']
    good, bad = facts['good'], facts['bad']
    positive = facts['positive']
    gap = (round((facts['best_cp'] - facts['played_cp']) / 100, 2)
           if facts['best_cp'] is not None and facts['played_cp'] is not None else None)
    benefit = ''
    if good['steps'] and good['steps'][0]['checkmate']:
        benefit = f'{best} is checkmate.'
    elif isinstance(mate_before, int) and mate_before > 0:
        benefit = (f'Stockfish evaluates {best} as leading to a forced mate '
                   f'(mate in {mate_before}); the recorded line is one illustration.')
    elif facts['opponent_mate_bad'] and not facts['opponent_mate_good'] and played:
        benefit = (f'Unlike {played}, {best} removes the immediate mate-in-one '
                   f'available to the opponent after that move.')
    elif facts['truly_saved']:
        x = facts['truly_saved'][0]
        benefit = (f'{best} addresses the attack on your {x["piece"]} on {x["square"]}; '
                   'it survives through the comparable saved line.')
    elif facts['shared_loss']:
        x = facts['shared_loss'][0]
        benefit = (f'The {x["piece"]} originally on {x["square"]} is taken in BOTH '
                   f'analyzed lines. {best} is therefore not a defense of that piece.')
        if facts['new_targets']:
            t = facts['new_targets'][0]
            benefit += (f' Instead, it counterattacks the opponent’s {t["piece"]} '
                        f'on {t["square"]}.')
        elif facts['best_is_capture']:
            benefit += f' Instead, it captures the opponent’s {facts["best_capture_piece"]}.'
    elif facts['differential_loss']:
        loss = facts['differential_loss'][0]
        benefit = (f'In the analyzed {best} line, your {loss["piece"]} originally '
                   f'from {loss["root_square"]} is not captured through the '
                   f'corresponding {loss["san"]} tactic. This is a distinction '
                   'between the saved lines, not a guarantee against every reply.')
    elif good['exchanges']:
        ex = good['exchanges'][0]
        one, two = ex['first'], ex['recapture']
        benefit = (f'The analyzed {best} line contains an exchange: {one["san"]} '
                   f'is followed by {two["san"]}.')
        if ex['balanced']:
            benefit += ' This is a trade, not a free material win.'
    elif facts['best_is_capture']:
        benefit = f'{best} captures the opponent’s {facts["best_capture_piece"]}.'
        if len(good['steps']) < 2:
            benefit += ' The saved continuation does not establish whether it can be recaptured.'
        else:
            recaptured = bool(good['captures'] and any(
                c['ply'] == 1 and c['square'] == good['captures'][0]['square']
                and not c['by_solver'] for c in good['captures']))
            if recaptured:
                benefit += ' The opponent recaptures in the analyzed line, so this is an exchange rather than a free piece.'
    elif facts['our_mate_good'] and not facts['our_mate_bad']:
        benefit = (f'{best} threatens {facts["our_mate_good"][0]} on the next turn '
                   'if the opponent does not answer the threat; this is not yet a forced mate.')
    elif facts['new_targets']:
        t = facts['new_targets'][0]
        benefit = (f'{best} attacks the opponent’s {t["piece"]} on {t["square"]}'
                   f'{", which is undefended" if t["loose"] else ""}.')
        if facts['own_loose']:
            benefit += ' This is an active counterattack, not necessarily protection of your threatened material.'
    elif board.is_check():
        benefit = f'{best} is a legal response to check.'
    else:
        benefit = f'{best} is the engine-preferred move.'
    parts = []
    if positive:
        parts.append(f'Why the game move works: {benefit}')
        if played and played != best:
            parts.append(f'The analyzed alternative {played} is less effective' +
                         (f' by about {gap:.2f} pawns in Stockfish’s evaluation.' if gap is not None and gap >= 0 else '.'))
    else:
        if played:
            lead = f'Why {played} falls short: '
            if facts['opponent_mate_bad'] and not facts['opponent_mate_good']:
                lead += (f'the opponent can play {facts["opponent_mate_bad"][0]} immediately '
                         'for checkmate.')
            elif bad and bad['exchanges']:
                ex = bad['exchanges'][0]
                lead += (f'the saved line reaches the exchange {ex["first"]["san"]} '
                         f'{ex["recapture"]["san"]}; a capture there is not necessarily a free piece.')
            elif bad and bad['captures']:
                loss = next((c for c in bad['captures'] if not c['by_solver'] and
                             c['root_square'] not in {x['square'] for x in facts['shared_loss']}), None)
                if loss:
                    lead += (f'in the analyzed continuation, {loss["san"]} captures your '
                             f'{loss["piece"]} on {loss["square"]}.')
                elif facts['shared_loss']:
                    lead += 'the same threatened material is lost even after the best move; the difference is elsewhere.'
                else:
                    lead += 'the saved line does not identify a single decisive tactical refutation.'
            elif bad and len(bad['steps']) >= 2:
                lead += (f'the analyzed opponent reply is {_first_reply(bad)}; '
                         'the saved line does not by itself prove a forced tactical loss.')
            else:
                lead += 'the current engine assessment favors a different continuation.'
            parts.append(lead)
        parts.append(f'Why {best} is better: {benefit}')
        if gap is not None and gap >= 0:
            parts.append(f'Stockfish evaluates the difference at about {gap:.2f} pawns.')
        if category == 'allowed_checkmate' and not facts['opponent_mate_bad']:
            parts.append('Stockfish reports a forced mate against the game move, although the saved line does not establish an immediate mate-in-one.')
    return ' '.join(parts)
