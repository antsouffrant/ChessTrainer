"""Player learning event log and reports (separate from Coach quality feedback).

A puzzle is not included in an activity session until it has a legal attempt.
Each session survives browser navigation and is closed on success. Resetting a
solved puzzle permits a fresh session without erasing prior results.
"""
from __future__ import annotations

import csv
import io
import math


def _safe_seconds(value):
    try:
        seconds = float(value)
        if math.isfinite(seconds) and 0 <= seconds <= 86400:
            return round(seconds, 3)
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def record_attempt(conn, row, *, move_uci, correct, elapsed_seconds=None,
                   lesson_key=None, opening_key=None, max_solve_seconds=300):
    """Append a legal attempt and update the current session atomically.

    Call within the same transaction as training_positions.attempts updates.
    Never create a session on mere display/hover or for invalid chess moves.
    """
    position_id = int(row['id'])
    session = conn.execute('''
        SELECT * FROM player_solve_sessions
        WHERE position_id=? AND solved_at IS NULL AND abandoned_at IS NULL ORDER BY id DESC LIMIT 1
    ''', (position_id,)).fetchone()
    if session is None:
        motif = conn.execute('''
            SELECT concept_key FROM position_concepts
            WHERE position_id=? AND is_primary=1 ORDER BY confidence DESC LIMIT 1
        ''', (position_id,)).fetchone()
        cur = conn.execute('''
            INSERT INTO player_solve_sessions (
                position_id, account_id, job_id, game_id, opening_key,
                opening_name, primary_motif_key, learning_mode, lesson_key, attempts,
                max_solve_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ''', (position_id, row['account_id'], row['job_id'], row['game_id'],
              opening_key or row['opening_key'], row['opening_name'],
              motif['concept_key'] if motif else None, row['learning_mode'],
              (lesson_key or '').strip() or None, float(max_solve_seconds)))
        session_id = cur.lastrowid
        previous_attempts = 0
        previous_seconds = 0.0
    else:
        session_id = session['id']
        previous_attempts = int(session['attempts'])
        previous_seconds = float(session['active_seconds'] or 0)

    # Missing/invalid timing is an unknown, not zero-second solving time.
    delta = _safe_seconds(elapsed_seconds)
    elapsed = previous_seconds + (delta if delta is not None else 0)
    attempt_number = previous_attempts + 1
    conn.execute('''
        INSERT INTO player_solve_attempts(session_id, position_id, attempt_number,
             move_uci, correct, active_seconds_delta)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (session_id, position_id, attempt_number, move_uci, int(bool(correct)), delta))
    if correct:
        # Only count valid, non-zero, reasonably short active solve times.
        # A long-open tab still records a solve, but never biases the time mean.
        cutoff = float(session['max_solve_seconds']) if session is not None else float(max_solve_seconds)
        valid = (delta is not None and 0 < elapsed <= cutoff and
                 conn.execute('''SELECT COUNT(*) AS n FROM player_solve_attempts
                     WHERE session_id=? AND active_seconds_delta IS NULL''', (session_id,)).fetchone()['n'] == 0)
        conn.execute('''
            UPDATE player_solve_sessions
            SET attempts=?, active_seconds=?, solved_at=CURRENT_TIMESTAMP,
                first_try_solved=?, solve_seconds=?, timing_status=?
            WHERE id=?
        ''', (attempt_number, elapsed, int(attempt_number == 1),
              round(elapsed, 3) if valid else None,
              'valid' if valid else 'excluded', session_id))
    else:
        conn.execute('''
            UPDATE player_solve_sessions SET attempts=?, active_seconds=? WHERE id=?
        ''', (attempt_number, elapsed, session_id))
    return {'session_id': session_id, 'session_attempt': attempt_number,
            'first_try_solved': bool(correct and attempt_number == 1)}


def abandon_session(conn, position_id):
    """Explicitly reset/retire an incomplete attempt cycle, preserving history."""
    conn.execute(
        "UPDATE player_solve_sessions SET abandoned_at=CURRENT_TIMESTAMP "
        "WHERE position_id=? AND solved_at IS NULL AND abandoned_at IS NULL",
        (int(position_id),),
    )


def reset_player_records(conn, job_id=None):
    """Delete Player practice events without changing curriculum or Coach data.

    Attempt events cascade via the session foreign key. The caller commits.
    """
    if job_id is not None:
        session_count = conn.execute(
            'SELECT COUNT(*) FROM player_solve_sessions WHERE job_id=?', (job_id,)
        ).fetchone()[0]
        attempt_count = conn.execute(
            'SELECT COUNT(*) FROM player_solve_attempts WHERE session_id IN '
            '(SELECT id FROM player_solve_sessions WHERE job_id=?)', (job_id,)
        ).fetchone()[0]
        conn.execute('DELETE FROM player_solve_sessions WHERE job_id=?', (job_id,))
    else:
        session_count = conn.execute('SELECT COUNT(*) FROM player_solve_sessions').fetchone()[0]
        attempt_count = conn.execute('SELECT COUNT(*) FROM player_solve_attempts').fetchone()[0]
        conn.execute('DELETE FROM player_solve_sessions')
    return {'sessions': session_count, 'attempts': attempt_count}


def _filters(args):
    clauses, params = [], []
    for key, expr in (
        ('job_id', 'tp.job_id'), ('position_id', 'tp.id'), ('opening_key', 'tp.opening_key'),
        ('primary_motif_key', 'pc.concept_key'), ('learning_mode', 'tp.learning_mode'),
    ):
        value = str(args.get(key, '') or '').strip()
        if not value:
            continue
        if key in ('job_id', 'position_id'):
            try:
                value = int(value)
                if value <= 0: continue
            except ValueError:
                continue
        clauses.append(f'{expr}=?')
        params.append(value)
    return (' AND '.join(clauses) if clauses else '1=1'), params


def player_positions(conn, args):
    """One row per position; events are separately joined in reports to avoid duplication."""
    where, params = _filters(args)
    # Primary motif only, so secondary motif labels never multiply a position.
    return [dict(x) for x in conn.execute(f'''
        SELECT tp.id AS position_id, tp.job_id, tp.game_id, tp.fen,
               tp.learned, tp.learning_mode, tp.opening_key, tp.opening_name,
               tp.move_number, tp.game_date, tp.estimated_rating,
               pc.concept_key AS primary_motif_key,
               lc.name AS primary_motif_name, j.date_range, a.username,
               tp.attempts AS legacy_attempts
        FROM training_positions tp
        JOIN analysis_jobs j ON j.id=tp.job_id
        JOIN accounts a ON a.id=j.account_id
        LEFT JOIN position_concepts pc ON pc.position_id=tp.id AND pc.is_primary=1
        LEFT JOIN learning_concepts lc ON lc.key=pc.concept_key
        WHERE {where}
        ORDER BY tp.id
    ''', params).fetchall()]


def player_sessions(conn, position_ids):
    if not position_ids:
        return []
    # Chunk for SQLite variable count limits on large game lists.
    rows = []
    for i in range(0, len(position_ids), 800):
        ids = position_ids[i:i+800]
        marker = ','.join('?' for _ in ids)
        rows += [dict(x) for x in conn.execute(f'''
            SELECT ps.*, lc.name AS motif_name,
                   tp.opening_name AS current_opening_name,
                   tp.fen, tp.move_number, tp.game_date
            FROM player_solve_sessions ps
            LEFT JOIN learning_concepts lc ON lc.key=ps.primary_motif_key
            JOIN training_positions tp ON tp.id=ps.position_id
            WHERE ps.position_id IN ({marker}) ORDER BY ps.id
        ''', ids).fetchall()]
    return sorted(rows, key=lambda session:session['id'])


def _round(value):
    return round(value, 1) if value is not None else None


def _mean(values):
    return _round(sum(values) / len(values)) if values else None


def _stats(positions, sessions):
    solved = [s for s in sessions if s['solved_at']]
    timed = [float(s['solve_seconds']) for s in solved if s['solve_seconds'] is not None]
    distinct_attempted = len({s['position_id'] for s in sessions})
    firsts = sum(bool(s['first_try_solved']) for s in solved)
    # "First-time" means the first ever practice session for a distinct puzzle,
    # not a later replay that may be easier because the answer is remembered.
    earliest = {}
    for session in sorted(sessions, key=lambda item: item['id']):
        earliest.setdefault(session['position_id'], session)
    first_encounter_success = sum(bool(s['first_try_solved']) for s in earliest.values())
    return {
        'total_positions': len(positions),
        'learned_positions': sum(bool(p['learned']) for p in positions),
        'attempted_positions': distinct_attempted,
        'attempted_sessions': len(sessions),
        'total_attempts': sum(int(s['attempts']) for s in sessions),
        'solved_sessions': len(solved),
        'first_try_solves': firsts,
        'first_encounter_solves': first_encounter_success,
        'first_try_rate': _round(100 * first_encounter_success / len(earliest)) if earliest else None,
        'first_try_rate_sessions': _round(100 * firsts / len(sessions)) if sessions else None,
        'first_try_rate_solved': _round(100 * firsts / len(solved)) if solved else None,
        'avg_attempts_per_solve': _mean([int(s['attempts']) for s in solved]),
        'avg_solve_seconds': _mean(timed),
        'timed_solves': len(timed),
        'excluded_solve_times': len(solved) - len(timed),
    }


def _breakdown(positions, sessions, key, label, limit=80):
    position_groups = {}
    for p in positions:
        group_id = p.get(key) or '__unspecified__'
        position_groups.setdefault(group_id, []).append(p)
    session_groups = {}
    for s in sessions:
        group_id = s.get(key) or '__unspecified__'
        session_groups.setdefault(group_id, []).append(s)
    # Use current position metadata for dashboard facets. Sessions store their
    # original motif/opening snapshot separately for future historical analysis.
    result=[]
    for group_id, group_positions in position_groups.items():
        ids = {p['position_id'] for p in group_positions}
        group_sessions = [s for s in sessions if s['position_id'] in ids]
        name = group_positions[0].get(label) or ('Unclassified' if key=='primary_motif_key' else 'Unknown')
        result.append({'key': group_id, 'name': name, **_stats(group_positions, group_sessions)})
    return sorted(result, key=lambda r: (-r['attempted_sessions'], -r['total_positions'], r['name']))[:limit]


def summary(conn, args):
    positions = player_positions(conn, args)
    sessions = player_sessions(conn, [p['position_id'] for p in positions])
    done = [s for s in sessions if s['solved_at']]
    buckets = [{'label': str(n) if n < 5 else '5+',
                'count': sum((int(s['attempts']) == n if n < 5 else int(s['attempts']) >= 5) for s in done)}
               for n in (1, 2, 3, 4, 5)]
    days = {}
    earliest = {}
    for s in sorted(sessions, key=lambda event: event['id']):
        earliest.setdefault(s['position_id'], s['id'])
    for s in sessions:
        day = str(s['started_at'] or '')[:10]
        item = days.setdefault(day, {'date':day, 'attempted_sessions':0, 'solves':0,
                                     'first_try_solves':0, 'first_encounters':0,
                                     'first_encounter_solves':0})
        item['attempted_sessions'] += 1
        if earliest[s['position_id']] == s['id']:
            item['first_encounters'] += 1
            item['first_encounter_solves'] += int(bool(s['first_try_solved']))
        if s['solved_at']:
            item['solves'] += 1
            item['first_try_solves'] += int(bool(s['first_try_solved']))
    return {
        'overview': _stats(positions, sessions),
        'histogram': buckets,
        'by_motif': _breakdown(positions, sessions, 'primary_motif_key', 'primary_motif_name'),
        'by_opening': _breakdown(positions, sessions, 'opening_key', 'opening_name'),
        'by_mode': _breakdown(positions, sessions, 'learning_mode', 'learning_mode'),
        'over_time': [days[d] for d in sorted(days)],
        'recent': list(reversed(sessions[-60:])),
    }


def facets(conn):
    jobs = [dict(r) for r in conn.execute('''
        SELECT j.id AS value, a.username || ' · ' || j.date_range || ' (#' || j.id || ')' AS label
        FROM analysis_jobs j JOIN accounts a ON a.id=j.account_id ORDER BY j.id DESC
    ''')]
    openings = [dict(r) for r in conn.execute('''
        SELECT opening_key AS value, MAX(opening_name) AS label FROM training_positions
        WHERE opening_key IS NOT NULL AND opening_key<>'' GROUP BY opening_key ORDER BY label
    ''')]
    motifs = [dict(r) for r in conn.execute('''
        SELECT lc.key AS value, lc.name AS label FROM learning_concepts lc
        WHERE EXISTS (SELECT 1 FROM position_concepts pc WHERE pc.concept_key=lc.key AND pc.is_primary=1)
        ORDER BY lc.name
    ''')]
    return {'game_lists': jobs, 'openings': openings, 'motifs': motifs,
            'learning_modes': [{'value': r['learning_mode'], 'label': r['learning_mode'].replace('_',' ').title()}
                               for r in conn.execute('SELECT DISTINCT learning_mode FROM training_positions ORDER BY learning_mode')]}


SESSION_COLUMNS = ['session_id', 'position_id','job_id','game_id','fen','opening_key','opening_name',
                   'primary_motif_key','motif_name','learning_mode','lesson_key','move_number',
                   'attempts','first_try_solved','started_at','solved_at','active_seconds',
                   'solve_seconds','timing_status','max_solve_seconds','abandoned_at']
ATTEMPT_COLUMNS = ['attempt_id','session_id','position_id','job_id','game_id','fen','move_uci',
                   'attempt_number','correct','active_seconds_delta','attempted_at','primary_motif_key','opening_key']


def export_rows(conn, args, kind='sessions'):
    positions = player_positions(conn, args)
    by_id = {p['position_id']:p for p in positions}
    sessions = player_sessions(conn, list(by_id))
    if kind == 'sessions':
        return [{**s, 'session_id':s['id']} for s in sessions]
    by_session = {s['id']:s for s in sessions}
    result=[]
    for i in range(0, len(by_session), 800):
        ids = list(by_session)[i:i+800]
        if not ids: continue
        marker = ','.join('?' for _ in ids)
        for a in conn.execute(f'SELECT * FROM player_solve_attempts WHERE session_id IN ({marker}) ORDER BY id', ids):
            sess=by_session[a['session_id']]
            result.append({'attempt_id': a['id'], 'session_id':a['session_id'],
                           'position_id':a['position_id'], 'job_id':sess['job_id'],
                           'game_id':sess['game_id'], 'fen':sess['fen'],
                           'move_uci':a['move_uci'], 'attempt_number':a['attempt_number'],
                           'correct':a['correct'], 'active_seconds_delta':a['active_seconds_delta'],
                           'attempted_at':a['attempted_at'],
                           'primary_motif_key':sess['primary_motif_key'],
                           'opening_key':sess['opening_key']})
    return result


def csv_data(rows, kind='sessions'):
    output = io.StringIO()
    columns = SESSION_COLUMNS if kind=='sessions' else ATTEMPT_COLUMNS
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        safe = {}
        for key in columns:
            value = row.get(key)
            if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            safe[key] = value
        writer.writerow(safe)
    return output.getvalue().encode('utf-8-sig')
