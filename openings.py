"""Opening playlists and evidence-based links to classic games.

Opening labels from PGN headers take priority. When missing, a compact local
opening tree supplies conservative family/variation labels. This is not a full
ECO database. Historical callouts require an identical *board position*;
sharing a few opening moves is never described as a historical match.
"""
from __future__ import annotations

import io
import json
import re
from functools import lru_cache

import chess.pgn

# Ordered from general to specific; longest matching move-prefix takes priority.
LINES = [
    ('King’s Pawn Game', '', 'e4'),
    ('Open Game', '', 'e4 e5'),
    ('Italian Game', '', 'e4 e5 Nf3 Nc6 Bc4'),
    ('Italian Game', 'Giuoco Piano', 'e4 e5 Nf3 Nc6 Bc4 Bc5'),
    ('Italian Game', 'Two Knights Defense', 'e4 e5 Nf3 Nc6 Bc4 Nf6'),
    ('Ruy Lopez', '', 'e4 e5 Nf3 Nc6 Bb5'),
    ('Ruy Lopez', 'Morphy Defense', 'e4 e5 Nf3 Nc6 Bb5 a6'),
    ('Scotch Game', '', 'e4 e5 Nf3 Nc6 d4'),
    ('Petrov Defense', '', 'e4 e5 Nf3 Nf6'),
    ('Philidor Defense', '', 'e4 e5 Nf3 d6'),
    ('King’s Gambit', '', 'e4 e5 f4'),
    ('King’s Gambit', 'Accepted', 'e4 e5 f4 exf4'),
    ('Sicilian Defense', '', 'e4 c5'),
    ('Sicilian Defense', 'Open Sicilian', 'e4 c5 Nf3 d6 d4 cxd4 Nxd4'),
    ('Sicilian Defense', 'Najdorf Variation', 'e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6'),
    ('Sicilian Defense', 'Dragon Variation', 'e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6'),
    ('French Defense', '', 'e4 e6'),
    ('French Defense', 'Advance Variation', 'e4 e6 d4 d5 e5'),
    ('Caro-Kann Defense', '', 'e4 c6'),
    ('Caro-Kann Defense', 'Advance Variation', 'e4 c6 d4 d5 e5'),
    ('Scandinavian Defense', '', 'e4 d5'),
    ('Pirc Defense', '', 'e4 d6 d4 Nf6 Nc3 g6'),
    ('Modern Defense', '', 'e4 g6'),
    ('Queen’s Pawn Game', '', 'd4'),
    ('Queen’s Gambit', '', 'd4 d5 c4'),
    ('Queen’s Gambit', 'Declined', 'd4 d5 c4 e6'),
    ('Queen’s Gambit', 'Accepted', 'd4 d5 c4 dxc4'),
    ('Slav Defense', '', 'd4 d5 c4 c6'),
    ('London System', '', 'd4 d5 Bf4'),
    ('King’s Indian Defense', '', 'd4 Nf6 c4 g6 Nc3 Bg7'),
    ('Nimzo-Indian Defense', '', 'd4 Nf6 c4 e6 Nc3 Bb4'),
    ('Grünfeld Defense', '', 'd4 Nf6 c4 g6 Nc3 d5'),
    ('Dutch Defense', '', 'd4 f5'),
    ('English Opening', '', 'c4'),
    ('Réti Opening', '', 'Nf3'),
]
LINES = sorted(((name, variation, tuple(san.split())) for name, variation, san in LINES), key=lambda x: len(x[2]), reverse=True)

# Publicly documented classical game scores. Source URLs remain available in UI.
CLASSICS = [
    {
        'key': 'opera-game', 'title': 'The Opera Game', 'players': 'Paul Morphy vs. Duke Karl / Count Isouard',
        'year': 1858, 'opening': 'Philidor Defense',
        'lesson': 'Development, open files, and coordinated sacrifices culminating in a mating net.',
        'notable': '10.Nxb5, 13.Rxd7 and 16.Qb8+',
        'source_url': 'https://github.com/georgi/morphy',
        'san': 'e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O-O Rd8 Rxd7 Rxd7 Rd1 Qe6 Bxd7+ Nxd7 Qb8+ Nxb8 Rd8#',
    },
    {
        'key': 'immortal-game', 'title': 'The Immortal Game', 'players': 'Adolf Anderssen vs. Lionel Kieseritzky',
        'year': 1851, 'opening': 'King’s Gambit',
        'lesson': 'A sustained initiative and material sacrifices lead to a striking mating finish.',
        'notable': '17.Nd5, 21.Nxg7+ and 22.Qf6+',
        'source_url': 'https://en.chessbase.com/post/kieseritzky-s-immortal-game',
        'san': 'e4 e5 f4 exf4 Bc4 Qh4+ Kf1 b5 Bxb5 Nf6 Nf3 Qh6 d3 Nh5 Nh4 Qg5 Nf5 c6 g4 Nf6 Rg1 cxb5 h4 Qg6 h5 Qg5 Qf3 Ng8 Bxf4 Qf6 Nc3 Bc5 Nd5 Qxb2 Bd6 Qxa1+ Ke2 Bxg1 e5 Na6 Nxg7+ Kd8 Qf6+ Nxf6 Be7#',
    },
    {
        'key': 'kasparov-immortal', 'title': 'Kasparov’s Immortal', 'players': 'Garry Kasparov vs. Veselin Topalov',
        'year': 1999, 'opening': 'Pirc Defense',
        'lesson': 'A spectacular rook sacrifice initiates a long king hunt.',
        'notable': '24.Rxd4!',
        'source_url': 'https://betterchess.co/games/kasparov-topalov-1999',
        'san': 'e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 c6 f3 b5 Nge2 Nbd7 Bh6 Bxh6 Qxh6 Bb7 a3 e5 O-O-O Qe7 Kb1 a6 Nc1 O-O-O Nb3 exd4 Rxd4 c5 Rd1 Nb6 g3 Kb8 Na5 Ba8 Bh3 d5 Qf4+ Ka7 Rhe1 d4 Nd5 Nbxd5 exd5 Qd6 Rxd4 cxd4 Re7+ Kb6 Qxd4+ Kxa5 b4+ Ka4 Qc3 Qxd5',
    },
]


def _slug(value):
    value = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    return value[:100] or 'unclassified'


@lru_cache(maxsize=64)
def _classic_positions(key):
    classic = next(c for c in CLASSICS if c['key'] == key)
    board = chess.Board()
    positions = {board.board_fen() + (' w' if board.turn else ' b'): 0}
    # Invalid/ambiguous imported reference lines must never prevent opening lookup.
    for ply, san in enumerate(classic['san'].split(), start=1):
        try:
            board.push_san(san)
        except ValueError:
            break
        positions[board.board_fen() + (' w' if board.turn else ' b')] = ply
    return positions


def famous_for_opening(opening_name):
    return [{k: v for k, v in item.items() if k != 'san'} for item in CLASSICS if item['opening'] == opening_name]


def historical_for_position(position_fen):
    """Exact board-position historical match, without reparsing the game's PGN."""
    if not position_fen:
        return None
    position_key = ' '.join(position_fen.split()[:2])
    for classic in CLASSICS:
        ply = _classic_positions(classic['key']).get(position_key)
        if ply is not None and ply >= 12:
            return json.dumps({**{k: v for k, v in classic.items() if k != 'san'},
                               'matched_ply': ply, 'match_type': 'exact_position'})
    return None

def classify_pgn(pgn, position_fen=None, game=None):
    # Refresh Metadata already parsed this PGN to reconstruct game context.
    # Accept that game to avoid parsing the identical text a second time.
    if game is None:
        try:
            game = chess.pgn.read_game(io.StringIO(pgn or '')) if pgn else None
        except (ValueError, TypeError, UnicodeError):
            game = None
    if game is None:
        return {'key': 'unclassified', 'name': 'Unclassified Opening', 'variation': '', 'eco': '', 'source': 'unknown', 'history': '[]', 'historical': None}
    board = game.board()
    moves_san = []
    for move in game.mainline_moves():
        moves_san.append(board.san(move))
        board.push(move)
    header = (game.headers.get('Opening') or '').strip()
    eco = (game.headers.get('ECO') or '').strip()[:4]
    variation_header = (game.headers.get('Variation') or '').strip()
    recognized = next(((name, variation, seq) for name, variation, seq in LINES if tuple(moves_san[:len(seq)]) == seq), None)
    if header and header not in {'?', 'Unknown', 'Opening'}:
        pieces = header.split(':', 1)
        name = pieces[0].strip()
        variation = variation_header or (pieces[1].strip() if len(pieces) > 1 else '')
        name = name.replace('Defence', 'Defense').replace('Réti', 'Reti')
        # Opening tags sometimes place the variation after a comma rather
        # than a colon. Keep the family stable when known.
        for family in sorted({entry[0] for entry in LINES}, key=len, reverse=True):
            if name.lower().startswith(family.lower() + ','):
                variation = variation or name[len(family)+1:].strip()
                name = family
                break
        if recognized and not variation and recognized[0].lower() == name.lower():
            variation = recognized[1]
        source = 'pgn-header'
    elif recognized:
        name, variation, _ = recognized
        variation = variation_header or variation
        source = 'move-prefix'
    else:
        name, variation, source = 'Unclassified Opening', '', 'unknown'
    historical = historical_for_position(position_fen)
    return {
        'key': 'unclassified' if name == 'Unclassified Opening' else _slug(name), 'name': name, 'variation': variation,
        'eco': eco, 'source': source, 'history': json.dumps(moves_san[:40]),
        'historical': historical,
    }


def ensure_opening_metadata(conn, job_id):
    """Backfill only new/legacy rows, preserving puzzles and learning progress."""
    rows = conn.execute('''
      SELECT tp.id, tp.game_id, COALESCE(tp.game_pgn, ag.game_pgn) AS game_pgn, tp.fen
      FROM training_positions tp
      JOIN analysis_jobs j ON j.id = tp.job_id
      LEFT JOIN analyzed_games ag ON ag.account_id = j.account_id AND ag.game_id = tp.game_id
      WHERE tp.job_id = ? AND tp.opening_key IS NULL ORDER BY tp.id
    ''', (job_id,)).fetchall()
    if not rows:
        return 0
    by_game = {}
    updates = []
    for row in rows:
        # Header/move-line is shared across positions in the same game; the
        # historic board-position match is computed for each puzzle separately.
        cache_key = row['game_id'] or f"position:{row['id']}"
        if cache_key not in by_game:
            by_game[cache_key] = classify_pgn(row['game_pgn'])
        base = by_game[cache_key]
        historical = historical_for_position(row['fen'])
        updates.append((base['key'], base['name'], base['variation'], base['eco'], base['source'], base['history'], historical, row['id']))
    conn.executemany('''UPDATE training_positions SET opening_key = ?, opening_name = ?,
      opening_variation = ?, opening_eco = ?, opening_source = ?, opening_history = ?,
      historical_match = ? WHERE id = ?''', updates)
    conn.commit()
    return len(updates)
