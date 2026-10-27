"""PGN export and source-link safety without requiring Flask or python-chess."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game_sharing import lichess_game_url, normalize_pgn, game_pgn_filename


class GameSharingTests(unittest.TestCase):
    def test_original_lichess_url(self):
        self.assertEqual(lichess_game_url('https://lichess.org/Ab9xZ123/black#43'), 'https://lichess.org/Ab9xZ123')
        self.assertEqual(lichess_game_url('http://www.lichess.org/Ab9xZ123'), 'https://lichess.org/Ab9xZ123')

    def test_pgn_fallback(self):
        pgn='[Event "Rapid"]\n[Site "https://lichess.org/Ab9xZ123"]\n\n1. e4 e5 *'
        self.assertEqual(lichess_game_url('-', pgn), 'https://lichess.org/Ab9xZ123')

    def test_untrusted_or_unrelated_site_does_not_make_a_lichess_link(self):
        for site in ['https://lichess.org.evil.example/Ab9xZ123',
                     'https://example.org/Ab9xZ123', 'https://lichess.org/@/someone',
                     'https://lichess.org/study/Ab9xZ123',
                     'https://user@lichess.org/Ab9xZ123',
                     'javascript:alert(1)', 'imported-8f7c2a3c', '-', 'https://lichess.org/Ab9xZ123more']:
            with self.subTest(site=site):
                self.assertIsNone(lichess_game_url(site))

    def test_normalization_and_safe_download_name(self):
        self.assertEqual(normalize_pgn(' [Event "Test"]\n\n1. e4 *  '), '[Event "Test"]\n\n1. e4 *\n')
        self.assertEqual(normalize_pgn(None), '')
        self.assertEqual(game_pgn_filename('../../../game\r\n.pgn'), 'game---pgn.pgn')
        self.assertEqual(game_pgn_filename(None), 'chess-game.pgn')


if __name__ == '__main__':
    unittest.main()
