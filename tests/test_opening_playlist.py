"""Opening playlists represent board states, not duplicate game records."""
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from opening_playlist import board_identity, enrich_opening_playlist

FEN = 'r3k2r/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/R3K2R w KQkq - 5 10'

def sample_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE training_positions (
      id INTEGER, job_id INTEGER, opening_key TEXT, game_id TEXT, fen TEXT,
      played_move_san TEXT, played_move_uci TEXT, opponent TEXT,
      game_date TEXT, historical_match TEXT)''')
    rows = [
      (1, 7, 'open-game', 'g1', FEN, 'O-O', 'e1g1', 'Alice', '2025-01-01', None),
      (2, 7, 'open-game', 'g2', FEN.replace('5 10', '2 20'), 'O-O-O', 'e1c1', 'Bob', None, '{"title":"Sample"}'),
      (3, 7, 'open-game', 'g3', FEN, 'O-O', 'e1g1', 'Chris', None, None),
      (4, 7, 'open-game', 'g4', FEN.replace('KQkq','KQ'), 'O-O', 'e1g1', None, None, None),
      (5, 7, 'other', 'g5', FEN, 'O-O-O', 'e1c1', None, None, None),
    ]
    conn.executemany('INSERT INTO training_positions VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
    return conn

def test_deduplicate_and_preserve_moves():
    conn = sample_db()
    positions = [{'id':i, 'fen':fen} for i,fen in [(1,FEN),(2,FEN.replace('5 10','2 20')),(4,FEN.replace('KQkq','KQ'))]]
    grouped = enrich_opening_playlist(conn, 7, 'open-game', positions)
    assert [x['id'] for x in grouped] == [1, 4]
    assert grouped[0]['group_position_ids'] == [1,2,3]
    assert grouped[0]['game_moves'] == [
      {'san':'O-O','uci':'e1g1','game_count':2,'opponents':['Alice','Chris']},
      {'san':'O-O-O','uci':'e1c1','game_count':1,'opponents':['Bob']},
    ]
    assert grouped[0]['historical_match'] == '{"title":"Sample"}'
    assert grouped[1]['group_position_ids'] == [4]

def test_restore_deduplicates_without_reordering():
    conn=sample_db()
    positions = [{'id':i, 'fen':fen} for i,fen in [(4,FEN.replace('KQkq','KQ')),(2,FEN.replace('5 10','2 20')),(1,FEN)]]
    grouped=enrich_opening_playlist(conn,7,'open-game',positions)
    assert [p['id'] for p in grouped] == [4,2]
    assert len(grouped[1]['game_moves']) == 2

def test_board_identity_includes_castling_and_en_passant():
    assert board_identity(FEN) == board_identity(FEN.replace('5 10', '1 60'))
    assert board_identity(FEN) != board_identity(FEN.replace('KQkq', '-'))
    assert board_identity(FEN) != board_identity(FEN.replace(' w ', ' b '))
    assert board_identity(FEN) != board_identity(FEN.replace(' - 5 ', ' e3 5 '))

if __name__=='__main__':
    test_deduplicate_and_preserve_moves()
    test_restore_deduplicates_without_reordering()
    test_board_identity_includes_castling_and_en_passant()
    print('opening playlist tests passed')
