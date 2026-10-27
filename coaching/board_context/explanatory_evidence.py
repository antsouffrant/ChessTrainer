"""Compact, board-grounded explanation evidence for saved engine variations.

Separate observed board facts from engine assessment. MultiPV and root-constrained
PV lines are samples, not proofs that every defense loses. This module is also
used by metadata refresh without starting Stockfish.
"""
from __future__ import annotations

import json
import chess
from coaching.board_context.pv_reasoning import legal_pv, fork_evidence
from coaching.board_context.discovered_counterfactuals import revealed_lines
from coaching.conceptual_understanding.decision_context import decision_facts, mate_in_one, unanswered_mate_threat

EVIDENCE_VERSION = 2
VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
          chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def _newly_loose(before, after, victim_color):
    found = []
    for sq, piece in after.piece_map().items():
        if piece.color != victim_color or piece.piece_type == chess.KING:
            continue
        if (after.is_attacked_by(not victim_color, sq)
                and not after.is_attacked_by(victim_color, sq)
                and (not before.is_attacked_by(not victim_color, sq)
                     or before.is_attacked_by(victim_color, sq))):
            found.append((VALUES[piece.piece_type], sq, piece))
    return sorted(found, reverse=True)


def _passed(board, sq, color):
    piece = board.piece_at(sq)
    if not piece or piece.color != color or piece.piece_type != chess.PAWN:
        return False
    file, rank = chess.square_file(sq), chess.square_rank(sq)
    return not any(abs(chess.square_file(x) - file) <= 1 and
                   (chess.square_rank(x) > rank if color == chess.WHITE
                    else chess.square_rank(x) < rank)
                   for x in board.pieces(chess.PAWN, not color))


def board_events(before, move, continuation=()):
    """Observable move effects, with their *actual* mover as the perspective."""
    if move not in before.legal_moves:
        return []
    side = before.turn
    san = before.san(move)
    victim = (chess.Piece(chess.PAWN, not side) if before.is_en_passant(move)
              else before.piece_at(move.to_square) if before.is_capture(move) else None)
    after = before.copy(stack=False)
    after.push(move)
    result = []

    def add(kind, text, motif, weight, **extras):
        result.append({'kind': kind, 'text': text, 'motif': motif,
                       'weight': weight, **extras})

    if after.is_checkmate():
        add('checkmate', f'{san} ends the game in checkmate', 'mating_net', 125)
    elif after.is_check():
        add('check', f'{san} gives check', 'forcing_moves', 46)
    if not after.is_check() and not after.is_game_over():
        potential_mates = unanswered_mate_threat(after)
        if potential_mates:
            add('mate_threat', f'{san} threatens mate next turn with '
                f'{potential_mates[0]} if the opponent does not respond',
                'mate_threat', 85)
    if victim:
        piece_name = chess.piece_name(victim.piece_type)
        add('capture', f'{san} captures the {piece_name} on {chess.square_name(move.to_square)}',
            'missed_capture', 68 + min(VALUES[victim.piece_type], 9),
            piece=piece_name, square=chess.square_name(move.to_square),
            piece_value=VALUES[victim.piece_type])
    if move.promotion:
        add('promotion', f'{san} promotes the pawn to a {chess.piece_name(move.promotion)}',
            'promotion_tactic', 95)
    if before.is_check() and not after.is_checkmate():
        add('check_evasion', f'{san} legally answers the check', 'defensive_resource', 35)
    for line in revealed_lines(before, move)[:2]:
        add(line['kind'], f'{san} reveals the {line["revealed_piece"]} on '
            f'{chess.square_name(line["attacker_square"])} attacking the '
            f'{line["target_piece"]} on {chess.square_name(line["target_square"])}',
            'discovered_attack', 90 if line['kind'] == 'discovered_check' else 55)
    # Forks need a forcing check or supporting PV; geometric double attacks
    # alone do not establish a winning tactical event.
    fork = fork_evidence(before, move, continuation)
    if fork and fork.get('strong') and (fork.get('check_fork') or fork.get('line_supported')):
        names = [f'{chess.piece_name(p.piece_type)} on {chess.square_name(sq)}'
                 for sq, p in fork['targets'][:2]]
        if len(names) == 2:
            add('fork', f'{san} attacks the {names[0]} and {names[1]} together',
                'fork', 83 if fork.get('check_fork') else 67)
    for sq, piece in after.piece_map().items():
        if (piece.color != side and piece.piece_type != chess.KING
                and before.piece_at(sq) == piece
                and not before.is_pinned(not side, sq)
                and after.is_pinned(not side, sq)):
            add('pin', f'{san} pins the {chess.piece_name(piece.piece_type)} on '
                f'{chess.square_name(sq)} to its king', 'pin', 52)
            break
    loose = _newly_loose(before, after, not side)
    if loose:
        _, sq, piece = loose[0]
        add('attack_loose_piece', f'{san} attacks or exposes the opponent’s undefended '
            f'{chess.piece_name(piece.piece_type)} on {chess.square_name(sq)}',
            'hanging_piece', 60, perspective='attack')
    # A trapped piece must have no legal escape when its side is actually to
    # move. Never infer a trap from pinned geometry or while under check.
    if not after.is_check():
        attacked = [(sq, pc) for sq, pc in after.piece_map().items()
                    if pc.color != side and pc.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)
                    and after.is_attacked_by(side, sq)]
        for sq, piece in sorted(attacked, key=lambda item: VALUES[item[1].piece_type], reverse=True)[:3]:
            escapes = [m for m in after.legal_moves if m.from_square == sq
                       and not after.is_attacked_by(side, m.to_square)]
            if not escapes and not after.is_attacked_by(not side, sq):
                add('trapped_piece', f'{san} leaves the {chess.piece_name(piece.piece_type)} '
                    f'on {chess.square_name(sq)} without a safe escape', 'trapped_piece', 64)
                break
    pawn = after.piece_at(move.to_square)
    if (pawn and pawn.color == side and pawn.piece_type == chess.PAWN
            and _passed(after, move.to_square, side)):
        add('passed_pawn', f'{san} advances a passed pawn toward promotion', 'passed_pawn', 44)
    # Explicit exchange evidence requires an actual recapture in the saved
    # continuation, not merely a capture onto a guarded square.
    line = legal_pv(before, continuation, first_move=move, max_plies=3)
    if len(line) > 1 and victim and after.is_capture(line[1]) and line[1].to_square == move.to_square:
        responder = after.san(line[1])
        add('exchange', f'{san} is answered by {responder} in the analyzed exchange',
            'simplification', 68)
    saved = []
    for sq, piece in before.piece_map().items():
        if piece.color != side or piece.piece_type == chess.KING:
            continue
        if (after.piece_at(sq) == piece and before.is_attacked_by(not side, sq)
                and not after.is_attacked_by(not side, sq)):
            saved.append((VALUES[piece.piece_type], sq, piece))
    if saved:
        _, sq, piece = max(saved)
        add('threat_neutralized', f'{san} removes the attack on the '
            f'{chess.piece_name(piece.piece_type)} on {chess.square_name(sq)}',
            'defensive_resource', 48)
    return result


def describe_variation(board, raw, role, eval_cp=None, mate=None, depth=None,
                       first_move=None, source='saved_engine', max_plies=10):
    """Standardized root-aligned PV and its board events, ready for persistence."""
    moves = legal_pv(board, raw, first_move=first_move, max_plies=max_plies)
    replay = board.copy(stack=False)
    plies = []
    for i, move in enumerate(moves):
        san = replay.san(move)
        facts = board_events(replay, move, moves[i:])
        # A recapture is observable only relative to the PRECEDING ply. Do
        # not call a capture a recapture merely because the target is guarded.
        if (i and replay.is_capture(move) and move.to_square == moves[i-1].to_square
                and any(event['kind'] in ('capture', 'recapture')
                        for event in plies[-1]['effects'])):
            victim = replay.piece_at(move.to_square)
            if victim is not None:
                facts = [event for event in facts if event['kind'] != 'capture']
                facts.append({'kind': 'recapture', 'text':
                    f'{san} recaptures the {chess.piece_name(victim.piece_type)} on '
                    f'{chess.square_name(move.to_square)}', 'motif':'exchange',
                    'piece':chess.piece_name(victim.piece_type), 'weight': 112})
        replay.push(move)
        # Preserve board identity for checked repetitions. Repeated checks
        # alone never justify claiming perpetual check or a drawn position.
        plies.append({'ply': i, 'uci': move.uci(), 'san': san,
                      'by_solver': replay.turn != board.turn,
                      'effects': facts, 'fen_after': replay.fen(),
                      'threefold_claimable': replay.can_claim_threefold_repetition()})
    return {'role': role, 'source': source, 'eval_cp': eval_cp, 'mate': mate,
            'depth': depth, 'root_uci': moves[0].uci() if moves else None,
            'start_fen': board.fen(), 'pv_uci': [m.uci() for m in moves], 'plies': plies}




def position_context(board):
    """Snapshot of directly visible threats, independent of a guessed motif."""
    side = board.turn
    attacked, loose, pins = [], [], []
    for square, piece in board.piece_map().items():
        if piece.color != side or piece.piece_type == chess.KING:
            continue
        descriptor = {'square': chess.square_name(square),
                      'piece': chess.piece_name(piece.piece_type),
                      'value': VALUES[piece.piece_type]}
        if board.is_attacked_by(not side, square):
            attacked.append(descriptor)
            if not board.is_attacked_by(side, square):
                loose.append(descriptor)
        if board.is_pinned(side, square):
            pins.append(descriptor)
    enemy_attacked, enemy_loose = [], []
    for square, piece in board.piece_map().items():
        if piece.color == side or piece.piece_type == chess.KING:
            continue
        item = {'square': chess.square_name(square), 'piece': chess.piece_name(piece.piece_type),
                'value': VALUES[piece.piece_type]}
        if board.is_attacked_by(side, square):
            enemy_attacked.append(item)
            if not board.is_attacked_by(not side, square):
                enemy_loose.append(item)
    return {'in_check': board.is_check(),
            'mate_in_one_available': mate_in_one(board),
            'opponent_mate_threat_if_unanswered': unanswered_mate_threat(board),
            'opponent_attacked': sorted(enemy_attacked, key=lambda x: -x['value'])[:8],
            'opponent_loose': sorted(enemy_loose, key=lambda x: -x['value'])[:8],
            'attacked': sorted(attacked, key=lambda x: -x['value'])[:8],
            'loose': sorted(loose, key=lambda x: -x['value'])[:8],
            'pinned': sorted(pins, key=lambda x: -x['value'])[:8],
            'legal_moves': board.legal_moves.count()}


def explanation_variations(board, best, played, best_pv, played_pv,
                           best_cp=None, played_cp=None, best_mate=None,
                           played_mate=None, alternatives=None, probe=None, coaching_probes=None):
    """2-3 non-duplicated explanatory lines: best, actual, strongest contrast.

    A probe is an extra engine-tested reply to the actual move. For positive
    training, a ranked root alternative is more meaningful than another reply
    to the same root move. Preserve the engine's score provenance and do not
    pretend the PV demonstrates a forced continuation.
    """
    lines = []
    if best in board.legal_moves:
        lines.append(describe_variation(board, best_pv, 'recommended', best_cp,
                                        best_mate, first_move=best))
    if played in board.legal_moves and played != best:
        lines.append(describe_variation(board, played_pv, 'played', played_cp,
                                        played_mate, first_move=played))
    options = alternatives
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except (ValueError, TypeError):
            options = []
    options = options if isinstance(options, list) else []
    # Negative lessons benefit more from a tested alternative reply; positive
    # lessons benefit more from a separate ranked root move.
    if played != best and isinstance(probe, dict) and played in board.legal_moves:
        probe_pv = probe.get('pv_uci') or []
        line = describe_variation(board, probe_pv, 'tested_reply', probe.get('eval_cp'),
                                  probe.get('mate'), probe.get('depth'), first_move=played,
                                  source='engine_reply_probe')
        if len(line['pv_uci']) >= 2 and not any(x['pv_uci'][:2] == line['pv_uci'][:2] for x in lines):
            lines.append(line)
    for option in options:
        if not isinstance(option, dict):
            continue
        try:
            mv = chess.Move.from_uci(option['move_uci'])
        except (ValueError, TypeError, KeyError):
            continue
        if mv in board.legal_moves and mv != best and (played == best or mv != played):
            line = describe_variation(board, option.get('pv_uci'), 'alternative',
                                      option.get('eval_cp'), option.get('mate'),
                                      option.get('depth'), first_move=mv)
            if line['pv_uci']:
                lines.append(line)
            break
    if len(lines) < 3 and isinstance(probe, dict) and played in board.legal_moves:
        probe_pv = probe.get('pv_uci') or []
        line = describe_variation(board, probe_pv, 'tested_reply', probe.get('eval_cp'),
                                  probe.get('mate'), probe.get('depth'), first_move=played,
                                  source='engine_reply_probe')
        if (len(line['pv_uci']) >= 2 and
                not any(x['pv_uci'][:2] == line['pv_uci'][:2] for x in lines)):
            lines.append(line)
    # Independently tested replies are supplementary: never replace the
    # deeper principal variations saved during Analyze. Retain only legal,
    # nonduplicate branches for future explanation/regression inspection.
    if isinstance(coaching_probes, dict):
        for branch in coaching_probes.get('branches', []):
            if not isinstance(branch, dict):
                continue
            try:
                root = chess.Move.from_uci(branch['root_uci'])
            except (KeyError, ValueError, TypeError):
                continue
            if root not in board.legal_moves:
                continue
            for tested in branch.get('lines', [])[:2]:
                role = 'coaching_best_reply' if branch.get('role') == 'best' else 'coaching_game_reply'
                line = describe_variation(board, tested.get('pv_uci'), role,
                                          tested.get('eval_cp'), tested.get('mate'),
                                          tested.get('depth'), first_move=root,
                                          source='proactive_stockfish')
                if (len(line['pv_uci']) >= 2 and
                        not any(item['pv_uci'][:2] == line['pv_uci'][:2] for item in lines)):
                    lines.append(line)
    grounded = decision_facts(board, best, played, best_pv, played_pv,
                              alternatives, best_cp, played_cp) if best in board.legal_moves else None
    # Keep the lightweight summary, not duplicate PV traces, in persistence.
    grounded_summary = None
    if grounded:
        grounded_summary = {k: v for k, v in grounded.items()
                            if k not in {'good', 'bad'}}
    return {'version': EVIDENCE_VERSION, 'perspective': 'training_side',
            'context': position_context(board), 'decision_context': grounded_summary,
            'assessment': {'recommended_cp': best_cp, 'played_cp': played_cp,
                           'difference_cp': (max(0, best_cp - played_cp)
                                             if best_cp is not None and played_cp is not None else None),
                           'recommended_mate': best_mate, 'played_mate': played_mate},
            'lines': [x for x in lines if x['pv_uci']][:7]}


def decode_variations(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    return raw if isinstance(raw, dict) and raw.get('version') in (1, EVIDENCE_VERSION) and isinstance(raw.get('lines'), list) else None
