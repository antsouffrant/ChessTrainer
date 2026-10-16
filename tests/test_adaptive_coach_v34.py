"""Run with: python -m pytest tests/test_adaptive_coach_v34.py
Requires the project's python-chess dependency, but not a running Stockfish binary.
"""
from types import SimpleNamespace
from unittest.mock import patch

import chess

from coach_learning import (
    requested_motif, wants_general_explanation, explain_general,
    shared_move_explanation, probe_motif,
)


def test_semantic_intents():
    assert requested_motif('Show me a fork in this position') == 'fork'
    assert requested_motif('Can you show a discovered check?') == 'discovered_attack'
    assert requested_motif('What if Nf3?') is None
    assert wants_general_explanation('Could you explain why the engine move is best?')
    assert wants_general_explanation('What is the lesson here?')
    assert wants_general_explanation('Why did I miss it?')
    assert requested_motif('Can you explain a pin?') == 'pin'


def test_unsolved_general_is_spoiler_safe():
    row = {'coach_prompt': 'Look for forcing moves.', 'coach_explanation': 'The answer is e4.',
           'fen': chess.STARTING_FEN}
    answer = explain_general(row, chess.STARTING_FEN, False)
    assert answer['reply'] == 'Look for forcing moves.'
    assert 'answer is e4' not in answer['reply']


def test_unsolved_motif_never_calls_engine():
    with patch('coach_learning.evaluate_multipv', side_effect=AssertionError('No engine before solve')):
        result = probe_motif({'fen': chess.STARTING_FEN}, chess.Board(), 'fork', False)
    assert result['intent'] == 'learning_motif'
    assert result['evidence']['spoiler_safe']


def test_shared_explanation_uses_two_branches():
    board = chess.Board()
    candidate = chess.Move.from_uci('d2d4')
    best = {'best_move_uci': 'e2e4', 'best_move_san': 'e4',
            'eval_cp': 52, 'mate': None, 'pv_uci':['e2e4','e7e5']}
    other = {'eval_cp': 35, 'pv_uci':['d2d4','d7d5']}
    with patch('coach_learning.generate_coaching_text', return_value=('prompt', 'e4 controls the center.')) as mock:
        reply = shared_move_explanation(board, candidate, best, other,
                                         position_row={'fen': chess.STARTING_FEN})
    assert reply == 'e4 controls the center.'
    assert mock.call_args.kwargs['played_move_uci'] == 'd2d4'
    assert mock.call_args.kwargs['best_pv_uci'] == ['e2e4','e7e5']
    assert mock.call_args.kwargs['played_pv_uci'] == ['d2d4','d7d5']


def test_motif_matches_evaluated_candidate_only():
    board = chess.Board()
    candidates = [
        {'move_uci': 'e2e4', 'move_san': 'e4', 'eval_cp': 70, 'pv_uci': ['e2e4', 'e7e5']},
        {'move_uci': 'd2d4', 'move_san': 'd4', 'eval_cp': 60, 'pv_uci': ['d2d4', 'd7d5']},
    ]
    def labels(_board, played, _best, _category, _loss, **kwargs):
        if played.uci() == 'd2d4':
            return [SimpleNamespace(key='fork', confidence=.88, evidence='a knight fork appears')]
        return [SimpleNamespace(key='calculation', confidence=.6, evidence='calculation')]
    with patch('coach_learning.evaluate_multipv', return_value=candidates), \
         patch('coach_learning.classify_learning_concepts', side_effect=labels), \
         patch('coach_learning.evaluate_fen', return_value={'best_move_uci': 'e2e4', 'eval_cp': 70}), \
         patch('coach_learning.evaluate_move_quality', return_value={'eval_cp': 60}), \
         patch('coach_learning.shared_move_explanation', return_value='e4 offers a different plan.'):
        answer = probe_motif({'fen': chess.STARTING_FEN}, board, 'fork', True)
    assert answer['verdict'] == 'supported'
    assert answer['evidence']['move_uci'] == 'd2d4'
    assert 'd4' in answer['reply']


def test_unknown_motif_does_not_invent_a_line():
    board = chess.Board()
    with patch('coach_learning.evaluate_multipv', return_value=[{
            'move_uci':'e2e4','move_san':'e4','eval_cp':50,'pv_uci':['e2e4']}]), \
         patch('coach_learning.classify_learning_concepts', return_value=[]):
        answer = probe_motif({'fen': chess.STARTING_FEN}, board, 'pin', True)
    assert answer['verdict'] == 'uncertain'
    assert 'clearly demonstrates' in answer['reply']
