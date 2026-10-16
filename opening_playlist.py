"""Deduplicate opening training positions without discarding their game histories.

A chess *position* is identified by piece placement, side to move, castling
rights and en-passant target; move counters are deliberately excluded.
"""
from collections import defaultdict
import json


def board_identity(fen):
    parts = str(fen or '').split()
    return ' '.join(parts[:4]) if len(parts) >= 4 else str(fen or '').strip()


def enrich_opening_playlist(conn, job_id, opening_key, positions):
    """Return one card per position and attach all source game moves.

    Preserve the supplied ordering, including for a restored pinned playlist.
    Only the returned cards are deduplicated; stored source games are untouched.
    Historical references are included only if attached to a matching board.
    """
    if not opening_key or not positions:
        return positions
    sources = conn.execute('''
        SELECT id, game_id, fen, played_move_san, played_move_uci,
               opponent, game_date, historical_match
        FROM training_positions WHERE job_id = ? AND opening_key = ?
        ORDER BY id
    ''', (job_id, opening_key)).fetchall()
    by_board = defaultdict(list)
    for source in sources:
        by_board[board_identity(source['fen'])].append(source)

    seen = set()
    unique = []
    for position in positions:
        key = board_identity(position.get('fen'))
        if key in seen:
            continue
        seen.add(key)
        members = by_board.get(key, [])
        moves = {}
        for row in members:
            san = (row['played_move_san'] or '').strip()
            uci = (row['played_move_uci'] or '').strip()
            if not san and not uci:
                continue
            move_key = uci or san
            entry = moves.setdefault(move_key, {'san': san or uci, 'uci': uci,
                                                'games': set(), 'opponents': []})
            game_key = row['game_id'] or f"position:{row['id']}"
            if game_key not in entry['games']:
                entry['games'].add(game_key)
                if row['opponent'] and len(entry['opponents']) < 3:
                    entry['opponents'].append(row['opponent'])
        position['game_moves'] = [
            {'san': move['san'], 'uci': move['uci'],
             'game_count': len(move['games']), 'opponents': move['opponents']}
            for move in sorted(moves.values(), key=lambda m: (-len(m['games']), m['san']))
        ]
        position['group_position_ids'] = [row['id'] for row in members]
        if not position.get('historical_match'):
            position['historical_match'] = next(
                (row['historical_match'] for row in members if row['historical_match']), None
            )
        unique.append(position)
    return unique
