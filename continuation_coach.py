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


def explain_attempt(row, attempt, best_san, *, saved_explanation=''):
    """Render the learner's *one* attempted continuation from typed evidence.

    Proactive coaching owns the root explanation for the saved best move.
    The reply interpreter owns only *new* observed opponent/follow-up effects.
    They do not separately narrate the root, and a bare legal reply without an
    explanatory consequence is not worth a sentence. This is the only place
    that composes the post-solve move commentary; no Stockfish calls occur.
    """
    san = _val(attempt, 'move_san') or _val(attempt, 'move_uci') or 'Move'
    uci = _val(attempt, 'move_uci')
    correct = bool(_val(attempt, 'correct'))
    is_best = uci == _val(row, 'best_move_uci')
    branch = branch_evidence(row, uci, attempt)
    plies = branch.get('plies', []) if branch else []
    reply_san = (plies[1].get('san') if len(plies) > 1 else None) or _val(attempt, 'best_reply_san')
    root_fact = _main_fact(plies[0]) if plies else None
    opponent_fact = _main_fact(plies[1], omit=('check_evasion', 'exchange')) if len(plies) > 1 else None
    followup_fact = _main_fact(plies[2], omit=('check_evasion', 'exchange')) if len(plies) > 2 else None
    followup_san = plies[2].get('san') if len(plies) > 2 else None

    # A proactive explanation can compare the saved *game* line to the best
    # move; that comparison cannot be transplanted into a different root.
    primary = ''
    if correct and is_best and saved_explanation:
        played_san = _val(row, 'played_move_san')
        lower = saved_explanation.lower()
        mentions_other = ('in the game you played' in lower or
                          ('instead of ' in lower and played_san and played_san != san) or
                          (played_san and played_san != san and
                           _move_mentioned(saved_explanation, played_san)))
        if not mentions_other:
            primary = saved_explanation.strip()
        else:
            # A saved proactive paragraph can contain *multiple* roots:
            # "Nxd7 takes a rook. Rxh4 misses it. After Ra7, ...".
            # That comparative history cannot share a card with a Bc7 reply
            # observed only on Nxd7's continuation. Keep just an independent
            # opening claim explicitly identifying this root; the wrong branch
            # gets its own message from its own verified evidence below.
            lead = re.split(r'(?<=[.!?])\s+', saved_explanation.strip(), maxsplit=1)[0]
            if _move_mentioned(lead, san) and not _move_mentioned(lead, played_san):
                primary = lead

    sentences = []
    # Single ownership: either the saved *complete* proactive lead, OR one
    # observed immediate root fact, never both. Semantic synonyms such as
    # 'moves the king out of check'/'legally answers the check' cannot repeat.
    if primary:
        sentences.append(primary)
    elif root_fact:
        if root_fact.get('kind') == 'check_evasion':
            # Prefer an instructive legal check response when the board is
            # accessible; never narrate the tautology 'legally answers'.
            root = _root_board_fact(row, uci)
            sentences.append((root or f'{san} resolves the check').rstrip('.') + '.')
        else:
            sentences.append(_phrase(root_fact) + '.')
    else:
        root = _root_board_fact(row, uci)
        if root:
            sentences.append(root.rstrip('.') + '.')

    # A reply must have something demonstrable to teach. 'After Kh1, Kh8' by
    # itself is a PV listing, not coaching. Likewise, ignore a reply already
    # explained by the proactive paragraph, which may phrase it differently.
    if reply_san and opponent_fact and not _move_mentioned(primary, reply_san):
        reply_comment = _opponent_consequence(opponent_fact, reply_san)
        if reply_comment:
            sentences.append(reply_comment)

    # A solver's third-ply action may demonstrate the tactical payoff. Do not
    # attribute it to the opponent or reproduce a line already explained.
    if followup_fact and followup_san and not _move_mentioned(primary, followup_san):
        if followup_fact.get('kind') in {
                'checkmate', 'promotion', 'fork', 'discovered_attack',
                'discovered_check', 'capture', 'mate_threat', 'trapped_piece'}:
            outcome = _phrase(followup_fact)
            if outcome.startswith(followup_san):
                outcome = outcome[len(followup_san):].lstrip(' ,').rstrip('.')
            if outcome:
                sentences.append(f'You can then continue with {followup_san}, which {outcome}.')

    if not sentences:
        # Honest evidence gap without narrating the puzzle-grading threshold or
        # claiming that a merely sampled opponent reply is a refutation.
        sentences.append(f'The saved analysis of {san} does not establish a specific tactical or positional consequence.')
    return {'move_san': san, 'move_uci': uci, 'correct': correct,
            'cached': bool(branch) or bool(_val(attempt, 'from_saved_line')),
            'source': 'saved_solution' if primary else
                      ('saved_analysis' if branch or _val(attempt, 'from_saved_line') else 'verified_attempt'),
            'reply_san': reply_san, 'text': ' '.join(sentences),
            'evidence_role': branch.get('role') if branch else None}
