import sqlite3
from pathlib import Path

from learning import CLASSIFIER_VERSION, CONCEPT_CATALOG

DB_PATH = Path('data/chess_trainer.sqlite3')

SCHEMA = '''
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, username)
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    date_range TEXT NOT NULL,
    game_types TEXT NOT NULL,
    screen_depth INTEGER NOT NULL DEFAULT 8,
    deep_depth INTEGER NOT NULL DEFAULT 16,
    screen_seconds REAL NOT NULL DEFAULT 3.0,
    deep_seconds REAL NOT NULL DEFAULT 10.0,
    current_pass INTEGER NOT NULL DEFAULT 1,
    max_passes INTEGER NOT NULL DEFAULT 4,
    passes_completed INTEGER NOT NULL DEFAULT 0,
    current_screen_depth INTEGER NOT NULL DEFAULT 8,
    current_deep_depth INTEGER NOT NULL DEFAULT 16,
    settings_json TEXT,
    source_type TEXT NOT NULL DEFAULT 'self',
    source_username TEXT,
    learning_modes TEXT NOT NULL DEFAULT '["mistakes"]',
    status TEXT NOT NULL DEFAULT 'queued',
    games_retrieved INTEGER NOT NULL DEFAULT 0,
    games_processed INTEGER NOT NULL DEFAULT 0,
    games_screened INTEGER NOT NULL DEFAULT 0,
    -- A checkpoint is committed only when one entire game's deep analysis finishes.
    -- Offset is the text-stream seek cookie into the saved immutable PGN batch.
    checkpoint_pass INTEGER NOT NULL DEFAULT 0,
    checkpoint_game_index INTEGER NOT NULL DEFAULT 0,
    checkpoint_file_offset INTEGER NOT NULL DEFAULT 0,
    positions_found INTEGER NOT NULL DEFAULT 0,
    perf_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    metadata_refreshed_at TEXT,
    force_reanalysis INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);


-- Retrieval is separate from Stockfish analysis and runs only for new lists.
CREATE TABLE IF NOT EXISTS retrieval_processes (
    job_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    bytes_downloaded INTEGER NOT NULL DEFAULT 0,
    bytes_total INTEGER NOT NULL DEFAULT 0,
    perf_json TEXT,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metadata_processes (
    job_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'idle',
    cursor INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    without_pgn INTEGER NOT NULL DEFAULT 0,
    perf_json TEXT,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analyzed_games (
    account_id INTEGER NOT NULL,
    game_id TEXT NOT NULL,
    site TEXT,
    game_date TEXT,
    game_pgn TEXT,
    source_job_id INTEGER,
    analysis_version TEXT NOT NULL DEFAULT 'legacy',
    max_screen_depth INTEGER NOT NULL DEFAULT 0,
    max_deep_depth INTEGER NOT NULL DEFAULT 0,
    analysis_pass INTEGER NOT NULL DEFAULT 0,
    settings_signature TEXT,
    source_type TEXT NOT NULL DEFAULT 'self',
    source_username TEXT,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(account_id, game_id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(source_job_id) REFERENCES analysis_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_analyzed_games_account
ON analyzed_games(account_id, completed_at);

CREATE TABLE IF NOT EXISTS analysis_candidates (
    job_id INTEGER NOT NULL,
    game_id TEXT NOT NULL,
    ply INTEGER NOT NULL,
    first_pass INTEGER NOT NULL DEFAULT 1,
    last_pass INTEGER NOT NULL DEFAULT 1,
    learning_mode TEXT NOT NULL DEFAULT 'mistakes',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id, game_id, ply),
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_analysis_candidates_job
ON analysis_candidates(job_id);

CREATE TABLE IF NOT EXISTS training_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    game_id TEXT,
    site TEXT,
    game_date TEXT,
    opponent TEXT,
    category TEXT NOT NULL,
    learning_mode TEXT NOT NULL DEFAULT 'mistakes',
    fen TEXT NOT NULL,
    previous_fen TEXT,
    opponent_move_uci TEXT,
    opponent_move_san TEXT,
    user_color TEXT NOT NULL,
    move_number INTEGER NOT NULL,
    mistake_ply INTEGER,
    game_pgn TEXT,
    opening_key TEXT,
    opening_name TEXT,
    opening_variation TEXT,
    opening_eco TEXT,
    opening_source TEXT,
    opening_history TEXT,
    historical_match TEXT,
    played_move_uci TEXT,
    played_move_san TEXT,
    best_move_uci TEXT NOT NULL,
    best_move_san TEXT,
    eval_before_cp INTEGER,
    eval_after_cp INTEGER,
    mate_before INTEGER,
    mate_after INTEGER,
    centipawn_loss INTEGER,
    difficulty_score REAL,
    estimated_rating INTEGER,
    difficulty_version TEXT,
    best_pv_uci TEXT,
    played_pv_uci TEXT,
    alternative_pvs_json TEXT,
    critical_events_json TEXT,
    explanatory_lines_json TEXT,
    proactive_coach_json TEXT,
    coach_prompt TEXT,
    coach_explanation TEXT,
    coaching_version TEXT,
    analysis_pass INTEGER NOT NULL DEFAULT 0,
    analysis_screen_depth INTEGER NOT NULL DEFAULT 0,
    analysis_deep_depth INTEGER NOT NULL DEFAULT 0,
    learned INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    correct_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, game_id, fen, played_move_uci),
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id)
);

CREATE TABLE IF NOT EXISTS learning_concepts (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    family TEXT NOT NULL,
    description TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'built_in',
    status TEXT NOT NULL DEFAULT 'seeded',
    account_id INTEGER,
    aliases_json TEXT,
    detector_json TEXT,
    concept_score REAL NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    validated_count INTEGER NOT NULL DEFAULT 0,
    distinct_games INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS position_concepts (
    position_id INTEGER NOT NULL,
    concept_key TEXT NOT NULL,
    confidence REAL NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    evidence TEXT,
    classifier_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(position_id, concept_key),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(concept_key) REFERENCES learning_concepts(key)
);

CREATE INDEX IF NOT EXISTS idx_position_concepts_concept
ON position_concepts(concept_key, position_id);

CREATE TABLE IF NOT EXISTS position_motif_taxonomy (
    position_id INTEGER PRIMARY KEY,
    context_key TEXT NOT NULL CHECK(context_key IN ('attack','defend')),
    move_type_key TEXT CHECK(move_type_key IN ('tactical','strategic') OR move_type_key IS NULL),
    motif_key TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence TEXT NOT NULL DEFAULT '',
    taxonomy_version TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(motif_key) REFERENCES learning_concepts(key)
);
CREATE INDEX IF NOT EXISTS idx_position_motif_taxonomy_filters
ON position_motif_taxonomy(context_key, move_type_key, motif_key, position_id);

CREATE INDEX IF NOT EXISTS idx_training_positions_job_game
ON training_positions(job_id, game_id);


CREATE TABLE IF NOT EXISTS coach_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, position_id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    structured_json TEXT,
    generation_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(thread_id) REFERENCES coach_threads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_board_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    move_uci TEXT NOT NULL,
    move_san TEXT,
    correct INTEGER NOT NULL DEFAULT 0,
    from_saved_line INTEGER NOT NULL DEFAULT 0,
    eval_cp INTEGER,
    mate INTEGER,
    best_reply_san TEXT,
    verified_pv_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_coach_board_attempts_session
    ON coach_board_attempts(position_id, session_key, id);

CREATE TABLE IF NOT EXISTS coach_solve_recaps (
    position_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    message_id INTEGER NOT NULL UNIQUE,
    PRIMARY KEY(position_id, session_key),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_proactive_history (
    job_id INTEGER NOT NULL,
    classic_key TEXT NOT NULL,
    position_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id, classic_key),
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_proactive_spotlights (
    job_id INTEGER NOT NULL,
    recommended_position_id INTEGER NOT NULL,
    at_position_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(job_id, recommended_position_id),
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(recommended_position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coach_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    intent TEXT,
    claim_type TEXT NOT NULL,
    subject TEXT,
    object TEXT,
    square TEXT,
    file TEXT,
    raw_claim TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    explanation TEXT,
    concept_key TEXT,
    structured_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(thread_id) REFERENCES coach_threads(id) ON DELETE CASCADE,
    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(concept_key) REFERENCES learning_concepts(key)
);

CREATE TABLE IF NOT EXISTS concept_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_key TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    claim_id INTEGER,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    evidence_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(concept_key) REFERENCES learning_concepts(key),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(claim_id) REFERENCES coach_claims(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_coach_messages_thread ON coach_messages(thread_id, id);
CREATE INDEX IF NOT EXISTS idx_coach_claims_position ON coach_claims(position_id, id);
CREATE INDEX IF NOT EXISTS idx_concept_evidence_concept ON concept_evidence(concept_key, account_id);

CREATE TABLE IF NOT EXISTS position_taxonomy_feedback (
    position_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    field_key TEXT NOT NULL CHECK(field_key IN ('context','move_type','motif')),
    selected_key TEXT NOT NULL,
    model_key_at_vote TEXT NOT NULL,
    taxonomy_version_at_vote TEXT,
    coaching_version_at_vote TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(position_id, field_key),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_position_taxonomy_feedback_account
ON position_taxonomy_feedback(account_id, field_key, selected_key);

CREATE TABLE IF NOT EXISTS position_feedback (
    position_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('position', 'explanation', 'motif')),
    rating INTEGER NOT NULL CHECK(rating IN (-1, 1)),
    lesson_key TEXT,
    primary_motif_key TEXT,
    content_snapshot TEXT,
    coaching_version TEXT,
    classifier_version_at_vote TEXT,
    suggested_text TEXT,
    suggested_motif_key TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(position_id, category),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_position_feedback_account ON position_feedback(account_id, category, rating);

CREATE TABLE IF NOT EXISTS coach_message_feedback (
    message_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK(rating IN (-1, 1)),
    lesson_key TEXT,
    suggested_text TEXT,
    coaching_version_at_vote TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_id) REFERENCES coach_messages(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_coach_feedback_account ON coach_message_feedback(account_id, rating, updated_at);

-- A rated explanation belongs to a specific attempted continuation, rather
-- than one combined solve recap. The original position_feedback explanation
-- row remains the canonical 'solving' continuation for backward compatibility.
CREATE TABLE IF NOT EXISTS continuation_explanation_feedback (
    position_id INTEGER NOT NULL,
    continuation_key TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK(rating IN (-1, 1)),
    lesson_key TEXT,
    content_snapshot TEXT,
    coaching_version TEXT,
    suggested_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(position_id, continuation_key),
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);
CREATE INDEX IF NOT EXISTS idx_continuation_feedback_account
ON continuation_explanation_feedback(account_id, rating, updated_at);


-- v86 durable feedback dictionaries: never cascade from ephemeral coach data.
CREATE TABLE IF NOT EXISTS feedback_positions (
    position_key TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    username TEXT NOT NULL,
    game_id TEXT NOT NULL,
    source_job_id INTEGER,
    ply INTEGER,
    fen TEXT,
    board_identity TEXT NOT NULL,
    user_color TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback_position_sources (
    position_id INTEGER PRIMARY KEY,
    position_key TEXT NOT NULL REFERENCES feedback_positions(position_key)
);
CREATE INDEX IF NOT EXISTS idx_feedback_position_sources_key ON feedback_position_sources(position_key);
CREATE TABLE IF NOT EXISTS feedback_continuations (
    continuation_id TEXT PRIMARY KEY,
    position_key TEXT NOT NULL REFERENCES feedback_positions(position_key),
    move_key TEXT NOT NULL,
    UNIQUE(position_key, move_key)
);
-- A fact table independent of coach_messages and training_positions deletion.
-- 0 is an explicit withdrawal event, not an unrated position.
-- Immutable displayed explanation snapshots. Not deleted on coaching refresh.
-- One position+continuation may have several messages across models or texts.
CREATE TABLE IF NOT EXISTS feedback_message_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    continuation_key TEXT NOT NULL,
    generation_version TEXT NOT NULL,
    content_snapshot TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(position_id,continuation_key,generation_version,content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_feedback_message_snapshots_position
ON feedback_message_snapshots(position_id,id);
CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_key TEXT NOT NULL REFERENCES feedback_positions(position_key),
    continuation_id TEXT REFERENCES feedback_continuations(continuation_id),
    source_position_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    feedback_type TEXT NOT NULL,
    evaluation_run_id INTEGER REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL CHECK(rating IN (-1,0,1)),
    lesson_key TEXT,
    content_snapshot TEXT,
    coaching_version TEXT,
    classifier_version TEXT,
    taxonomy_version TEXT,
    suggested_text TEXT,
    suggested_motif_key TEXT,
    model_key TEXT,
    selected_key TEXT,
    source_message_id INTEGER,
    message_snapshot_id INTEGER,
    chat_user_message TEXT,
    chat_structured_json TEXT,
    source TEXT NOT NULL DEFAULT 'vote',
    source_reference TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_feedback_events_position ON feedback_events(position_key,id DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_events_version ON feedback_events(coaching_version,feedback_type,rating);
CREATE INDEX IF NOT EXISTS idx_feedback_events_source ON feedback_events(source_position_id,id DESC);


-- Frozen apples-to-apples coaching cohort: never redraw on a refresh.
CREATE TABLE IF NOT EXISTS coach_benchmark_cohorts (
    job_id INTEGER PRIMARY KEY REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    selection_version TEXT NOT NULL DEFAULT 'v1-stratified-hash',
    source_count INTEGER NOT NULL,
    sample_size INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS coach_benchmark_positions (
    job_id INTEGER NOT NULL REFERENCES coach_benchmark_cohorts(job_id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    fen TEXT NOT NULL,
    category TEXT NOT NULL,
    learning_mode TEXT NOT NULL,
    PRIMARY KEY(job_id,position_id), UNIQUE(job_id,ordinal)
);
-- Only authoritative active cache for generated teaching text. One record
-- per position, message kind, and continuation. Feedback snapshots are an
-- immutable archive, and conversational transcripts are not replay caches.
CREATE TABLE IF NOT EXISTS coaching_message_cache (
    position_id INTEGER NOT NULL REFERENCES training_positions(id) ON DELETE CASCADE,
    message_type TEXT NOT NULL CHECK(message_type IN ('best_move','attempted_move','game_move')),
    continuation_key TEXT NOT NULL,
    generation_version TEXT NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL DEFAULT '',
    coach_prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(position_id,message_type,continuation_key)
);
CREATE INDEX IF NOT EXISTS idx_coaching_message_cache_model
    ON coaching_message_cache(generation_version,message_type);

CREATE TABLE IF NOT EXISTS coach_benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES coach_benchmark_cohorts(job_id) ON DELETE CASCADE,
    coaching_version TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL,
    expected_positions INTEGER NOT NULL,
    captured_positions INTEGER NOT NULL,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id,coaching_version)
);
CREATE TABLE IF NOT EXISTS coach_benchmark_snapshots (
    run_id INTEGER NOT NULL REFERENCES coach_benchmark_runs(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL,
    explanation TEXT,
    coach_prompt TEXT,
    motif_key TEXT,
    context_key TEXT,
    move_type_key TEXT,
    PRIMARY KEY(run_id,position_id)
);
CREATE INDEX IF NOT EXISTS idx_coach_benchmark_positions_order
    ON coach_benchmark_positions(job_id,ordinal);

-- Independent evaluation sessions. Neither global training_positions.learned
-- nor coach cache deletion determines the status of an evaluation position.
CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    benchmark_run_id INTEGER NOT NULL REFERENCES coach_benchmark_runs(id) ON DELETE CASCADE,
    coaching_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_job ON evaluation_runs(job_id,id);
CREATE TABLE IF NOT EXISTS evaluation_run_positions (
    run_id INTEGER NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    solved_at TEXT,
    PRIMARY KEY(run_id,position_id)
);
CREATE TABLE IF NOT EXISTS evaluation_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    position_id INTEGER NOT NULL,
    move_uci TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK(correct IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id,position_id) REFERENCES evaluation_run_positions(run_id,position_id)
);
CREATE INDEX IF NOT EXISTS idx_evaluation_attempts_run ON evaluation_attempts(run_id,position_id);

-- Activity history is append-only across manual puzzle resets. The first
-- legal training attempt creates a session; merely showing a puzzle does not.
CREATE TABLE IF NOT EXISTS player_solve_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    game_id TEXT,
    opening_key TEXT,
    opening_name TEXT,
    primary_motif_key TEXT,
    learning_mode TEXT,
    lesson_key TEXT,
    evaluation_run_id INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    first_try_solved INTEGER NOT NULL DEFAULT 0,
    active_seconds REAL NOT NULL DEFAULT 0,
    solve_seconds REAL,
    timing_status TEXT NOT NULL DEFAULT 'pending',
    max_solve_seconds REAL NOT NULL DEFAULT 300,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    solved_at TEXT,
    abandoned_at TEXT,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES analysis_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_player_sessions_job ON player_solve_sessions(job_id, position_id);
CREATE TABLE IF NOT EXISTS player_solve_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    position_id INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    move_uci TEXT NOT NULL,
    correct INTEGER NOT NULL,
    active_seconds_delta REAL,
    attempted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES player_solve_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY(position_id) REFERENCES training_positions(id) ON DELETE CASCADE,
    UNIQUE(session_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS idx_player_attempts_position ON player_solve_attempts(position_id);

CREATE TABLE IF NOT EXISTS engine_eval_cache (
    fen TEXT PRIMARY KEY,
    best_move_uci TEXT,
    best_move_san TEXT,
    eval_white_cp INTEGER,
    mate_white INTEGER,
    depth INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''


class _ClosingConnection(sqlite3.Connection):
    """Unlike sqlite3's normal context manager, close after commit/rollback.

    Most request handlers use ``with connect() as conn``; sqlite3.Connection
    normally leaves the connection open on context exit. In a threaded Flask
    server, leaked readers can retain WAL snapshots and exacerbate busy errors.
    """
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _fen_board_identity(fen):
    parts = str(fen or '').split()
    return ' '.join(parts[:4]) if len(parts) >= 4 else str(fen or '').strip()


def connect(timeout=15):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=timeout, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.create_function('board_identity', 1, _fen_board_identity, deterministic=True)
    conn.execute('PRAGMA foreign_keys = ON')
    # WAL is enabled by init_db; changing journal_mode on every request can
    # itself require a database lock while an evaluation worker is active.
    conn.execute(f'PRAGMA busy_timeout = {max(1, int(timeout * 1000))}')
    return conn


def _columns(conn, table):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _seed_learning_concepts(conn):
    for concept in CONCEPT_CATALOG:
        conn.execute('''
            INSERT INTO learning_concepts(key, name, family, description, priority, source, status)
            VALUES (?, ?, ?, ?, ?, 'built_in', ?)
            ON CONFLICT(key) DO UPDATE SET
                name = excluded.name,
                family = excluded.family,
                description = excluded.description,
                priority = excluded.priority,
                status = CASE WHEN learning_concepts.source = 'built_in'
                              THEN excluded.status ELSE learning_concepts.status END
        ''', (
            concept['key'], concept['name'], concept['family'],
            concept['description'], concept['priority'], concept.get('status','seeded'),
        ))


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)

        # v100 migration: retain only the newest evaluation per game list and
        # coaching version as authoritative. Older runs, their attempts and
        # their append-only feedback stay in the database for provenance.
        conn.execute('''UPDATE evaluation_runs SET status='superseded'
            WHERE id NOT IN (SELECT MAX(id) FROM evaluation_runs
                             GROUP BY job_id,coaching_version)''')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_one_current_model
            ON evaluation_runs(job_id,coaching_version)
            WHERE status!='superseded' ''')

        # Player stats use a single opt-in switch in all modes. Evaluation
        # runs have independent open activity sessions, so they cannot absorb
        # ordinary attempts or attempts from another benchmark run.
        if 'evaluation_run_id' not in _columns(conn, 'player_solve_sessions'):
            conn.execute('ALTER TABLE player_solve_sessions ADD COLUMN evaluation_run_id INTEGER')
        conn.execute('DROP INDEX IF EXISTS idx_player_open_session')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_player_open_regular_session
            ON player_solve_sessions(position_id)
            WHERE evaluation_run_id IS NULL AND solved_at IS NULL AND abandoned_at IS NULL''')
        conn.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_player_open_evaluation_session
            ON player_solve_sessions(position_id, evaluation_run_id)
            WHERE evaluation_run_id IS NOT NULL AND solved_at IS NULL AND abandoned_at IS NULL''')

        # v112 message-level, generation-time attribution. Legacy votes remain
        # untouched; snapshots are additive and independent of cache reset.
        if 'message_snapshot_id' not in _columns(conn, 'feedback_events'):
            conn.execute('ALTER TABLE feedback_events ADD COLUMN message_snapshot_id INTEGER')
        if 'generation_version' not in _columns(conn, 'coach_messages'):
            conn.execute('ALTER TABLE coach_messages ADD COLUMN generation_version TEXT')

        if 'evaluation_run_id' not in _columns(conn, 'feedback_events'):
            conn.execute('ALTER TABLE feedback_events ADD COLUMN evaluation_run_id INTEGER')

        # v101 one-time cleanup: the experimental v33 evaluation is not part
        # of the canonical benchmark series. Preserve all non-evaluation v33
        # feedback and immutable coaching snapshots.
        if not conn.execute(
            "SELECT 1 FROM app_settings WHERE key='v101_v33_evaluation_retired'"
        ).fetchone():
            from evaluation_runs import retire_v33_evaluation_feedback
            retire_v33_evaluation_feedback(conn)
            conn.execute('''INSERT INTO app_settings(key,value)
                VALUES ('v101_v33_evaluation_retired','1')''')

        # Store the Stockfish PV already computed when verifying an attempted move.
        # This is a lightweight additive migration; no deep reanalysis.
        if 'verified_pv_json' not in _columns(conn, 'coach_board_attempts'):
            conn.execute('ALTER TABLE coach_board_attempts ADD COLUMN verified_pv_json TEXT')

        # Existing chat thumbs remain intact. Context is optional for older rows.
        if 'lesson_key' not in _columns(conn, 'coach_message_feedback'):
            conn.execute('ALTER TABLE coach_message_feedback ADD COLUMN lesson_key TEXT')
        if 'suggested_text' not in _columns(conn, 'coach_message_feedback'):
            conn.execute('ALTER TABLE coach_message_feedback ADD COLUMN suggested_text TEXT')
        if 'coaching_version_at_vote' not in _columns(conn, 'coach_message_feedback'):
            conn.execute('ALTER TABLE coach_message_feedback ADD COLUMN coaching_version_at_vote TEXT')
        if 'coaching_version_at_vote' not in _columns(conn, 'position_taxonomy_feedback'):
            conn.execute('ALTER TABLE position_taxonomy_feedback ADD COLUMN coaching_version_at_vote TEXT')
        # Defensive additive migration for incomplete experimental ledgers or
        # databases built from historical schemas. Never drop event records.
        for table, columns in {
            'feedback_events': ('suggested_text', 'suggested_motif_key', 'lesson_key',
                                'chat_user_message', 'chat_structured_json'),
        }.items():
            known = _columns(conn, table)
            for column in columns:
                if column not in known:
                    conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} TEXT')

        if 'perf_json' not in _columns(conn, 'retrieval_processes'):
            conn.execute('ALTER TABLE retrieval_processes ADD COLUMN perf_json TEXT')
        if 'perf_json' not in _columns(conn, 'metadata_processes'):
            conn.execute('ALTER TABLE metadata_processes ADD COLUMN perf_json TEXT')

        job_columns = _columns(conn, 'analysis_jobs')
        job_migrations = {
            'perf_json': 'ALTER TABLE analysis_jobs ADD COLUMN perf_json TEXT',
            'screen_seconds': 'ALTER TABLE analysis_jobs ADD COLUMN screen_seconds REAL NOT NULL DEFAULT 3.0',
            'deep_seconds': 'ALTER TABLE analysis_jobs ADD COLUMN deep_seconds REAL NOT NULL DEFAULT 10.0',
            'current_pass': 'ALTER TABLE analysis_jobs ADD COLUMN current_pass INTEGER NOT NULL DEFAULT 1',
            'max_passes': 'ALTER TABLE analysis_jobs ADD COLUMN max_passes INTEGER NOT NULL DEFAULT 4',
            'passes_completed': 'ALTER TABLE analysis_jobs ADD COLUMN passes_completed INTEGER NOT NULL DEFAULT 0',
            'current_screen_depth': 'ALTER TABLE analysis_jobs ADD COLUMN current_screen_depth INTEGER NOT NULL DEFAULT 8',
            'current_deep_depth': 'ALTER TABLE analysis_jobs ADD COLUMN current_deep_depth INTEGER NOT NULL DEFAULT 16',
            'settings_json': 'ALTER TABLE analysis_jobs ADD COLUMN settings_json TEXT',
            'games_screened': 'ALTER TABLE analysis_jobs ADD COLUMN games_screened INTEGER NOT NULL DEFAULT 0',
            'checkpoint_pass': 'ALTER TABLE analysis_jobs ADD COLUMN checkpoint_pass INTEGER NOT NULL DEFAULT 0',
            'checkpoint_game_index': 'ALTER TABLE analysis_jobs ADD COLUMN checkpoint_game_index INTEGER NOT NULL DEFAULT 0',
            'checkpoint_file_offset': 'ALTER TABLE analysis_jobs ADD COLUMN checkpoint_file_offset INTEGER NOT NULL DEFAULT 0',
            'source_type': "ALTER TABLE analysis_jobs ADD COLUMN source_type TEXT NOT NULL DEFAULT 'self'",
            'source_username': 'ALTER TABLE analysis_jobs ADD COLUMN source_username TEXT',
            'learning_modes': "ALTER TABLE analysis_jobs ADD COLUMN learning_modes TEXT NOT NULL DEFAULT '[\"mistakes\"]'",
            'metadata_refreshed_at': 'ALTER TABLE analysis_jobs ADD COLUMN metadata_refreshed_at TEXT',
            'force_reanalysis': 'ALTER TABLE analysis_jobs ADD COLUMN force_reanalysis INTEGER NOT NULL DEFAULT 0',
        }
        for column, statement in job_migrations.items():
            if column not in job_columns:
                conn.execute(statement)

        # Preserve a monotonic count of unique games that have made it through
        # at least one screening/cache pass. Older databases only had the
        # per-pass games_processed counter, so use the best recoverable value.
        conn.execute('''
            UPDATE analysis_jobs
            SET games_screened = MAX(
                COALESCE(games_screened, 0),
                COALESCE(games_processed, 0),
                COALESCE((SELECT COUNT(*) FROM analyzed_games ag WHERE ag.source_job_id = analysis_jobs.id), 0)
            )
        ''')

        conn.execute("UPDATE analysis_jobs SET source_type = COALESCE(NULLIF(source_type, ''), 'self')")
        conn.execute("UPDATE analysis_jobs SET learning_modes = COALESCE(NULLIF(learning_modes, ''), '[\"mistakes\"]')")
        conn.execute('''
            UPDATE analysis_jobs
            SET source_username = COALESCE(
                NULLIF(source_username, ''),
                (SELECT username FROM accounts a WHERE a.id = analysis_jobs.account_id)
            )
        ''')

        candidate_columns = _columns(conn, 'analysis_candidates')
        if 'learning_mode' not in candidate_columns:
            conn.execute("ALTER TABLE analysis_candidates ADD COLUMN learning_mode TEXT NOT NULL DEFAULT 'mistakes'")

        analyzed_columns = _columns(conn, 'analyzed_games')
        analyzed_migrations = {
            'max_screen_depth': 'ALTER TABLE analyzed_games ADD COLUMN max_screen_depth INTEGER NOT NULL DEFAULT 0',
            'max_deep_depth': 'ALTER TABLE analyzed_games ADD COLUMN max_deep_depth INTEGER NOT NULL DEFAULT 0',
            'analysis_pass': 'ALTER TABLE analyzed_games ADD COLUMN analysis_pass INTEGER NOT NULL DEFAULT 0',
            'settings_signature': 'ALTER TABLE analyzed_games ADD COLUMN settings_signature TEXT',
            'source_type': "ALTER TABLE analyzed_games ADD COLUMN source_type TEXT NOT NULL DEFAULT 'self'",
            'source_username': 'ALTER TABLE analyzed_games ADD COLUMN source_username TEXT',
        }
        for column, statement in analyzed_migrations.items():
            if column not in analyzed_columns:
                conn.execute(statement)

        position_columns = _columns(conn, 'training_positions')
        position_migrations = {
            'opening_key': 'ALTER TABLE training_positions ADD COLUMN opening_key TEXT',
            'opening_name': 'ALTER TABLE training_positions ADD COLUMN opening_name TEXT',
            'opening_variation': 'ALTER TABLE training_positions ADD COLUMN opening_variation TEXT',
            'opening_eco': 'ALTER TABLE training_positions ADD COLUMN opening_eco TEXT',
            'opening_source': 'ALTER TABLE training_positions ADD COLUMN opening_source TEXT',
            'opening_history': 'ALTER TABLE training_positions ADD COLUMN opening_history TEXT',
            'historical_match': 'ALTER TABLE training_positions ADD COLUMN historical_match TEXT',
            'previous_fen': 'ALTER TABLE training_positions ADD COLUMN previous_fen TEXT',
            'opponent_move_uci': 'ALTER TABLE training_positions ADD COLUMN opponent_move_uci TEXT',
            'opponent_move_san': 'ALTER TABLE training_positions ADD COLUMN opponent_move_san TEXT',
            'mistake_ply': 'ALTER TABLE training_positions ADD COLUMN mistake_ply INTEGER',
            'game_pgn': 'ALTER TABLE training_positions ADD COLUMN game_pgn TEXT',
            'difficulty_score': 'ALTER TABLE training_positions ADD COLUMN difficulty_score REAL',
            'estimated_rating': 'ALTER TABLE training_positions ADD COLUMN estimated_rating INTEGER',
            'difficulty_version': 'ALTER TABLE training_positions ADD COLUMN difficulty_version TEXT',
            'best_pv_uci': 'ALTER TABLE training_positions ADD COLUMN best_pv_uci TEXT',
            'played_pv_uci': 'ALTER TABLE training_positions ADD COLUMN played_pv_uci TEXT',
            'alternative_pvs_json': 'ALTER TABLE training_positions ADD COLUMN alternative_pvs_json TEXT',
            'critical_events_json': 'ALTER TABLE training_positions ADD COLUMN critical_events_json TEXT',
            'explanatory_lines_json': 'ALTER TABLE training_positions ADD COLUMN explanatory_lines_json TEXT',
            'proactive_coach_json': 'ALTER TABLE training_positions ADD COLUMN proactive_coach_json TEXT',
            'coach_prompt': 'ALTER TABLE training_positions ADD COLUMN coach_prompt TEXT',
            'coach_explanation': 'ALTER TABLE training_positions ADD COLUMN coach_explanation TEXT',
            'coaching_version': 'ALTER TABLE training_positions ADD COLUMN coaching_version TEXT',
            'analysis_pass': 'ALTER TABLE training_positions ADD COLUMN analysis_pass INTEGER NOT NULL DEFAULT 0',
            'analysis_screen_depth': 'ALTER TABLE training_positions ADD COLUMN analysis_screen_depth INTEGER NOT NULL DEFAULT 0',
            'analysis_deep_depth': 'ALTER TABLE training_positions ADD COLUMN analysis_deep_depth INTEGER NOT NULL DEFAULT 0',
            'learning_mode': "ALTER TABLE training_positions ADD COLUMN learning_mode TEXT NOT NULL DEFAULT 'mistakes'",
        }
        for column, statement in position_migrations.items():
            if column not in position_columns:
                conn.execute(statement)

        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_openings ON training_positions(job_id, opening_key, move_number)')
        # Listing/summary indexes: avoid repeated full scans for large game lists.
        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_list_rating ON training_positions(job_id, estimated_rating, id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_first_page ON training_positions(job_id, (estimated_rating IS NULL), estimated_rating, id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_list_mode ON training_positions(job_id, learning_mode, estimated_rating, id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_opening_status ON training_positions(job_id, opening_key, learned, move_number)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_positions_missing_opening ON training_positions(job_id, id) WHERE opening_key IS NULL')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_position_concept_primary ON position_concepts(concept_key, is_primary, position_id)')

        conn.execute("UPDATE training_positions SET learning_mode = COALESCE(NULLIF(learning_mode, ''), 'mistakes')")

        concept_columns = _columns(conn, 'learning_concepts')
        concept_migrations = {
            'source': "ALTER TABLE learning_concepts ADD COLUMN source TEXT NOT NULL DEFAULT 'built_in'",
            'status': "ALTER TABLE learning_concepts ADD COLUMN status TEXT NOT NULL DEFAULT 'seeded'",
            'account_id': 'ALTER TABLE learning_concepts ADD COLUMN account_id INTEGER',
            'aliases_json': 'ALTER TABLE learning_concepts ADD COLUMN aliases_json TEXT',
            'detector_json': 'ALTER TABLE learning_concepts ADD COLUMN detector_json TEXT',
            'concept_score': 'ALTER TABLE learning_concepts ADD COLUMN concept_score REAL NOT NULL DEFAULT 0',
            'evidence_count': 'ALTER TABLE learning_concepts ADD COLUMN evidence_count INTEGER NOT NULL DEFAULT 0',
            'validated_count': 'ALTER TABLE learning_concepts ADD COLUMN validated_count INTEGER NOT NULL DEFAULT 0',
            'distinct_games': 'ALTER TABLE learning_concepts ADD COLUMN distinct_games INTEGER NOT NULL DEFAULT 0',
            'created_at': 'ALTER TABLE learning_concepts ADD COLUMN created_at TEXT',
            'updated_at': 'ALTER TABLE learning_concepts ADD COLUMN updated_at TEXT',
        }
        for column, statement in concept_migrations.items():
            if column not in concept_columns:
                conn.execute(statement)
        conn.execute("UPDATE learning_concepts SET source = COALESCE(source, 'built_in'), status = COALESCE(status, 'seeded')")
        conn.execute("UPDATE learning_concepts SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP), updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_concepts_account ON learning_concepts(account_id, status)")

        # Preserve existing thumbs votes while extending their reproducible
        # classifier identity. Historical votes leave this field NULL.
        if 'classifier_version_at_vote' not in _columns(conn, 'position_feedback'):
            conn.execute('ALTER TABLE position_feedback ADD COLUMN classifier_version_at_vote TEXT')
        for column in ('suggested_text', 'suggested_motif_key'):
            if column not in _columns(conn, 'position_feedback'):
                conn.execute(f'ALTER TABLE position_feedback ADD COLUMN {column} TEXT')
        _seed_learning_concepts(conn)
        # Retire the generic candidate-comparison pseudo-motif from older
        # releases. Refresh/reclassification will assign a supported, specific
        # motif; keep the catalog row only for historical feedback snapshots.
        conn.execute("DELETE FROM position_concepts WHERE concept_key='candidate_evaluation'")
        conn.execute("UPDATE learning_concepts SET status='retired' WHERE key='candidate_evaluation'")

        # v2.19 separates learning modes from learning motifs. Older builds
        # injected mode labels (Excellent/Brilliant/Opposition) into the concept
        # taxonomy; remove only those associations while preserving the positions,
        # learning_mode values, and all genuine tactical/strategic concepts.
        conn.execute("DELETE FROM position_concepts WHERE concept_key IN ('excellent_move','brilliant_move','opposition_opportunity')")

        # Candidate-level reporting was added after early releases. Confirmed
        # puzzles are a conservative lower bound for legacy jobs; new analysis
        # records every deep-confirmed candidate, including rejected ones.
        conn.execute('''
            INSERT OR IGNORE INTO analysis_candidates(job_id, game_id, ply, first_pass, last_pass, learning_mode)
            SELECT job_id, COALESCE(game_id, 'position:' || id), COALESCE(mistake_ply, id),
                   MAX(1, COALESCE(analysis_pass, 1)), MAX(1, COALESCE(analysis_pass, 1)),
                   COALESCE(learning_mode, 'mistakes')
            FROM training_positions
        ''')

        # Backward-compatible cache seed: any legacy game that already produced
        # at least one saved training position is known to have been analyzed.
        # Games with zero saved positions cannot be inferred from older schemas,
        # so they will be screened one final time and cached thereafter.
        conn.execute('''
            INSERT OR IGNORE INTO analyzed_games (
                account_id, game_id, site, game_date, game_pgn,
                source_job_id, analysis_version, completed_at
            )
            SELECT j.account_id, tp.game_id,
                   MAX(tp.site), MAX(tp.game_date), MAX(tp.game_pgn),
                   MAX(tp.job_id), 'legacy-position-cache', CURRENT_TIMESTAMP
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.game_id IS NOT NULL AND tp.game_id <> ''
            GROUP BY j.account_id, tp.game_id
        ''')

        # One-time v85 -> v86 migration. Never reimport the mutable compatibility
        # projections on later starts: doing so would invent duplicate votes.
        migrated = conn.execute("SELECT 1 FROM app_settings WHERE key='feedback_ledger_v86_migrated'").fetchone()
        if not migrated:
            from feedback_history import migrate_legacy_feedback
            migrate_legacy_feedback(conn)
            conn.execute("""INSERT INTO app_settings(key,value) VALUES
                ('feedback_ledger_v86_migrated','1')""")
        # Add recoverable message identities to older immutable events using
        # their own original snapshots, never today's active coaching version.
        if not conn.execute("SELECT 1 FROM app_settings WHERE key='feedback_messages_v112_attributed'").fetchone():
            from feedback_messages import backfill_legacy_message_attribution
            backfill_legacy_message_attribution(conn)
            conn.execute("INSERT INTO app_settings(key,value) VALUES ('feedback_messages_v112_attributed','1')")
        # v114 migrates the current best-move projection once. Old-version
        # rows remain stamped as old and are never exposed as current advice.
        # Never repopulate the cache after an explicit clear/refresh.
        if not conn.execute("SELECT 1 FROM app_settings WHERE key='coaching_cache_v114_migrated'").fetchone():
            from coaching.coaching_refresh.message_cache import cache_message
            rows = conn.execute('''SELECT tp.id,tp.coaching_version,tp.coach_explanation,tp.coach_prompt
                FROM training_positions tp LEFT JOIN metadata_processes mp ON mp.job_id=tp.job_id
                WHERE tp.coaching_version IS NOT NULL AND tp.coach_explanation IS NOT NULL
                  AND LENGTH(TRIM(tp.coach_explanation))>0
                  AND COALESCE(mp.status,'')!='needs_refresh' ''').fetchall()
            for row in rows:
                cache_message(conn,row['id'],'best_move','position',row['coaching_version'],
                              row['coach_explanation'],prompt=row['coach_prompt'])
            # Recover already-generated v35 attempted/game messages from
            # stamped recap metadata. Do not import older-model recaps just
            # because the position has since been refreshed to v35.
            import json as _json
            from coaching.coaching_refresh.message_cache import note_kind, note_key
            from coaching.coaching_refresh.version import COACHING_VERSION as _ACTIVE_MODEL
            recaps = conn.execute('''SELECT cm.structured_json,cm.generation_version,tp.id AS position_id,
                    tp.coaching_version AS position_version
                FROM coach_solve_recaps sr
                JOIN coach_messages cm ON cm.id=sr.message_id
                JOIN training_positions tp ON tp.id=sr.position_id
                LEFT JOIN metadata_processes mp ON mp.job_id=tp.job_id
                WHERE tp.coaching_version=? AND COALESCE(mp.status,'')!='needs_refresh'
                ORDER BY cm.id ''',(_ACTIVE_MODEL,)).fetchall()
            for saved in recaps:
                try: meta=_json.loads(saved['structured_json'] or '{}')
                except (ValueError,TypeError): continue
                if not isinstance(meta,dict) or meta.get('kind')!='solved_attempt_recap': continue
                if meta.get('coaching_version')!=_ACTIVE_MODEL: continue
                if saved['generation_version'] not in (None,_ACTIVE_MODEL): continue
                for note in meta.get('attempt_comments') or []:
                    if not isinstance(note,dict) or not str(note.get('text') or '').strip():continue
                    if note_kind(note) != 'best_move' and not str(note.get('move_uci') or '').strip():continue
                    cache_message(conn,saved['position_id'],note_kind(note),note_key(note),
                                  _ACTIVE_MODEL,note['text'])
            conn.execute("INSERT INTO app_settings(key,value) VALUES ('coaching_cache_v114_migrated','1')")
        # The legacy explanation copy had a different lifetime and could
        # retain v34 after v35. It is no longer read or written; remove it.
        conn.execute('DROP TABLE IF EXISTS coaching_explanation_cache')
        conn.commit()
