"""Stage 1: spoiler-conscious hints, independent of the post-solve narrator.

The pre-solve prompt describes the decision faced, never transcribes the PV or
claims a tactical mechanism that is not grounded in the board.
"""
from __future__ import annotations

CATEGORIES = {
    'missed_checkmate':'The opposing king is vulnerable. Compare forcing checks and the available defenses.',
    'allowed_checkmate':'Your king is threatened. Find a move that addresses the immediate danger.',
    'excellent_move':'A strong choice is available. What is the most important opportunity in this position?',
    'brilliant_move':'An unusual move works here. Look for a forcing idea beyond routine captures.',
    'threw_away_win':'You have an advantage, but an inaccurate move can give the opponent counterplay.',
    'blundered_into_loss':'The position contains a defensive resource. Identify the threat before choosing.',
    'opposition_opportunity':'The opponent has created an opportunity. Look for a concrete way to exploit it.',
}
MOTIFS = {
    'fork': 'Can a move threaten two valuable targets?',
    'pin': 'Does an alignment restrict a piece that protects something important?',
    'discovered_attack':'Could moving one piece reveal a stronger attack?',
    'king_activity':'How can the king contribute in this endgame?',
    'passed_pawn':'Which move best influences the race to promotion?',
    'mating_net':'What restricts the opposing king’s escape squares?',
    'simplification':'Would trading pieces make the position easier to handle?',
    'counterattack':'Is a forcing counter-threat stronger than retreating?',
    'capture_loose_piece':'Which opposing piece lacks sufficient protection?',
}

def prompt_for_position(*, fen, category='', motif_key='', previous_fen=None,
                        opponent_move_uci=None, best_move_uci=None,
                        played_move_uci=None, **unused):
    try:
        import chess
        board=chess.Board(fen)
        if board.is_check():
            return 'Your king is in check. Find the safest legal response and check what each defense allows.'
        if previous_fen and opponent_move_uci and best_move_uci:
            from coaching.board_context.position_context import inspect_response, piece_description
            def legal(uci):
                try:
                    move=chess.Move.from_uci(uci or '')
                    return move if move in board.legal_moves else None
                except (ValueError,TypeError):
                    return None
            best,played=legal(best_move_uci),legal(played_move_uci)
            context=inspect_response(board,best,played,previous_fen,opponent_move_uci) if best else None
            if context:
                if context.get('new_loose'):
                    sq=context['new_loose'][0]
                    return (f'The last move left your {piece_description(board,sq)} hanging. '
                            'Can you defend it or counterattack?')
                if context.get('new_pressure'):
                    sq=context['new_pressure'][0]
                    return (f'The opponent increased pressure on your {piece_description(board,sq)}. '
                            'Find the most effective response.')
                if context.get('new_pins_on_us'):
                    return 'The opponent created a pin. Check which defenses and captures remain legal.'
    except (ImportError,TypeError,ValueError,KeyError):
        pass
    return (CATEGORIES.get(category) or MOTIFS.get(motif_key)
            or 'Identify the immediate threats and the move that changes the position most effectively.')
