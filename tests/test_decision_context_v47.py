"""v47 regression scenarios for contextual chess explanations.

Requires python-chess (pip install -r requirements.txt). Test PVs are
explicitly supplied samples; no Stockfish network or binary is used.
"""
import unittest
import chess

from coaching.conceptual_understanding.decision_context import (
    decision_facts, concrete_explanation, has_decisive_context,
    mate_in_one, unanswered_mate_threat, trace_variation,
)
from coaching.narrative_composition.coaching import generate_coaching_text
from learning import classify_learning_concepts
from coaching.board_context.explanatory_evidence import explanation_variations


class DecisionContextTests(unittest.TestCase):
    def test_unavoidable_pawn_is_not_described_as_saved(self):
        # Nxe4 occurs against both root moves. Na3 creates pressure on b5.
        board = chess.Board('6k1/8/5n2/1p6/4P3/8/7P/1N4K1 w - - 0 1')
        good, bad = board.parse_san('Na3'), board.parse_san('h3')
        facts = decision_facts(board, good, bad,
                               ['b1a3', 'f6e4'], ['h2h3', 'f6e4'],
                               best_cp=-100, played_cp=-220)
        self.assertEqual(facts['shared_loss'][0]['square'], 'e4')
        self.assertEqual(facts['new_targets'][0]['square'], 'b5')
        self.assertFalse(facts['truly_saved'])
        result = concrete_explanation(board, facts)
        self.assertIn('BOTH analyzed lines', result)
        self.assertIn('counterattacks', result)
        self.assertNotIn('saves', result.lower())
        self.assertIn('b5', result)

        _, coached = generate_coaching_text(
            fen=board.fen(), previous_fen=None, opponent_move_uci=None,
            opponent_move_san=None, played_move_uci=bad.uci(), played_move_san='h3',
            best_move_uci=good.uci(), best_move_san='Na3', category='major_blunder',
            best_pv_uci=['b1a3', 'f6e4'], played_pv_uci=['h2h3', 'f6e4'],
            eval_before_cp=-100, eval_after_cp=-220)
        self.assertIn('counterattacks', coached)
        self.assertIn('both analyzed lines', coached.lower())
        self.assertNotIn('saves', coached.lower())
        labels = classify_learning_concepts(board, bad, good, 'major_blunder', 120,
                best_pv_uci=['b1a3', 'f6e4'], played_pv_uci=['h2h3', 'f6e4'])
        self.assertEqual(next(l.key for l in labels if l.is_primary), 'counterattack')

    def test_capture_trade_is_not_a_free_piece(self):
        board = chess.Board('4r1k1/8/8/4n3/8/2B5/8/R5K1 w - - 0 1')
        move = board.parse_san('Bxe5')
        traced = trace_variation(board, ['c3e5', 'e8e5'], move)
        self.assertEqual(len(traced['exchanges']), 1)
        self.assertTrue(traced['exchanges'][0]['balanced'])
        facts = decision_facts(board, move, board.parse_san('Ra2'),
                              ['c3e5', 'e8e5'], ['a1a2', 'e8f8'],
                              best_cp=100, played_cp=-100)
        self.assertTrue(has_decisive_context(board, facts))
        text = concrete_explanation(board, facts)
        self.assertIn('exchange', text)
        self.assertIn('trade, not a free material win', text)

    def test_mate_threat_must_be_legal_and_is_not_forced(self):
        board = chess.Board('rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq g3 0 2')
        self.assertIn('Qh4#', mate_in_one(board))
        # This is an actual mating move, not merely an attacked king square.

    def test_mate_threat_requires_a_response_but_is_not_forced(self):
        # After 1.e4 e5 2.Bc4 Nc6 3.Qh5, an irrelevant move allows Qxf7#.
        board = chess.Board('r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 3 3')
        self.assertIn('Qxf7#', unanswered_mate_threat(board))
        a6 = board.parse_san('a6')
        after_a6 = board.copy(stack=False)
        after_a6.push(a6)
        self.assertIn('Qxf7#', mate_in_one(after_a6))
        g6 = board.parse_san('g6')
        after_g6 = board.copy(stack=False)
        after_g6.push(g6)
        self.assertNotIn('Qxf7#', mate_in_one(after_g6))

    def test_pieces_remain_identifiable_after_moving(self):
        board = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        traced = trace_variation(board, ['c3d4', 'd8d4'])
        self.assertEqual(traced['captures'][0]['root_square'], 'c3')
        self.assertEqual(traced['captures'][0]['square'], 'd4')

    def test_positive_game_move_without_alt_is_not_its_own_comparison(self):
        board = chess.Board('3q2k1/8/8/8/8/2B5/8/R5K1 w - - 0 1')
        best = board.parse_san('Ra2')
        facts = decision_facts(board, best, best, ['a1a2', 'd8f6'],
                               ['a1a2', 'd8f6'], best_cp=120, played_cp=120)
        self.assertTrue(facts['positive'])
        self.assertIsNone(facts['bad'])
        self.assertIsNone(facts['played_san'])

    def test_data_contract_has_both_perspectives(self):
        board = chess.Board('6k1/8/5n2/1p6/4P3/8/7P/1N4K1 w - - 0 1')
        best, played = board.parse_san('Na3'), board.parse_san('h3')
        evidence = explanation_variations(board, best, played,
                         ['b1a3', 'f6e4'], ['h2h3', 'f6e4'], -100, -220)
        self.assertIn('decision_context', evidence)
        self.assertIn('own_loose', evidence['decision_context'])
        self.assertIn('opponent_loose', evidence['context'])
        self.assertIn('mate_in_one_available', evidence['context'])
        self.assertEqual(evidence['decision_context']['shared_loss'][0]['square'], 'e4')


if __name__ == '__main__':
    unittest.main()
