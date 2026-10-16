"""Explain the meaningful *difference* between alternatives at one decision.

The two lines share the same starting FEN. A continuation is evidence of a
possible tactical consequence, not proof every reply is forced. Keep near-term
consequences distinct from incidental distant motifs.
"""
from __future__ import annotations

import json
import chess
from pv_reasoning import legal_pv, fork_evidence, continuation_facts

_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
           chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def _alternatives(raw):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return []
    return raw if isinstance(raw, list) else []


def _line(board, move, raw):
    if move is None or move not in board.legal_moves:
        return []
    return legal_pv(board, raw, first_move=move, max_plies=10)


def _critical_events(board, moves, horizon=6):
    replay = board.copy(stack=False)
    events = []
    for ply, move in enumerate(moves[:horizon]):
        if move not in replay.legal_moves:
            break
        actor = replay.turn
        is_capture = replay.is_capture(move)
        victim = (chess.Piece(chess.PAWN, not actor) if replay.is_en_passant(move)
                  else replay.piece_at(move.to_square) if is_capture else None)
        san = replay.san(move)
        before = replay.copy(stack=False)
        replay.push(move)
        events.append({'ply': ply, 'san': san, 'move': move, 'actor': actor,
                       'capture': victim, 'capture_square': move.to_square,
                       'after': replay.copy(stack=False), 'before': before,
                       'mate': replay.is_checkmate(),
                       'check': replay.is_check()})
    return events


def _forced_reply_problem(board, failing_line, better_line):
    """A reply to the inferior root move reveals near-term tactical harm.

    Never claim the reply is forced; a legal Stockfish PV is one demonstrated
    choice. Forks count only when they survive their own immediate-recapture
    check and target materially different valuable pieces.
    """
    if len(failing_line) < 2:
        return None
    bad = _critical_events(board, failing_line)
    good = _critical_events(board, better_line)
    side = board.turn
    for e in bad[1:4:2]:
        if e['actor'] == side:
            continue
        # Differentiate an actual checkmating continuation from a claim of
        # proven forced mate (which requires a mate score, elsewhere).
        if e['mate'] and not any(x['mate'] and x['actor'] != side for x in good):
            return ('mate', f'{e["san"]} checkmates in the analyzed reply.')
        rest = failing_line[e['ply']:]
        fork = fork_evidence(e['before'], e['move'], rest)
        if fork and fork.get('strong') and (fork.get('line_supported') or e['check']):
            victim_names = []
            for square, piece in fork['targets'][:2]:
                name = 'king' if piece.piece_type == chess.KING else chess.piece_name(piece.piece_type)
                if name not in victim_names:
                    victim_names.append(name)
            if len(victim_names) >= 2:
                # If the same fork is available after the better root move,
                # it cannot explain the comparison.
                if not any(x['san'] == e['san'] and x['actor'] != side for x in good):
                    return ('fork', f'{e["san"]} forks your {victim_names[0]} and {victim_names[1]}.')
    return None


def _material_difference(board, worse, better):
    """Require a *net* loss in the competing line, not simply a trade."""
    if len(worse) < 2 or len(better) < 2:
        return None
    bad = continuation_facts(board, [m.uci() for m in worse[:6]], first_move=worse[0], max_plies=6)
    good = continuation_facts(board, [m.uci() for m in better[:6]], first_move=better[0], max_plies=6)
    n = min(len(bad['events']), len(good['events']), 6)
    if n < 2:
        return None
    bad_net = bad['events'][n-1]['net']
    good_net = good['events'][n-1]['net']
    if good_net - bad_net < 2:
        return None
    losses = [e for e in bad['events'][1:n] if not e['ours'] and e['capture'] and
              e['captured'] is not None and _VALUES.get(e['captured'].piece_type, 0) >= 3]
    if not losses:
        return None
    # Avoid calling a balanced exchange a lost piece. A net material
    # difference is required at the same horizon above.
    event = max(losses, key=lambda x: x['piece_value'])
    piece = chess.piece_name(event['captured'].piece_type)
    return ('material', f'{event["san"]} wins your {piece} in the analyzed continuation.')


def decisive_contrast(board, best, played, best_pv=None, played_pv=None,
                      alternatives=None, category='', best_eval_cp=None):
    """Return one human-facing root-move contrast, or None if unproved.

    Positive training: compare the move played to an independently evaluated
    runner-up. Negative training: compare the played move with the best line.
    No alternative -> no claim that an excellent move is unique.
    """
    if best is None or best not in board.legal_moves:
        return None
    positive = category in {'excellent_move', 'brilliant_move', 'correct_move', 'correct'}
    best_line = _line(board, best, best_pv)
    if positive and played == best:
        options = []
        for entry in _alternatives(alternatives):
            # Don't claim superiority over an essentially equivalent choice.
            # A ranking alone is not proof of a meaningful practical gap.
            if best_eval_cp is not None and entry.get('eval_cp') is not None:
                try:
                    if int(best_eval_cp) - int(entry['eval_cp']) < 70:
                        continue
                except (ValueError, TypeError):
                    continue
            if not isinstance(entry, dict):
                continue
            try:
                other = chess.Move.from_uci(entry['move_uci'])
            except (ValueError, KeyError, TypeError):
                continue
            if other != best and other in board.legal_moves:
                options.append((other, _line(board, other, entry.get('pv_uci'))))
        for alternative, inferior in options[:2]:
            if not inferior or not best_line:
                continue
            finding = (_forced_reply_problem(board, inferior, best_line)
                       or _material_difference(board, inferior, best_line))
            if finding:
                san = board.san(alternative)
                return {'kind': finding[0],
                        'text': f'After the alternative {san}, {finding[1][0].lower() + finding[1][1:]} {board.san(best)} avoids that problem.',
                        'alternative_san': san}
        return None
    if played is None or played == best or played not in board.legal_moves:
        return None
    bad_line = _line(board, played, played_pv)
    if not best_line or not bad_line:
        return None
    finding = (_forced_reply_problem(board, bad_line, best_line)
               or _material_difference(board, bad_line, best_line))
    if not finding:
        return None
    played_san = board.san(played)
    best_san = board.san(best)
    return {'kind': finding[0],
            'text': f'After {played_san}, {finding[1][0].lower() + finding[1][1:]} {best_san} avoids that problem.',
            'alternative_san': played_san}
