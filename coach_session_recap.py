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
    comments = [_comment_for_attempt(a, best_san, model_explanation=saved_explanation,
                                     position_row=position_row) for a in attempts]
    # Attempts from earlier completed sessions deserve their own blue messages
    # too. Only include ones made BEFORE this solve, never retroactively attach
    # future moves when an older recap is refreshed. One card per distinct
    # move is enough; the approval identity is root-locked across sessions.
    current_roots = {a['move_uci'] for a in attempts}
    earlier = conn.execute('''SELECT move_uci, move_san, correct, from_saved_line,
                eval_cp, mate, best_reply_san, verified_pv_json
        FROM coach_board_attempts WHERE position_id=? AND correct=0 AND id<?
        ORDER BY id DESC''', (position_row['id'], attempts[0]['id'])).fetchall()
    earlier_roots = set()
    earlier_notes = []
    for a in earlier:
        root = a['move_uci']
        if root in current_roots or root in earlier_roots:
            continue
        earlier_roots.add(root)
        note = _comment_for_attempt(a, best_san,
                                    model_explanation=saved_explanation,
                                    position_row=position_row)
        note['origin'] = 'previous_session'
        earlier_notes.append(note)
    comments[:0] = reversed(earlier_notes)
    # The move from the original game is a useful earlier continuation even
    # when the learner did not happen to replay it in this solve session.
    # Include only saved, root-locked evidence, and never label an untested
    # original-game move as a failed training attempt.
    game_uci = position_row['played_move_uci']
    solved_uci = attempts[-1]['move_uci']
    if (game_uci and game_uci != solved_uci and game_uci != position_row['best_move_uci']
            and all(note['move_uci'] != game_uci for note in comments)
            and _saved_continuation(position_row, game_uci)):
        game_note = _comment_for_attempt({
            'move_uci':game_uci,
            'move_san':position_row['played_move_san'] or game_uci,
            'correct':0, 'from_saved_line':1,
        }, best_san, model_explanation=saved_explanation,
           position_row=position_row)
        game_note['origin'] = 'game'
        comments.insert(0, game_note)
    content = '\n'.join(f"{c['move_san']}: {c['text']}" for c in comments)
    evidence = {'kind':'solved_attempt_recap', 'explanation_version':5,
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
        if structured.get('kind') != 'solved_attempt_recap' or structured.get('explanation_version', 0) >= 5:
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


def save_solved_recap(conn, position_row, *, session_key):
    """Persist one concise post-solve report; never synthesize new chess claims."""
    if not valid_session_key(session_key):
        raise ValueError('Invalid solve-session identifier')
    if not position_row['learned']:
        raise PermissionError('Solve the position before viewing the coaching recap')
    previous = conn.execute('''SELECT cm.id, cm.content, cm.structured_json
        FROM coach_solve_recaps csr JOIN coach_messages cm ON cm.id=csr.message_id
        WHERE csr.position_id=? AND csr.session_key=?''',
        (position_row['id'], session_key)).fetchone()
    if previous:
        refresh_saved_recaps(conn, position_row)
        current = conn.execute('SELECT content, structured_json FROM coach_messages WHERE id=?', (previous['id'],)).fetchone()
        return dict(id=previous['id'], content=current['content'],
                    structured_json=current['structured_json'], created=False)

    content, evidence = _build_recap(conn, position_row, session_key)
    from adaptive_coach import get_or_create_thread
    thread_id = get_or_create_thread(conn, position_row['id'], position_row['account_id'])
    cursor = conn.execute('''INSERT INTO coach_messages(thread_id, role, content, structured_json)
        VALUES (?, 'assistant', ?, ?)''', (thread_id, content, evidence))
    conn.execute('''INSERT INTO coach_solve_recaps(position_id, session_key, message_id)
        VALUES (?, ?, ?)''', (position_row['id'], session_key, cursor.lastrowid))
    conn.commit()
    return dict(id=cursor.lastrowid, content=content,
                structured_json=evidence, created=True)
