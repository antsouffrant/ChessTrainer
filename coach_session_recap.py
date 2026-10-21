"""Fast, evidence-grounded post-solve coaching from recorded board attempts.

Does no engine work: position evaluation and stored PVs are authoritative.
Messages are idempotent per puzzle/solve session and never shown pre-solve.
"""
import json
import re

SESSION_KEY = re.compile(r'^[a-zA-Z0-9_-]{8,100}$')


def valid_session_key(value):
    return isinstance(value, str) and bool(SESSION_KEY.fullmatch(value))


def _saved_continuation(row, move_uci):
    """Compatibility view of the ONE canonical branch selector.

    The position's PV/ply selection lives in continuation_coach; this module
    only handles attempt persistence and recap lifecycle.
    """
    from continuation_coach import branch_evidence, _main_fact
    line = branch_evidence(row, move_uci)
    if not line:
        return None
    plies = line.get('plies') or []
    fact = _main_fact(plies[0]) if plies else None
    result = dict(line)
    result['fact'] = fact.get('text') if fact else None
    result['reply_san'] = plies[1].get('san') if len(plies) > 1 else None
    return result


def cached_move(row, move_uci):
    """Only label a move cached when it heads a saved analyzed line."""
    if _saved_continuation(row, move_uci) is not None:
        return True
    for name in ('best_pv_uci', 'played_pv_uci'):
        value = row[name] if name in row.keys() else None
        if value:
            tokens = str(value).replace(',', ' ').split()
            if tokens and tokens[0] == move_uci:
                return True
    alternatives = row['alternative_pvs_json'] if 'alternative_pvs_json' in row.keys() else None
    if alternatives:
        try:
            for line in json.loads(alternatives):
                if not isinstance(line, dict):
                    continue
                moves = line.get('pv_uci') or line.get('moves_uci') or line.get('pv')
                if isinstance(moves, str):
                    moves = moves.split()
                if isinstance(moves, list) and moves and moves[0] == move_uci:
                    return True
        except (ValueError, TypeError):
            pass
    return move_uci in {row['best_move_uci'], row['played_move_uci']}


def record_board_attempt(conn, row, *, session_key, move_uci, move_san,
                         correct, quality=None):
    """Record only server-verified legal moves. No additional Stockfish calls."""
    if not valid_session_key(session_key):
        return False
    quality = quality or {}
    conn.execute('''INSERT INTO coach_board_attempts
        (position_id, session_key, move_uci, move_san, correct,
         from_saved_line, eval_cp, mate, best_reply_san, verified_pv_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (row['id'], session_key, move_uci, move_san, int(bool(correct)),
         int(cached_move(row, move_uci)), quality.get('eval_cp'),
         quality.get('mate'), quality.get('best_reply_san'),
         json.dumps(quality.get('pv_uci', [])[:12])
         if isinstance(quality.get('pv_uci'), list) else None))
    return True


def _comment_for_attempt(attempt, best_san, *, model_explanation='', saved_line=None,
                         position_row=None):
    """One nuanced, root-aligned continuation explanation, never a threshold label."""
    from continuation_coach import explain_attempt
    row = position_row or {'best_move_uci': (attempt['move_uci']
                          if attempt['correct'] and attempt['move_san'] == best_san else ''),
                          'explanatory_lines_json': None}
    if saved_line is not None and position_row is None:
        # Compatibility with older callers providing a minimal saved line.
        data = {'lines': [dict(saved_line, root_uci=attempt['move_uci'])]}
        row = {'best_move_uci':attempt['move_uci'] if attempt['correct'] else '',
               'explanatory_lines_json':json.dumps(data)}
    return explain_attempt(row, attempt, best_san, saved_explanation=model_explanation)


def _build_recap(conn, position_row, session_key):
    attempts = conn.execute('''SELECT id, move_uci, move_san, correct, from_saved_line,
                eval_cp, mate, best_reply_san, verified_pv_json
        FROM coach_board_attempts WHERE position_id=? AND session_key=? ORDER BY id''',
        (position_row['id'], session_key)).fetchall()
    if not attempts or not attempts[-1]['correct']:
        raise ValueError('No verified completed solve in this session')
    best_san = position_row['best_move_san'] or position_row['best_move_uci']
    saved_explanation = position_row['coach_explanation'] or ''
    solving = _comment_for_attempt(attempts[-1], best_san,
                                   model_explanation=saved_explanation, position_row=position_row)
    solving['origin'] = 'solving'
    solving['purpose'] = 'explanation'
    # Latest move per root in this solve. A solution is not a failed attempt.
    attempts_by_root = {}
    for attempt in attempts[:-1]:
        if not attempt['correct']:
            attempts_by_root[attempt['move_uci']] = attempt
    current_notes = []
    for attempt in attempts_by_root.values():
        note = _comment_for_attempt(attempt, best_san,
                                    model_explanation=saved_explanation, position_row=position_row)
        note['origin'] = 'attempt'
        note['purpose'] = 'learning'
        current_notes.append(note)
    # Earlier training attempts remain distinct from this solve, deduplicated
    # by chess root for feedback identity and avoiding repeated cards.
    known = set(attempts_by_root) | {attempts[-1]['move_uci']}
    evaluation_session = str(session_key).startswith('eval_')
    earlier = conn.execute('''SELECT move_uci, move_san, correct, from_saved_line,
                eval_cp, mate, best_reply_san, verified_pv_json
        FROM coach_board_attempts WHERE position_id=? AND correct=0 AND id<?
          AND (?=0 OR session_key=?)
        ORDER BY id DESC''', (position_row['id'], attempts[0]['id'], int(evaluation_session), session_key)).fetchall()
    earlier_notes = []
    for attempt in earlier:
        root = attempt['move_uci']
        if root in known: continue
        known.add(root)
        note = _comment_for_attempt(attempt, best_san,
                                    model_explanation=saved_explanation, position_row=position_row)
        note['origin'] = 'previous_session'
        note['purpose'] = 'learning'
        earlier_notes.append(note)
    # At most one card per root move. An attempted-move learning card takes
    # precedence over a duplicate original-game card, including past sessions.
    game_uci = position_row['played_move_uci']
    game_notes = []
    if game_uci and game_uci not in known and _saved_continuation(position_row, game_uci):
        game_mode = str(position_row['learning_mode'] or '').lower() if 'learning_mode' in position_row.keys() else ''
        game_category = str(position_row['category'] or '').lower() if 'category' in position_row.keys() else ''
        game_is_best = (game_uci == position_row['best_move_uci'] or
                        ((game_mode in {'correct', 'excellent', 'brilliant', 'creative'} or
                          game_category in {'correct', 'excellent', 'brilliant', 'creative'}) and
                         game_category not in {'missed_checkmate','allowed_checkmate','major_blunder'}))
        game_note = _comment_for_attempt({
            'move_uci':game_uci,
            'move_san':position_row['played_move_san'] or game_uci,
            'correct':int(game_is_best), 'from_saved_line':1,
        }, best_san, model_explanation=saved_explanation, position_row=position_row)
        game_note['origin'] = 'game'
        game_note['purpose'] = 'explanation' if game_is_best else 'learning'
        game_notes.append(game_note)
    comments = [solving, *current_notes, *earlier_notes, *game_notes]
    content = '\n'.join(f"{c['move_san']}: {c['text']}" for c in comments)
    evidence = {'kind':'solved_attempt_recap', 'explanation_version':7,
                'session_key':session_key, 'source':'root_aligned_chess_interpretation',
                'attempt_count':len(attempts), 'attempts':[dict(a) for a in attempts],
                'attempt_comments':comments, 'model_explanation':saved_explanation,
                'coaching_version':position_row['coaching_version'] or ''}
    return content, json.dumps(evidence)


def refresh_saved_recaps(conn, position_row):
    """Upgrade older solved recaps in place, without touching thumbs records.

    No new Stockfish work. Only successful sessions are upgraded; historical
    messages and primary-position feedback remain tied to their existing IDs.
    """
    rows = conn.execute('''SELECT csr.session_key, cm.id, cm.structured_json
        FROM coach_solve_recaps csr JOIN coach_messages cm ON cm.id=csr.message_id
        WHERE csr.position_id=?''', (position_row['id'],)).fetchall()
    upgraded = 0
    for r in rows:
        try:
            structured = json.loads(r['structured_json'] or '{}')
            if not isinstance(structured, dict): structured = {}
        except (TypeError, ValueError):
            structured = {}
        if structured.get('kind') != 'solved_attempt_recap':
            continue
        # Never rewrite an old model's rated conversation in place.
        if structured.get('coaching_version') != position_row['coaching_version']:
            continue
        if structured.get('explanation_version', 0) >= 7:
            continue
        try:
            content, evidence = _build_recap(conn, position_row, r['session_key'])
        except ValueError:
            continue
        conn.execute('UPDATE coach_messages SET content=?, structured_json=? WHERE id=?',
                     (content, evidence, r['id']))
        upgraded += 1
    if upgraded:
        conn.commit()
    return upgraded


def save_solved_recap(conn, position_row, *, session_key, evaluation_solved=False):
    """Persist one concise post-solve report; never synthesize new chess claims."""
    if not valid_session_key(session_key):
        raise ValueError('Invalid solve-session identifier')
    if not position_row['learned'] and not evaluation_solved:
        raise PermissionError('Solve the position before viewing the coaching recap')
    previous = conn.execute('''SELECT cm.id, cm.content, cm.structured_json
        FROM coach_solve_recaps csr JOIN coach_messages cm ON cm.id=csr.message_id
        WHERE csr.position_id=? AND csr.session_key=?''',
        (position_row['id'], session_key)).fetchone()
    stale_previous = False
    if previous:
        try:
            old_record = json.loads(previous['structured_json'] or '{}')
        except (TypeError, ValueError):
            old_record = {}
        stale_previous = old_record.get('coaching_version') != position_row['coaching_version']
        if not stale_previous:
            refresh_saved_recaps(conn, position_row)
            current = conn.execute('SELECT content, structured_json FROM coach_messages WHERE id=?', (previous['id'],)).fetchone()
            return dict(id=previous['id'], content=current['content'],
                        structured_json=current['structured_json'], created=False)

    content, evidence = _build_recap(conn, position_row, session_key)
    from adaptive_coach import get_or_create_thread
    thread_id = get_or_create_thread(conn, position_row['id'], position_row['account_id'])
    cursor = conn.execute('''INSERT INTO coach_messages(thread_id, role, content, structured_json)
        VALUES (?, 'assistant', ?, ?)''', (thread_id, content, evidence))
    if stale_previous:
        # Retain the original message and its feedback history, but point this
        # session to a NEW message for the current version. Never overwrite a
        # historical rated explanation or reuse its approval state.
        conn.execute('''UPDATE coach_solve_recaps SET message_id=?
            WHERE position_id=? AND session_key=?''',
            (cursor.lastrowid, position_row['id'], session_key))
    else:
        conn.execute('''INSERT INTO coach_solve_recaps(position_id, session_key, message_id)
            VALUES (?, ?, ?)''', (position_row['id'], session_key, cursor.lastrowid))
    conn.commit()
    return dict(id=cursor.lastrowid, content=content,
                structured_json=evidence, created=True)
