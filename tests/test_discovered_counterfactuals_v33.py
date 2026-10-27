"""Run with python-chess: python -m unittest discover -s tests -p '*v33.py' -v."""
import unittest
import chess

from coaching.board_context.discovered_counterfactuals import revealed_lines, discovered_reply_checks
from coaching.board_context.position_context import inspect_response
from learning import classify_learning_concepts
from coaching.narrative_composition.coaching import generate_coaching_text


class DiscoveredAttackComprehensionTests(unittest.TestCase):
    def test_discovered_check_blocks_an_apparent_knight_capture(self):
        board = chess.Board('4k3/8/8/8/4B2n/8/8/4R1K1 w - - 0 1')
        best = board.parse_san('Bf3+')
        played = board.parse_san('Kh2')
        lines = revealed_lines(board, best)
        self.assertEqual(lines[0]['kind'], 'discovered_check')
        self.assertEqual(lines[0]['attacker_square'], chess.E1)
        self.assertEqual(lines[0]['target_square'], chess.E8)
        after = board.copy(stack=False); after.push(best)
        attempted = chess.Move.from_uci('h4f3')
        self.assertIn(attempted, list(after.generate_pseudo_legal_moves()))
        self.assertNotIn(attempted, after.legal_moves)
        findings = discovered_reply_checks(board, best, lines)
        self.assertTrue(any(f['kind'] == 'illegal_capture_during_discovered_check'
                            and f['reply_uci'] == attempted.uci() for f in findings))
        context = inspect_response(board, best, played)
        self.assertIn('discovered_attack', context['response_motifs'])
        labels = classify_learning_concepts(board, played, best, 'major_blunder', 280)
        self.assertEqual(next(label.key for label in labels if label.is_primary),
                         'discovered_attack')
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san='Kh2', best_move_uci=best.uci(),
            best_move_san='Bf3+', category='major_blunder', labels=labels,
        )
        self.assertIn('Bf3+', explanation)
        self.assertIn('uncovers check', explanation)
        self.assertIn('cannot take', explanation)

    def test_discovered_attack_exposes_queen_but_is_not_called_forced_win(self):
        board = chess.Board('6k1/4q3/8/8/4B1p1/8/8/4R1K1 w - - 0 1')
        best = board.parse_san('Bf3')
        played = board.parse_san('Kh2')
        lines = revealed_lines(board, best)
        self.assertTrue(any(d['kind'] == 'discovered_attack'
                            and d['target_square'] == chess.E7 for d in lines))
        checks = discovered_reply_checks(board, best, lines)
        self.assertTrue(any(d['kind'] == 'legal_capture_allows_followup'
                            and d['followup_uci'] == 'e1e7' for d in checks))
        _, explanation = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=played.uci(),
            played_move_san='Kh2', best_move_uci=best.uci(),
            best_move_san='Bf3', category='major_blunder',
        )
        self.assertIn('queen', explanation)
        self.assertNotIn('forced win', explanation)

    def test_shared_discovered_line_does_not_explain_best_move_over_played(self):
        board = chess.Board('6k1/4q3/8/8/4B1p1/8/8/4R1K1 w - - 0 1')
        best = board.parse_san('Bf3')
        played = board.parse_san('Bd3')
        context = inspect_response(board, best, played)
        self.assertTrue(context['discovered_lines'])
        self.assertFalse(context['discovered_unique_lines'])
        self.assertNotIn('discovered_attack', context['response_motifs'])

    def test_diagonal_pawn_promotion_can_open_a_line(self):
        board = chess.Board('4rbk1/4P3/8/8/8/8/8/4R1K1 w - - 0 1')
        best = board.parse_san('exf8=Q+')
        lines = revealed_lines(board, best)
        self.assertTrue(any(d['kind'] == 'discovered_attack'
                            and d['attacker_square'] == chess.E1
                            and d['target_square'] == chess.E8 for d in lines))

    def test_no_discovery_when_move_does_not_open_ray(self):
        board = chess.Board('6k1/4q3/8/8/4B1p1/8/8/4R1K1 w - - 0 1')
        self.assertEqual(revealed_lines(board, board.parse_san('Kh2')), [])


if __name__ == '__main__':
    unittest.main()
