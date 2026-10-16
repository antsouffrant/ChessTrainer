"""Evidence from a stored principal variation, with no invented forced results.

The PV is an engine hypothesis at a bounded search depth, not a proof (except
for a verified mate score). Only legal prefixes are used, and we distinguish
observed tactical actions from unverified geometrical motifs.
"""
from __future__ import annotations
import json
import chess
from pv_outcomes import positional_outcome

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
               chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def encode_pv(pv, max_plies=12):
    if not pv:
        return None
    return json.dumps([(move.uci() if isinstance(move, chess.Move) else str(move))
                       for move in list(pv)[:max_plies]])


def legal_pv(board, raw, first_move=None, max_plies=12):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    raw = list(raw)
    # Compatibility: if a stored PV begins with a legal reply from *after*
    # the expected move, recover the omitted root. Normal root-constrained
    # Stockfish output already contains the root and passes through unchanged.
    if first_move is not None and raw and first_move in board.legal_moves:
        try:
            first_stored = raw[0] if isinstance(raw[0], chess.Move) else chess.Move.from_uci(str(raw[0]))
        except (TypeError, ValueError):
            first_stored = None
        if first_stored is not None and first_stored != first_move and first_stored not in board.legal_moves:
            after_root = board.copy(stack=False)
            after_root.push(first_move)
            if first_stored in after_root.legal_moves:
                raw = [first_move] + raw
    replay = board.copy(stack=False)
    result = []
    for value in raw[:max_plies]:
        try:
            move = value if isinstance(value, chess.Move) else chess.Move.from_uci(str(value))
        except (TypeError, ValueError):
            break
        if move not in replay.legal_moves:
            break
        result.append(move)
        replay.push(move)
    if first_move is not None and (not result or result[0] != first_move):
        return []
    return result


def pv_san(board, raw, first_move=None, max_plies=6):
    moves = legal_pv(board, raw, first_move=first_move, max_plies=max_plies)
    replay = board.copy(stack=False)
    parts = []
    for move in moves:
        san = replay.san(move)
        prefix = f'{replay.fullmove_number}.' if replay.turn == chess.WHITE else (f'{replay.fullmove_number}...' if not parts else '')
        parts.append(f'{prefix}{san}' if prefix else san)
        replay.push(move)
    return ' '.join(parts)


def fork_evidence(board, best_move, raw=None):
    """Return a candidate double attack only when its two threats are new.

    A checking fork is intrinsically forcing. Without check, require a safe
    attacker and at least one target whose fate the PV actually illustrates.
    This is intentionally stricter than testing attacks() geometrically alone.
    """
    if best_move not in board.legal_moves:
        return None
    side = board.turn
    after = board.copy(stack=False)
    after.push(best_move)
    moved = after.piece_at(best_move.to_square)
    if not moved or moved.color != side:
        return None
    targets = []
    for sq in after.attacks(best_move.to_square):
        piece = after.piece_at(sq)
        if not piece or piece.color == side or PIECE_VALUE[piece.piece_type] < 3:
            continue
        # Attacked targets can be defended; we do not treat defended == harmless.
        # Require two distinct valuable targets, with at least one new pressure.
        targets.append((sq, piece))
    if len(targets) < 2:
        return None
    targets.sort(key=lambda item: PIECE_VALUE[item[1].piece_type], reverse=True)
    line = legal_pv(board, raw, first_move=best_move)
    if len(line) > 1:
        reply_board = after.copy(stack=False)
        reply = line[1]
        if (reply_board.is_capture(reply)
                and reply.to_square == best_move.to_square):
            # The alleged attacker is immediately removed. A temporary attack
            # on two squares is not an actionable double attack.
            return None
    demonstrates = False
    illustrative = None
    for ply, move in enumerate(line[1:], start=1):
        # a defender's first move shifts a threatened piece, or the attacker
        # subsequently captures a threatened target. Neither claims a forced win.
        if ply == 1 and move.from_square in {sq for sq, _ in targets}:
            demonstrates = True
            illustrative = 'the defender must respond to one of the attacked pieces'
        if ply % 2 == 0 and move.to_square in {sq for sq, _ in targets}:
            replay = board.copy(stack=False)
            for preceding in line[:ply]:
                replay.push(preceding)
            if replay.is_capture(move):
                demonstrates = True
                illustrative = 'the continuation captures one of the targets'
                break
    check_fork = after.is_check() and any(pc.piece_type != chess.KING for _, pc in targets)
    safe_attacker = not after.is_attacked_by(not side, best_move.to_square)
    # Two loose targets and a safe attacker are also a concrete double threat
    # even when an older saved puzzle has no principal variation.
    loose_pair = safe_attacker and sum(
        1 for sq, piece in targets if piece.piece_type != chess.KING
        and not after.is_attacked_by(not side, sq)
    ) >= 2
    # Even a checking fork is not actionable when an inexpensive legal
    # recapture removes the attacking piece immediately. In the absence of a
    # stored reply, prefer an unclassified tactic to a false lesson.
    inexpensive_recapture = any(
        after.is_capture(reply) and reply.to_square == best_move.to_square
        and (after.piece_type_at(reply.from_square) == chess.KING
             or PIECE_VALUE.get(after.piece_type_at(reply.from_square), 100)
                <= PIECE_VALUE.get(moved.piece_type, 0))
        for reply in after.legal_moves
    )
    strong = ((check_fork and not inexpensive_recapture)
              or loose_pair or (safe_attacker and demonstrates))
    return {
        'strong': strong,
        'check_fork': check_fork,
        'loose_pair': loose_pair,
        'line_supported': demonstrates,
        'targets': targets,
        'reason': illustrative,
    }


def evidence_summary(board, best_move, played_move, best_line, played_line):
    """Grounded optional continuation sentences, capped for UI readability."""
    best = pv_san(board, best_line, first_move=best_move, max_plies=5)
    played = pv_san(board, played_line, first_move=played_move, max_plies=4) if played_move else ''
    if best and len(legal_pv(board, best_line, first_move=best_move)) >= 2:
        sentence = f'In a sampled engine continuation, the best move leads to {best}.'
        if played and len(legal_pv(board, played_line, first_move=played_move)) >= 2:
            sentence += f' The game move instead allows {played}.'
        return sentence
    return ''


def continuation_facts(board, raw, first_move=None, max_plies=12):
    """Interpret a legal PV as board events, not as a prose move list.

    All material changes are measured from the same training FEN and the
    original solver's perspective. A bounded PV illustrates a *possible*
    continuation, not a proof that the opponent must choose every reply.
    """
    moves = legal_pv(board, raw, first_move=first_move, max_plies=max_plies)
    original_side = board.turn
    replay = board.copy(stack=False)
    events = []
    material_delta = 0
    for ply, move in enumerate(moves):
        mover = replay.turn
        san = replay.san(move)
        capture = replay.is_capture(move)
        captured = replay.piece_at(move.to_square) if capture else None
        if capture and captured is None and replay.is_en_passant(move):
            captured = chess.Piece(chess.PAWN, not mover)
        gained = PIECE_VALUE.get(captured.piece_type, 0) if captured else 0
        if move.promotion:
            gained += PIECE_VALUE.get(move.promotion, 0) - 1
        material_delta += gained * (1 if mover == original_side else -1)
        replay.push(move)
        events.append({
            'ply': ply, 'move': move, 'san': san, 'ours': mover == original_side,
            'capture': capture, 'captured': captured, 'piece_value': gained,
            'square': chess.square_name(move.to_square),
            'check': replay.is_check(), 'mate': replay.is_checkmate(),
            'net': material_delta,
        })
    return {'moves': moves, 'events': events, 'net': material_delta,
            'mate': bool(events and events[-1]['mate']), 'terminal': replay.is_game_over()}


def comparative_insight(board, best_move, played_move, best_line=None, played_line=None):
    """Find the tactical payoff of best and played continuations.

    The resulting motif is evidence-based, drawn from moves actually present
    in the saved line. It never treats a sampled reply as the only reply.
    """
    best = continuation_facts(board, best_line, first_move=best_move)
    played = continuation_facts(board, played_line, first_move=played_move) if played_move else {'events': [], 'moves': [], 'net': 0, 'mate': False}
    events = best['events']
    if not events:
        return {'motif': None, 'motif_ply': None, 'narrative': '', 'best': best, 'played': played}

    first = events[0]
    second = events[1] if len(events) > 1 else None
    recaptured = bool(
        second and not second['ours'] and second['capture']
        and second['move'].to_square == first['move'].to_square
    )
    # An exchange is not a sacrifice. Even when there is a later payoff,
    # require a *material deficit* after the tempting reply, not merely an
    # opponent capture of the just-moved piece.
    initial_deficit = -second['net'] if recaptured else 0
    gain_events = [e for e in events[2:] if e['ours'] and e['capture'] and e['captured']]
    valuable_payoffs = [e for e in gain_events if e['piece_value'] >= 3 and e['ply'] <= 6]
    opponent_gains = [e for e in played['events'] if not e['ours'] and e['capture'] and e['captured']]
    has_check = first['check']
    sacrifice = (
        has_check and recaptured and initial_deficit >= 2
        and best['net'] >= 0 and bool(valuable_payoffs)
        and any(e['net'] >= 0 for e in events[2:])
    )
    # Seek a later fork whose tactical result is visible, not merely a
    # geometric attack. This catches sacrificial checks that set up a fork.
    later_fork = None
    # An incidental fork five moves later must not own the lesson. Limit
    # motif evidence to the near-root tactical sequence (maximum 4 plies).
    for ply in range(2, min(len(best['moves']), 5), 2):
        replay = board.copy(stack=False)
        for prior in best['moves'][:ply]:
            replay.push(prior)
        if ply >= len(best['moves']) or replay.turn != board.turn:
            continue
        possible = fork_evidence(replay, best['moves'][ply], best['moves'][ply:])
        if (not recaptured and possible and possible['strong']
                and possible['line_supported']):
            later_fork = best['events'][ply]
            break

    # An opponent reply can deflect a defender, exposing the piece it guarded.
    # Require the *actual* capture of that target later in the PV: a moved
    # defender and an unrelated pin are not enough evidence.
    deflection = None
    if len(events) >= 3 and not events[1]['ours']:
        reply = events[1]['move']
        initial_defender = board.piece_at(reply.from_square)
        if initial_defender and initial_defender.color != board.turn:
            for payoff in gain_events:
                if payoff['ply'] > 4:
                    continue  # Distant captures cannot establish the root deflection motif.
                target_sq = payoff['move'].to_square
                initial_target = board.piece_at(target_sq)
                if (initial_target and initial_target.color != board.turn
                        and reply.from_square in board.attackers(not board.turn, target_sq)
                        and payoff['captured'] and payoff['captured'].piece_type == initial_target.piece_type):
                    deflection = (events[1], payoff, initial_target)
                    break

    motif = None
    motif_ply = None
    if best['mate'] and events[-1]['ours']:
        motif = 'mating_net'
        motif_ply = events[-1]['ply'] + 1
    elif later_fork is not None:
        motif = 'fork'
        motif_ply = later_fork['ply'] + 1
    elif deflection is not None:
        motif = 'deflection'
        motif_ply = deflection[1]['ply'] + 1
    elif sacrifice:
        motif = 'tactical_combination'
        motif_ply = max(e['ply'] for e in valuable_payoffs) + 1 if valuable_payoffs else None
    elif (any(e['ply'] <= 4 for e in valuable_payoffs)
          and (best['net'] >= 2 or (played['events'] and best['net'] - played['net'] >= 3))):
        # Long-tail captures may be narrated as eventual outcomes but they
        # must not determine the primary motif at the training decision.
        motif = 'tactical_combination'
        motif_ply = min(e['ply'] for e in valuable_payoffs) + 1 if valuable_payoffs else None

    # Compare captures at matched horizons; a line with twice as many plies
    # must not be called materially better merely because it has more moves.
    comparable = min(len(best['events']), len(played['events']))
    material_edge = None
    if comparable >= 2:
        best_equal = best['events'][comparable - 1]['net']
        played_equal = played['events'][comparable - 1]['net']
        material_edge = best_equal - played_equal
    geometry = positional_outcome(board, best['moves'], played['moves'])
    sentences = []
    if best['mate'] and events[-1]['ours']:
        sentences.append(f"The best analyzed continuation ends in checkmate with {events[-1]['san']}.")
    elif later_fork:
        sentences.append(f"The key payoff comes later: {later_fork['san']} creates a double attack in the analyzed continuation.")
    elif deflection:
        reply, payoff, target = deflection
        sentences.append(
            f'The analyzed reply {reply["san"]} draws a defender away from the '
            f'{chess.piece_name(target.piece_type)} on {payoff["square"]}; '
            f'{payoff["san"]} then captures that target. The distraction makes '
            'the later capture possible in the best-move line.'
        )
    elif sacrifice:
        important = max(gain_events, key=lambda event: event['piece_value'])
        taken = chess.piece_name(important['captured'].piece_type)
        sentences.append(
            f"The checking sacrifice invites {second['san']} to capture your piece, "
            f"but the follow-up {important['san']} captures the opponent's {taken}. "
            f"Across this line, the combination recovers its material investment."
        )
    elif valuable_payoffs and (best['net'] >= 1 or played['events'] and best['net'] > played['net']):
        important = max(valuable_payoffs, key=lambda event: event['piece_value'])
        taken = chess.piece_name(important['captured'].piece_type)
        if important['ply'] >= 6:
            timing = f'Eventually, {important["san"]}'
        elif has_check:
            timing = f'After the check, {important["san"]}'
        else:
            timing = f'In the continuation, {important["san"]}'
        sentences.append(f'{timing} captures the opponent’s {taken}.')

    # If the engine's line offers a material result that the played branch
    # does not, express the specific gain rather than a generic balance shift.
    if not sentences and material_edge is not None and material_edge >= 2:
        own_gains = [e for e in best['events'][:comparable] if e['ours'] and e['capture'] and e['captured']]
        opp_losses = [e for e in played['events'][:comparable] if not e['ours'] and e['capture'] and e['captured']]
        if own_gains and best['events'][comparable-1]['net'] >= played['events'][comparable-1]['net']:
            important = max(own_gains, key=lambda e:e['piece_value'])
            payoff = ('leaving a better material result than the game continuation'
                      if important['ply'] < comparable - 1 else
                      'providing the material payoff shown at the end of the analyzed line')
            sentences.append(f'In the best continuation, {important["san"]} captures the opponent’s '
                             f'{chess.piece_name(important["captured"].piece_type)}, {payoff}.')
            if motif is None:
                motif, motif_ply = 'missed_capture', important['ply'] + 1
        elif opp_losses:
            important = max(opp_losses, key=lambda e:e['piece_value'])
            sentences.append(f'The best continuation avoids the loss of your '
                             f'{chess.piece_name(important["captured"].piece_type)} '
                             f'that follows {important["san"]} in the game-move line.')
            if motif is None:
                motif, motif_ply = 'defensive_resource', important['ply'] + 1
    # Describe measured geometry/structure only if a more decisive tactic has
    # not already explained the advantage. The motif is shared with lessons.
    if not sentences and geometry is not None:
        sentences.append(geometry['narrative'])
        if motif is None:
            motif, motif_ply = geometry['motif'], geometry.get('ply')
    # Describe the *comparison*, not a second raw engine variation.
    if not sentences and opponent_gains and played['net'] < best['net']:
        important = max(opponent_gains, key=lambda event: event['piece_value'])
        taken = chess.piece_name(important['captured'].piece_type)
        sentences.append(
            f"In the played-move continuation, {important['san']} captures your {taken}."
        )

    return {'motif': motif, 'motif_ply': motif_ply,
            'narrative': ' '.join(sentences[:2]),
            'best': best, 'played': played}
