"""Opening name and variation fallback tests using a stub PGN reader.
Full legal-move and historic FEN tests require python-chess.
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]
class FakeBoard:
    turn=True
    def san(self, move): return move
    def push(self, move): pass
class FakeGame:
    def __init__(self, headers, moves): self.headers=headers;self.moves=moves
    def board(self):return FakeBoard()
    def mainline_moves(self):return self.moves
class Tests(unittest.TestCase):
    def setUp(self):
        self.old={name:sys.modules.get(name) for name in ('chess','chess.pgn')}
        chess=types.ModuleType('chess');pgn=types.ModuleType('chess.pgn')
        pgn.read_game=lambda src: FakeGame({},src.read().split())
        chess.pgn=pgn; sys.modules['chess']=chess;sys.modules['chess.pgn']=pgn
        spec=importlib.util.spec_from_file_location('openings_test_module',PROJECT/'openings.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
    def tearDown(self):
        for k,v in self.old.items():
            if v is None:sys.modules.pop(k,None)
            else:sys.modules[k]=v
    def test_sicilian_and_najdorf(self):
        item=self.module.classify_pgn('e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Nf3')
        self.assertEqual(item['name'],'Sicilian Defense')
        self.assertEqual(item['variation'],'Najdorf Variation')
    def test_philidor(self):
        item=self.module.classify_pgn('e4 e5 Nf3 d6 d4 Bg4')
        self.assertEqual(item['name'],'Philidor Defense')
    def test_unknown(self):
        self.assertEqual(self.module.classify_pgn('h4 a5')['key'],'unclassified')
    def test_header_variation(self):
        self.module.chess.pgn.read_game=lambda _:FakeGame({'Opening':'Sicilian Defense: English Attack','ECO':'B90'},['e4','c5'])
        item=self.module.classify_pgn('ignored')
        self.assertEqual((item['name'],item['variation'],item['eco']),('Sicilian Defense','English Attack','B90'))
if __name__=='__main__':unittest.main()
