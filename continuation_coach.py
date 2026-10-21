"""One-branch chess explanation: decisions, replies and demonstrated consequences.

This is intentionally a post-solve, engine-free interpretation layer. Every
assertion about a continuation is attached to that attempted root move, never
borrowed from the recommended line. Only legally replayed PVs are eligible.
"""
import json
import re

SIGNIFICANT = {
    'checkmate': 120, 'promotion': 110, 'mate_threat': 97,
    'discovered_check': 94, 'discovered_attack': 90,
    'fork': 89, 'trapped_piece': 87, 'pin': 77,
    'threat_neutralized': 74, 'passed_pawn': 69,
    'attack_loose_piece': 63, 'capture': 68,
    'check': 44, 'exchange': 30, 'check_evasion': 12,
}


def _json(data, fallback):
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (TypeError, ValueError):
            return fallback
    return data if data is not None else fallback


def _val(row, field, default=None):
    try:
        return row[field]
    except (KeyError, IndexError, TypeError):
        return default


def _effects(ply):
    if not isinstance(ply, dict):
        return []
    effects = ply.get('effects', [])
    return [e for e in effects if isinstance(e, dict) and e.get('text')] if isinstance(effects, list) else []


def _main_fact(ply, *, omit=('exchange',)):
    facts = [e for e in _effects(ply) if e.get('kind') not in omit]
    return max(facts, key=lambda x: SIGNIFICANT.get(x.get('kind'), 0), default=None)


def _phrase(fact):
    return str(fact.get('text') or '').strip().rstrip('.') if fact else ''


def _move_mentioned(text, san):
    """A saved solution paragraph owns a reply if it already names that ply."""
    if not text or not san:
        return False
    tokens = re.findall(r"[a-z0-9]+", str(san).casefold())
    move = ''.join(tokens)
    # Ignore SAN punctuation but not the move's destination or piece letter.
    normalized = re.sub(r"[^a-z0-9]+", "", str(text).casefold())
    return bool(move and move in normalized)


def _reply_from_opponents_perspective(text):
    """Invert the explicit *opponent's* possessive in recorded board events.

    Some historical/pre-v81 effect strings already use learner-facing 'your',
    so never blindly flip all pronouns: doing that would attribute a captured
    learner rook to the opponent. Only invert the explicit mover-relative
    'the opponent’s' phrase emitted by the shared board-events detector.
    """
    return re.sub(r"the opponent[’']s", 'your', text, flags=re.I)


def _opponent_consequence(fact, reply_san):
    """Only observed, informative reply events are suitable for narration."""
    if not fact or fact.get('kind') in {'check_evasion', 'exchange'}:
        return None
    observation = _phrase(fact)
    if not observation or not reply_san:
        return None
    if observation.startswith(reply_san):
        observation = observation[len(reply_san):].lstrip(' ,').rstrip('.')
    if not observation:
        return None
    observation = _reply_from_opponents_perspective(observation)
    return f'Your opponent can respond with {reply_san}, which {observation}.'


def _selected_lines(position_row, move_uci):
    raw = _json(_val(position_row, 'explanatory_lines_json'), {})
    lines = raw.get('lines', []) if isinstance(raw, dict) else []
    matches = [l for l in lines if isinstance(l, dict) and l.get('root_uci') == move_uci
               and isinstance(l.get('plies'), list) and l.get('plies')
               and l['plies'][0].get('uci', move_uci) == move_uci]
    order = {'recommended': 3, 'played': 3, 'alternative': 3,
             'coaching_best_reply': 2, 'coaching_game_reply': 2, 'tested_reply': 1}
    return sorted(matches, key=lambda l: (order.get(l.get('role'), 0), len(l['plies'])), reverse=True)


def branch_evidence(row, move_uci, attempt=None):
    """Find exactly this attempted branch and optionally replay verified PV.

    Evidence saved during Positions/Coaching is first choice; independently
    verified training moves can supply a new root-locked PV. No engine calls.
    """
    candidates = _selected_lines(row, move_uci)
    if candidates and len(candidates[0].get('plies', [])) >= 2:
        return candidates[0]
    attempt = attempt or {}
    pv = _json(_val(attempt, 'verified_pv_json'), [])
    if not isinstance(pv, list) or not pv or pv[0] != move_uci:
        pv = []
    if not pv:
        if candidates:
            return candidates[0]
        return None
    try:
        import chess
        from explanatory_evidence import describe_variation
        board = chess.Board(row['fen'])
        root = chess.Move.from_uci(move_uci)
        if root in board.legal_moves:
            verified = describe_variation(board, pv, 'verified_attempt',
                                          _val(attempt, 'eval_cp'), _val(attempt, 'mate'),
                                          first_move=root)
            if verified.get('root_uci') == move_uci and verified.get('plies'):
                return verified
    except (ImportError, ValueError, KeyError, TypeError):
        pass
    return candidates[0] if candidates else None


def _root_board_fact(row, move_uci):
    """Use existing chess-fact producers rather than reimplementing detectors.

    We generate this only when no saved solution explanation and no saved root
    event is available. No engine call is made here.
    """
    try:
        import chess
        from check_response import check_response
        from explanatory_evidence import board_events
        from root_explanation import root_move_impact
        board = chess.Board(row['fen'])
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            return None
        evasion = check_response(board, move)
        if evasion:
            return evasion['evidence'].rstrip('.')
        facts = board_events(board, move, [move])
        informative = [fact for fact in facts if fact.get('kind') not in ('check_evasion', 'exchange')]
        if informative:
            return _phrase(max(informative, key=lambda fact: SIGNIFICANT.get(fact.get('kind'), 0)))
        root = root_move_impact(board, move)
        return _phrase(root) if isinstance(root, dict) else None
    except (ImportError, ValueError, KeyError, TypeError):
        return None


def _root_claim(san, primary, subsequent_moves=()):
    """Only the root sentence from proactive coaching may enter this branch.

    Comparisons, PV claims and captures belonging to later plies are produced
    exclusively by the verified chronological event renderer below.
    """
    if not primary: return ''
    lead = re.split(r'(?<=[.!?])\s+', str(primary).strip(), maxsplit=1)[0]
    if any(other and str(other).rstrip('+#') != str(san).rstrip('+#')
           and _move_mentioned(lead, other) for other in subsequent_moves):
        return ''  # This sentence crosses ply boundaries.
    return lead if _move_mentioned(lead, san) else ''


def _sequential_event(plies, index):
    """Favor concrete ply effects, with explicit capture/recapture detection."""
    ply = plies[index]
    effects = _effects(ply)
    if not effects: return None
    if index and any(e['kind']=='capture' for e in effects):
        last = plies[index-1]
        uci = str(ply.get('uci') or '')
        prior_uci = str(last.get('uci') or '')
        prior_capture = any(e['kind'] in ('capture','recapture') for e in _effects(last))
        if (prior_capture and len(uci)>=4 and len(prior_uci)>=4
                and uci[2:4] == prior_uci[2:4]):
            capture = next(e for e in effects if e['kind']=='capture')
            return dict(capture, kind='recapture',
                        text=f"{ply.get('san', '')} recaptures on {uci[2:4]}")
    preferred = ('checkmate', 'recapture', 'promotion', 'discovered_check',
                 'fork', 'discovered_attack', 'trapped_piece', 'capture',
                 'check_evasion', 'mate_threat', 'pin', 'threat_neutralized', 'attack_loose_piece',
                 'check', 'passed_pawn')
    for kind in preferred:
        hit = next((event for event in effects if event['kind'] == kind), None)
        if hit: return hit
    return None


def _sentence_for_ply(fact, san, ply_idx):
    if fact.get('kind') == 'check_evasion':
        phrase = 'moves the king out of check' if san.startswith('K') else 'gets out of check'
    else:
        phrase = _phrase(fact)
    if not phrase: return ''
    if ply_idx and phrase.startswith(san):
        phrase = phrase[len(san):].lstrip(' ,').rstrip('.')
    if not ply_idx:
        return phrase.rstrip('.') + '.'
    if ply_idx % 2:
        phrase = _reply_from_opponents_perspective(phrase)
        return f'Your opponent can respond with {san}' + (f', which {phrase}' if phrase else '') + '.'
    return f'You can then play {san}' + (f', which {phrase}' if phrase else '') + '.'


def _checking_cycle(branch):
    """Classify observed recurring checks; never infer a forced perpetual.

    Threefold uses exact side/castling/en-passant board identities. The
    initial position counts, but hypothetical future Stockfish lines do not.
    Older evidence without per-ply board identities is not proof of a cycle.
    """
    if not isinstance(branch, dict): return None
    plies = branch.get('plies') or []
    start = branch.get('start_fen')
    if not start or len(plies) < 5: return None
    key = lambda fen: tuple(str(fen).split()[:4]) if fen else ()
    seen = {key(start):1}
    checks = [0, 0]
    repeats = False
    threefold = False
    for i, ply in enumerate(plies):
        # Board-event check markers are mover-relative and verified by replay.
        if any(e.get('kind') in ('check','discovered_check')
               for e in _effects(ply)):
            checks[i % 2] += 1
        position = key(ply.get('fen_after'))
        if len(position) != 4: return None
        seen[position] = seen.get(position, 0) + 1
        if seen[position] >= 2: repeats = True
        if seen[position] >= 3: threefold = True
    if max(checks) < 3: return None
    if threefold:
        return ('The saved continuation repeats a position three times during '
                'a series of checks; a draw by threefold repetition can be claimed.')
    if repeats:
        return ('The checking sequence returns to an earlier position, '
                'suggesting a perpetual-check possibility; this saved line '
                'does not establish a forced draw.')
    return ('This line contains a sequence of checks, but no repeated position '
            'has been verified; perpetual check is not established.')


def _missed_immediate_mate(row, uci, san):
    """Only call it a missed mate when the best *single move* is mate."""
    if uci == _val(row, 'best_move_uci'): return ''
    best = _val(row, 'best_move_uci')
    try:
        import chess
        board = chess.Board(row['fen'])
        move = chess.Move.from_uci(best)
        if move in board.legal_moves:
            after = board.copy(stack=False); after.push(move)
            if after.is_checkmate():
                return f'{san} overlooks immediate checkmate with {board.san(move)}.'
    except (ImportError, KeyError, ValueError, TypeError, AttributeError):
        pass
    return ''


def explain_attempt(row, attempt, best_san, *, saved_explanation=''):
    """Compose only ONE root-locked PV in chronological ply order.

    Correct lines explain demonstrated value. Wrong lines teach the concrete
    refutation first, with an honest generic fallback only if evidence is
    genuinely insufficient. Never attach an invented reply or later effect.
    """
    san = _val(attempt, 'move_san') or _val(attempt, 'move_uci') or 'Move'
    uci = _val(attempt, 'move_uci')
    correct = bool(_val(attempt, 'correct'))
    is_best = uci == _val(row, 'best_move_uci')
    branch = branch_evidence(row, uci, attempt)
    plies = branch.get('plies', []) if branch else []
    check_cycle = _checking_cycle(branch)
    # Saved proactive prose may contain an out-of-order narrative. Extract
    # ONLY its immediate first sentence. Subsequent claims come from PV plies.
    lead = _root_claim(san, saved_explanation, [p.get('san') for p in plies[1:]]) if correct and is_best else ''
    root_fact = _sequential_event(plies, 0) if plies else None
    sentences = []
    missed_mate = _missed_immediate_mate(row, uci, san) if not correct else ''
    if missed_mate: sentences.append(missed_mate)
    if not correct and root_fact and root_fact.get('kind') in {'attack_loose_piece', 'passed_pawn', 'pin'} and len(plies)>1:
        # A quiet surface feature distracts from a demonstrated reply.
        if _sequential_event(plies, 1): root_fact = None
    if lead:
        sentences.append(lead)
    elif root_fact:
        if root_fact.get('kind') == 'check_evasion':
            root = _root_board_fact(row, uci)
            sentences.append((root or f'{san} resolves the check').rstrip('.') + '.')
        else:
            sentences.append(_sentence_for_ply(root_fact, san, 0))
    else:
        root = _root_board_fact(row, uci)
        if root: sentences.append(root.rstrip('.') + '.')

    # The answer to a failed move should foreground the opponent's refutation.
    # Show up to four *chronological* plies. An immediate recapture (especially
    # on the solver's next turn) is always worth mentioning.
    root_was_capture = any(event['kind'] in ('capture', 'recapture') for event in _effects(plies[0])) if plies else False
    for i in range(1, min(len(plies), 5)):
        fact = _sequential_event(plies, i)
        if not fact:
            continue
        if check_cycle and fact.get('kind') == 'check':
            continue  # Replace repetitive standalone check facts with one finding.
        if i == 1 and root_was_capture and fact['kind'] == 'recapture':
            pass  # Already prioritized by _sequential_event.
        message = _sentence_for_ply(fact, plies[i].get('san') or '', i)
        if message and not sentences and i == 1:
            message = f'After {san}, ' + message[0].lower() + message[1:]
        if message and not any(message == old for old in sentences):
            sentences.append(message)
    if check_cycle:
        sentences.append(check_cycle)
    # If a saved line is absent, a verified but uncategorized response should
    # never be marketed as a forced tactical refutation.
    if not sentences:
        if correct:
            sentences.append(f'{san} is the solving move, but the saved analysis does not establish a specific tactical reason.')
        else:
            sentences.append(f'{san} falls short of the solving continuation; the saved analysis does not establish a specific tactical refutation.')
    return {'move_san':san, 'move_uci':uci, 'correct':correct,
            'purpose':'explanation' if correct else 'learning',
            'cached':bool(branch) or bool(_val(attempt,'from_saved_line')),
            'source':'saved_solution' if lead else
                     ('saved_analysis' if branch or _val(attempt,'from_saved_line') else 'verified_attempt'),
            'reply_san':plies[1].get('san') if len(plies)>1 else _val(attempt,'best_reply_san'),
            'text':' '.join(sentences),
            'evidence_role':branch.get('role') if branch else None}
