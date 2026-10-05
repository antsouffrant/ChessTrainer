from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import chess.pgn


# ---------------------------------------------------------------------
# LOCAL CONFIGURATION
# ---------------------------------------------------------------------

USERNAME = "antsouffrant"

PGN_FILE = Path("data/antsouffrant_2026_blitz.pgn")
STOCKFISH_DIR = Path("stockfish")
OUTPUT_FILE = Path("data/training_positions.json")

# Cheap first-pass screening
SCREEN_NODES = 2_000
SCREEN_MIN_ADVANTAGE_CP = 100
SCREEN_MIN_CPL_CP = 100

# Deeper confirmation
DEEP_NODES = 100_000
MIN_CPL_CP = 150
WINNING_CP = 150
EQUAL_CP = 50

# Used only to convert forced-mate evaluations to a large numeric score
# for centipawn-loss calculations.
MATE_SCORE_CP = 100_000

# Save this many plies from Stockfish's confirmed principal variation.
PV_PLIES = 10

# Stockfish configuration
STOCKFISH_THREADS = max(1, min(4, os.cpu_count() or 1))
STOCKFISH_HASH_MB = 256


@dataclass
class EvalResult:
    cp: int
    mate: Optional[int]
    best_move: Optional[chess.Move]
    pv: list[chess.Move]
    depth: Optional[int]
    nodes: Optional[int]


def find_stockfish() -> Path:
    """
    Find a Stockfish executable somewhere inside ./stockfish.
    """

    if not STOCKFISH_DIR.exists():
        raise FileNotFoundError(
            f"Stockfish folder not found: {STOCKFISH_DIR.resolve()}"
        )

    candidates = []

    for path in STOCKFISH_DIR.rglob("*"):
        if not path.is_file():
            continue

        name = path.name.lower()

        if not name.startswith("stockfish"):
            continue

        if sys.platform == "win32":
            if path.suffix.lower() == ".exe":
                candidates.append(path)
        else:
            if os.access(path, os.X_OK):
                candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            "No Stockfish executable was found inside the stockfish folder."
        )

    candidates.sort(
        key=lambda p: (
            len(p.relative_to(STOCKFISH_DIR).parts),
            len(p.name),
            p.name,
        )
    )

    return candidates[0].resolve()


def get_user_color(game: chess.pgn.Game) -> Optional[chess.Color]:
    white = game.headers.get("White", "")
    black = game.headers.get("Black", "")

    if white.casefold() == USERNAME.casefold():
        return chess.WHITE

    if black.casefold() == USERNAME.casefold():
        return chess.BLACK

    return None


def evaluate_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    user_color: chess.Color,
    nodes: int,
) -> EvalResult:
    """
    Evaluate a board from antsouffrant's perspective.
    """

    info = engine.analyse(
        board,
        chess.engine.Limit(nodes=nodes),
        info=(
            chess.engine.INFO_SCORE
            | chess.engine.INFO_PV
            | chess.engine.INFO_BASIC
        ),
    )

    pov_score = info["score"].pov(user_color)

    cp = pov_score.score(mate_score=MATE_SCORE_CP)

    if cp is None:
        raise RuntimeError("Unable to convert Stockfish score.")

    pv = list(info.get("pv", []))

    return EvalResult(
        cp=cp,
        mate=pov_score.mate(),
        best_move=pv[0] if pv else None,
        pv=pv,
        depth=info.get("depth"),
        nodes=info.get("nodes"),
    )


def evaluate_played_move(
    engine: chess.engine.SimpleEngine,
    board_before: chess.Board,
    played_move: chess.Move,
    user_color: chess.Color,
    nodes: int,
) -> tuple[EvalResult, EvalResult]:
    """
    Compare the best evaluation before the move against the evaluation
    after the move antsouffrant actually played.
    """

    before = evaluate_position(
        engine,
        board_before,
        user_color,
        nodes,
    )

    board_after = board_before.copy(stack=False)
    board_after.push(played_move)

    after = evaluate_position(
        engine,
        board_after,
        user_color,
        nodes,
    )

    return before, after


def centipawn_loss(before: EvalResult, after: EvalResult) -> int:
    return max(0, before.cp - after.cp)


def should_screen_deeply(
    before: EvalResult,
    after: EvalResult,
) -> bool:
    """
    Cheap screening is intentionally permissive.

    We prefer false positives here rather than missing a useful
    training position.
    """

    if before.mate is not None and before.mate > 0:
        return True

    return (
        before.cp >= SCREEN_MIN_ADVANTAGE_CP
        and centipawn_loss(before, after) >= SCREEN_MIN_CPL_CP
    )


def classify_position(
    before: EvalResult,
    after: EvalResult,
) -> Optional[str]:
    """
    Return one of:

        missed_checkmate
        blundered_win
        squandered_advantage

    or None if the position does not meet the requested criteria.
    """

    # Forced mate existed before the move, but no longer exists afterward.
    if (
        before.mate is not None
        and before.mate > 0
        and not (
            after.mate is not None
            and after.mate > 0
        )
    ):
        return "missed_checkmate"

    cpl = centipawn_loss(before, after)

    if cpl < MIN_CPL_CP:
        return None

    # Large advantage reduced to approximately equal.
    if (
        before.cp >= WINNING_CP
        and abs(after.cp) <= EQUAL_CP
    ):
        return "squandered_advantage"

    # Large error, but the resulting position is still clearly winning.
    if (
        before.cp >= WINNING_CP
        and after.cp >= WINNING_CP
    ):
        return "blundered_win"

    return None


def evaluation_label(result: EvalResult) -> str:
    if result.mate is not None:
        if result.mate > 0:
            return f"M{result.mate}"
        return f"-M{abs(result.mate)}"

    return f"{result.cp / 100:+.2f}"


def principal_variation_san(
    board: chess.Board,
    pv: list[chess.Move],
) -> list[str]:
    temp = board.copy(stack=False)
    san_moves = []

    for move in pv[:PV_PLIES]:
        if move not in temp.legal_moves:
            break

        san_moves.append(temp.san(move))
        temp.push(move)

    return san_moves


def get_game_id(
    game: chess.pgn.Game,
    fallback_index: int,
) -> str:
    site = game.headers.get("Site", "")

    if site:
        return site.rstrip("/").split("/")[-1]

    return f"game_{fallback_index}"


def build_record(
    game: chess.pgn.Game,
    game_index: int,
    ply: int,
    board_before: chess.Board,
    played_move: chess.Move,
    before: EvalResult,
    after: EvalResult,
    category: str,
    user_color: chess.Color,
) -> dict:
    best_move = before.best_move

    return {
        "category": category,

        "game_id": get_game_id(game, game_index),
        "site": game.headers.get("Site"),
        "date": (
            game.headers.get("UTCDate")
            or game.headers.get("Date")
        ),
        "utc_time": game.headers.get("UTCTime"),

        "white": game.headers.get("White"),
        "black": game.headers.get("Black"),
        "white_elo": game.headers.get("WhiteElo"),
        "black_elo": game.headers.get("BlackElo"),
        "result": game.headers.get("Result"),

        "opening": game.headers.get("Opening"),
        "eco": game.headers.get("ECO"),

        "user_color": (
            "white"
            if user_color == chess.WHITE
            else "black"
        ),

        "ply": ply,
        "move_number": board_before.fullmove_number,

        "fen": board_before.fen(),

        "played_move_uci": played_move.uci(),
        "played_move_san": board_before.san(played_move),

        "best_move_uci": (
            best_move.uci()
            if best_move
            else None
        ),
        "best_move_san": (
            board_before.san(best_move)
            if best_move
            else None
        ),

        "eval_before_cp": before.cp,
        "eval_after_cp": after.cp,
        "eval_before": evaluation_label(before),
        "eval_after": evaluation_label(after),

        "mate_before": before.mate,
        "mate_after": after.mate,

        "centipawn_loss": centipawn_loss(
            before,
            after,
        ),

        "stockfish_depth": before.depth,
        "stockfish_nodes": before.nodes,

        "principal_variation_uci": [
            move.uci()
            for move in before.pv[:PV_PLIES]
        ],

        "principal_variation_san": (
            principal_variation_san(
                board_before,
                before.pv,
            )
        ),
    }


def cheap_screen(
    engine: chess.engine.SimpleEngine,
) -> tuple[list[dict], int, int]:
    """
    First pass through all games.

    Returns:
        candidates
        games_seen
        user_positions_seen
    """

    candidates = []
    games_seen = 0
    positions_seen = 0

    with PGN_FILE.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as pgn:

        while True:
            game = chess.pgn.read_game(pgn)

            if game is None:
                break

            games_seen += 1

            user_color = get_user_color(game)

            if user_color is None:
                continue

            board = game.board()

            for ply, move in enumerate(
                game.mainline_moves(),
                start=1,
            ):
                if board.turn == user_color:
                    positions_seen += 1

                    before, after = evaluate_played_move(
                        engine,
                        board,
                        move,
                        user_color,
                        SCREEN_NODES,
                    )

                    if should_screen_deeply(
                        before,
                        after,
                    ):
                        candidates.append(
                            {
                                "game_index": games_seen,
                                "ply": ply,
                                "fen": board.fen(),
                                "played_move_uci": move.uci(),
                                "user_color": user_color,
                                "headers": dict(
                                    game.headers
                                ),
                            }
                        )

                board.push(move)

            if games_seen % 100 == 0:
                print(
                    f"Screened {games_seen:,} games | "
                    f"{positions_seen:,} positions | "
                    f"{len(candidates):,} candidates"
                )

    return (
        candidates,
        games_seen,
        positions_seen,
    )


def reconstruct_game_from_headers(
    headers: dict,
) -> chess.pgn.Game:
    game = chess.pgn.Game()
    game.headers.clear()

    for key, value in headers.items():
        game.headers[key] = value

    return game


def deep_confirmation(
    engine: chess.engine.SimpleEngine,
    candidates: list[dict],
) -> list[dict]:
    confirmed = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        board = chess.Board(
            candidate["fen"]
        )

        played_move = chess.Move.from_uci(
            candidate["played_move_uci"]
        )

        before, after = evaluate_played_move(
            engine,
            board,
            played_move,
            candidate["user_color"],
            DEEP_NODES,
        )

        category = classify_position(
            before,
            after,
        )

        if category is not None:
            game = reconstruct_game_from_headers(
                candidate["headers"]
            )

            confirmed.append(
                build_record(
                    game=game,
                    game_index=candidate[
                        "game_index"
                    ],
                    ply=candidate["ply"],
                    board_before=board,
                    played_move=played_move,
                    before=before,
                    after=after,
                    category=category,
                    user_color=candidate[
                        "user_color"
                    ],
                )
            )

        if index % 25 == 0:
            print(
                f"Deep analysis: "
                f"{index:,}/{len(candidates):,} | "
                f"{len(confirmed):,} confirmed"
            )

    return confirmed


def save_results(
    positions: list[dict],
    stockfish_path: Path,
    games_seen: int,
    positions_seen: int,
    candidate_count: int,
) -> None:

    counts = {
        "missed_checkmate": 0,
        "blundered_win": 0,
        "squandered_advantage": 0,
    }

    for position in positions:
        counts[position["category"]] += 1

    output = {
        "metadata": {
            "username": USERNAME,
            "pgn_file": str(PGN_FILE),
            "stockfish": str(stockfish_path),

            "games_screened": games_seen,
            "user_positions_screened": (
                positions_seen
            ),
            "screen_candidates": (
                candidate_count
            ),
            "confirmed_positions": len(
                positions
            ),

            "counts": counts,

            "settings": {
                "screen_nodes": SCREEN_NODES,
                "deep_nodes": DEEP_NODES,

                "screen_min_advantage_cp": (
                    SCREEN_MIN_ADVANTAGE_CP
                ),
                "screen_min_cpl_cp": (
                    SCREEN_MIN_CPL_CP
                ),

                "min_cpl_cp": MIN_CPL_CP,
                "winning_cp": WINNING_CP,
                "equal_cp": EQUAL_CP,
            },
        },

        "positions": positions,
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=2,
        )

def add_position_to_lichess_url(url, move_number, user_color):
    """
    Append the Lichess move-position fragment to a game URL.

    Example:
        move_number = 31, white -> #59
        move_number = 31, black -> #60
    """

    if user_color.lower() == "white":
        move_count = (move_number - 1) * 2 - 1
    else:
        move_count = (move_number - 1) * 2

    # Remove any existing fragment first.
    base_url = url.split("#")[0]

    return f"{base_url}#{move_count}"
    

def update_lichess_urls(json_file):
    with open(json_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    for position in data["positions"]:
        position["position_url"] = add_position_to_lichess_url(
            position["site"],
            position["move_number"],
            position["user_color"],
        )
        position["position_url"] = position["position_url"].replace(
            "https://lichess.org/",
            "https://lichess.org/embed/",
            1,
        )

    with open(json_file, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def main() -> None:
    if not PGN_FILE.exists():
        raise FileNotFoundError(
            f"PGN file not found: "
            f"{PGN_FILE.resolve()}"
        )

    stockfish_path = find_stockfish()

    print(
        f"Using Stockfish: "
        f"{stockfish_path}"
    )

    engine = chess.engine.SimpleEngine.popen_uci(
        str(stockfish_path)
    )

    try:
        options = {}

        if "Threads" in engine.options:
            options["Threads"] = (
                STOCKFISH_THREADS
            )

        if "Hash" in engine.options:
            options["Hash"] = (
                STOCKFISH_HASH_MB
            )

        if options:
            engine.configure(options)

        print("Starting cheap screening...")

        (
            candidates,
            games_seen,
            positions_seen,
        ) = cheap_screen(engine)

        print(
            f"Cheap screening complete: "
            f"{len(candidates):,} candidates."
        )

        print(
            "Starting deeper confirmation..."
        )

        confirmed = deep_confirmation(
            engine,
            candidates,
        )

    finally:
        engine.quit()

    category_order = {
        "missed_checkmate": 0,
        "squandered_advantage": 1,
        "blundered_win": 2,
    }

    confirmed.sort(
        key=lambda position: (
            category_order[
                position["category"]
            ],
            -position["centipawn_loss"],
        )
    )

    save_results(
        positions=confirmed,
        stockfish_path=stockfish_path,
        games_seen=games_seen,
        positions_seen=positions_seen,
        candidate_count=len(candidates),
    )

    print()
    print("Analysis complete.")
    print(
        f"Saved "
        f"{len(confirmed):,} positions to "
        f"{OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
