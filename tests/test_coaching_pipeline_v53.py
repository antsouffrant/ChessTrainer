"""Learning taxonomy, game-specific prose, optional exact endgame verdicts."""
import unittest
from unittest.mock import patch
from coaching.narrative_composition.coaching_language import game_continuation

try:
    import chess
    from learning import classify_learning_concepts, CONCEPTS
    from coaching.conceptual_understanding.semantic_coaching import causal_coaching
except ImportError:
    chess = None


class LanguageTests(unittest.TestCase):
    def test_immediate_refutation_is_game_feedback(self):
        self.assertEqual(game_continuation('Re1','Qxe1+','capture your rook on e1'),
                         'In the game you played Re1, allowing Qxe1+ to capture your rook on e1.')

    def test_later_event_is_not_claimed_to_be_forced(self):
        self.assertIn('Your opponent can capture your queen with Qxd1+',
                      game_continuation('e5','Qxd1+','capture your queen',ply=3))


@unittest.skipIf(chess is None,'Install python-chess to run position tests')
class SpecificMotifTests(unittest.TestCase):
    def setUp(self):
        self.board=chess.Board('7k/8/8/8/8/3N4/8/7K w - - 0 1')
        self.best=self.board.parse_san('Ne5')
        self.played=self.board.parse_san('Nb4')
        self.good=[self.best.uci(),'h8g8']
        self.bad=[self.played.uci(),'h8g8']

    def classify(self):
        return classify_learning_concepts(self.board,self.played,self.best,'mistake',90,
                       best_pv_uci=self.good,played_pv_uci=self.bad)

    def test_candidate_comparison_is_not_a_learning_motif(self):
        self.assertNotIn('candidate_evaluation',CONCEPTS)
        primary=next(l.key for l in self.classify() if l.is_primary)
        self.assertIn(primary,CONCEPTS)
        self.assertNotEqual(primary,'calculation')

    def test_tablebase_verified_endgame_outranks_unrelated_labels(self):
        with patch('coaching.board_context.endgame_evidence.exact_move_contrast',return_value={
                    'best':'win','played':'draw','source':'Syzygy','exact':True}):
            primary=next(l.key for l in self.classify() if l.is_primary)
            self.assertEqual(primary,'endgame_precision')
            result=causal_coaching(self.board,self.best,self.played,self.good,self.bad,
                                    best_cp=100,played_cp=0)
            self.assertEqual(result['motif'],'endgame_precision')
            self.assertIn('Syzygy confirms',result['text'])

if __name__=='__main__':unittest.main()
