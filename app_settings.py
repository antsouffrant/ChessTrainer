from __future__ import annotations

import hashlib
import json
from collections import OrderedDict


# User-tunable settings. Internal schema/classifier version strings and thread
# locks deliberately live outside this registry because changing them manually
# would break cache semantics rather than tune chess analysis.
SETTING_DEFINITIONS = OrderedDict([
    ('engine', [
        {'key': 'stockfish_dir', 'label': 'Stockfish folder', 'type': 'text', 'default': 'stockfish',
         'help': 'Folder containing the local Stockfish executable.'},
        {'key': 'analysis_engine_threads', 'label': 'Analysis engine threads', 'type': 'int', 'default': 2, 'min': 1, 'max': 32,
         'help': 'CPU threads used by the background analysis engine.'},
        {'key': 'analysis_engine_hash_mb', 'label': 'Analysis engine hash', 'type': 'int', 'default': 128, 'min': 16, 'max': 4096, 'unit': 'MB',
         'help': 'Stockfish hash memory for background analysis.'},
        {'key': 'engine_start_timeout_seconds', 'label': 'Engine startup timeout', 'type': 'float', 'default': 20.0, 'min': 2.0, 'max': 120.0, 'step': 1.0, 'unit': 'sec',
         'help': 'Maximum time allowed for Stockfish to initialize.'},
        {'key': 'engine_restart_retries', 'label': 'Background engine restart retries', 'type': 'int', 'default': 2, 'min': 0, 'max': 10,
         'help': 'How many times a terminated Stockfish process is restarted before the job errors.'},
    ]),
    ('passes', [
        {'key': 'screen_seconds', 'label': 'Screening budget per game', 'type': 'float', 'default': 3.0, 'min': 0.5, 'max': 30.0, 'step': 0.5, 'unit': 'sec',
         'help': 'Approximate total time budget for the fast screen of one game.'},
        {'key': 'deep_seconds', 'label': 'Deep confirmation per candidate', 'type': 'float', 'default': 10.0, 'min': 1.0, 'max': 120.0, 'step': 1.0, 'unit': 'sec',
         'help': 'Approximate total budget for confirming one candidate training position.'},
        {'key': 'explanation_probe_enabled', 'label': 'Test explanatory replies', 'type': 'bool', 'default': True,
         'help': 'After deep confirmation, test other credible opponent replies to improve tactical explanations. Adds Stockfish analysis time.'},
        {'key': 'explanation_probe_fraction', 'label': 'Reply-probe time budget', 'type': 'float', 'default': 0.18, 'min': 0.0, 'max': 0.5, 'step': 0.02,
         'help': 'Additional reply-probe time as a fraction of deep-confirmation seconds (0 disables).' },
        {'key': 'base_screen_depth', 'label': 'Initial screening depth cap', 'type': 'int', 'default': 8, 'min': 1, 'max': 40,
         'help': 'Depth cap for pass 1 screening.'},
        {'key': 'base_deep_depth', 'label': 'Initial deep depth cap', 'type': 'int', 'default': 16, 'min': 1, 'max': 60,
         'help': 'Depth cap for pass 1 deep confirmation.'},
        {'key': 'progressive_depths_enabled', 'label': 'Try multiple evaluation depths', 'type': 'bool', 'default': True,
         'help': 'After a complete pass, automatically revisit the game set with higher depth caps.'},
        {'key': 'max_passes', 'label': 'Maximum refinement passes', 'type': 'int', 'default': 4, 'min': 1, 'max': 12,
         'help': 'Used only when multiple evaluation depths are enabled.'},
        {'key': 'screen_depth_step', 'label': 'Screen depth increase per pass', 'type': 'int', 'default': 2, 'min': 0, 'max': 12,
         'help': 'Additional screening plies allowed on each refinement pass.'},
        {'key': 'deep_depth_step', 'label': 'Deep depth increase per pass', 'type': 'int', 'default': 4, 'min': 0, 'max': 16,
         'help': 'Additional deep-confirmation plies allowed on each refinement pass.'},
        {'key': 'min_screen_search_seconds', 'label': 'Minimum shallow search per move', 'type': 'float', 'default': 0.015, 'min': 0.001, 'max': 2.0, 'step': 0.001, 'unit': 'sec',
         'help': 'Floor for each individual shallow Stockfish call during a game screen.'},
        {'key': 'max_screen_search_seconds', 'label': 'Maximum shallow search per move', 'type': 'float', 'default': 0.15, 'min': 0.005, 'max': 5.0, 'step': 0.005, 'unit': 'sec',
         'help': 'Ceiling for each individual shallow Stockfish call during a game screen.'},
    ]),
    ('thresholds', [
        {'key': 'mate_score_cp', 'label': 'Mate score', 'type': 'int', 'default': 100000, 'min': 10000, 'max': 1000000, 'unit': 'cp',
         'help': 'Centipawn proxy used when Stockfish reports a forced mate.'},
        {'key': 'min_cpl_cp', 'label': 'Minimum confirmed centipawn loss', 'type': 'int', 'default': 150, 'min': 0, 'max': 2000, 'unit': 'cp',
         'help': 'Minimum deep-confirmed loss required before ordinary mistake categories are considered.'},
        {'key': 'winning_cp', 'label': 'Winning threshold', 'type': 'int', 'default': 150, 'min': 0, 'max': 2000, 'unit': 'cp',
         'help': 'Evaluation treated as clearly winning from the user point of view.'},
        {'key': 'equal_cp', 'label': 'Equality band', 'type': 'int', 'default': 50, 'min': 0, 'max': 500, 'unit': 'cp',
         'help': 'Absolute evaluation considered roughly equal/drawable.'},
        {'key': 'loss_cp', 'label': 'Losing threshold', 'type': 'int', 'default': -150, 'min': -5000, 'max': 0, 'unit': 'cp',
         'help': 'Evaluation treated as clearly losing from the user point of view.'},
        {'key': 'playable_cp', 'label': 'Playable-position threshold', 'type': 'int', 'default': -100, 'min': -5000, 'max': 1000, 'unit': 'cp',
         'help': 'Lowest deep evaluation from which a major one-move blunder can still be classified.'},
        {'key': 'screen_playable_cp', 'label': 'Screening playable threshold', 'type': 'int', 'default': -100, 'min': -5000, 'max': 1000, 'unit': 'cp',
         'help': 'Lowest shallow pre-move evaluation that receives a follow-up screen.'},
        {'key': 'screen_min_cpl_cp', 'label': 'Minimum shallow centipawn loss', 'type': 'int', 'default': 100, 'min': 0, 'max': 2000, 'unit': 'cp',
         'help': 'Minimum shallow loss needed to promote an uncategorized move into deep confirmation.'},
        {'key': 'major_blunder_cpl_cp', 'label': 'Major-blunder centipawn loss', 'type': 'int', 'default': 250, 'min': 0, 'max': 3000, 'unit': 'cp',
         'help': 'Large loss used to catch severe errors that do not cross a named outcome threshold.'},
    ]),
    ('selection', [
        {'key': 'distinct_ply_gap', 'label': 'Distinct-position ply gap', 'type': 'int', 'default': 8, 'min': 0, 'max': 40, 'unit': 'plies',
         'help': 'Nearby manifestations of the same error category within this distance are treated as one episode.'},
        {'key': 'max_positions_per_game', 'label': 'Maximum retained positions per game', 'type': 'int', 'default': 4, 'min': 1, 'max': 20,
         'help': 'Hard cap on confirmed training positions retained from one game.'},
        {'key': 'max_deep_candidates_per_game', 'label': 'Maximum deep candidates per game', 'type': 'int', 'default': 4, 'min': 1, 'max': 20,
         'help': 'Hard cap on shallow candidates that receive the expensive deep confirmation.'},
    ]),
    ('learning_modes', [
        {'key': 'learning_mode_mistakes', 'label': 'Learn from mistakes', 'type': 'bool', 'default': True,
         'help': 'Find consequential mistakes, missed wins, and defensive errors in a personal game list.'},
        {'key': 'learning_mode_blunders', 'label': 'Train smaller blunders', 'type': 'bool', 'default': True,
         'help': 'Missed opportunities and smaller errors, separately from consequential mistakes.'},
        {'key': 'learning_mode_excellent', 'label': 'Reinforce excellent moves', 'type': 'bool', 'default': False,
         'help': 'Add unusually strong, instructive moves to the same personal lesson taxonomy rather than routine engine-best moves.'},
        {'key': 'learning_mode_brilliant', 'label': 'Celebrate brilliant / creative moves', 'type': 'bool', 'default': False,
         'help': 'Celebrate !!-style creative resources. Explicit PGN annotations are preferred when available; otherwise a strict sacrifice + uniqueness heuristic is used.'},
        {'key': 'excellent_uniqueness_cp', 'label': 'Excellent-move uniqueness gap', 'type': 'int', 'default': 80, 'min': 20, 'max': 500, 'unit': 'cp',
         'help': 'Minimum deep-evaluation gap between the played best move and the next-best alternative.'},
        {'key': 'brilliant_uniqueness_cp', 'label': 'Brilliant-move uniqueness gap', 'type': 'int', 'default': 180, 'min': 50, 'max': 1000, 'unit': 'cp',
         'help': 'Minimum alternative-move gap used by the unannotated brilliant-move fallback. Forced mate alone never creates a brilliancy label.'},
        {'key': 'positive_easy_win_cp', 'label': 'Routine-win suppression threshold', 'type': 'int', 'default': 500, 'min': 100, 'max': 3000, 'unit': 'cp',
         'help': 'Positions already above this advantage are normally excluded from reinforcement unless the move is exceptionally unique or sacrificial.'},
        {'key': 'max_reinforcement_candidates_per_game', 'label': 'Maximum reinforcement candidates per game', 'type': 'int', 'default': 2, 'min': 1, 'max': 8,
         'help': 'Hard cap on excellent/brilliant candidates sent to deep confirmation in one game.'},
        {'key': 'max_reinforcement_positions_per_game', 'label': 'Maximum reinforcement positions per game', 'type': 'int', 'default': 1, 'min': 1, 'max': 4,
         'help': 'Hard cap on retained excellent/brilliant training positions from one game.'},
        {'key': 'max_opposition_positions_per_game', 'label': 'Maximum opposition positions per game', 'type': 'int', 'default': 2, 'min': 1, 'max': 6,
         'help': 'Hard cap on retained exploit-the-opponent positions from one researched game.'},
    ]),
    ('lessons', [
        {'key': 'lesson_page_size', 'label': 'Lesson positions per page', 'type': 'int', 'default': 16, 'min': 8, 'max': 200,
         'help': 'Maximum number of training-position tiles loaded on one lesson-detail page.'},
    ]),
    ('appearance', [
        {'key': 'show_square_coordinates', 'label': 'Show square coordinates', 'type': 'bool', 'default': False,
         'help': 'Show file and rank labels inside the board squares, oriented to your side.'},
        {'key': 'wooden_board_enabled', 'label': 'Use polished wooden board', 'type': 'bool', 'default': False,
         'help': 'Switch the trainer to polished wood squares with light-pine White pieces and hickory-brown Black pieces.'},
    ]),
    ('adaptive_coach', [
        {'key': 'adaptive_coach_enabled', 'label': 'Enable adaptive coaching chat', 'type': 'bool', 'default': True,
         'help': 'Show the adaptive coaching chat beside the training position.'},
        {'key': 'adaptive_coach_use_ollama', 'label': 'Use local Ollama for contextual comprehension', 'type': 'bool', 'default': False,
         'help': 'When enabled, a local Ollama model helps reconstruct ambiguous free-form chess language using the exact board, legal moves, and recent coach conversation. Chess truth is still verified by python-chess and Stockfish.'},
        {'key': 'ollama_base_url', 'label': 'Ollama URL', 'type': 'text', 'default': 'http://127.0.0.1:11434',
         'help': 'Local Ollama server used only when local model parsing is enabled.'},
        {'key': 'ollama_model', 'label': 'Ollama model', 'type': 'text', 'default': 'qwen2.5:7b',
         'help': 'Local model used only to interpret ambiguous natural-language references and claims. It cannot invent legal moves or decide chess truth.'},
        {'key': 'adaptive_concept_min_games', 'label': 'Games required to promote a concept', 'type': 'int', 'default': 2, 'min': 1, 'max': 20,
         'help': 'A candidate concept must recur across at least this many distinct games before it becomes a personal lesson.'},
        {'key': 'adaptive_concept_min_verified_claims', 'label': 'Verified claims required', 'type': 'int', 'default': 1, 'min': 1, 'max': 10,
         'help': 'Minimum number of user-originated confirmed claims before a candidate concept can be promoted.'},
        {'key': 'adaptive_concept_promotion_score', 'label': 'Concept promotion score', 'type': 'float', 'default': 0.68, 'min': 0.0, 'max': 1.0, 'step': 0.01,
         'help': 'Combined verification, recurrence, distinctiveness, and teachability score required for promotion.'},
    ]),
    ('trainer', [
        {'key': 'near_optimal_cp', 'label': 'Near-optimal acceptance margin', 'type': 'int', 'default': 60, 'min': 0, 'max': 500, 'unit': 'cp',
         'help': 'A non-engine move may pass when it stays within this margin of the top move.'},
        {'key': 'min_improvement_over_game_cp', 'label': 'Minimum improvement over game move', 'type': 'int', 'default': 75, 'min': 0, 'max': 1000, 'unit': 'cp',
         'help': 'A near-optimal alternative must improve on the move actually played by at least this amount.'},
        {'key': 'review_engine_seconds', 'label': 'Post-solve Stockfish time', 'type': 'float', 'default': 0.45, 'min': 0.05, 'max': 10.0, 'step': 0.05, 'unit': 'sec',
         'help': 'Time used for each post-solve analysis-mode evaluation.'},
        {'key': 'review_engine_retries', 'label': 'Review engine restart retries', 'type': 'int', 'default': 2, 'min': 0, 'max': 10,
         'help': 'Restart attempts for the interactive review engine.'},
        {'key': 'review_engine_threads', 'label': 'Review engine threads', 'type': 'int', 'default': 1, 'min': 1, 'max': 16,
         'help': 'CPU threads used by post-solve Stockfish analysis.'},
        {'key': 'review_engine_hash_mb', 'label': 'Review engine hash', 'type': 'int', 'default': 64, 'min': 16, 'max': 2048, 'unit': 'MB',
         'help': 'Stockfish hash memory for post-solve interactive analysis.'},
    ]),
])

DEFAULT_SETTINGS = {
    item['key']: item['default']
    for items in SETTING_DEFINITIONS.values()
    for item in items
}

# Settings that change background candidate discovery / deep analysis. The hash
# becomes part of cache eligibility so changing these settings causes games to
# be reconsidered instead of silently reusing stale analysis.
ANALYSIS_SIGNATURE_KEYS = (
    'stockfish_dir', 'analysis_engine_threads', 'analysis_engine_hash_mb',
    'mate_score_cp', 'min_cpl_cp', 'winning_cp', 'equal_cp', 'loss_cp',
    'playable_cp', 'screen_playable_cp', 'screen_min_cpl_cp',
    'major_blunder_cpl_cp', 'distinct_ply_gap', 'max_positions_per_game',
    'max_deep_candidates_per_game', 'min_screen_search_seconds',
    'max_screen_search_seconds', 'screen_seconds', 'deep_seconds',
    'explanation_probe_enabled', 'explanation_probe_fraction',
    'base_screen_depth', 'base_deep_depth', 'progressive_depths_enabled',
    'max_passes', 'screen_depth_step', 'deep_depth_step',
    'learning_mode_mistakes', 'learning_mode_blunders', 'learning_mode_excellent', 'learning_mode_brilliant',
    'excellent_uniqueness_cp', 'brilliant_uniqueness_cp', 'positive_easy_win_cp',
    'max_reinforcement_candidates_per_game', 'max_reinforcement_positions_per_game',
    'max_opposition_positions_per_game',
)


def _coerce(definition, raw):
    kind = definition['type']
    if kind == 'bool':
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in {'1', 'true', 'yes', 'on'}
    if kind == 'int':
        value = int(float(raw))
    elif kind == 'float':
        value = float(raw)
    else:
        return str(raw).strip()

    if 'min' in definition:
        value = max(definition['min'], value)
    if 'max' in definition:
        value = min(definition['max'], value)
    return value


def definitions_by_key():
    return {
        item['key']: item
        for items in SETTING_DEFINITIONS.values()
        for item in items
    }


def get_settings(conn=None):
    close_conn = False
    if conn is None:
        from db import connect
        conn = connect()
        close_conn = True
    try:
        values = dict(DEFAULT_SETTINGS)
        try:
            rows = conn.execute('SELECT key, value FROM app_settings').fetchall()
        except Exception:
            rows = []
        defs = definitions_by_key()
        for row in rows:
            key = row['key']
            if key not in defs:
                continue
            try:
                decoded = json.loads(row['value'])
                values[key] = _coerce(defs[key], decoded)
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
        return values
    finally:
        if close_conn:
            conn.close()


def settings_from_snapshot(snapshot_text, conn=None):
    base = get_settings(conn)
    if not snapshot_text:
        return base
    try:
        supplied = json.loads(snapshot_text)
    except (TypeError, json.JSONDecodeError):
        return base
    defs = definitions_by_key()
    for key, raw in supplied.items():
        if key in defs:
            try:
                base[key] = _coerce(defs[key], raw)
            except (ValueError, TypeError):
                pass
    return base


def serialize_settings(settings):
    return json.dumps(settings, sort_keys=True, separators=(',', ':'))


def analysis_signature(settings):
    payload = {key: settings.get(key, DEFAULT_SETTINGS[key]) for key in ANALYSIS_SIGNATURE_KEYS}
    payload['_job_learning_modes'] = sorted(settings.get('_job_learning_modes') or [])
    payload['_source_type'] = settings.get('_source_type', 'self')
    payload['_source_username'] = str(settings.get('_source_username') or '').casefold()
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha1(raw).hexdigest()[:16]


def save_settings(form, conn):
    defs = definitions_by_key()
    saved = {}
    for key, definition in defs.items():
        if definition['type'] == 'bool':
            raw = form.get(key, 'off')
        else:
            raw = form.get(key, definition['default'])
        value = _coerce(definition, raw)
        saved[key] = value
        conn.execute('''
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        ''', (key, json.dumps(value)))
    return saved



def save_setting(key, raw_value, conn):
    """Persist one setting without mutating unrelated settings."""
    defs = definitions_by_key()
    if key not in defs:
        raise KeyError(key)
    definition = defs[key]
    value = _coerce(definition, raw_value)
    conn.execute(
        """
        INSERT INTO app_settings(key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (key, json.dumps(value)),
    )
    return value

def reset_settings(conn):
    conn.execute('DELETE FROM app_settings')
