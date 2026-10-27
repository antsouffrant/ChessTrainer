"""Causal-ranking policy and selected chess regression scenarios for v60.

Pure ranking and fixture tests run without python-chess. Board-level tests
require python-chess and do not invoke Stockfish.
"""
import json
import unittest
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from coaching.motif_selection.causal_selection import ranked_findings, finding_score, primary_causal_finding


@dataclass
class Candidate:
    key: str
    motif: str
    horizon: int
    confidence: int
    impact: int


class SelectionTests(unittest.TestCase):
    def test_near_specific_mechanism_beats_distant_generic_label(self):
        cause = Candidate('line_refutation', 'removal_of_defender', 0, 2, 104)
        incidental = Candidate('remote_pin', 'pin', 4, 2, 125)
        self.assertEqual(ranked_findings([incidental, cause])[0].key, 'line_refutation')

    def test_verified_root_free_piece_outranks_low_confidence_pin(self):
        free = Candidate('capture', 'capture_loose_piece', 0, 3, 101)
        pin = Candidate('pin', 'pin', 1, 1, 109)
        self.assertEqual(primary_causal_finding([pin, free]), free)

    def test_weak_geometry_does_not_become_verified_cause(self):
        weak = Candidate('spatial', 'pin', 0, 1, 88)
        self.assertIsNone(primary_causal_finding([weak]))

    def test_immediate_checkmate_still_dominates_strategy(self):
        mate = Candidate('mate_allowed', 'mate_defense', 1, 3, 119)
        strategy = Candidate('active_king', 'king_activity', 0, 2, 84)
        self.assertEqual(ranked_findings([strategy, mate])[0], mate)


class CorrectionCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = Path(__file__).parent / 'fixtures' / 'coach_regression_candidates_v60.jsonl'
        cls.rows = [json.loads(line) for line in cls.fixture.read_text(encoding='utf-8').splitlines()]

    def test_corrections_are_anonymized_and_have_legal_test_inputs(self):
        self.assertEqual(len(self.rows), 51)
        self.assertEqual(Counter(r['feedback_type'] for r in self.rows),
                         {'motif': 25, 'explanation': 26})
        self.assertTrue(all(r['fen'] and r['played_move_uci'] and r['best_move_uci']
                            and r['review_status'] == 'proposed' for r in self.rows))
        private = {'username', 'opponent', 'game_id', 'source_username', 'job_id'}
        self.assertTrue(all(not (private & r.keys()) for r in self.rows))


try:
    import chess
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
    from coaching.conceptual_understanding.continuation_refutations import scan_branch
    from learning import classify_learning_concepts
except ImportError:
    chess = None


@unittest.skipIf(chess is None, 'python-chess is needed to execute chess-position regressions')
class CausalChessTests(unittest.TestCase):
    @staticmethod
    def moves(board, sans):
        child = board.copy(stack=False)
        line = []
        for san in sans:
            move = child.parse_san(san)
            line.append(move.uci())
            child.push(move)
        return line

    def test_removing_bishop_defender_enables_pawn_capture(self):
        board = chess.Board('7k/1b6/8/8/4p3/8/5N2/1R5K w - - 0 1')
        best, played = board.parse_san('Rxb7'), board.parse_san('Ra1')
        good = self.moves(board, ['Rxb7', 'Kg8', 'Nxe4'])
        bad = self.moves(board, ['Ra1', 'Kg8'])
        line = scan_branch(board, best, good, branch='best')
        self.assertTrue(any(x.motif == 'removal_of_defender' for x in line), line)
        result = causal_coaching(board, best, played, good, bad, best_cp=380, played_cp=20)
        self.assertEqual(result['motif'], 'removal_of_defender')
        self.assertIn('Nxe4', result['text'])
        labels = classify_learning_concepts(board, played, best, 'mistake', 360,
                                            best_pv_uci=good, played_pv_uci=bad)
        self.assertEqual(next(x.key for x in labels if x.is_primary), 'removal_of_defender')

    def test_endgame_king_activity_without_incidental_capture(self):
        board = chess.Board('7k/8/8/2PK4/8/8/8/8 w - - 0 1')
        best, played = board.parse_san('Kd4'), board.parse_san('Ke6')
        result = causal_coaching(board, best, played,
                                 self.moves(board, ['Kd4', 'Kg8']),
                                 self.moves(board, ['Ke6', 'Kg8']),
                                 best_cp=120, played_cp=-90)
        self.assertEqual(result['motif'], 'king_activity')
        self.assertIn('activates your king', result['text'])

    def test_root_pawn_doubling_is_not_remote_pin(self):
        board = chess.Board('7k/8/8/8/3p4/4P3/3P4/7K w - - 0 1')
        best, played = board.parse_san('e4'), board.parse_san('exd4')
        result = causal_coaching(board, best, played,
                                 self.moves(board, ['e4', 'Kg8']),
                                 self.moves(board, ['exd4', 'Kg8']),
                                 best_cp=100, played_cp=-120)
        self.assertEqual(result['motif'], 'pawn_structure')
        self.assertIn('doubled d-pawns', result['text'])


if __name__ == '__main__':
    unittest.main()
