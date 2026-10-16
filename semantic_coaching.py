"""Causal, compact coaching on top of saved legal chess evidence.

The explanatory unit is NOT a motif hit. It is a contrast between two moves:
  context (the decision), consequence (why the evaluation differs), learning.

Candidates carry their evidentiary limits: one legal reply is a *possibility*;
a saved PV is an *illustration*; only mate-in-one or a signed mate score
establishes mate. Positional descriptions require root-board measurements and
cannot be upgraded to a forced tactical result by stylistic language.

No chess engine is called here. This module consumes saved variation evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess

from decision_context import decision_facts, trace_variation
from loose_piece_provenance import differential_loss_motif
from coaching_language import game_continuation

VERSION = 'chess-idea-coaching-v5-provenance'
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
CENTRAL = {chess.D4, chess.E4, chess.D5, chess.E5}


@dataclass(frozen=True)
class Finding:
    key: str
    motif: str
    horizon: int                 # 0 immediate, 1 reply, 2+ longer term
    confidence: int              # 3 verified immediate, 2 PV-grounded, 1 board-only
    impact: int                  # importance before proximity
    assessment: str              # why this choice fails / succeeds
    comparison: str              # what the better choice achieves
    lesson: str                  # one transferable takeaway


def _legal(board, move):
    return move is not None and move in board.legal_moves


def _after(board, move):
    after = board.copy(stack=False)
    after.push(move)
    return after


def _s(square):
    return chess.square_name(square)


def _piece(piece):
    return chess.piece_name(piece.piece_type)


def _role(facts):
    return 'the alternative' if facts and facts.get('contrast_role') == 'tempting alternative' else 'the game move'


def _gap(best_cp, worse_cp):
    try:
        return int(best_cp) - int(worse_cp)
    except (ValueError, TypeError):
        return None


def _find_legal_capture(board, square):
    for reply in board.legal_moves:
        if board.is_capture(reply) and reply.to_square == square:
            return board.san(reply)
    return None


def _root_piece_capture(facts, root_square, *, bad=True):
    line = facts.get('bad') if bad else facts.get('good')
    if not line:
        return None
    return next((x for x in line['captures'] if not x['by_solver']
                 and x['root_square'] == root_square), None)


def _material_losses(facts):
    """Losses in the inferior line not also demonstrated in the better line.

    Mere captures in exchanges are not treated as lost material. Require a
    net worsening at comparable PV horizons, and only attribute a named
    victim when it can be identified from the original board.
    """
    good, bad = facts['good'], facts.get('bad')
    if not bad or len(good['steps']) < 2 or len(bad['steps']) < 2:
        return []
    good_loss = {c['root_square'] for c in good['captures'] if not c['by_solver']}
    captures = [c for c in bad['captures'] if not c['by_solver']
                and c['root_square'] and c['root_square'] not in good_loss]
    # We can't say a traded bishop was hung if 3 points are recovered.
    if bad['material_delta'] >= good['material_delta'] - 1:
        return []
    # Compare only through the first loss; require sufficient good-line
    # evidence at that horizon, avoiding false 'saved' assertions.
    return [c for c in captures if c['ply'] <= 2 and c['ply'] < len(good['steps'])]


def _central_control(board, move):
    piece = board.piece_at(move.from_square)
    if not piece:
        return set(), set()
    before = set(board.attacks(move.from_square)) & CENTRAL
    after = _after(board, move)
    later_piece = after.piece_at(move.to_square)
    after_squares = set(after.attacks(move.to_square)) & CENTRAL if later_piece else set()
    return before, after_squares


def _new_pin(board, pv_moves, *, color):
    """Detect a genuinely new king pin of a surviving root-side piece in a PV.

    This is illustrative, never a forced prediction. The pin must be absent
    before the choice, and present after at least one actual reply.
    """
    start = {sq for sq, pc in board.piece_map().items()
             if pc.color == color and pc.piece_type != chess.KING and board.is_pinned(color, sq)}
    replay = board.copy(stack=False)
    for ply, uci in enumerate(pv_moves[:7]):
        try:
            move = chess.Move.from_uci(uci) if isinstance(uci, str) else uci
        except ValueError:
            break
        if move not in replay.legal_moves:
            break
        replay.push(move)
        if ply < 1:
            continue
        for sq, piece in replay.piece_map().items():
            if piece.color == color and piece.piece_type != chess.KING and replay.is_pinned(color, sq):
                if sq not in start:
                    return (ply, piece, sq)
    return None



def _capture_value(trace, solver):
    return sum(c['value'] for c in trace['captures'] if c['by_solver'] == solver)


def _realized_gain(facts, threshold=1):
    """Material payoff along a legal PV, not a claim of forced gain."""
    good = facts['good']
    if len(good['steps']) < 3 or good['material_delta'] < threshold:
        return False
    bad = facts.get('bad')
    return bad is None or good['material_delta'] > bad['material_delta']


def _free_root_capture(board, best, facts):
    """Prefer decisive root opportunities over incidental later PV events.

    'Free' is reserved for a capture with no legal immediate recapture; merely
    omitting a legal recapture from one sampled PV doesn't make it free.
    """
    if not board.is_capture(best):
        return None
    victim = board.piece_at(best.to_square)
    if board.is_en_passant(best):
        victim = chess.Piece(chess.PAWN, not board.turn)
    if not victim:
        return None
    after = _after(board, best)
    recaptures = [m for m in after.legal_moves
                  if after.is_capture(m) and m.to_square == best.to_square]
    good = facts['good']
    line_recaptured = any(c['ply'] == 1 and not c['by_solver']
                          and c['square'] == _s(best.to_square)
                          for c in good['captures'])
    return {'victim': victim, 'recaptures': recaptures,
            'free': not recaptures and not line_recaptured,
            'line_recaptured': line_recaptured, 'after': after}


def _legal_mating_refutation(board, capture):
    """If a legal recapture is met by a *legal mate in one*, identify it.

    Never claim that a recapture loses to a mating attack on geometry alone.
    """
    from decision_context import mate_in_one
    child = _after(board, capture)
    mates = mate_in_one(child, limit=1)
    return mates[0] if mates else None


def _queen_activity(board, best, root_capture):
    piece = board.piece_at(best.from_square)
    if not root_capture or not piece or piece.piece_type != chess.QUEEN:
        return False
    after = root_capture['after']
    sq = best.to_square
    # A queen capture on a safe, influential square; don't infer activity from
    # the mere presence of a queen or call an en prise queen "active".
    if after.is_attacked_by(not board.turn, sq):
        return False
    return len(after.attacks(sq)) >= 9


def _missed_window(board, best, bad_move, victim_sq, facts):
    """Name a reply only if it removes the capture window in the saved line."""
    bad = facts.get('bad')
    if not bad or len(bad['steps']) < 2 or bad_move is None:
        return ''
    moves = bad['steps']
    reply = chess.Move.from_uci(moves[1]['uci'])
    after = _after(board, bad_move)
    if reply not in after.legal_moves:
        return ''
    victim = after.piece_at(victim_sq)
    before_capture = victim is not None and victim.color != board.turn
    after.push(reply)
    # Opponent moved or exchanged the piece we could previously have taken.
    if before_capture and after.piece_at(victim_sq) != victim:
        return f' After {moves[1]["san"]}, that capture is no longer available.'
    # Alternatively the opponent now protects an originally unprotected victim.
    if before_capture and not board.is_attacked_by(not board.turn, victim_sq) and \
            after.is_attacked_by(not board.turn, victim_sq):
        return f' {moves[1]["san"]} gives the opponent time to defend it.'
    return ''


def _double_attack(board, best, facts):
    """Two relevant targets attacked by the new mover, with a PV payoff.

    A checking move counts the king as one target. For non-checking forks,
    require two enemy pieces worth at least a minor piece each. Only call it
    a material-winning combination when the saved continuation demonstrates it.
    """
    after = _after(board, best)
    mover = after.piece_at(best.to_square)
    if mover is None or mover.piece_type == chess.PAWN:
        return None
    attacked = [(_s(sq), pc, VALUES[pc.piece_type])
                for sq, pc in after.piece_map().items()
                if pc.color != board.turn and pc.piece_type != chess.KING
                and after.is_attacked_by(board.turn, sq)
                and sq in after.attacks(best.to_square)
                and VALUES[pc.piece_type] >= 1]
    valuable = [t for t in attacked if t[2] >= 3]
    checking = after.is_check()
    if not ((checking and attacked) or len(valuable) >= 2):
        return None
    if not _realized_gain(facts):
        return None
    return {'checking': checking, 'targets': attacked}


def _exchange_loss(facts):
    """An exchange loss means giving up a rook for a minor piece, not simply
    appearing in an exchange sequence somewhere down a PV.
    """
    bad, good = facts.get('bad'), facts.get('good')
    if not bad or len(bad['steps']) < 3 or len(good['steps']) < 3:
        return False
    ours = [c for c in bad['captures'] if c['by_solver'] and c['value'] == 3]
    theirs = [c for c in bad['captures'] if not c['by_solver'] and c['value'] == 5]
    if not ours or not theirs:
        return False
    if abs(ours[0]['ply'] - theirs[0]['ply']) > 3 or max(ours[0]['ply'], theirs[0]['ply']) > 3:
        return False
    return (good['material_delta'] - bad['material_delta'] >= 2
            and bad['material_delta'] <= -2)


def _trade_for_castling(board, bad_move, facts):
    """An actual queen exchange forcing an immediate king recapture.

    Queen exchanges alone do not prevent castling. A king recapture during
    the saved continuation demonstrates a genuine loss of castling rights.
    """
    bad = facts.get('bad')
    if not bad or len(bad['steps']) < 3:
        return False
    rights = (board.has_kingside_castling_rights(board.turn) or
              board.has_queenside_castling_rights(board.turn))
    if not rights:
        return False
    replay = board.copy(stack=False)
    queen_taken_previous = False
    for step in bad['steps'][:7]:
        move = chess.Move.from_uci(step['uci'])
        if move not in replay.legal_moves:
            return False
        victim = replay.piece_at(move.to_square)
        mover = replay.piece_at(move.from_square)
        if (queen_taken_previous and mover and mover.piece_type == chess.KING
                and mover.color == board.turn and victim and
                victim.piece_type == chess.QUEEN):
            return True
        queen_taken_previous = bool(victim and victim.piece_type == chess.QUEEN
                                    and victim.color == board.turn)
        replay.push(move)
    return False


def _pawn_sacrifice_plan(board, best, facts):
    """Detect a visible pawn offer followed by a *documented* bishop payoff.

    Avoid explaining a random downstream pawn capture as the purpose of a
    sacrifice. Require the bishop to use the cleared square or capture the
    pawn that appeared as the stated payoff.
    """
    pawn = board.piece_at(best.from_square)
    good = facts['good']
    if not pawn or pawn.piece_type != chess.PAWN or board.is_capture(best):
        return None
    if len(good['steps']) < 4:
        return None
    pawn_losses = [c for c in good['captures'] if not c['by_solver']
                   and c['root_square'] == _s(best.from_square)]
    if not pawn_losses:
        return None
    pawn_capture_ply = pawn_losses[0]['ply']
    replay = board.copy(stack=False)
    bishop_used_opening = False
    bishop_takes_pawn = None
    for ply, step in enumerate(good['steps']):
        move = chess.Move.from_uci(step['uci'])
        if move not in replay.legal_moves:
            return None
        piece = replay.piece_at(move.from_square)
        victim = replay.piece_at(move.to_square)
        if ply > pawn_capture_ply and piece and piece.color == board.turn and piece.piece_type == chess.BISHOP:
            if move.to_square in {best.from_square, best.to_square}:
                bishop_used_opening = True
            if victim and victim.piece_type == chess.PAWN and victim.color != board.turn:
                bishop_takes_pawn = _s(move.to_square)
        replay.push(move)
    if bishop_used_opening and bishop_takes_pawn and good['material_delta'] >= 0:
        return bishop_takes_pawn
    return None


def evidence_findings(board, best, played, best_pv=None, played_pv=None,
                      alternatives=None, best_cp=None, played_cp=None,
                      category='', mate_before=None, facts=None):
    """Rank chess ideas, *not* two move-by-move descriptions.

    Each candidate has a causal mechanism, observation horizon, strength, and
    an optional explanatory contrast. The top finding owns both the displayed
    sentence and the suggested primary learning motif.
    """
    if not _legal(board, best):
        return [], None
    if facts is None:
        facts = decision_facts(board, best, played, best_pv, played_pv,
                               alternatives, best_cp, played_cp)
    if not facts:
        return [], None
    best_name = facts['best_san']
    bad_name = facts.get('played_san')
    bad_uci = facts.get('played_move_uci')
    bad_move = chess.Move.from_uci(bad_uci) if bad_uci else None
    if bad_move and not _legal(board, bad_move):
        bad_move = None
    good, bad = facts['good'], facts.get('bad')
    gap = _gap(facts['best_cp'], facts['played_cp'])
    positive = facts['positive']
    findings = []

    def add(key, motif, horizon, confidence, impact, statement, comparison='', lesson=''):
        findings.append(Finding(key, motif, horizon, confidence, impact,
                                statement, comparison, lesson))

    after_best = _after(board, best)
    after_bad = _after(board, bad_move) if bad_move else None
    # An installed Syzygy tablebase provides exact WDL evidence. Stockfish's
    # centipawn estimates are not treated as solved-endgame results.
    if bad_move:
        from endgame_evidence import exact_move_contrast
        exact = exact_move_contrast(board, best, bad_move)
        if exact:
            consequence = ('throws away the win' if exact['best'] == 'win' else
                           'throws away the draw' if exact['best'] == 'draw' else
                           'worsens the result')
            add('solved_endgame', 'endgame_precision', 0, 3, 125,
                f'Syzygy confirms {best_name} achieves a {exact["best"]}. '
                f'In the game, {bad_name} {consequence}: the resulting endgame is a {exact["played"]}.')

    if after_best.is_checkmate():
        add('mate_now', 'mating_net', 0, 3, 120,
            f'{best_name} is checkmate.')
    elif isinstance(mate_before, int) and mate_before > 0 and category == 'missed_checkmate':
        add('mate_forced', 'mating_net', 2, 3, 117,
            f'{best_name} begins a forced mate in {mate_before}.')
    if bad_move and facts['opponent_mate_bad'] and not facts['opponent_mate_good']:
        reply = facts['opponent_mate_bad'][0]
        text = (f'{best_name} stops the immediate threat of {reply}.' if positive else
                f'{bad_name} allows checkmate with {reply}. {best_name} stops it.')
        add('mate_allowed', 'mate_defense', 1, 3, 119, text)

    root = _free_root_capture(board, best, facts)
    if root and not root['line_recaptured']:
        victim = _piece(root['victim'])
        free = root['free']
        label = 'free ' if free else ''
        if root['recaptures'] and not free:
            refutations = [(root['after'].san(m), _legal_mating_refutation(root['after'], m))
                           for m in root['recaptures']]
            mating = next(((rec, mate) for rec, mate in refutations if mate), None)
        else:
            mating = None
        if mating:
            statement = (f'{best_name} wins the {victim}: {mating[0]} fails to '
                         f'{mating[1]} checkmate.')
            add('capture_mate_trap', 'mating_net', 2, 3, 114, statement)
        elif free or (len(good['steps']) >= 2 and
                      good['material_delta'] >= VALUES[root['victim'].piece_type]):
            if _queen_activity(board, best, root):
                statement = f'{best_name} captures a {label}{victim} and keeps your queen active.'
            else:
                statement = f'{best_name} takes a {label}{victim}.'
            same_root_capture = bool(bad and any(c['ply'] == 0 and c['by_solver']
                                       and c['square'] == _s(best.to_square)
                                       for c in bad['captures']))
            if bad_move and not positive and not same_root_capture:
                window = _missed_window(board, best, bad_move, best.to_square, facts)
                comparison = (f'{bad_name} misses that opportunity.{window}' if window else
                              f'{bad_name} passes up the capture.')
            else:
                comparison = ''
            add('clean_capture', 'capture_loose_piece' if free else 'missed_capture', 0,
                3 if free else 2, 101 if free else 86, statement, comparison)

    # Root exchanges: evaluate the *values surrendered*, not merely whether
    # capture/recapture occurred. A rook for a minor piece is an exchange
    # sacrifice; a queen for lesser material is a material sacrifice. These
    # are never described as neutral trades or automatic blunders. Evidence
    # requires a legal immediate recapture in the stored principal variation.
    immediate_exchange = next((ex for ex in good['exchanges']
                               if ex['first']['ply'] == 0 and ex['recapture']['ply'] == 1
                               and ex['first']['by_solver']), None)
    if immediate_exchange:
        take = immediate_exchange['first']
        give = immediate_exchange['recapture']
        deficit = give['value'] - take['value']
        if deficit >= 2:
            if give['value'] == 5 and take['value'] == 3:
                add('exchange_sacrifice', 'exchange_sacrifice', 1, 3, 110,
                    f'{best_name} sacrifices the exchange: a rook for a '
                    f'{take["piece"]}. The trade gives up material for the resulting position.')
            else:
                add('material_sacrifice', 'material_sacrifice', 1, 3, 109,
                    f'{best_name} sacrifices a {give["piece"]} for a '
                    f'{take["piece"]}. This is a deliberate material investment, not an even trade.')
        elif abs(deficit) <= 1:
            # Only call it simplification when no immediate tactic provides
            # a more specific explanation. Quiet trades are otherwise too
            # easily mislabeled as wins or losses of hanging pieces.
            early_consequence = any(f.impact >= 75 and f.horizon <= 1 for f in findings)
            if not early_consequence:
                add('simplification', 'simplification', 1, 2, 66,
                    f'{best_name} exchanges {give["piece"]} for {take["piece"]}, '
                    'simplifying without an immediate material gain.')

    if bad_move and after_bad and facts['opponent_mate_bad'] == [] and _trade_for_castling(board, bad_move, facts):
        if root and root['free']:
            point = (f'{best_name} takes a free {_piece(root["victim"])} and preserves castling; '
                     f'{bad_name} allows a queen trade that forces your king to recapture.'
                     if positive else
                     f'{bad_name} allows a queen trade that forces your king to recapture, '
                     f'giving up castling. {best_name} takes a free {_piece(root["victim"])} instead.')
            add('queen_trade_castling', 'king_safety', 2, 2, 109, point)
        else:
            add('queen_trade_castling', 'king_safety', 2, 2, 89,
                f'{bad_name} permits a queen trade that forces your king to move, losing castling rights.')

    if facts['our_mate_good'] and not facts['our_mate_bad']:
        add('mate_threat', 'mate_threat', 0, 3, 95,
            f'{best_name} threatens {facts["our_mate_good"][0]} checkmate if the threat goes unanswered.')

    double = _double_attack(board, best, facts)
    if double:
        targets = sorted(double['targets'], key=lambda t: -t[2])
        if double['checking']:
            square, piece, _ = targets[0]
            mechanism = f'checks the king and attacks the {_piece(piece)} on {square}'
        else:
            (sq1, pc1, _), (sq2, pc2, _) = targets[:2]
            mechanism = (f'attacks the {_piece(pc1)} on {sq1} and '
                         f'the {_piece(pc2)} on {sq2} at once')
        add('double_attack', 'fork', 2, 2, 107,
            f'{best_name} {mechanism}; the follow-up wins material.')

    sacrifice = _pawn_sacrifice_plan(board, best, facts)
    if sacrifice:
        add('pawn_sacrifice_plan', 'material_sacrifice', 3, 2, 104,
            f'{best_name} offers a pawn to open a route for your bishop, which later captures the pawn on {sacrifice}.')

    if bad and _exchange_loss(facts) and (gap is None or gap >= 60):
        add('exchange_loss', 'exchange', 2, 2, 99,
            f'{bad_name} loses the exchange in the analyzed continuation—a rook for a minor piece.')

    if bad_move and bad and (gap is None or gap >= 60):
        for lost in sorted(_material_losses(facts), key=lambda c: (c['ply'], -c['value'])):
            sq = lost['root_square']
            piece = board.piece_at(chess.parse_square(sq)) if sq else None
            if not piece:
                continue
            is_root_piece = lost['ply'] == 1 and bad_move.from_square == chess.parse_square(sq)
            victim_square = _s(bad_move.to_square) if is_root_piece else (sq or '')
            statement = game_continuation(
                bad_name, lost['san'],
                f'capture your {_piece(piece)} on {victim_square}' if victim_square else
                f'capture your {_piece(piece)}',
                ply=lost['ply'], alternative=(facts.get('contrast_role') == 'tempting alternative'))
            add('material_loss', differential_loss_motif(board, bad_move, lost), lost['ply'], 2,
                (111 if is_root_piece and lost['value'] >= 5 else
                 100 if is_root_piece else 88 if lost['value'] >= 3 else 64),
                statement)
            break
        if not any(f.key == 'material_loss' for f in findings):
            bp = board.piece_at(bad_move.from_square)
            if bp and bp.piece_type != chess.KING:
                cap = _find_legal_capture(after_bad, bad_move.to_square)
                if cap and not after_bad.is_attacked_by(board.turn, bad_move.to_square) and not bad['steps']:
                    add('loose_mover', 'dont_hang_pieces', 1, 1, 54,
                        f'{bad_name} leaves your {_piece(bp)} exposed to {cap}.')

    if facts['shared_loss']:
        lost = facts['shared_loss'][0]
        if facts['new_targets']:
            t = facts['new_targets'][0]
            add('counterattack', 'counterattack', 0, 2, 88,
                f'{best_name} counterattacks the opponent’s {t["piece"]} on {t["square"]}, '
                f'rather than trying to save the {lost["piece"]} on {lost["square"]}.')
        elif root:
            add('countercapture', 'counterattack', 0, 2, 87,
                f'{best_name} wins material in return for the {lost["piece"]} that falls in both lines.')

    if bad and bad_move and len(bad['steps']) >= 3 and len(good['steps']) >= 3:
        pin_bad = _new_pin(board, [s['uci'] for s in bad['steps']], color=board.turn)
        pin_good = _new_pin(board, [s['uci'] for s in good['steps']], color=board.turn)
        if pin_bad and pin_bad[0] <= 2 and not pin_good and (gap is None or gap >= 60):
            ply, pinned, sq = pin_bad
            add('future_pin', 'pin', ply, 2, 28,
                f'{bad_name} allows your {_piece(pinned)} on {_s(sq)} to become pinned.')

    if bad_move and gap is not None and gap >= 65:
        mover = board.piece_at(bad_move.from_square)
        if mover and mover.piece_type == chess.KNIGHT:
            before, after = _central_control(board, bad_move)
            abandoned = before - after
            origin_rank, target_rank = chess.square_rank(bad_move.from_square), chess.square_rank(bad_move.to_square)
            retreat = target_rank < origin_rank if board.turn == chess.WHITE else target_rank > origin_rank
            _, best_control = _central_control(board, best)
            if retreat and abandoned and len(best_control) >= len(after):
                add('passive_knight', 'piece_activity', 0, 1, 45,
                    f'{bad_name} retreats the knight and gives up control of {_s(sorted(abandoned)[0])}. '
                    f'{best_name} keeps the piece more active.')

    # Only use exchange as a headline when the trade has some strategic
    # relevance; an arbitrary capture/recapture later in a line isn't a reason.
    # A remote capture/recapture is not a root explanation. If none of the
    # candidate findings is sufficiently local, leave the question open for
    # more analysis instead of fabricating a far-future tactical cause.

    # Downweight non-mating remote incidents. Exception: a verified pawn
    # sacrifice whose bishop payoff is causally rooted in the pawn advance.
    findings.sort(key=lambda f: (
        -(f.impact - (65 if f.horizon > 2 and f.key not in {'pawn_sacrifice_plan', 'mate_forced'} else 0)),
        f.horizon, -f.confidence, f.key))
    return findings, facts


def causal_coaching(board, best, played, best_pv=None, played_pv=None,
                    alternatives=None, best_cp=None, played_cp=None,
                    category='', mate_before=None, facts=None):
    """One chess idea, one compact natural explanation, optional useful contrast.

    Explanations make concrete chess claims only when backed by legal board
    states or a saved variation; unproven hypotheses are not prose.
    """
    findings, facts = evidence_findings(board, best, played, best_pv,
                                        played_pv, alternatives, best_cp,
                                        played_cp, category, mate_before, facts)
    if not findings:
        return None
    winner = findings[0]
    if facts['positive'] and winner.key in {'material_loss', 'passive_knight', 'loose_mover',
                                           'future_pin', 'exchange_loss'}:
        return None
    text = winner.assessment
    # The alternative is only mentioned when it illuminates the *same* idea.
    if winner.comparison and winner.comparison.casefold() not in text.casefold():
        text += ' ' + winner.comparison
    # No generic moral, no 'why move X is better' labels, no centipawn filler.
    return {'text': text, 'motif': winner.motif, 'finding': winner,
            'evidence_level': winner.confidence, 'alternatives': findings}
