"""Stage 1: immutable, root-locked evidence for a coaching decision.

No engine invocation and no board claim manufactured from a motif. Saved PV
plies come from the legality-checked analyzer; independently verified attempts
are normalized by the same branch_evidence selector. This is a read-only stage.
"""
from __future__ import annotations
from dataclasses import dataclass
import json


def field(row, key, default=None):
    try:
        value = row[key]
        return default if value is None else value
    except (KeyError, IndexError, TypeError):
        return default


def unpack(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value if value is not None else default


@dataclass(frozen=True)
class Event:
    kind: str
    text: str
    ply: int
    san: str
    uci: str


@dataclass(frozen=True)
class DecisionEvidence:
    root_uci: str
    root_san: str
    role: str
    events: tuple[Event, ...]
    reply_san: str | None
    verified: bool
    root_motif: str
    best_uci: str
    best_san: str
    eval_before_cp: int | None
    eval_after_cp: int | None
    mate_before: int | None


def _validated_root(row, uci):
    try:
        import chess
        board = chess.Board(field(row, 'fen', ''))
        move = chess.Move.from_uci(uci)
        return move in board.legal_moves
    except (ImportError, ValueError, TypeError):
        # Unavailable chess library should never turn untrusted data into
        # *verified* evidence. Stored analyzer plies are filtered by root.
        return False


def extract_decision(row, attempt, *, branch=None, motif_key=''):
    uci = str(field(attempt, 'move_uci', '') or '')
    san = str(field(attempt, 'move_san', uci) or uci)
    legal = None
    try:
        import chess
        board=chess.Board(field(row,'fen',''))
        move=chess.Move.from_uci(uci)
        legal=move in board.legal_moves
        if legal:
            san=board.san(move)  # Never trust a stale SAN paired with a UCI.
    except ImportError:
        pass  # Standalone corpus/test mode without python-chess.
    except (TypeError,ValueError):
        legal=False
    if branch is None:
        branch = branch_evidence(row, uci, attempt)
    match = bool(branch and branch.get('root_uci') == uci
                 and isinstance(branch.get('plies'), list)
                 and branch['plies']
                 and branch['plies'][0].get('uci') == uci)
    plies = branch['plies'] if match and legal is not False else []
    events = []
    for index, ply in enumerate(plies[:7]):
        if not isinstance(ply, dict):
            continue
        for raw in ply.get('effects', []) if isinstance(ply.get('effects'), list) else []:
            if isinstance(raw, dict) and raw.get('kind') and raw.get('text'):
                events.append(Event(str(raw['kind']), str(raw['text']).strip(), index,
                                    str(ply.get('san') or ''), str(ply.get('uci') or '')))
    # Repetition is a property of the full saved position sequence, not of a
    # check symbol in SAN. Only a threefold with repeated checks is recorded.
    if match and isinstance(branch.get('start_fen'),str) and len(plies)>=6:
        def signature(fen):
            bits=str(fen or '').split()
            return tuple(bits[:4]) if len(bits)>=4 else None
        initial=signature(branch['start_fen'])
        if initial:
            counts={initial:1}
            checks=[0,0]
            for i,ply in enumerate(plies):
                if any(e.get('kind') in ('check','discovered_check') for e in
                       (ply.get('effects') or []) if isinstance(e,dict)):
                    checks[i%2]+=1
                ident=signature(ply.get('fen_after'))
                if ident is None: break
                counts[ident]=counts.get(ident,0)+1
                if counts[ident]>=3 and max(checks)>=3:
                    events.append(Event('perpetual_check',
                        f'{san} illustrates a checking sequence that repeats a position three times; a draw may be claimed',
                        0,san,uci))
                    break
    # Avoid claiming that a root-locked record has independent proof if the
    # board cannot be replayed. This does not invalidate its stored evidence.
    return DecisionEvidence(
        root_uci=uci, root_san=san,
        role=str(branch.get('role') or '') if match else '',
        events=tuple(events),
        reply_san=str(plies[1].get('san')) if len(plies) > 1 and plies[1].get('san') else None,
        verified=bool(match and legal is True),
        root_motif=str(motif_key or field(row, 'motif_key', '') or field(row,'primary_motif_key','')),
        best_uci=str(field(row,'best_move_uci','') or ''),
        best_san=str(field(row,'best_move_san',field(row,'best_move_uci','')) or ''),
        eval_before_cp=field(row,'eval_before_cp'), eval_after_cp=field(row,'eval_after_cp'),
        mate_before=field(row,'mate_before') if legal is not False else None,
    )


def board_root_facts(row, uci, san):
    """Only immediate facts verifiable by replaying the exact legal root move."""
    try:
        import chess
        board = chess.Board(field(row,'fen',''))
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return ()
        before_piece = board.piece_at(move.from_square)
        opponent = not board.turn
        before_attacked = board.is_attacked_by(opponent,move.from_square)
        in_check = board.is_check()
        capture = board.is_capture(move)
        after = board.copy(stack=False)
        after.push(move)
        target = chess.square_name(move.to_square)
        results = []
        def add(kind,text):
            results.append(Event(kind,text,0,san,uci))
        if after.is_checkmate():
            add('checkmate',f'{san} checkmates the opponent king')
        elif before_piece and before_piece.piece_type == chess.KING:
            if in_check:
                add('check_evasion',f'{san} brings the king out of check')
            # An active king is more important in an ending than the mere
            # ability to respond to a checking move.
            if (len(board.piece_map()) <= 12 and
                    not any(p.piece_type == chess.QUEEN for p in board.piece_map().values())):
                add('king_activity',f'{san} activates the king on {target} in the endgame')
        if before_piece and before_piece.piece_type == chess.QUEEN and before_attacked \
                and not after.is_attacked_by(opponent,move.to_square):
            add('queen_safety',f'{san} moves the queen out of attack to {target}')
        if capture:
            captured = board.piece_at(move.to_square)
            if captured:
                add('capture',f'{san} captures the {chess.piece_name(captured.piece_type)} on {target}')
        # Only an actual new attack on two valuable pieces warrants 'fork'.
        piece = after.piece_at(move.to_square)
        if piece and piece.piece_type in (chess.KNIGHT,chess.BISHOP,chess.ROOK,chess.QUEEN):
            victims=[]
            for square in after.attacks(move.to_square):
                other=after.piece_at(square)
                if other and other.color==opponent and other.piece_type in (
                        chess.KING,chess.ROOK,chess.QUEEN,chess.BISHOP,chess.KNIGHT):
                    victims.append((other.piece_type,chess.square_name(square)))
            if len(victims)>=2:
                names=[f'{chess.piece_name(k)} on {sq}' for k,sq in victims[:2]]
                add('fork',f'{san} attacks the {names[0]} and {names[1]} together')
        return tuple(results)
    except (ImportError, KeyError,TypeError,ValueError):
        return ()


# One root-specific source of truth for old saved lines and newly verified
# attempt variations. Callers cannot accidentally narrate another root move.
def _selected_lines(row, move_uci):
    raw=unpack(field(row,'explanatory_lines_json'),{})
    lines=raw.get('lines',[]) if isinstance(raw,dict) else []
    valid=[line for line in lines if isinstance(line,dict)
        and line.get('root_uci')==move_uci
        and isinstance(line.get('plies'),list) and line['plies']
        and isinstance(line['plies'][0],dict)
        and line['plies'][0].get('uci',move_uci)==move_uci]
    priority={'recommended':3,'played':3,'alternative':3,
              'coaching_best_reply':2,'coaching_game_reply':2,'tested_reply':1}
    return sorted(valid,key=lambda l:(priority.get(l.get('role'),0),len(l['plies'])),reverse=True)


def branch_evidence(row,move_uci,attempt=None):
    lines=_selected_lines(row,move_uci)
    if lines and len(lines[0].get('plies',[]))>=2:
        return lines[0]
    attempt=attempt or {}
    pv=unpack(field(attempt,'verified_pv_json'),[])
    if not isinstance(pv,list) or not pv or pv[0]!=move_uci:
        pv=[]
    if pv:
        try:
            import chess
            from coaching.board_context.explanatory_evidence import describe_variation
            board=chess.Board(row['fen'])
            move=chess.Move.from_uci(move_uci)
            if move in board.legal_moves:
                desc=describe_variation(board,pv,'verified_attempt',
                     field(attempt,'eval_cp'),field(attempt,'mate'),first_move=move)
                if desc.get('root_uci')==move_uci and desc.get('plies'):
                    return desc
        except (ImportError,TypeError,ValueError,KeyError):
            pass
    return lines[0] if lines else None


def main_fact(ply):
    if not isinstance(ply,dict) or not isinstance(ply.get('effects'),list):
        return None
    priority={'checkmate':110,'promotion':100,'fork':95,'discovered_attack':88,
              'pin':87,'capture':68,'threat_neutralized':60,'check':25,'check_evasion':12}
    events=[e for e in ply['effects'] if isinstance(e,dict) and e.get('text')]
    return max(events,key=lambda e:priority.get(e.get('kind'),0),default=None)
