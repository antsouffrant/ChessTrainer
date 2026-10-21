from __future__ import annotations

import io
import json
import sqlite3
import time
import threading
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for, send_file

from analysis import (
    DIFFICULTY_VERSION, EvalResult, _refresh_position_labels,
    estimate_puzzle_difficulty, run_analysis_job, batch_path_for_job,
)
from db import connect, init_db
from game_sharing import lichess_game_url, normalize_pgn, game_pgn_filename
from app_settings import (
    SETTING_DEFINITIONS, get_settings, reset_settings, save_settings, save_setting,
    serialize_settings,
)
from coaching import COACHING_VERSION, generate_coaching_text
from engine_service import evaluate_fen, evaluate_move_quality, reset_review_engine
from learning import CLASSIFIER_VERSION, classify_learning_concepts
from coaching_taxonomy import CONTEXTS as COACHING_CONTEXTS, MOVE_TYPES as COACHING_MOVE_TYPES, MotifPath
from openings import ensure_opening_metadata, famous_for_opening, CLASSICS
from metadata_refresh import refresh_metadata_batch
from process_runtime import PROCESS_LOCK
from retrieval import retrieve_game_list
from list_readiness import list_state
from feedback_analytics import (
    record_position_vote, position_votes, position_feedback_details, motif_feedback_options,
    record_continuation_vote, continuation_votes, continuation_feedback_details,
    save_taxonomy_feedback, taxonomy_feedback_choices,
    report_rows, report_facets, report_summary, taxonomy_change_rates, solved_taxonomy_rows, solved_taxonomy_csv, coaching_comparison, coaching_metric_chart, current_taxonomy_status, csv_bytes, regression_candidate_rows,
)
from process_policy import queue_analysis, restart_analysis
from coaching_cache import clear_coaching_cache
from feedback_history import append_feedback
from player_learning import record_attempt as record_player_attempt, abandon_session as abandon_player_session, summary as player_summary, facets as player_facets, export_rows as player_export_rows, csv_data as player_csv_data, reset_player_records
from opening_playlist import enrich_opening_playlist, board_identity
from balanced_playlist import balanced_playlist_order
from coach_session_recap import record_board_attempt, save_solved_recap, refresh_saved_recaps
from coach_benchmark import ensure_cohort, snapshot_completed_refresh, benchmark_status, benchmark_manifest
from evaluation_runs import (start_evaluation_run, resolve_run, run_position,
                             record_evaluation_attempt, evaluation_manifest, run_history)
from coach_benchmark import benchmark_comparison
from coaching_taxonomy import TAXONOMY_VERSION
from adaptive_coach import (
    apply_adaptive_concepts_to_position, coach_history, handle_coach_message, get_or_create_thread,
)

app = Flask(__name__)
app.secret_key = 'local-development-change-me'


@app.context_processor
def inject_ui_settings():
    settings = get_settings()
    account_id = session.get('account_id')
    latest_job = None
    try:
        with connect() as conn:
            if account_id:
                latest_job = conn.execute(
                    "SELECT id, status FROM analysis_jobs WHERE account_id = ? ORDER BY id DESC LIMIT 1",
                    (account_id,),
                ).fetchone()
            if latest_job is None:
                latest_job = conn.execute(
                    "SELECT id, status FROM analysis_jobs ORDER BY id DESC LIMIT 1"
                ).fetchone()
    except Exception:
        latest_job = None
    current_job_id = None
    try:
        current_job_id = int((request.view_args or {}).get('job_id') or request.args.get('job_id') or 0) or None
    except (TypeError, ValueError):
        current_job_id = None
    return {
        'ui_settings': settings,
        'nav_job_id': current_job_id or (latest_job['id'] if latest_job else None),
    }

_job_threads = {}
_job_threads_lock = threading.Lock()


def start_analysis_thread(job_id: int):
    """Start one local worker thread per job id, never duplicate it in-process."""
    with _job_threads_lock:
        existing = _job_threads.get(job_id)
        if existing is not None and existing.is_alive():
            return existing

        def target():
            try:
                run_analysis_job(job_id)
            finally:
                with _job_threads_lock:
                    _job_threads.pop(job_id, None)

        thread = threading.Thread(target=target, daemon=True, name=f'analysis-job-{job_id}')
        _job_threads[job_id] = thread
        thread.start()
        return thread


def resume_analysis_thread(job_id: int):
    """Resume safely even if a just-paused worker is still winding down."""
    with _job_threads_lock:
        existing = _job_threads.get(job_id)

    if existing is not None and existing.is_alive():
        def wait_then_restart():
            existing.join()
            start_analysis_thread(job_id)
        threading.Thread(
            target=wait_then_restart,
            daemon=True,
            name=f'analysis-resume-{job_id}',
        ).start()
        return existing
    return start_analysis_thread(job_id)


def restart_analysis_after_current_worker(job_id: int):
    """Drain the existing analysis worker before resetting its saved cursor."""
    with _job_threads_lock:
        existing = _job_threads.get(job_id)

    def finish_restart():
        try:
            if existing is not None and existing.is_alive():
                existing.join()
            # A paused refresh might be finishing an atomic metadata batch.
            # Let it drain too, or it could reinsert labels during the purge.
            with _refresh_threads_lock:
                refresh_worker = _refresh_threads.get(job_id)
            if refresh_worker is not None and refresh_worker.is_alive():
                refresh_worker.join()
            with connect() as conn:
                state = conn.execute('SELECT status FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()
                if not state or state['status'] != 'restarting':
                    return
                restart_analysis(conn, job_id, get_settings(conn))
                conn.commit()
            start_analysis_thread(job_id)
        except Exception as exc:
            # Do not leave the toolbar indefinitely locked on 'Restarting'.
            with connect() as conn:
                conn.execute('''UPDATE analysis_jobs SET status='error', error=?
                    WHERE id=? AND status IN ('restarting','queued')''', (str(exc), job_id))
                conn.commit()

    threading.Thread(target=finish_restart, daemon=True,
        name=f'analysis-restart-{job_id}').start()


# Retrieving a new PGN is independent of Stockfish and metadata refresh.
# Only newly created lists (or their explicit retries) enter this workflow.
_retrieval_threads = {}
_retrieval_threads_lock = threading.Lock()


def start_retrieval_thread(job_id: int):
    with _retrieval_threads_lock:
        current = _retrieval_threads.get(job_id)
        if current is not None and current.is_alive():
            return current
        def worker():
            try:
                retrieve_game_list(job_id, on_complete=start_analysis_thread)
            finally:
                with _retrieval_threads_lock:
                    _retrieval_threads.pop(job_id, None)
        thread = threading.Thread(target=worker, daemon=True, name=f'game-retrieval-{job_id}')
        _retrieval_threads[job_id] = thread
        thread.start()
        return thread


def resume_retrieval_thread(job_id: int):
    """Do not reuse an in-flight .part file when retrying a stopped retrieval."""
    with _retrieval_threads_lock:
        current = _retrieval_threads.get(job_id)
    if current is not None and current.is_alive():
        def restart_after_cancel():
            current.join()
            start_retrieval_thread(job_id)
        threading.Thread(target=restart_after_cancel, daemon=True,
                         name=f'retrieval-retry-{job_id}').start()
        return current
    return start_retrieval_thread(job_id)


# Metadata refresh has a persisted cursor and a dedicated background thread.
# It shares the execution mutex with Stockfish analysis, while short SQLite
# commits + WAL permit training requests to continue reading and saving.
_refresh_threads = {}
_refresh_threads_lock = threading.Lock()


def _run_refresh_worker(job_id):
    """Stockfish coaching probes outside SQLite writes; atomic batch commits.

    The game list's saved deep evaluations/positions remain unchanged. Pause
    and stop requests are respected between small batches of bounded probes.
    """
    from engine_service import find_stockfish
    from proactive_coaching import probe_training_position, reusable_coaching_probe
    from app_settings import get_settings

    with PROCESS_LOCK:
        engine = None
        try:
            # Fail fast and visibly if Stockfish is unavailable. Never silently
            # claim to have refreshed the causal coaching layer without it.
            with connect() as conn:
                settings = get_settings(conn)
                count = conn.execute('SELECT COUNT(*) FROM training_positions WHERE job_id=?',
                                     (job_id,)).fetchone()[0]
            if not count:
                with connect() as conn:
                    conn.execute("UPDATE metadata_processes SET status='complete',total=0,processed=0,updated_at=CURRENT_TIMESTAMP WHERE job_id=? AND status IN ('queued','running')", (job_id,))
                    conn.commit()
                return
            executable = find_stockfish(settings)
            engine = chess.engine.SimpleEngine.popen_uci(
                str(executable), setpgrp=True,
                timeout=float(settings['engine_start_timeout_seconds']))
            options = {}
            if 'Threads' in engine.options:
                options['Threads'] = int(settings['analysis_engine_threads'])
            if 'Hash' in engine.options:
                options['Hash'] = int(settings['analysis_engine_hash_mb'])
            if options:
                engine.configure(options)
            engine.ping()
            busy_retries = 0
            from collections import OrderedDict
            game_cache = OrderedDict()  # Reuse classified game history across batches.
            # Cumulative timings are persisted each batch for Process diagnostics.
            totals = {'engine_seconds': 0.0, 'metadata_seconds': 0.0,
                      'cached_probes': 0, 'new_probes': 0, 'probe_errors': 0}
            with connect() as conn:
                task_perf = conn.execute('SELECT perf_json FROM metadata_processes WHERE job_id=?',
                                         (job_id,)).fetchone()
                if task_perf and task_perf['perf_json']:
                    try:
                        totals.update({k: float(v) if k.endswith('_seconds') else int(v)
                                       for k, v in json.loads(task_perf['perf_json']).items()
                                       if k in totals})
                    except (ValueError, TypeError):
                        pass
            engine_name = (engine.id or {}).get('name', '')
            while True:
                try:
                    # Release the connection before engine analysis.
                    with connect() as conn:
                        task = conn.execute('SELECT * FROM metadata_processes WHERE job_id=?',
                                            (job_id,)).fetchone()
                        if task is None or task['status'] not in ('queued', 'running'):
                            return
                        analysis = conn.execute('SELECT status FROM analysis_jobs WHERE id=?',
                                                (job_id,)).fetchone()
                        if analysis is None:
                            return
                        if analysis['status'] in ('queued', 'running', 'retrieving', 'restarting'):
                            conn.execute("UPDATE metadata_processes SET status='paused',error='Pause analysis before coaching refresh.',updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
                            conn.commit()
                            return
                        batch = conn.execute('''SELECT * FROM training_positions
                            WHERE job_id=? AND id>? ORDER BY id LIMIT 3''',
                            (job_id, task['cursor'])).fetchall()
                    evidence = {}
                    for row in batch:
                        cached = reusable_coaching_probe(row, settings, engine_name)
                        if cached is not None:
                            evidence[row['id']] = cached
                            totals['cached_probes'] += 1
                            continue
                        probe_started = time.perf_counter()
                        try:
                            evidence[row['id']] = probe_training_position(engine, row, settings)
                            totals['new_probes'] += 1
                        except (ValueError, TypeError, KeyError):
                            # Older malformed FEN/moves do not stop other puzzles.
                            totals['probe_errors'] += 1
                        finally:
                            totals['engine_seconds'] += time.perf_counter() - probe_started
                    with connect() as conn:
                        current = conn.execute('SELECT status,cursor FROM metadata_processes WHERE job_id=?',
                                               (job_id,)).fetchone()
                        if current is None or current['status'] not in ('queued', 'running'):
                            return
                        if current['cursor'] != task['cursor']:
                            continue
                        conn.execute("UPDATE metadata_processes SET status='running',updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
                        metadata_started = time.perf_counter()
                        result = refresh_metadata_batch(conn, job_id, task['cursor'], 3,
                                                        probes=evidence, game_cache=game_cache)
                        totals['metadata_seconds'] += time.perf_counter() - metadata_started
                        conn.execute("UPDATE metadata_processes SET perf_json=? WHERE job_id=?",
                                     (json.dumps(totals, sort_keys=True), job_id))
                        conn.execute('''UPDATE metadata_processes SET
                            cursor=?, processed=?, total=?, updated=updated+?,
                            failed=failed+?, without_pgn=without_pgn+?, status=?,error=NULL,
                            updated_at=CURRENT_TIMESTAMP WHERE job_id=?''',
                            (result['next_cursor'] or result['processed'],
                             result['processed'], result['total'], result['updated'],
                             result['failed'], result['without_pgn'],
                             'complete' if result['done'] else 'running', job_id))
                        if result['done']:
                            snapshot_completed_refresh(conn,job_id,COACHING_VERSION,TAXONOMY_VERSION)
                            # Every completed refresh creates a fresh, independently
                            # unanswered evaluation. Earlier runs remain immutable.
                            try:
                                start_evaluation_run(conn,job_id,COACHING_VERSION)
                            except ValueError:
                                # Incomplete/stale benchmark stays visible but
                                # is not misrepresented as ready for evaluation.
                                pass
                        conn.commit()
                    busy_retries = 0
                    if result['done']:
                        return
                except sqlite3.OperationalError as exc:
                    if ('locked' in str(exc).lower() or 'busy' in str(exc).lower()) and busy_retries < 6:
                        busy_retries += 1
                        time.sleep(min(1.5, 0.2 * busy_retries))
                        continue
                    raise
        except Exception as exc:
            _mark_refresh_failure(job_id, exc)
        finally:
            if engine is not None:
                try:
                    engine.quit()
                except Exception:
                    try:
                        engine.close()
                    except Exception:
                        pass


def _mark_refresh_failure(job_id, exc):
    try:
        with connect() as conn:
            conn.execute("UPDATE metadata_processes SET status='error',error=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (str(exc), job_id))
            conn.commit()
    except sqlite3.OperationalError:
        # Even error reporting must not crash the worker if another writer is busy.
        pass


def start_refresh_thread(job_id):
    with _refresh_threads_lock:
        existing = _refresh_threads.get(job_id)
        if existing is not None and existing.is_alive():
            return existing
        def target():
            try:
                _run_refresh_worker(job_id)
            finally:
                with _refresh_threads_lock:
                    _refresh_threads.pop(job_id, None)
        worker = threading.Thread(target=target, daemon=True, name=f'metadata-refresh-{job_id}')
        _refresh_threads[job_id] = worker
        worker.start()
        return worker


@app.get('/processes')
def processes():
    selected = request.args.get('job_id', type=int)
    return render_template('processes.html', selected_job_id=selected)


@app.get('/api/jobs/<int:job_id>/coaching-benchmark')
def coaching_benchmark(job_id):
    with connect() as conn:
        if not conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?',(job_id,)).fetchone():
            return jsonify({'error':'Game list not found'}),404
        result=benchmark_status(conn,job_id)
        return jsonify({'benchmark':result,'position_ids':[r['id'] for r in benchmark_manifest(conn,job_id)],
                        'evaluation_runs':run_history(conn,job_id)})


@app.post('/api/jobs/<int:job_id>/evaluations')
def create_evaluation(job_id):
    """New independent attempt of the fixed cohort; never resets learned state."""
    payload=request.get_json(silent=True) or {}
    version=str(payload.get('coaching_version') or '').strip() or None
    with connect() as conn:
        if not conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?',(job_id,)).fetchone():
            return jsonify({'error':'Game list not found'}),404
        try:
            run_id=start_evaluation_run(conn,job_id,version)
        except ValueError as exc:
            return jsonify({'error':str(exc)}),409
        conn.commit()
    return jsonify({'ok':True,'run_id':run_id,'url':f'/trainer/{job_id}?benchmark=1&run_id={run_id}'}),201


@app.get('/api/coach/benchmark-comparison')
def coaching_benchmark_comparison():
    try:
        job_id=int(request.args.get('job_id') or 0)
    except ValueError:
        return jsonify({'error':'Select a game list'}),400
    if job_id<=0:return jsonify({'error':'Select a game list'}),400
    model_a=str(request.args.get('model_a') or '').strip()
    model_b=str(request.args.get('model_b') or '').strip()
    with connect() as conn:
        if not conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?',(job_id,)).fetchone():
            return jsonify({'error':'Game list not found'}),404
        try:
            result=benchmark_comparison(conn,job_id,model_a,model_b)
        except ValueError as exc:
            return jsonify({'error':str(exc)}),400
    return jsonify(result)


@app.get('/api/processes')
def process_listing():
    # Reads never need to wait for a full evaluation/metadata write cycle.
    # A busy WAL checkpoint is transient and should not become a persistent UI error.
    for attempt in range(4):
        try:
            with connect(timeout=0.5) as conn:
                jobs = conn.execute('''SELECT j.id, j.date_range, j.status AS analysis_status,
            j.games_retrieved, j.games_screened, j.games_processed, j.positions_found, j.current_pass,
            j.max_passes, j.error AS analysis_error, j.metadata_refreshed_at,
            j.created_at, j.perf_json AS analysis_perf, j.source_type, j.source_username, a.username,
            EXISTS(SELECT 1 FROM training_positions t WHERE t.job_id=j.id LIMIT 1) AS has_training_positions,
            r.status AS retrieval_status, r.bytes_downloaded, r.bytes_total, r.error AS retrieval_error,
            r.started_at AS retrieval_started_at, r.finished_at AS retrieval_finished_at,
            r.perf_json AS retrieval_perf,
            p.status AS refresh_status, p.processed, p.total, p.updated,
            p.failed, p.without_pgn, p.error AS refresh_error, p.perf_json AS refresh_perf
            FROM analysis_jobs j JOIN accounts a ON a.id=j.account_id
            LEFT JOIN metadata_processes p ON p.job_id=j.id
            LEFT JOIN retrieval_processes r ON r.job_id=j.id
            ORDER BY j.id DESC''').fetchall()
                # Benchmark lookups must share the live connection used to fetch
                # jobs. db._ClosingConnection closes at the end of `with`.
                details = []
                for row in jobs:
                    item = dict(row)
                    item['benchmark'] = benchmark_status(conn, row['id'])
                    history = run_history(conn, row['id'])
                    item['evaluation_run'] = history[0] if history else None
                    details.append(item)
            return jsonify({'processes': details})
        except sqlite3.OperationalError as exc:
            if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                raise
            if attempt == 3:
                return jsonify({'error': 'Database is momentarily busy; status will retry.'}), 503, {'Retry-After': '1'}
            time.sleep(0.12 * (attempt + 1))


@app.post('/api/jobs/<int:job_id>/process/retrieve')
def process_retrieve(job_id):
    # Retry failed or interrupted retrieval for a newly created list.
    with connect() as conn:
        task = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if task is None:
            return jsonify({'error':'Retrieval only applies to newly created game lists.'}), 409
        if task['status'] not in ('error', 'stopped', 'paused'):
            return jsonify({'error':'Retrieval is already active or complete.'}), 409
        conn.execute('''UPDATE retrieval_processes SET status='queued', error=NULL,
            bytes_downloaded=0, bytes_total=0,perf_json=NULL, finished_at=NULL,updated_at=CURRENT_TIMESTAMP
            WHERE job_id=?''', (job_id,))
        conn.execute("UPDATE analysis_jobs SET status='waiting_for_games',error=NULL,finished_at=NULL WHERE id=?", (job_id,))
        conn.commit()
    resume_retrieval_thread(job_id)
    return jsonify({'ok':True,'status':'queued'}), 202


@app.post('/api/jobs/<int:job_id>/process/retrieve/stop')
def process_stop_retrieval(job_id):
    with connect() as conn:
        task = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if task is None:
            return jsonify({'error':'No retrieval task for this game list.'}), 404
        if task['status'] not in ('queued','running','paused'):
            return jsonify({'error':'Retrieval is not active.'}), 409
        conn.execute("UPDATE retrieval_processes SET status='stopped',updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(job_id,))
        conn.execute("UPDATE analysis_jobs SET status='stopped' WHERE id=? AND status='waiting_for_games'", (job_id,))
        conn.commit()
    return jsonify({'ok':True,'status':'stopped'})


@app.post('/api/jobs/<int:job_id>/process/coaching-cache/clear')
def process_clear_coaching_cache(job_id):
    """Discard one list's generated coaching, never root Stockfish/game data.

    Chat transcript and its live thumbs projection are deleted. Immutable
    feedback_events snapshots survive, including rated chat message content.
    """
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'CLEAR COACHING CACHE':
        return jsonify({'error': 'Explicit CLEAR COACHING CACHE confirmation required.'}), 400
    # Synchronize with the same local worker lock used by metadata/analysis.
    # Do not block the web request behind a multi-minute Stockfish operation.
    if not PROCESS_LOCK.acquire(blocking=False):
        return jsonify({'error': 'An analysis or coaching worker is still active. Pause it and retry after it stops.'}), 409
    try:
        with connect() as conn:
            job = conn.execute('SELECT status FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()
            if job is None:
                return jsonify({'error': 'Game list not found.'}), 404
            refresh = conn.execute('SELECT status FROM metadata_processes WHERE job_id=?', (job_id,)).fetchone()
            retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
            if job['status'] in ('queued','running','retrieving','restarting','waiting_for_games') or \
                    (refresh and refresh['status'] in ('queued','running')) or \
                    (retrieval and retrieval['status'] != 'complete'):
                return jsonify({'error':'Finish or pause retrieval, Analysis, and Coaching refresh before clearing the cache.'}), 409
            deleted = clear_coaching_cache(conn, job_id)
            conn.commit()
        return jsonify({'ok':True, 'status':'needs_refresh', 'job_id':job_id,
                        'cleared':deleted, 'next_step':'Start Coaching refresh.'})
    finally:
        PROCESS_LOCK.release()


@app.post('/api/jobs/<int:job_id>/process/refresh')
def process_refresh(job_id):
    with connect() as conn:
        job = conn.execute('SELECT id FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404
        current = conn.execute('SELECT status FROM metadata_processes WHERE job_id=?', (job_id,)).fetchone()
        if current and current['status'] in ('running', 'queued'):
            return jsonify({'error':'Metadata refresh already queued or running.'}), 409
        analysis_status = conn.execute('SELECT status FROM analysis_jobs WHERE id=?', (job_id,)).fetchone()['status']
        if analysis_status in ('running', 'queued', 'retrieving', 'restarting', 'waiting_for_games'):
            return jsonify({'error':'This game list is being analyzed. Pause or finish evaluation before refreshing.'}), 409
        retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?',(job_id,)).fetchone()
        if retrieval is not None and retrieval['status'] != 'complete':
            return jsonify({'error':'Retrieval must finish before refreshing metadata.'}), 409
        # Cohort is chosen only on the FIRST refresh. Never redraw it.
        ensure_cohort(conn,job_id)
        # Paused work resumes at its cursor. A completed refresh starts from zero.
        resume = bool(current and current['status'] == 'paused' and
                      (request.get_json(silent=True) or {}).get('resume'))
        if resume:
            conn.execute("UPDATE metadata_processes SET status='queued', error=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        else:
            conn.execute('''INSERT INTO metadata_processes(job_id,status,cursor,processed,total,updated,failed,without_pgn,error)
                VALUES (?,'queued',0,0,0,0,0,0,NULL)
                ON CONFLICT(job_id) DO UPDATE SET status='queued',cursor=0,processed=0,total=0,
                updated=0,failed=0,without_pgn=0,perf_json=NULL,error=NULL,updated_at=CURRENT_TIMESTAMP''', (job_id,))
        conn.commit()
    start_refresh_thread(job_id)
    return jsonify({'ok': True, 'status': 'queued'}), 202


@app.post('/api/jobs/<int:job_id>/process/refresh/<action>')
def control_refresh(job_id, action):
    if action not in ('pause', 'stop', 'resume'):
        return jsonify({'error': 'Unknown operation'}), 404
    if action == 'resume':
        return process_refresh(job_id)
    with connect() as conn:
        row = conn.execute('SELECT status FROM metadata_processes WHERE job_id=?', (job_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'No refresh task for this list'}), 404
        if row['status'] not in ('queued', 'running'):
            return jsonify({'error':'This refresh is not running.'}), 409
        state = 'paused' if action == 'pause' else 'stopped'
        conn.execute('UPDATE metadata_processes SET status=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?', (state, job_id))
        conn.commit()
    return jsonify({'ok': True, 'status': state})


@app.post('/api/jobs/<int:job_id>/process/retrieve/pause')
def process_pause_retrieval(job_id):
    with connect() as conn:
        task = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if task is None:
            return jsonify({'error': 'This game list has no retrieval task.'}), 404
        if task['status'] not in ('queued', 'running'):
            return jsonify({'error': 'Retrieval is not active.'}), 409
        conn.execute("UPDATE retrieval_processes SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (job_id,))
        conn.execute("UPDATE analysis_jobs SET status='paused' WHERE id=? AND status='waiting_for_games'", (job_id,))
        conn.commit()
    # Paused retrieval drops its incomplete .part file; saved batches are intact.
    return jsonify({'ok': True, 'status': 'paused'})


@app.post('/api/jobs/<int:job_id>/process/analyze')
def process_analyze(job_id):
    with connect() as conn:
        job = conn.execute('''SELECT j.status, j.source_username, j.passes_completed,
            j.max_passes, a.username FROM analysis_jobs j
            JOIN accounts a ON a.id=j.account_id WHERE j.id=?''', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404
        if job['status'] in ('queued', 'running', 'retrieving', 'restarting'):
            return jsonify({'error': 'Analysis is already queued or running.'}), 409
        retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if (retrieval is not None and retrieval['status'] != 'complete') or job['status'] == 'waiting_for_games':
            return jsonify({'error': 'Wait for game retrieval to finish before starting analysis.'}), 409
        source = job['source_username'] or job['username']
        batch = batch_path_for_job(source, job_id)
        if not batch.exists() or batch.stat().st_size == 0:
            return jsonify({'error': 'The saved game batch is missing. Reimport the PGN before analyzing.'}), 409
        refresh = conn.execute('SELECT status FROM metadata_processes WHERE job_id=?', (job_id,)).fetchone()
        if refresh and refresh['status'] in ('running', 'queued'):
            return jsonify({'error': 'This list has an active metadata refresh. Pause or finish it first.'}), 409
        action = queue_analysis(conn, job_id, job['status'],
            completed_passes=job['passes_completed'], max_passes=job['max_passes'])
        conn.commit()
    resume_analysis_thread(job_id)
    return jsonify({'ok': True, 'status': 'queued', 'action': action}), 202


@app.post('/api/jobs/<int:job_id>/process/analyze/restart')
def process_restart_analysis(job_id):
    """Discard the list’s derived state, then reanalyze the saved PGN."""
    with connect() as conn:
        job = conn.execute('''SELECT j.status, j.source_username, a.username
            FROM analysis_jobs j JOIN accounts a ON a.id=j.account_id
            WHERE j.id=?''', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error':'Game list not found'}), 404
        if job['status'] == 'restarting':
            return jsonify({'error':'Analysis restart is already in progress.'}), 409
        retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if (retrieval is not None and retrieval['status'] != 'complete') or job['status'] == 'waiting_for_games':
            return jsonify({'error':'Game retrieval must finish before restarting analysis.'}), 409
        batch = batch_path_for_job(job['source_username'] or job['username'], job_id)
        if not batch.exists() or batch.stat().st_size == 0:
            return jsonify({'error':'Saved game batch not found; cannot restart analysis.'}), 409
        refresh = conn.execute('SELECT status FROM metadata_processes WHERE job_id=?', (job_id,)).fetchone()
        if refresh and refresh['status'] in ('running', 'queued'):
            return jsonify({'error':'Pause or finish metadata refresh before restarting analysis.'}), 409
        conn.execute("UPDATE analysis_jobs SET status='restarting',error=NULL WHERE id=?", (job_id,))
        conn.commit()
    restart_analysis_after_current_worker(job_id)
    return jsonify({'ok':True,'status':'restarting','action':'restart'}), 202


def verify_lichess_username(username: str) -> bool:
    response = requests.get(
        f'https://lichess.org/api/user/{username}',
        headers={'Accept': 'application/json', 'User-Agent': 'personal-chess-trainer/1.0'},
        timeout=15,
    )
    return response.status_code == 200


def _store_labels(conn, position_id: int, labels):
    from coaching_taxonomy import normalize_learning_labels
    row = conn.execute('SELECT * FROM training_positions WHERE id=?', (position_id,)).fetchone()
    is_in_check = False
    king_evasion = False
    try:
        board = chess.Board(row['fen'])
        best = chess.Move.from_uci(row['best_move_uci'])
        is_in_check = board.is_check()
        king_evasion = (is_in_check and best in board.legal_moves
                        and board.piece_at(best.from_square) is not None
                        and board.piece_at(best.from_square).piece_type == chess.KING
                        and not board.is_capture(best))
    except (ValueError, TypeError, KeyError, chess.InvalidMoveError):
        pass
    labels = normalize_learning_labels(labels, row,
                                       is_in_check=is_in_check,
                                       best_is_king_evasion=king_evasion)
    conn.execute('DELETE FROM position_concepts WHERE position_id = ?', (position_id,))
    for label in labels:
        conn.execute('''
            INSERT INTO position_concepts (
                position_id, concept_key, confidence, is_primary, evidence, classifier_version
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            position_id,
            label.key,
            label.confidence,
            1 if label.is_primary else 0,
            label.evidence,
            CLASSIFIER_VERSION,
        ))
    primary = next((label for label in labels if label.is_primary), None)
    if primary:
        from coaching_taxonomy import save_taxonomy
        row = conn.execute('SELECT * FROM training_positions WHERE id=?', (position_id,)).fetchone()
        save_taxonomy(conn, position_id, row, primary.key, confidence=primary.confidence,
                      is_in_check=is_in_check)


def backfill_taxonomy_paths():
    """Fast, non-engine migration for every older classified position."""
    from coaching_taxonomy import TAXONOMY_VERSION, save_taxonomy
    with connect() as conn:
        rows = conn.execute("""
            SELECT tp.*, pc.concept_key AS assigned_motif, pc.confidence AS motif_confidence
            FROM training_positions tp
            JOIN position_concepts pc ON pc.position_id=tp.id AND pc.is_primary=1
            LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
            WHERE (tx.position_id IS NULL OR tx.taxonomy_version <> ?
                OR tx.motif_key <> pc.concept_key)
              AND tp.job_id NOT IN (SELECT job_id FROM metadata_processes
                                    WHERE status='needs_refresh')
        """, (TAXONOMY_VERSION,)).fetchall()
        from coaching_taxonomy import canonical_motif_key, evaluation_outcome_key
        from learning import LearningLabel
        for row in rows:
            if canonical_motif_key(row['assigned_motif']) is None:
                # Prevent the legacy context/pseudo-motif becoming a leaf.
                # Refresh Metadata will test all supported candidate motifs.
                key = evaluation_outcome_key(row)
                _store_labels(conn, row['id'], [LearningLabel(key, .55,
                    'Evaluation outcome for retired generic motif.', True)])
                # _store_labels already wrote the current taxonomy path.
                continue
            check = False
            best_check = False
            try:
                board = chess.Board(row['fen'])
                best = chess.Move.from_uci(row['best_move_uci'])
                check = board.is_check()
                best_check = best in board.legal_moves and board.gives_check(best)
            except (ValueError, TypeError, KeyError, chess.InvalidMoveError):
                pass
            save_taxonomy(conn, row['id'], row, row['assigned_motif'],
                          confidence=row['motif_confidence'],
                          is_in_check=check, root_best_is_check=best_check)
        conn.commit()


def backfill_learning_concepts():
    """Label older saved positions that predate the lesson-plan schema."""
    with connect() as conn:
        rows = conn.execute('''
            SELECT tp.*
            FROM training_positions tp
            WHERE NOT EXISTS (
                SELECT 1
                FROM position_concepts pc
                WHERE pc.position_id = tp.id
                  AND pc.is_primary = 1
            )
              AND tp.job_id NOT IN (SELECT job_id FROM metadata_processes
                                    WHERE status='needs_refresh')
        ''', ()).fetchall()

        for row in rows:
            try:
                board = chess.Board(row['fen'])
                played = chess.Move.from_uci(row['played_move_uci'])
                best = chess.Move.from_uci(row['best_move_uci'])
                if played not in board.legal_moves or best not in board.legal_moves:
                    continue
                labels = classify_learning_concepts(
                    board=board,
                    played_move=played,
                    best_move=best,
                    category=row['category'],
                    centipawn_loss=row['centipawn_loss'] or 0,
                    mate_before=row['mate_before'],
                    previous_fen=row['previous_fen'],
                    opponent_move_uci=row['opponent_move_uci'],
                    best_pv_uci=row['best_pv_uci'],
                    played_pv_uci=row['played_pv_uci'],
                )
                _store_labels(conn, row['id'], labels)
                try:
                    apply_adaptive_concepts_to_position(conn, row['id'])
                except Exception:
                    pass
            except (ValueError, TypeError):
                continue
        conn.commit()


def backfill_adaptive_concepts():
    """Reapply persisted personal concept detectors to all saved positions."""
    with connect() as conn:
        active = conn.execute("""
            SELECT COUNT(*) AS n FROM learning_concepts
            WHERE account_id IS NOT NULL AND source <> 'built_in'
              AND status IN ('candidate', 'personal', 'promoted')
        """).fetchone()['n']
        if not active:
            return
        rows = conn.execute('''SELECT id FROM training_positions
            WHERE job_id NOT IN (SELECT job_id FROM metadata_processes
                                 WHERE status='needs_refresh')''').fetchall()
        for row in rows:
            try:
                apply_adaptive_concepts_to_position(conn, row['id'])
            except Exception:
                continue
        conn.commit()


def backfill_difficulty_estimates():
    """Populate a first-pass estimated puzzle rating for older positions."""
    with connect() as conn:
        rows = conn.execute("""
            SELECT * FROM training_positions
            WHERE estimated_rating IS NULL OR difficulty_score IS NULL
               OR difficulty_version IS NULL OR difficulty_version <> ?
        """, (DIFFICULTY_VERSION,)).fetchall()

        for row in rows:
            try:
                board = chess.Board(row['fen'])
                best = chess.Move.from_uci(row['best_move_uci'])
                if best not in board.legal_moves:
                    continue
                before = EvalResult(
                    cp=int(row['eval_before_cp'] or 0),
                    mate=row['mate_before'],
                    best_move=best,
                    depth=None,
                )
                score, rating = estimate_puzzle_difficulty(
                    board, best, before, row['category']
                )
                conn.execute("""
                    UPDATE training_positions
                    SET difficulty_score = ?, estimated_rating = ?, difficulty_version = ?
                    WHERE id = ?
                """, (score, rating, DIFFICULTY_VERSION, row['id']))
            except (ValueError, TypeError):
                continue
        conn.commit()



def backfill_coaching_texts():
    """Fill gaps only for positions already owned by this version.

    A new release MUST NOT relabel old evidence on startup. Older versions
    require a deliberate Coaching refresh (which regenerates probes first).
    """
    from coaching_copy_refresh import rebuild_coaching_copy
    with connect() as conn:
        rows=conn.execute("""SELECT id FROM training_positions
            WHERE (coach_prompt IS NULL OR coach_explanation IS NULL)
              AND coaching_version = ?
              AND job_id NOT IN (SELECT job_id FROM metadata_processes
                                 WHERE status='needs_refresh')""",
            (COACHING_VERSION,)).fetchall()
        for row in rows:
            try:
                rebuild_coaching_copy(conn,row['id'])
            except (ValueError,TypeError,KeyError):
                continue
        conn.commit()


def import_existing_json_if_present():
    source = Path('data/training_positions.json')
    if not source.exists():
        return

    with connect() as conn:
        existing = conn.execute('SELECT COUNT(*) AS n FROM training_positions').fetchone()['n']
        if existing:
            return

        data = json.loads(source.read_text(encoding='utf-8'))
        username = data.get('metadata', {}).get('username', 'antsouffrant')

        conn.execute(
            'INSERT OR IGNORE INTO accounts(provider, username) VALUES (?, ?)',
            ('lichess', username),
        )
        account_id = conn.execute(
            'SELECT id FROM accounts WHERE provider = ? AND username = ?',
            ('lichess', username),
        ).fetchone()['id']

        cur = conn.execute('''
            INSERT INTO analysis_jobs (
                account_id, date_range, game_types, screen_depth, deep_depth,
                screen_seconds, deep_seconds,
                status, games_retrieved, games_processed, positions_found, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'complete', 0, 0, 0, CURRENT_TIMESTAMP)
        ''', (account_id, 'imported', json.dumps(['blitz']), 8, 16, 3.0, 10.0))
        job_id = cur.lastrowid

        count = 0
        for p in data.get('positions', []):
            cur = conn.execute('''
                INSERT OR IGNORE INTO training_positions (
                    job_id, game_id, site, game_date, opponent, category, fen,
                    previous_fen, opponent_move_uci, opponent_move_san,
                    user_color, move_number, played_move_uci, played_move_san,
                    best_move_uci, best_move_san, eval_before_cp, eval_after_cp,
                    mate_before, mate_after, centipawn_loss
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_id,
                p.get('game_id'),
                p.get('site'),
                p.get('date'),
                p.get('black') if p.get('user_color') == 'white' else p.get('white'),
                p.get('category'),
                p.get('fen'),
                p.get('previous_fen'),
                p.get('opponent_move_uci'),
                p.get('opponent_move_san'),
                p.get('user_color'),
                p.get('move_number'),
                p.get('played_move_uci'),
                p.get('played_move_san'),
                p.get('best_move_uci'),
                p.get('best_move_san'),
                p.get('eval_before_cp'),
                p.get('eval_after_cp'),
                p.get('mate_before'),
                p.get('mate_after'),
                p.get('centipawn_loss'),
            ))
            count += cur.rowcount

        conn.execute('UPDATE analysis_jobs SET positions_found = ? WHERE id = ?', (count, job_id))
        conn.execute('''
            INSERT OR IGNORE INTO analyzed_games (
                account_id, game_id, site, game_date, game_pgn,
                source_job_id, analysis_version, completed_at
            )
            SELECT ?, game_id, MAX(site), MAX(game_date), MAX(game_pgn),
                   ?, 'legacy-json-import', CURRENT_TIMESTAMP
            FROM training_positions
            WHERE job_id = ? AND game_id IS NOT NULL AND game_id <> ''
            GROUP BY game_id
        ''', (account_id, job_id, job_id))
        conn.commit()


@app.route('/', methods=['GET', 'POST'])
def index():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        if not username:
            error = 'Enter a Lichess username.'
        else:
            try:
                if not verify_lichess_username(username):
                    error = 'That Lichess account could not be verified.'
                else:
                    with connect() as conn:
                        conn.execute(
                            'INSERT OR IGNORE INTO accounts(provider, username) VALUES (?, ?)',
                            ('lichess', username),
                        )
                        row = conn.execute(
                            'SELECT id FROM accounts WHERE provider = ? AND username = ?',
                            ('lichess', username),
                        ).fetchone()
                        session['account_id'] = row['id']
                        session['username'] = username
                    return redirect(url_for('setup'))
            except requests.RequestException as exc:
                error = f'Lichess could not be reached: {exc}'

    with connect() as conn:
        latest_job = conn.execute('''
            SELECT j.*, a.username
            FROM analysis_jobs j
            JOIN accounts a ON a.id = j.account_id
            ORDER BY j.id DESC LIMIT 1
        ''').fetchone()

        game_lists = conn.execute('''
            SELECT j.id, j.date_range, j.source_type, j.source_username,
                   j.status, j.created_at, j.metadata_refreshed_at, j.games_retrieved,
                   r.status AS retrieval_status, p.status AS refresh_status,
                   a.username, COUNT(tp.id) AS position_count,
                   COUNT(DISTINCT tp.game_id) AS game_count
            FROM analysis_jobs j
            JOIN accounts a ON a.id = j.account_id
            LEFT JOIN training_positions tp ON tp.job_id = j.id
            LEFT JOIN retrieval_processes r ON r.job_id = j.id
            LEFT JOIN metadata_processes p ON p.job_id = j.id
            GROUP BY j.id ORDER BY j.id DESC LIMIT 30
        ''').fetchall()
    game_lists = [dict(item) for item in game_lists]
    for item in game_lists:
        item['home_state'] = list_state(item['retrieval_status'], item['status'], item['position_count'])
    return render_template('index.html', error=error,
                           latest_job=latest_job, game_lists=game_lists)


@app.route('/settings', methods=['GET', 'POST'])
def settings_page():
    reset = request.args.get('reset') == '1'
    if request.method == 'POST':
        action = request.form.get('action', 'save')
        with connect() as conn:
            if action == 'reset':
                reset_settings(conn)
            else:
                save_settings(request.form, conn)
            conn.execute('DELETE FROM engine_eval_cache')
            conn.commit()
        reset_review_engine()
        backfill_adaptive_concepts()
        return redirect(url_for('settings_page', **({'reset': 1} if action == 'reset' else {})))

    values = get_settings()
    active_job = None
    try:
        requested_job_id = int(request.args.get('job_id', '') or 0) or None
    except (TypeError, ValueError):
        requested_job_id = None
    if requested_job_id:
        with connect() as conn:
            row = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (requested_job_id,)).fetchone()
        if row is not None:
            active_job = dict(row)
            try:
                active_job['learning_modes'] = json.loads(active_job.get('learning_modes') or '[]')
            except (TypeError, json.JSONDecodeError):
                active_job['learning_modes'] = ['mistakes']
            if (active_job.get('source_type') or 'self') == 'self':
                modes = set(active_job['learning_modes'])
                values = dict(values)
                values['learning_mode_mistakes'] = 'mistakes' in modes
                values['learning_mode_blunders'] = 'blunders' in modes
                values['learning_mode_excellent'] = 'excellent' in modes
                values['learning_mode_brilliant'] = 'brilliant' in modes
            else:
                values = dict(values)
                values['learning_mode_mistakes'] = False
                values['learning_mode_blunders'] = False
                values['learning_mode_excellent'] = False
                values['learning_mode_brilliant'] = False
    return render_template(
        'settings.html',
        sections=SETTING_DEFINITIONS,
        values=values,
        reset=reset,
        active_job=active_job,
    )


@app.post('/api/settings/<key>')
def update_setting(key):
    payload = request.get_json(silent=True) or {}
    if 'value' not in payload:
        return jsonify({'error': 'Missing setting value'}), 400
    try:
        job_id = int(payload.get('job_id') or 0) or None
    except (TypeError, ValueError):
        job_id = None
    mode_map = {
        'learning_mode_mistakes': 'mistakes',
        'learning_mode_blunders': 'blunders',
        'learning_mode_excellent': 'excellent',
        'learning_mode_brilliant': 'brilliant',
    }
    job_update = None
    should_start = False
    try:
        with connect() as conn:
            value = save_setting(key, payload['value'], conn)
            if key.startswith('review_engine_') or key == 'stockfish_dir':
                conn.execute('DELETE FROM engine_eval_cache')
            if job_id and key in mode_map:
                row = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
                if row is not None and (row['source_type'] or 'self') == 'self':
                    try:
                        modes = set(json.loads(row['learning_modes'] or '[]'))
                    except (TypeError, json.JSONDecodeError):
                        modes = {'mistakes'}
                    mode = mode_map[key]
                    before = set(modes)
                    if bool(value):
                        modes.add(mode)
                    else:
                        modes.discard(mode)
                    if not modes:
                        modes.add('mistakes')
                    ordered = [m for m in ('mistakes', 'blunders', 'excellent', 'brilliant') if m in modes]
                    changed = modes != before
                    if changed:
                        status = row['status']
                        retrieval_row = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
                        retrieved = retrieval_row is None or retrieval_row['status'] == 'complete'
                        conn.execute('UPDATE analysis_jobs SET learning_modes = ? WHERE id = ?',
                                     (json.dumps(ordered), job_id))
                        if status in ('complete', 'error', 'stopped') and modes - before and retrieved:
                            queue_analysis(conn, job_id, status,
                                completed_passes=row['passes_completed'], max_passes=row['max_passes'])
                            should_start = True
                            status = 'queued' 
                        job_update = {'job_id': job_id, 'learning_modes': ordered, 'status': status}
            conn.commit()
    except KeyError:
        return jsonify({'error': 'Unknown setting'}), 404
    except (ValueError, TypeError) as exc:
        return jsonify({'error': str(exc)}), 400

    if key.startswith('review_engine_') or key == 'stockfish_dir':
        reset_review_engine()
    if key.startswith('adaptive_') or key in {'ollama_base_url', 'ollama_model'}:
        backfill_adaptive_concepts()
    if should_start and job_id:
        start_analysis_thread(job_id)
    result = {'ok': True, 'key': key, 'value': value}
    if job_update:
        result['game_list'] = job_update
    return jsonify(result)


@app.post('/api/settings/reset')
def reset_all_settings():
    with connect() as conn:
        reset_settings(conn)
        conn.execute('DELETE FROM engine_eval_cache')
        conn.commit()
    reset_review_engine()
    backfill_adaptive_concepts()
    return jsonify({'ok': True, 'values': get_settings()})


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    account_id = session.get('account_id')
    if not account_id:
        return redirect(url_for('index'))

    global_settings = get_settings()
    error = None

    if request.method == 'POST':
        date_range = request.form.get('date_range', 'month')
        game_types = request.form.getlist('game_types') or ['blitz']
        source_type = request.form.get('analysis_source', 'self').strip().lower()
        owner_username = session.get('username') or ''
        if source_type == 'opposition':
            source_username = request.form.get('opponent_username', '').strip()
            if not source_username:
                error = 'Enter the opponent Lichess username to research.'
            else:
                try:
                    if not verify_lichess_username(source_username):
                        error = 'That opponent Lichess account could not be verified.'
                except requests.RequestException as exc:
                    error = f'Lichess could not verify that opponent: {exc}'
            learning_modes = ['opposition']
        else:
            source_type = 'self'
            source_username = owner_username
            learning_modes = [m for m in request.form.getlist('learning_modes') if m in {'mistakes', 'blunders', 'excellent', 'brilliant'}]
            if not learning_modes:
                learning_modes = ['mistakes']

        try:
            screen_seconds = float(request.form.get('screen_seconds', global_settings['screen_seconds']))
            deep_seconds = float(request.form.get('deep_seconds', global_settings['deep_seconds']))
        except ValueError:
            screen_seconds = float(global_settings['screen_seconds'])
            deep_seconds = float(global_settings['deep_seconds'])
        screen_seconds = max(0.1, min(120.0, screen_seconds))
        deep_seconds = max(0.1, min(300.0, deep_seconds))

        if error is None:
            job_settings = dict(global_settings)
            job_settings['screen_seconds'] = screen_seconds
            job_settings['deep_seconds'] = deep_seconds
            base_screen_depth = int(job_settings['base_screen_depth'])
            base_deep_depth = int(job_settings['base_deep_depth'])
            max_passes = int(job_settings['max_passes']) if job_settings['progressive_depths_enabled'] else 1
            job_settings['max_passes'] = max_passes
            settings_json = serialize_settings(job_settings)

            with connect() as conn:
                # Game lists are independent: a new import must not cancel or
                # supersede any previous list, even from the same account.
                cur = conn.execute("""
                    INSERT INTO analysis_jobs (
                        account_id, date_range, game_types,
                        screen_depth, deep_depth, screen_seconds, deep_seconds,
                        current_pass, max_passes, passes_completed,
                        current_screen_depth, current_deep_depth, settings_json,
                        source_type, source_username, learning_modes, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 0, ?, ?, ?, ?, ?, ?, 'waiting_for_games')
                """, (
                    account_id, date_range, json.dumps(game_types),
                    base_screen_depth, base_deep_depth, screen_seconds, deep_seconds,
                    max_passes, base_screen_depth, base_deep_depth, settings_json,
                    source_type, source_username, json.dumps(learning_modes),
                ))
                job_id = cur.lastrowid
                conn.execute("INSERT INTO retrieval_processes(job_id,status) VALUES (?,'queued')", (job_id,))
                conn.commit()

            start_retrieval_thread(job_id)
            return redirect(url_for('analyzing', job_id=job_id))

    default_modes = []
    if global_settings.get('learning_mode_mistakes', True):
        default_modes.append('mistakes')
    if global_settings.get('learning_mode_blunders', True):
        default_modes.append('blunders')
    if global_settings.get('learning_mode_excellent', False):
        default_modes.append('excellent')
    if global_settings.get('learning_mode_brilliant', False):
        default_modes.append('brilliant')
    if not default_modes:
        default_modes = ['mistakes']
    return render_template('setup.html', username=session.get('username'), settings=global_settings,
                           default_modes=default_modes, error=error)


@app.route('/analyzing/<int:job_id>')
def analyzing(job_id):
    return redirect(url_for('processes', job_id=job_id))



def list_has_positions(job_id):
    with connect() as conn:
        return conn.execute(
            'SELECT 1 FROM training_positions WHERE job_id=? LIMIT 1', (job_id,)
        ).fetchone() is not None


@app.route('/openings/<int:job_id>')
def openings(job_id):
    if not list_has_positions(job_id):
        return redirect(url_for('processes', job_id=job_id))
    with connect() as conn:
        job = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return redirect(url_for('index'))
        ensure_opening_metadata(conn, job_id)
    return render_template('openings.html', job_id=job_id, job=dict(job))


@app.route('/openings/<int:job_id>/<opening_key>')
def opening_detail(job_id, opening_key):
    if not list_has_positions(job_id):
        return redirect(url_for('processes', job_id=job_id))
    with connect() as conn:
        job = conn.execute('SELECT id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return redirect(url_for('index'))
        ensure_opening_metadata(conn, job_id)
        summary = conn.execute('''
          SELECT opening_name AS name, opening_key AS key,
                 COUNT(*) AS position_count,
                 MIN(estimated_rating) AS rating_min, MAX(estimated_rating) AS rating_max,
                 CASE WHEN COUNT(DISTINCT NULLIF(opening_eco, '')) = 1 THEN MAX(opening_eco) ELSE 'Multiple ECOs' END AS eco
          FROM training_positions WHERE job_id = ? AND opening_key = ?
          GROUP BY opening_key, opening_name
        ''', (job_id, opening_key)).fetchone()
        if summary is None:
            return redirect(url_for('openings', job_id=job_id))
        variations = [dict(row) for row in conn.execute('''
          SELECT COALESCE(opening_variation, '') AS variation, COUNT(*) AS positions
          FROM training_positions WHERE job_id = ? AND opening_key = ?
          GROUP BY COALESCE(opening_variation, '') ORDER BY positions DESC, variation ASC
        ''', (job_id, opening_key)).fetchall()]
    rating_min = max(200, (int(summary['rating_min'] or 600) // 50) * 50)
    rating_max = min(3200, ((int(summary['rating_max'] or 2400) + 49) // 50) * 50)
    if rating_max <= rating_min:
        rating_max = min(3200, rating_min + 200)
    return render_template('opening_detail.html', job_id=job_id,
      opening=dict(summary), variations=variations,
      historical_games=famous_for_opening(summary['name']),
      rating_min=rating_min, rating_max=rating_max)


@app.get('/api/jobs/<int:job_id>/openings')
def opening_plans(job_id):
    with connect() as conn:
        job = conn.execute('SELECT id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Job not found'}), 404
        ensure_opening_metadata(conn, job_id)
        rows = conn.execute('''
          SELECT opening_key AS key, MAX(opening_name) AS name, CASE WHEN COUNT(DISTINCT NULLIF(opening_eco, '')) = 1 THEN MAX(opening_eco) ELSE 'Multiple ECOs' END AS eco,
            COUNT(DISTINCT COALESCE(game_id, 'position:' || id)) AS game_count,
            COUNT(*) AS position_count, SUM(learned) AS learned_positions,
            COUNT(DISTINCT COALESCE(NULLIF(opening_variation,''),'Main line')) AS variation_count,
            COUNT(DISTINCT CASE WHEN historical_match IS NOT NULL THEN id END) AS historical_positions,
            MIN(move_number) AS first_move
          FROM training_positions WHERE job_id = ? AND opening_key IS NOT NULL
          GROUP BY opening_key ORDER BY position_count DESC, name ASC
        ''', (job_id,)).fetchall()
    # Group equivalent boards inside SQLite, returning only one aggregate row
    # per family instead of transferring every FEN into Python on each visit.
    with connect() as conn:
        unique_rows = conn.execute("""
            SELECT opening_key, COUNT(*) AS positions,
                   SUM(fully_learned) AS learned
            FROM (
                SELECT opening_key, board_identity(fen) AS board_key,
                       MIN(learned) AS fully_learned
                FROM training_positions
                WHERE job_id = ? AND opening_key IS NOT NULL
                GROUP BY opening_key, board_key
            )
            GROUP BY opening_key
        """, (job_id,)).fetchall()
    opening_totals = {row['opening_key']: [int(row['positions']), int(row['learned'] or 0)]
                      for row in unique_rows}
    output = []
    for row in rows:
        item = dict(row)
        item['position_count'], item['learned_positions'] = opening_totals.get(row['key'], [0, 0])
        item['classic_count'] = len(famous_for_opening(row['name']))
        output.append(item)
    return jsonify(output)


@app.post('/api/jobs/<int:job_id>/openings/<opening_key>/reset')
def reset_opening(job_id, opening_key):
    with connect() as conn:
        job = conn.execute('SELECT account_id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None: return jsonify({'error': 'Job not found'}), 404
        ensure_opening_metadata(conn, job_id)
        positions = conn.execute('''
          SELECT id, job_id, game_id, fen, played_move_uci, best_move_uci
          FROM training_positions WHERE job_id = ? AND opening_key = ?
        ''', (job_id, opening_key)).fetchall()
        if not positions: return jsonify({'error': 'Opening not found'}), 404
        for position in positions:
            _set_account_position_learned(conn, job['account_id'], position, False)
        conn.commit()
    return jsonify({'ok': True, 'reset_positions': len(positions)})


@app.route('/lessons/<int:job_id>')
def lessons(job_id):
    if not list_has_positions(job_id):
        return redirect(url_for('processes', job_id=job_id))
    with connect() as conn:
        job = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
    if job is None:
        return redirect(url_for('index'))
    job = dict(job)
    try:
        job['learning_modes'] = json.loads(job.get('learning_modes') or '[]')
    except (TypeError, json.JSONDecodeError):
        job['learning_modes'] = ['mistakes']
    return render_template('lessons.html', job_id=job_id, job=job)


@app.route('/lessons/<int:job_id>/<concept_key>')
def lesson_detail(job_id, concept_key):
    if not list_has_positions(job_id):
        return redirect(url_for('processes', job_id=job_id))
    with connect() as conn:
        job = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        lesson = conn.execute('''
            SELECT key, name, family, description, source, status
            FROM learning_concepts
            WHERE key = ?
        ''', (concept_key,)).fetchone()
        rating_bounds = conn.execute('''
            SELECT MIN(tp.estimated_rating) AS rating_min, MAX(tp.estimated_rating) AS rating_max
            FROM training_positions tp
            WHERE tp.job_id = ? AND tp.estimated_rating IS NOT NULL
        ''', (job_id,)).fetchone()
        lesson_options = conn.execute('''
            SELECT lc.key, lc.name
            FROM learning_concepts lc
            JOIN position_concepts pc ON pc.concept_key = lc.key
            JOIN training_positions tp ON tp.id = pc.position_id
            WHERE tp.job_id = ? AND pc.is_primary = 1
              AND lc.key <> 'candidate_evaluation' AND lc.status <> 'retired'
              AND (lc.source = 'built_in' OR lc.status IN ('personal','promoted'))
            GROUP BY lc.key, lc.name, lc.priority
            ORDER BY lc.name COLLATE NOCASE ASC, lc.key ASC
        ''', (job_id,)).fetchall()
        taxonomy_scopes = conn.execute("""
            SELECT DISTINCT tx.context_key, tx.move_type_key
            FROM training_positions tp
            JOIN position_concepts pc ON pc.position_id=tp.id AND pc.is_primary=1
            JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
            WHERE tp.job_id=? AND pc.concept_key=?
        """, (job_id, concept_key)).fetchall()
        has_position = conn.execute('''
            SELECT 1
            FROM training_positions tp
            JOIN position_concepts pc ON pc.position_id = tp.id
            WHERE tp.job_id = ? AND pc.concept_key = ? AND pc.is_primary = 1
            LIMIT 1
        ''', (job_id, concept_key)).fetchone()
    if job is None:
        return redirect(url_for('index'))
    if lesson is None or has_position is None:
        return redirect(url_for('lessons', job_id=job_id))
    raw_min = int(rating_bounds['rating_min']) if rating_bounds and rating_bounds['rating_min'] is not None else 600
    raw_max = int(rating_bounds['rating_max']) if rating_bounds and rating_bounds['rating_max'] is not None else 2400
    rating_min = max(200, (raw_min // 50) * 50)
    rating_max = min(3200, ((raw_max + 49) // 50) * 50)
    if rating_max <= rating_min:
        rating_max = min(3200, rating_min + 200)
    return render_template(
        'lesson_detail.html', job_id=job_id, lesson=dict(lesson),
        rating_min=rating_min, rating_max=rating_max,
        lesson_options=[dict(row) for row in lesson_options],
        lesson_taxonomy_contexts=[name for key, name in COACHING_CONTEXTS.items()
                                  if any(scope['context_key'] == key for scope in taxonomy_scopes)],
        lesson_taxonomy_move_types=[name for key, name in COACHING_MOVE_TYPES.items()
                                    if any(scope['move_type_key'] == key for scope in taxonomy_scopes)],
    )


@app.route('/trainer/<int:job_id>')
def trainer(job_id):
    if not list_has_positions(job_id):
        return redirect(url_for('processes', job_id=job_id))
    concept_key = request.args.get('concept', '').strip()
    opening_key = request.args.get('opening', '').strip()
    opening_variation = request.args.get('variation','')
    learning_mode = request.args.get('learning_mode', '').strip().lower()
    if learning_mode not in {'mistakes', 'blunders', 'excellent', 'brilliant', 'opposition'}:
        learning_mode = ''
    # An unfiltered general playlist should mix openings and motifs. Preserve
    # explicit sorting and all lesson/opening/single-position launch behavior.
    general_playlist = not any((concept_key, opening_key, opening_variation, learning_mode,
                                request.args.get('context'), request.args.get('move_type'),
                                request.args.get('position'), request.args.get('rating_min'),
                                request.args.get('rating_max')))
    default_sort = 'balanced' if general_playlist else 'rating-asc'
    sort_key = request.args.get('sort', default_sort).strip().lower()
    if sort_key not in {'balanced', 'rating-asc', 'rating-desc', 'date-desc', 'date-asc', 'move-asc', 'move-desc'}:
        sort_key = default_sort
    if sort_key == 'balanced' and not general_playlist:
        sort_key = 'rating-asc'
    listing_scope = request.args.get('listing', '').strip() == '1'
    try:
        rating_min = int(request.args.get('rating_min', '') or 0) or None
    except (TypeError, ValueError):
        rating_min = None
    try:
        rating_max = int(request.args.get('rating_max', '') or 0) or None
    except (TypeError, ValueError):
        rating_max = None
    try:
        selected_position_id = int(request.args.get('position', '') or 0) or None
    except (TypeError, ValueError):
        selected_position_id = None
    evaluation_run_id = None
    if request.args.get('benchmark') == '1':
        with connect() as conn:
            requested_run=request.args.get('run_id',type=int)
            evaluated=resolve_run(conn,job_id,requested_run)
            # An invalid explicit run must not silently select a different run.
            if requested_run and evaluated is None:
                return redirect(url_for('processes',job_id=job_id))
            evaluation_run_id=evaluated['id'] if evaluated else None
            if evaluation_run_id is None:
                return redirect(url_for('processes',job_id=job_id))
    opening = None
    if opening_key:
        with connect() as conn:
            ensure_opening_metadata(conn, job_id)
            opening_row = conn.execute('SELECT opening_key AS key, MAX(opening_name) AS name FROM training_positions WHERE job_id = ? AND opening_key = ? GROUP BY opening_key', (job_id, opening_key)).fetchone()
            opening = dict(opening_row) if opening_row else None
            if opening is None: opening_key = ''
    lesson = None
    if concept_key:
        with connect() as conn:
            row = conn.execute(
                'SELECT key, name, family, description, source, status FROM learning_concepts WHERE key = ?',
                (concept_key,),
            ).fetchone()
            lesson = dict(row) if row else None
            if lesson is None:
                concept_key = ''
    coach_enabled = bool(get_settings().get('adaptive_coach_enabled', False))
    return render_template(
        'trainer.html', job_id=job_id, concept_key=concept_key, lesson=lesson, opening=opening, opening_key=opening_key, opening_variation=opening_variation,
        historical_references=famous_for_opening(opening['name']) if opening else [],
        coach_enabled=coach_enabled, selected_position_id=selected_position_id,
        learning_mode=learning_mode, sort_key=sort_key, listing_scope=listing_scope,
        rating_min=rating_min, rating_max=rating_max,
        evaluation_run_id=evaluation_run_id,
    )


@app.get('/api/jobs/<int:job_id>')
def job_status(job_id):
    with connect() as conn:
        row = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Job not found'}), 404

        training = int(conn.execute(
            'SELECT COUNT(*) AS n FROM training_positions WHERE job_id = ?', (job_id,)
        ).fetchone()['n'])
        learned = int(conn.execute(
            'SELECT COUNT(*) AS n FROM training_positions WHERE job_id = ? AND learned = 1', (job_id,)
        ).fetchone()['n'])
        candidates = int(conn.execute(
            'SELECT COUNT(*) AS n FROM analysis_candidates WHERE job_id = ?', (job_id,)
        ).fetchone()['n'])

    payload = dict(row)
    try:
        payload['learning_modes'] = json.loads(payload.get('learning_modes') or '["mistakes"]')
    except (TypeError, json.JSONDecodeError):
        payload['learning_modes'] = ['mistakes']
    payload['source_type'] = payload.get('source_type') or 'self'
    payload['source_username'] = payload.get('source_username') or ''
    screened = max(int(payload.get('games_screened') or 0), int(payload.get('games_processed') or 0))
    positions_analyzed = max(candidates, training)
    learned_pct = round((learned / training) * 100) if training else 0
    payload.update({
        'games_screened': screened,
        'positions_analyzed': positions_analyzed,
        'training_positions': training,
        'learned_positions': learned,
        'learned_pct': learned_pct,
        # Compatibility: old clients used positions_found for confirmed puzzles.
        'positions_found': training,
        'stats': {
            'total_games': int(payload.get('games_retrieved') or 0),
            'games_screened': screened,
            'positions_analyzed': positions_analyzed,
            'training_positions': training,
            'positions_learned': learned,
            'percent_learned': learned_pct,
        },
    })
    return jsonify(payload)


@app.post('/api/jobs/<int:job_id>/learning-modes')
def set_job_learning_modes(job_id):
    payload = request.get_json(silent=True) or {}
    requested = [m for m in (payload.get('modes') or []) if m in {'mistakes', 'blunders', 'excellent', 'brilliant'}]
    if not requested:
        return jsonify({'error': 'Keep at least one personal learning mode enabled.'}), 400
    requested_set = set(requested)
    should_start = False
    with connect() as conn:
        row = conn.execute('SELECT * FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Job not found'}), 404
        if (row['source_type'] or 'self') != 'self':
            return jsonify({'error': 'Opposition research is a standalone game list and cannot mix personal learning modes.'}), 409
        try:
            current = set(json.loads(row['learning_modes'] or '[]'))
        except (TypeError, json.JSONDecodeError):
            current = {'mistakes'}
        ordered = [m for m in ('mistakes', 'blunders', 'excellent', 'brilliant') if m in requested_set]
        added = requested_set - current
        removed = current - requested_set
        status = row['status']
        if requested_set != current:
            conn.execute('UPDATE analysis_jobs SET learning_modes = ? WHERE id = ?',
                         (json.dumps(ordered), job_id))
            retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
            retrieved = retrieval is None or retrieval['status'] == 'complete'
            if added and status in ('complete', 'error', 'stopped') and retrieved:
                queue_analysis(conn, job_id, status,
                    completed_passes=row['passes_completed'], max_passes=row['max_passes'])
                status = 'queued'
                should_start = True
        if payload.get('persist_defaults'):
            defaults = {
                'learning_mode_mistakes': 'mistakes' in requested_set,
                'learning_mode_blunders': 'blunders' in requested_set,
                'learning_mode_excellent': 'excellent' in requested_set,
                'learning_mode_brilliant': 'brilliant' in requested_set,
            }
            for key, value in defaults.items():
                save_setting(key, value, conn)
        conn.commit()
    if should_start:
        start_analysis_thread(job_id)
    return jsonify({
        'ok': True, 'learning_modes': ordered, 'added': sorted(added), 'removed': sorted(removed),
        'status': status, 'reanalysis_queued': should_start,
    })


@app.post('/api/jobs/<int:job_id>/pause')
def pause_job(job_id):
    with connect() as conn:
        row = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Job not found'}), 404
        if row['status'] not in ('queued', 'running', 'retrieving'):
            return jsonify({'error': 'Analysis is not active.'}), 409
        conn.execute(
            "UPDATE analysis_jobs SET status = 'paused' WHERE id = ?",
            (job_id,),
        )
        conn.commit()
    return jsonify({'ok': True, 'status': 'paused'})


@app.post('/api/jobs/<int:job_id>/resume')
def resume_job(job_id):
    with connect() as conn:
        row = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Job not found'}), 404
        if row['status'] != 'paused':
            return jsonify({'error': 'Only paused jobs can be resumed'}), 409
        retrieval = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
        if retrieval is not None and retrieval['status'] != 'complete':
            return jsonify({'error': 'Resume the Retrieval process first.'}), 409
        conn.execute(
            "UPDATE analysis_jobs SET status = 'queued', error = NULL, finished_at = NULL WHERE id = ?",
            (job_id,),
        )
        conn.commit()
    resume_analysis_thread(job_id)
    return jsonify({'ok': True, 'status': 'queued'})


def _set_account_position_learned(conn, account_id, position_row, learned):
    """Persist curriculum status only within the same game-list source scope."""
    value = 1 if learned else 0
    fen = position_row['fen']
    best_move = position_row['best_move_uci']
    job_id = position_row['job_id'] if 'job_id' in position_row.keys() else None
    scope = conn.execute('SELECT source_type, source_username FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone() if job_id else None
    source_type = (scope['source_type'] if scope else 'self') or 'self'
    source_username = (scope['source_username'] if scope else '') or ''
    if fen and best_move:
        conn.execute("""
            UPDATE training_positions
            SET learned = ?
            WHERE fen = ? AND best_move_uci = ?
              AND job_id IN (
                  SELECT id FROM analysis_jobs
                  WHERE account_id = ?
                    AND COALESCE(source_type, 'self') = ?
                    AND lower(COALESCE(source_username, '')) = lower(?)
              )
        """, (value, fen, best_move, account_id, source_type, source_username))
        return
    conn.execute('UPDATE training_positions SET learned = ? WHERE id = ?', (value, position_row['id']))


def _set_opening_position_group_learned(conn, position_row, opening_key, learned):
    """An opening puzzle is one board state, regardless of its game continuation.

    Synchronize equivalent imported positions when explicitly trained within
    an opening playlist. This also retires alternate move records next launch.
    """
    if not opening_key or position_row['opening_key'] != opening_key:
        return
    rows = conn.execute('''
        SELECT tp.id, tp.job_id, tp.fen, tp.best_move_uci, j.account_id
        FROM training_positions tp JOIN analysis_jobs j ON j.id = tp.job_id
        WHERE tp.job_id = ? AND tp.opening_key = ?
    ''', (position_row['job_id'], opening_key)).fetchall()
    board_key = board_identity(position_row['fen'])
    for other in rows:
        if board_identity(other['fen']) == board_key:
            _set_account_position_learned(conn, other['account_id'], other, learned)


def _sync_account_learning_progress(conn, account_id):
    """Repair duplicate puzzle progress within each source scope, never across opposition/personal lists."""
    learned_signatures = conn.execute("""
        SELECT DISTINCT tp.fen, tp.best_move_uci,
               COALESCE(j.source_type, 'self') AS source_type,
               COALESCE(j.source_username, '') AS source_username
        FROM training_positions tp
        JOIN analysis_jobs j ON j.id = tp.job_id
        WHERE j.account_id = ? AND tp.learned = 1
          AND tp.fen IS NOT NULL AND tp.best_move_uci IS NOT NULL
    """, (account_id,)).fetchall()
    for sig in learned_signatures:
        conn.execute("""
            UPDATE training_positions SET learned = 1
            WHERE fen = ? AND best_move_uci = ?
              AND job_id IN (
                  SELECT id FROM analysis_jobs
                  WHERE account_id = ?
                    AND COALESCE(source_type, 'self') = ?
                    AND lower(COALESCE(source_username, '')) = lower(?)
              )
        """, (sig['fen'], sig['best_move_uci'], account_id, sig['source_type'], sig['source_username']))


def _position_concepts(conn, position_ids):
    if not position_ids:
        return {}
    placeholders = ','.join('?' for _ in position_ids)
    rows = conn.execute(f'''
        SELECT pc.position_id, pc.concept_key AS key, lc.name, lc.family,
               lc.description, lc.source, lc.status, pc.confidence, pc.is_primary, pc.evidence
        FROM position_concepts pc
        JOIN learning_concepts lc ON lc.key = pc.concept_key
        WHERE pc.position_id IN ({placeholders})
        ORDER BY pc.position_id, pc.is_primary DESC, pc.confidence DESC, lc.priority DESC
    ''', tuple(position_ids)).fetchall()
    grouped = {position_id: [] for position_id in position_ids}
    for row in rows:
        item = dict(row)
        position_id = item.pop('position_id')
        item['is_primary'] = bool(item['is_primary'])
        grouped.setdefault(position_id, []).append(item)
    return grouped


def _position_taxonomies(conn, position_ids):
    """Expose exact two/three-level paths; read-only and batch scoped."""
    if not position_ids:
        return {}
    from coaching_taxonomy import CONTEXTS, MOVE_TYPES, TAXONOMY_VERSION
    output = {}
    for offset in range(0, len(position_ids), 400):
        chunk = position_ids[offset:offset + 400]
        placeholders = ','.join('?' for _ in chunk)
        rows = conn.execute(f"""
            SELECT tx.position_id, tx.context_key, tx.move_type_key,
                   tx.motif_key, tx.confidence, tx.evidence, tx.taxonomy_version,
                   lc.name AS motif_name
            FROM position_motif_taxonomy tx
            JOIN learning_concepts lc ON lc.key=tx.motif_key
            WHERE tx.position_id IN ({placeholders})
        """, tuple(chunk)).fetchall()
        for row in rows:
            data = dict(row)
            ctx = data['context_key']; move_type = data['move_type_key']
            if ctx not in CONTEXTS or move_type not in (*MOVE_TYPES, None):
                continue
            path = [{'level': 'context', 'key': ctx, 'name': CONTEXTS[ctx]}]
            if move_type:
                path.append({'level': 'move_type', 'key': move_type, 'name': MOVE_TYPES[move_type]})
            path.append({'level': 'motif', 'key': data['motif_key'], 'name': data['motif_name']})
            data.update(context_name=CONTEXTS[ctx], move_type_name=MOVE_TYPES.get(move_type),
                        levels=path)
            output[data['position_id']] = data
    return output


@app.get('/api/jobs/<int:job_id>/positions')
def positions(job_id):
    concept_key = request.args.get('concept', '').strip()
    context_filter = request.args.get('context', '').strip()
    move_type_filter = request.args.get('move_type', '').strip()
    if context_filter not in {'', 'attack', 'defend'} or move_type_filter not in {'', 'general', 'tactical', 'strategic'}:
        return jsonify({'error': 'Invalid taxonomy filter'}), 400
    opening_key = request.args.get('opening', '').strip()
    opening_variation = request.args.get('variation', '')
    learning_mode = request.args.get('learning_mode', '').strip().lower()
    if learning_mode not in {'mistakes', 'blunders', 'excellent', 'brilliant', 'opposition'}:
        learning_mode = ''
    sort_key = request.args.get('sort', 'rating-asc').strip().lower()
    listing_scope = request.args.get('listing', '').strip() == '1'
    try:
        rating_min = int(request.args.get('rating_min', '') or 0) or None
    except (TypeError, ValueError):
        rating_min = None
    try:
        rating_max = int(request.args.get('rating_max', '') or 0) or None
    except (TypeError, ValueError):
        rating_max = None
    try:
        selected_position_id = int(request.args.get('position_id', '') or 0) or None
    except (TypeError, ValueError):
        selected_position_id = None
    with connect() as conn:
        job = conn.execute('SELECT account_id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        # Learning writes already propagate; page reads must remain read-only.
        if opening_key: ensure_opening_metadata(conn, job_id)
        params = [job_id]
        join = ''
        if selected_position_id:
            where = 'WHERE tp.job_id = ? AND (tp.learned = 0 OR tp.id = ?)'
            params.append(selected_position_id)
        else:
            where = 'WHERE tp.job_id = ? AND tp.learned = 0'
        order = {
            'rating-asc': 'ORDER BY CASE WHEN tp.estimated_rating IS NULL THEN 1 ELSE 0 END, tp.estimated_rating ASC, tp.id ASC',
            'rating-desc': 'ORDER BY CASE WHEN tp.estimated_rating IS NULL THEN 1 ELSE 0 END, tp.estimated_rating DESC, tp.id ASC',
            'date-desc': "ORDER BY COALESCE(tp.game_date, '') DESC, tp.id DESC",
            'date-asc': "ORDER BY COALESCE(tp.game_date, '') ASC, tp.id ASC",
        'move-asc': 'ORDER BY tp.move_number ASC, tp.opening_history ASC, tp.id ASC',
        'move-desc': 'ORDER BY tp.move_number DESC, tp.opening_history ASC, tp.id ASC',
        }.get(sort_key, 'ORDER BY CASE WHEN tp.estimated_rating IS NULL THEN 1 ELSE 0 END, tp.estimated_rating ASC, tp.id ASC')
        if concept_key:
            join += ' JOIN position_concepts selected_pc ON selected_pc.position_id = tp.id AND selected_pc.is_primary = 1'
            where += ' AND selected_pc.concept_key = ?'
            params.append(concept_key)
        if opening_key:
            where += ' AND tp.opening_key = ?'
            params.append(opening_key)
            if opening_variation:
                where += ' AND tp.opening_variation = ?'
                params.append(opening_variation)
        if context_filter or move_type_filter:
            join += ' JOIN position_motif_taxonomy scoped_tx ON scoped_tx.position_id = tp.id'
            if context_filter:
                where += ' AND scoped_tx.context_key = ?'
                params.append(context_filter)
            if move_type_filter:
                if move_type_filter == 'general':
                    where += ' AND scoped_tx.move_type_key IS NULL'
                else:
                    where += ' AND scoped_tx.move_type_key = ?'
                    params.append(move_type_filter)
        if learning_mode:
            where += ' AND tp.learning_mode = ?'
            params.append(learning_mode)
        if rating_min is not None:
            where += ' AND tp.estimated_rating >= ?'
            params.append(rating_min)
        if rating_max is not None:
            where += ' AND tp.estimated_rating <= ?'
            params.append(rating_max)

        rows = conn.execute(f'''
            SELECT tp.id, tp.game_id, tp.category, tp.learning_mode, tp.fen, tp.previous_fen,
                   tp.opponent_move_uci, tp.opponent_move_san, tp.played_move_san, tp.played_move_uci,
                   tp.user_color, tp.move_number, tp.mistake_ply, tp.game_date, tp.opponent,
                   tp.learned, tp.attempts, tp.correct_attempts, tp.centipawn_loss,
                   tp.difficulty_score, tp.estimated_rating, tp.coach_prompt,
                   tp.opening_name, tp.opening_variation, tp.opening_eco, tp.historical_match
            FROM training_positions tp
            {join}
            {where}
            {order}
        ''', tuple(params)).fetchall()

        items = [dict(row) for row in rows]

        # A lesson playlist is game-centric: keep the strongest representative
        # position for a concept from each game, rather than repeating one game.
        if concept_key and not listing_scope:
            seen_games = set()
            deduped = []
            for item in items:
                game_key = item['game_id'] or f"position:{item['id']}"
                if game_key in seen_games:
                    continue
                seen_games.add(game_key)
                deduped.append(item)
            items = deduped

        if opening_key:
            items = enrich_opening_playlist(conn, job_id, opening_key, items)

        concepts = _position_concepts(conn, [item['id'] for item in items])
        taxonomy_paths = _position_taxonomies(conn, [item['id'] for item in items])
        for item in items:
            item['taxonomy'] = taxonomy_paths.get(item['id'])
            item['concepts'] = concepts.get(item['id'], [])
            item['primary_concept'] = next(
                (concept for concept in item['concepts'] if concept['is_primary']),
                item['concepts'][0] if item['concepts'] else None,
            )

    return jsonify(items)


# A small manifest is enough to establish stable playlist membership, order, and
# learned progress. Training cards and their motif details are hydrated separately
# in bounded chunks, so opening a long playlist does not fetch every card at once.
@app.route('/api/jobs/<int:job_id>/positions/manifest', methods=['GET', 'POST'])
def training_playlist_manifest(job_id):
    with connect() as conn:
        job = conn.execute('SELECT id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404

        if request.method == 'POST':
            payload = request.get_json(silent=True) or {}
            raw_ids = payload.get('position_ids')
            if not isinstance(raw_ids, list) or len(raw_ids) > 20000:
                return jsonify({'error': 'Invalid playlist'}), 400
            try:
                ids = [int(value) for value in raw_ids]
            except (ValueError, TypeError):
                return jsonify({'error': 'Invalid playlist position IDs'}), 400
            if any(value <= 0 for value in ids) or len(set(ids)) != len(ids):
                return jsonify({'error': 'Invalid playlist position IDs'}), 400
            by_id = {}
            for offset in range(0, len(ids), 400):
                chunk = ids[offset:offset + 400]
                if not chunk:
                    continue
                placeholders = ','.join('?' for _ in chunk)
                rows = conn.execute(f'''SELECT id, learned FROM training_positions
                    WHERE job_id = ? AND id IN ({placeholders})''', (job_id, *chunk)).fetchall()
                by_id.update({int(row['id']): {'id': int(row['id']), 'learned': int(row['learned'])}
                              for row in rows})
            return jsonify([by_id[value] for value in ids if value in by_id])

        if request.args.get('benchmark') == '1':
            run_id=request.args.get('run_id',type=int)
            run=resolve_run(conn,job_id,run_id)
            if not run or (run_id and int(run['id'])!=run_id):
                return jsonify({'error':'No evaluation run. Complete Coaching refresh or start one from Process.'}),409
            return jsonify(evaluation_manifest(conn,job_id,run['id']))

        concept = request.args.get('concept', '').strip()
        context_filter = request.args.get('context', '').strip()
        move_type_filter = request.args.get('move_type', '').strip()
        if context_filter not in {'', 'attack', 'defend'} or move_type_filter not in {'', 'general', 'tactical', 'strategic'}:
            return jsonify({'error': 'Invalid taxonomy filter'}), 400
        opening = request.args.get('opening', '').strip()
        variation = request.args.get('variation', '')
        mode = request.args.get('learning_mode', '').strip().lower()
        if mode not in {'mistakes', 'blunders', 'excellent', 'brilliant', 'opposition'}:
            mode = ''
        sort_key = request.args.get('sort', 'rating-asc').strip().lower()
        listing = request.args.get('listing', '') == '1'
        try:
            rating_min = int(request.args.get('rating_min', '') or 0) or None
            rating_max = int(request.args.get('rating_max', '') or 0) or None
            requested_id = int(request.args.get('position_id', '') or 0) or None
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid filter'}), 400
        if opening:
            ensure_opening_metadata(conn, job_id)
        where = ['tp.job_id = ?', '(tp.learned = 0 OR tp.id = ?)' if requested_id else 'tp.learned = 0']
        args = [job_id]
        if requested_id:
            args.append(requested_id)
        join = ''
        if concept:
            join = 'JOIN position_concepts pc ON pc.position_id = tp.id AND pc.is_primary = 1'
            where.append('pc.concept_key = ?')
            args.append(concept)
        if context_filter or move_type_filter:
            join += ' JOIN position_motif_taxonomy scoped_tx ON scoped_tx.position_id = tp.id'
            if context_filter:
                where.append('scoped_tx.context_key = ?')
                args.append(context_filter)
            if move_type_filter:
                if move_type_filter == 'general':
                    where.append('scoped_tx.move_type_key IS NULL')
                else:
                    where.append('scoped_tx.move_type_key = ?')
                    args.append(move_type_filter)
        if opening:
            where.append('tp.opening_key = ?')
            args.append(opening)
            if variation:
                where.append('tp.opening_variation = ?')
                args.append(variation)
        if mode:
            where.append('tp.learning_mode = ?')
            args.append(mode)
        if rating_min is not None:
            where.append('tp.estimated_rating >= ?')
            args.append(rating_min)
        if rating_max is not None:
            where.append('tp.estimated_rating <= ?')
            args.append(rating_max)
        order = {
            'rating-asc': 'ORDER BY tp.estimated_rating IS NULL, tp.estimated_rating ASC, tp.id ASC',
            'rating-desc': 'ORDER BY tp.estimated_rating IS NULL, tp.estimated_rating DESC, tp.id ASC',
            'date-desc': "ORDER BY COALESCE(tp.game_date, '') DESC, tp.id DESC",
            'date-asc': "ORDER BY COALESCE(tp.game_date, '') ASC, tp.id ASC",
            'move-asc': 'ORDER BY tp.move_number ASC, tp.opening_history ASC, tp.id ASC',
            'move-desc': 'ORDER BY tp.move_number DESC, tp.opening_history ASC, tp.id ASC',
        }.get(sort_key, 'ORDER BY tp.estimated_rating IS NULL, tp.estimated_rating ASC, tp.id ASC')
        # Only unfiltered All Positions training uses balanced randomness.
        # The explicit sort key is supplied by the trainer page; direct manifest
        # consumers retain their historical rating-based default.
        balanced = (sort_key == 'balanced' and not any((concept, context_filter,
                    move_type_filter, opening, variation, mode, requested_id,
                    rating_min, rating_max)))
        if balanced:
            rows = conn.execute(f'''SELECT tp.id, tp.game_id, tp.learned, tp.fen,
                tp.opening_key, tp.learning_mode,
                COALESCE(tx.motif_key,
                    (SELECT pc.concept_key FROM position_concepts pc
                     WHERE pc.position_id=tp.id AND pc.is_primary=1 LIMIT 1),
                    'unclassified') AS motif_key
                FROM training_positions tp
                LEFT JOIN position_motif_taxonomy tx ON tx.position_id=tp.id
                {join} WHERE {' AND '.join(where)} ORDER BY tp.id ASC''', tuple(args)).fetchall()
            rows = balanced_playlist_order(rows)
        else:
            rows = conn.execute(f'''SELECT tp.id, tp.game_id, tp.learned, tp.fen
                FROM training_positions tp {join}
                WHERE {' AND '.join(where)} {order}''', tuple(args)).fetchall()
        seen = set()
        output = []
        for row in rows:
            # Exactly the same representative rules as the legacy full endpoint.
            key = (board_identity(row['fen']) if opening else
                   (row['game_id'] or f"position:{row['id']}") if concept and not listing else row['id'])
            if key in seen:
                continue
            seen.add(key)
            output.append({'id': int(row['id']), 'learned': int(row['learned'])})
        return jsonify(output)


@app.post('/api/jobs/<int:job_id>/positions/playlist')
def restore_training_playlist(job_id):
    # Restore a fixed training session, including positions since marked learned.

    # Client passes saved position IDs; every ID is scoped to the analysis job.
    payload = request.get_json(silent=True) or {}
    opening_key = str(payload.get('opening_key') or '').strip()
    try:
        evaluation_run_id=int(payload.get('evaluation_run_id') or 0)
    except (ValueError,TypeError):
        return jsonify({'error':'Invalid evaluation run'}),400
    raw_ids = payload.get('position_ids')
    if not isinstance(raw_ids, list) or len(raw_ids) > 20000:
        return jsonify({'error': 'Invalid playlist'}), 400
    try:
        position_ids = [int(value) for value in raw_ids]
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid playlist position IDs'}), 400
    if not position_ids or any(pid <= 0 for pid in position_ids):
        return jsonify([])
    if len(set(position_ids)) != len(position_ids):
        return jsonify({'error': 'Duplicate playlist position IDs'}), 400

    items_by_id = {}
    with connect() as conn:
        job = conn.execute('SELECT account_id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404
        # Read-only batch hydration must not resynchronize every position on
        # every 20-card request. Learning writes already propagate progress.
        for start in range(0, len(position_ids), 450):
            chunk = position_ids[start:start + 450]
            placeholders = ','.join('?' for _ in chunk)
            rows = conn.execute(f'''
                SELECT tp.id, tp.game_id, tp.category, tp.learning_mode, tp.fen, tp.previous_fen,
                       tp.opponent_move_uci, tp.opponent_move_san, tp.played_move_san, tp.played_move_uci,
                       tp.best_move_uci, tp.best_move_san,
                       tp.user_color, tp.move_number, tp.mistake_ply, tp.game_date, tp.opponent,
                       tp.learned, tp.attempts, tp.correct_attempts, tp.centipawn_loss,
                       tp.difficulty_score, tp.estimated_rating, tp.coach_prompt, tp.coach_explanation, tp.coaching_version,
                       tp.eval_before_cp, tp.eval_after_cp, tp.mate_before, tp.mate_after,
                       tp.opening_name, tp.opening_variation, tp.opening_eco, tp.historical_match
                FROM training_positions tp
                WHERE tp.job_id = ? AND tp.id IN ({placeholders})
            ''', (job_id, *chunk)).fetchall()
            items_by_id.update({int(row['id']): dict(row) for row in rows})
        # Evaluation has its own completion state. Global learned remains the
        # curriculum record, never the state of a new benchmark attempt.
        if evaluation_run_id:
            run=resolve_run(conn,job_id,evaluation_run_id)
            if not run:
                return jsonify({'error':'Evaluation run not found'}),404
            for pid,card in list(items_by_id.items()):
                state=run_position(conn,evaluation_run_id,pid,job_id)
                if state is None:
                    return jsonify({'error':'Position is not in this evaluation'}),400
                card['learned'] = int(state['status']=='solved')
                card['evaluation_run_id']=evaluation_run_id
                # Suppress stale current-version prose when refresh incomplete.
                if card.get('coach_explanation') and card.get('coaching_version') != run['coaching_version']:
                    card['coach_explanation']=''
        # Preserve the original, user-selected sort order from the snapshot.
        items = [items_by_id[pid] for pid in position_ids if pid in items_by_id]
        if opening_key:
            items = enrich_opening_playlist(conn, job_id, opening_key, items)

        # Review boards show the accepted engine move, not the unsolved FEN.
        # The browser retains the actual accepted alternative during this session.
        for item in items:
            item['review_best_fen'] = None
            if item['learned'] and item.get('best_move_uci'):
                try:
                    review_board = chess.Board(item['fen'])
                    move = chess.Move.from_uci(item['best_move_uci'])
                    if move in review_board.legal_moves:
                        review_board.push(move)
                        item['review_best_fen'] = review_board.fen()
                except (ValueError, chess.InvalidMoveError):
                    pass

        concepts = _position_concepts(conn, [item['id'] for item in items])
        taxonomy_paths = _position_taxonomies(conn, [item['id'] for item in items])
        for item in items:
            item['taxonomy'] = taxonomy_paths.get(item['id'])
            item['concepts'] = concepts.get(item['id'], [])
            item['primary_concept'] = next(
                (concept for concept in item['concepts'] if concept['is_primary']),
                item['concepts'][0] if item['concepts'] else None,
            )
    return jsonify(items)


@app.get('/api/jobs/<int:job_id>/lessons')
def lesson_plans(job_id):
    with connect() as conn:
        job = conn.execute('SELECT account_id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        # Learning writes already propagate; page reads must remain read-only.
        rows = conn.execute('''
            SELECT lc.key, lc.name, lc.family, lc.description, lc.source, lc.status,
                   COUNT(DISTINCT COALESCE(tp.game_id, 'position:' || tp.id)) AS game_count,
                   COUNT(*) AS position_count,
                   COUNT(DISTINCT CASE WHEN tp.learned = 1
                       THEN COALESCE(tp.game_id, 'position:' || tp.id) END) AS learned_games,
                   SUM(CASE WHEN tp.learned = 1 THEN 1 ELSE 0 END) AS learned_positions,
                   ROUND(AVG(pc.confidence), 3) AS avg_confidence,
                   SUM(CASE WHEN pc.is_primary = 1 THEN 1 ELSE 0 END) AS primary_positions,
                   GROUP_CONCAT(DISTINCT tx.context_key) AS coaching_contexts,
                   GROUP_CONCAT(DISTINCT tx.move_type_key) AS coaching_move_types
            FROM position_concepts pc
            JOIN learning_concepts lc ON lc.key = pc.concept_key
            JOIN training_positions tp ON tp.id = pc.position_id
            LEFT JOIN position_motif_taxonomy tx ON tx.position_id = tp.id
            WHERE tp.job_id = ? AND pc.is_primary = 1
              AND lc.key <> 'candidate_evaluation'
              AND lc.status <> 'retired' AND (lc.source = 'built_in' OR lc.status IN ('personal', 'promoted'))
            GROUP BY lc.key, lc.name, lc.family, lc.description, lc.source, lc.status, lc.priority
            ORDER BY lc.name COLLATE NOCASE ASC, lc.key ASC
        ''', (job_id,)).fetchall()
        lessons = [dict(row) for row in rows]
    return jsonify(lessons)


@app.get('/api/jobs/<int:job_id>/position-library')
def position_library(job_id):
    """Return one server-paginated lesson position page."""
    concept_key = request.args.get('concept', '').strip()
    context_filter = request.args.get('context', '').strip()
    move_type_filter = request.args.get('move_type', '').strip()
    if context_filter not in {'', 'attack', 'defend'}:
        return jsonify({'error': 'Invalid coaching context'}), 400
    if move_type_filter not in {'', 'general', 'tactical', 'strategic'}:
        return jsonify({'error': 'Invalid move type'}), 400
    opening_key = request.args.get('opening', '').strip()
    opening_variation = request.args.get('variation', '')
    status_filter = request.args.get('status', 'all').strip().lower()
    learning_mode = request.args.get('learning_mode', 'all').strip().lower()
    if learning_mode not in {'all', 'mistakes', 'blunders', 'excellent', 'brilliant', 'opposition'}:
        learning_mode = 'all'
    sort_key = request.args.get('sort', 'rating-asc').strip().lower()
    try:
        rating_min = int(request.args.get('rating_min', '') or 0) or None
    except (TypeError, ValueError):
        rating_min = None
    try:
        rating_max = int(request.args.get('rating_max', '') or 0) or None
    except (TypeError, ValueError):
        rating_max = None
    try:
        page = max(1, int(request.args.get('page', '1') or 1))
    except (TypeError, ValueError):
        page = 1
    phase = request.args.get('phase', '').strip().lower()
    settings = get_settings()
    per_page = max(8, min(200, int(settings.get('lesson_page_size', 16))))

    sort_sql = {
        'rating-asc': '(tp.estimated_rating IS NULL), tp.estimated_rating ASC, tp.id ASC',
        'rating-desc': '(tp.estimated_rating IS NULL), tp.estimated_rating DESC, tp.id ASC',
        'date-desc': "COALESCE(tp.game_date, '') DESC, tp.id DESC",
        'date-asc': "COALESCE(tp.game_date, '') ASC, tp.id ASC",
        'move-asc': 'tp.move_number ASC, tp.opening_history ASC, tp.id ASC',
        'move-desc': 'tp.move_number DESC, tp.opening_history ASC, tp.id ASC',
    }.get(sort_key, '(tp.estimated_rating IS NULL), tp.estimated_rating ASC, tp.id ASC')

    with connect() as conn:
        job = conn.execute('SELECT account_id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Job not found'}), 404
        # Page reads must not write or resynchronize the entire account.
        if opening_key: ensure_opening_metadata(conn, job_id)

        join = ''
        base_where = 'WHERE tp.job_id = ?'
        base_params = [job_id]
        if concept_key:
            join = 'JOIN position_concepts scoped_pc ON scoped_pc.position_id = tp.id AND scoped_pc.is_primary = 1'
            base_where += ' AND scoped_pc.concept_key = ?'
            base_params.append(concept_key)

        if opening_key:
            base_where += ' AND tp.opening_key = ?'
            base_params.append(opening_key)
            if opening_variation:
                base_where += ' AND tp.opening_variation = ?'
                base_params.append(opening_variation)

        if context_filter or move_type_filter:
            join += ' JOIN position_motif_taxonomy scoped_tx ON scoped_tx.position_id = tp.id'
            if context_filter:
                base_where += ' AND scoped_tx.context_key = ?'
                base_params.append(context_filter)
            if move_type_filter:
                if move_type_filter == 'general':
                    base_where += ' AND scoped_tx.move_type_key IS NULL'
                else:
                    base_where += ' AND scoped_tx.move_type_key = ?'
                    base_params.append(move_type_filter)

        # Concept, learning mode and rating define the lesson slice whose progress
        # we want to measure. Status is only a listing filter: otherwise choosing
        # "Learned" would make the progress statistics trivially read 100%.
        scope_where = base_where
        scope_params = list(base_params)
        if learning_mode != 'all':
            scope_where += ' AND tp.learning_mode = ?'
            scope_params.append(learning_mode)
        if rating_min is not None:
            scope_where += ' AND tp.estimated_rating >= ?'
            scope_params.append(rating_min)
        if rating_max is not None:
            scope_where += ' AND tp.estimated_rating <= ?'
            scope_params.append(rating_max)

        where = scope_where
        params = list(scope_params)
        if status_filter == 'learned':
            where += ' AND tp.learned = 1'
        elif status_filter == 'unlearned':
            where += ' AND tp.learned = 0'
        else:
            status_filter = 'all'

        # First-paint request: hydrate only the first page (typically 16 cards),
        # with one extra row to establish next-page availability. Exact filtered
        # counts and lesson analytics are requested in parallel, separately.
        if phase == 'page':
            offset = (page - 1) * per_page
            light_rows = conn.execute(f'''
                SELECT DISTINCT tp.id, tp.game_id, tp.game_date, tp.opponent,
                    tp.category, tp.learning_mode, tp.fen, tp.user_color,
                    tp.move_number, tp.learned, tp.attempts, tp.correct_attempts,
                    tp.estimated_rating, tp.difficulty_score, tp.centipawn_loss,
                    tp.opening_name, tp.opening_variation, tp.opening_eco,
                    tp.historical_match
                FROM training_positions tp {join} {where}
                ORDER BY {sort_sql}
                LIMIT ? OFFSET ?
            ''', tuple(params + [per_page + 1, offset])).fetchall()
            has_next = len(light_rows) > per_page
            items = [dict(row) for row in light_rows[:per_page]]
            concepts = _position_concepts(conn, [item['id'] for item in items])
            taxonomy_paths = _position_taxonomies(conn, [item['id'] for item in items])
            for item in items:
                item['taxonomy'] = taxonomy_paths.get(item['id'])
                item['learned'] = bool(item['learned'])
                item['concepts'] = concepts.get(item['id'], [])
                item['primary_concept'] = next(
                    (concept for concept in item['concepts'] if concept['is_primary']),
                    item['concepts'][0] if item['concepts'] else None,
                )
            return jsonify({'items': items, 'pagination': {
                'page': page, 'per_page': per_page,
                'has_previous': page > 1, 'has_next': has_next,
            }})

        summary = conn.execute(f'''
            SELECT COUNT(DISTINCT tp.id) AS total,
                   COUNT(DISTINCT CASE WHEN tp.learned = 1 THEN tp.id END) AS learned,
                   ROUND(AVG(tp.estimated_rating), 1) AS average_rating
            FROM training_positions tp
            {join}
            {scope_where}
        ''', tuple(scope_params)).fetchone()
        total = int(summary['total'] or 0)
        learned = int(summary['learned'] or 0)
        average_rating = float(summary['average_rating']) if summary['average_rating'] is not None else None

        filtered_total = int(conn.execute(f'''
            SELECT COUNT(DISTINCT tp.id) AS n
            FROM training_positions tp
            {join}
            {where}
        ''', tuple(params)).fetchone()['n'] or 0)
        if status_filter == 'learned':
            trainable_total = 0
        else:
            train_where = scope_where + ' AND tp.learned = 0'
            trainable_total = int(conn.execute(f'''
                SELECT COUNT(DISTINCT tp.id) AS n
                FROM training_positions tp
                {join}
                {train_where}
            ''', tuple(scope_params)).fetchone()['n'] or 0)
        if opening_key:
            # The training launch count must represent the unique boards that
            # will actually appear, not every game that reached each board.
            if status_filter != 'learned':
                trainable_total = int(conn.execute(f'''
                    SELECT COUNT(DISTINCT board_identity(tp.fen)) AS n
                    FROM training_positions tp {join}
                    {scope_where} AND tp.learned = 0
                ''', tuple(scope_params)).fetchone()['n'] or 0)
            else:
                trainable_total = 0
        if phase == 'summary':
            pages = max(1, (filtered_total + per_page - 1) // per_page)
            return jsonify({
                'summary': {
                    'total': total, 'learned': learned,
                    'unlearned': max(0, total - learned),
                    'percent_learned': round((learned / total) * 100) if total else 0,
                    'average_rating': average_rating,
                },
                'pagination': {
                    'page': min(page, pages), 'per_page': per_page,
                    'pages': pages, 'filtered_total': filtered_total,
                    'has_previous': page > 1,
                    'has_next': page < pages,
                },
                'trainable_total': trainable_total,
            })
        selection_items = None
        if request.args.get('include_selection') == '1':
            selection_items = [dict(row) for row in conn.execute(f'''
                SELECT DISTINCT tp.id, tp.learned, tp.learning_mode, tp.estimated_rating
                FROM training_positions tp
                {join}
                {where}
                ORDER BY tp.id ASC
            ''', tuple(params)).fetchall()]
        pages = max(1, (filtered_total + per_page - 1) // per_page)
        page = min(page, pages)
        offset = (page - 1) * per_page

        rows = conn.execute(f'''
            SELECT DISTINCT tp.id, tp.game_id, tp.game_date, tp.opponent, tp.category, tp.learning_mode, tp.fen,
                   tp.user_color, tp.move_number, tp.learned, tp.attempts, tp.correct_attempts,
                   tp.estimated_rating, tp.difficulty_score, tp.centipawn_loss,
                   tp.opening_name, tp.opening_variation, tp.opening_eco, tp.historical_match
            FROM training_positions tp
            {join}
            {where}
            ORDER BY {sort_sql}
            LIMIT ? OFFSET ?
        ''', tuple(params + [per_page, offset])).fetchall()
        items = [dict(row) for row in rows]
        concepts = _position_concepts(conn, [item['id'] for item in items])
        for item in items:
            item['learned'] = bool(item['learned'])
            item['concepts'] = concepts.get(item['id'], [])
            item['primary_concept'] = next(
                (concept for concept in item['concepts'] if concept['is_primary']),
                item['concepts'][0] if item['concepts'] else None,
            )

    return jsonify({
        'items': items,
        'summary': {
            'total': total,
            'learned': learned,
            'unlearned': max(0, total - learned),
            'percent_learned': round((learned / total) * 100) if total else 0,
            'average_rating': average_rating,
        },
        'pagination': {
            'page': page,
            'per_page': per_page,
            'pages': pages,
            'filtered_total': filtered_total,
            'has_previous': page > 1,
            'has_next': page < pages,
        },
        'filters': {
            'status': status_filter, 'learning_mode': learning_mode, 'sort': sort_key,
            'rating_min': rating_min, 'rating_max': rating_max,
        },
        'trainable_total': trainable_total,
        **({'selection_items': selection_items} if selection_items is not None else {}),
    })


@app.post('/api/jobs/<int:job_id>/positions/status')
def bulk_position_status(job_id):
    """Bulk-update learned state while preserving account-wide duplicate consistency."""
    payload = request.get_json(force=True)
    raw_ids = payload.get('position_ids') or []
    learned = 1 if payload.get('learned') else 0
    try:
        position_ids = sorted({int(value) for value in raw_ids})
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid position ids'}), 400
    if not position_ids:
        return jsonify({'error': 'Select at least one position'}), 400

    placeholders = ','.join('?' for _ in position_ids)
    with connect() as conn:
        rows = conn.execute(f'''
            SELECT tp.id, tp.job_id, tp.game_id, tp.fen, tp.played_move_uci, tp.best_move_uci, tp.opening_key, j.account_id
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.job_id = ? AND tp.id IN ({placeholders})
        ''', (job_id, *position_ids)).fetchall()
        if not rows:
            return jsonify({'error': 'No matching positions found'}), 404

        for row in rows:
            _set_account_position_learned(conn, row['account_id'], row, bool(learned))
        conn.commit()
    return jsonify({'ok': True, 'learned': bool(learned), 'updated_positions': len(rows)})


@app.post('/api/jobs/<int:job_id>/positions/status-batch')
def batch_position_status(job_id):
    """Atomically save mixed learned/unlearned edits from a lesson detail page."""
    payload = request.get_json(force=True)
    raw_updates = payload.get('updates') or []
    if not isinstance(raw_updates, list) or not raw_updates:
        return jsonify({'error': 'No learning-status changes supplied'}), 400

    updates = {}
    try:
        for item in raw_updates:
            position_id = int(item.get('position_id'))
            updates[position_id] = bool(item.get('learned'))
    except (TypeError, ValueError, AttributeError):
        return jsonify({'error': 'Invalid learning-status changes'}), 400

    position_ids = sorted(updates)
    if len(position_ids) > 20000:
        return jsonify({'error': 'Too many position changes in one save'}), 400
    with connect() as conn:
        rows = []
        # Chunk SQL IN queries so select-all works with older SQLite builds.
        for start in range(0, len(position_ids), 450):
            chunk = position_ids[start:start + 450]
            placeholders = ','.join('?' for _ in chunk)
            rows.extend(conn.execute(f'''
                SELECT tp.id, tp.job_id, tp.game_id, tp.fen, tp.played_move_uci, tp.best_move_uci, j.account_id
                FROM training_positions tp
                JOIN analysis_jobs j ON j.id = tp.job_id
                WHERE tp.job_id = ? AND tp.id IN ({placeholders})
            ''', (job_id, *chunk)).fetchall())
        if len(rows) != len(position_ids):
            return jsonify({'error': 'One or more positions were not found'}), 404

        for row in rows:
            _set_account_position_learned(conn, row['account_id'], row, updates[int(row['id'])])
        conn.commit()
    return jsonify({'ok': True, 'updated_positions': len(rows)})


@app.post('/api/jobs/<int:job_id>/lessons/<concept_key>/reset')
def reset_lesson(job_id, concept_key):
    """Mark every position in a lesson unsolved while preserving analysis data."""
    with connect() as conn:
        job = conn.execute(
            'SELECT account_id FROM analysis_jobs WHERE id = ?',
            (job_id,),
        ).fetchone()
        if job is None:
            return jsonify({'error': 'Job not found'}), 404

        targets = conn.execute("""
            SELECT DISTINCT tp.id, tp.job_id, tp.game_id, tp.fen, tp.played_move_uci, tp.best_move_uci
            FROM training_positions tp
            JOIN position_concepts pc ON pc.position_id = tp.id
            WHERE tp.job_id = ? AND pc.concept_key = ? AND pc.is_primary = 1
        """, (job_id, concept_key)).fetchall()

        if not targets:
            return jsonify({'error': 'Lesson not found'}), 404

        for target in targets:
            _set_account_position_learned(conn, job['account_id'], target, False)
        conn.commit()

    return jsonify({'ok': True, 'reset_positions': len(targets)})


def _original_game_share_data(position_id):
    """Read original game data (not the transient Stockfish analysis branch).

    Older imports can have PGN only in analyzed_games, or metadata only in
    training_positions. Keep these existing databases usable without imports.
    """
    with connect() as conn:
        row = conn.execute("""
            SELECT tp.id, tp.game_id, tp.site, tp.game_pgn, j.account_id
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        """, (position_id,)).fetchone()
        if row is None:
            return None
        pgn = row['game_pgn'] or ''
        site = row['site'] or ''
        if row['game_id'] and (not pgn or not site):
            cached = conn.execute("""
                SELECT game_pgn, site FROM analyzed_games
                WHERE account_id = ? AND game_id = ?
            """, (row['account_id'], row['game_id'])).fetchone()
            if cached:
                pgn = pgn or cached['game_pgn'] or ''
                site = site or cached['site'] or ''
    pgn = normalize_pgn(pgn)
    return {
        'pgn': pgn,
        'lichess_url': lichess_game_url(site, pgn),
        'filename': game_pgn_filename(row['game_id']),
    }


@app.get('/api/positions/<int:position_id>/share')
def position_share(position_id):
    data = _original_game_share_data(position_id)
    if data is None:
        return jsonify({'error': 'Position not found'}), 404
    response = jsonify({
        'pgn': data['pgn'] if data['pgn'] else None,
        'lichess_url': data['lichess_url'],
        'download_url': url_for('download_position_pgn', position_id=position_id) if data['pgn'] else None,
        'filename': data['filename'] if data['pgn'] else None,
    })
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/positions/<int:position_id>/pgn')
def download_position_pgn(position_id):
    data = _original_game_share_data(position_id)
    if data is None:
        return jsonify({'error': 'Position not found'}), 404
    if not data['pgn']:
        return jsonify({'error': 'Original PGN is unavailable for this older position'}), 404
    response = send_file(
        io.BytesIO(data['pgn'].encode('utf-8')),
        mimetype='application/x-chess-pgn',
        as_attachment=True,
        download_name=data['filename'],
    )
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/positions/<int:position_id>/game-context')
def game_context(position_id):
    with connect() as conn:
        row = conn.execute('''
            SELECT id, fen, game_pgn, mistake_ply, previous_fen,
                   opponent_move_uci, opponent_move_san, user_color
            FROM training_positions WHERE id = ?
        ''', (position_id,)).fetchone()

    if row is None:
        return jsonify({'error': 'Position not found'}), 404

    target_board = chess.Board(row['fen'])
    legal_moves = [move.uci() for move in target_board.legal_moves]

    if not row['game_pgn'] or not row['mistake_ply']:
        return jsonify({
            'available': False,
            'target_fen': row['fen'],
            'legal_moves': legal_moves,
            'moves': [],
        })

    game = chess.pgn.read_game(io.StringIO(row['game_pgn']))
    if game is None:
        return jsonify({'available': False, 'target_fen': row['fen'], 'legal_moves': legal_moves, 'moves': []})

    board = game.board()
    initial_fen = board.fen()
    target_history_ply = max(0, int(row['mistake_ply']) - 1)
    moves = []

    for ply, move in enumerate(game.mainline_moves(), start=1):
        if ply > target_history_ply:
            break
        color = 'white' if board.turn == chess.WHITE else 'black'
        move_number = board.fullmove_number
        san = board.san(move)
        fen_before = board.fen()
        uci = move.uci()
        board.push(move)
        moves.append({
            'ply': ply,
            'move_number': move_number,
            'color': color,
            'san': san,
            'uci': uci,
            'fen_before': fen_before,
            'fen_after': board.fen(),
        })

    return jsonify({
        'available': True,
        'initial_fen': initial_fen,
        'target_fen': row['fen'],
        'legal_moves': legal_moves,
        'target_history_ply': target_history_ply,
        'moves': moves,
    })


@app.post('/api/positions/<int:position_id>/attempt')
def attempt(position_id):
    payload = request.get_json(force=True)
    requested_move = str(payload.get('move', '')).lower().strip()

    with connect() as conn:
        row = conn.execute("""
            SELECT tp.*, j.account_id
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        """, (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        try:
            evaluation_run_id=int(payload.get('evaluation_run_id') or 0)
        except (TypeError,ValueError):
            return jsonify({'error':'Invalid evaluation run'}),400
        evaluation_item=None
        if evaluation_run_id:
            evaluation_item=run_position(conn,evaluation_run_id,position_id,row['job_id'])
            if evaluation_item is None:
                return jsonify({'error':'Position not in evaluation run'}),404
            if row['coaching_version']!=evaluation_item['coaching_version']:
                return jsonify({'error':'This evaluation requires its original coaching model; start a current-version evaluation.'}),409
            if evaluation_item['status']=='solved':
                return jsonify({'error':'Already solved in this evaluation run'}),409

        board = chess.Board(row['fen'])
        legal_moves = list(board.legal_moves)
        resolved = None

        try:
            candidate = chess.Move.from_uci(requested_move)
            if candidate in legal_moves:
                resolved = candidate
        except ValueError:
            candidate = None

        # A browser drag supplies from/to squares. For promotions, prefer a queen
        # unless only another legal promotion exists.
        if resolved is None and len(requested_move) == 4:
            promotion_moves = [m for m in legal_moves if m.uci().startswith(requested_move)]
            if promotion_moves:
                resolved = next((m for m in promotion_moves if m.promotion == chess.QUEEN), promotion_moves[0])

        if resolved is None:
            return jsonify({
                'legal': False,
                'correct': False,
                'learned': bool(row['learned']),
            }), 400

        attempted_uci = resolved.uci()
        attempted_san = board.san(resolved)
        puzzle_settings = get_settings(conn)
        best = row['best_move_uci'].lower()
        correct = attempted_uci == best
        accepted_alternative = False
        move_eval_cp = None
        move_mate = None
        best_gap_cp = None
        improvement_cp = None
        review_quality = None

        # If the player found a different legal move, judge the quality of that
        # move rather than automatically failing it.  Exact-best remains free
        # and instant; alternatives get a short Stockfish verification.
        if not correct:
            # The actual game move was already evaluated during Positions.
            # Its saved score and PV are authoritative for this puzzle; avoid
            # launching an identical Stockfish search in the Training UI.
            quality = None
            if (attempted_uci == row['played_move_uci']
                    and row['eval_after_cp'] is not None):
                cached_reply = None
                # played_pv_uci was analyzed *after* the user's game move,
                # so its first UCI move is already the opponent's reply.
                saved_pv = str(row['played_pv_uci'] or '').split()
                if saved_pv:
                    next_board = board.copy(stack=False)
                    next_board.push(resolved)
                    try:
                        reply = chess.Move.from_uci(saved_pv[0])
                        if reply in next_board.legal_moves:
                            cached_reply = next_board.san(reply)
                    except ValueError:
                        pass
                quality = {'eval_cp': int(row['eval_after_cp']),
                           'mate': row['mate_after'], 'best_reply_san': cached_reply,
                           'pv_uci': [attempted_uci] + saved_pv}
            if quality is None:
                try:
                    quality = evaluate_move_quality(
                        row['fen'],
                        attempted_uci,
                        chess.BLACK if row['user_color'] == 'black' else chess.WHITE,
                    )
                except (FileNotFoundError, chess.engine.EngineError, RuntimeError, ValueError) as exc:
                    return jsonify({'error': f'Could not verify move quality: {exc}'}), 503

            review_quality = quality
            move_eval_cp = quality['eval_cp']
            move_mate = quality['mate']
            best_cp = row['eval_before_cp']
            played_cp = row['eval_after_cp']

            if row['mate_before'] is not None and row['mate_before'] > 0:
                # In a forced-mate lesson, any move that preserves a forced mate
                # is pedagogically equivalent enough to count as a success.
                correct = move_mate is not None and move_mate > 0
            elif best_cp is not None:
                best_gap_cp = max(0, int(best_cp) - int(move_eval_cp))
                if played_cp is not None:
                    improvement_cp = int(move_eval_cp) - int(played_cp)
                close_to_best = best_gap_cp <= int(puzzle_settings['near_optimal_cp'])
                materially_better = (
                    improvement_cp is None
                    or improvement_cp >= int(puzzle_settings['min_improvement_over_game_cp'])
                )
                correct = close_to_best and materially_better

            accepted_alternative = bool(correct)

        board.push(resolved)
        attempted_fen = board.fen()

        # Append player-learning evidence only for genuine legal training moves.
        # The old per-position counters are retained for backward compatibility.
        # Already-learned positions can be reviewed in Analysis mode without
        # creating another learning session.
        learning_event = None
        if not evaluation_run_id and not row['learned'] and (payload.get('track_learning', True) is False
                                   or payload.get('start_new_learning_session') is True):
            abandon_player_session(conn, position_id)
        if not evaluation_run_id and not row['learned'] and payload.get('track_learning', True) is not False:
            learning_event = record_player_attempt(
                conn, row, move_uci=attempted_uci, correct=correct,
                elapsed_seconds=payload.get('active_seconds_delta'),
                lesson_key=payload.get('lesson_key'),
                opening_key=payload.get('opening_key'),
                max_solve_seconds=puzzle_settings['max_puzzle_solve_seconds'],
            )

        # Independent of optional Player statistics. This lightweight local
        # evidence log enables a post-solve recap; no additional engine search.
        record_board_attempt(
            conn, row, session_key=payload.get('coach_session_key'),
            move_uci=attempted_uci, move_san=attempted_san,
            correct=correct, quality=review_quality,
        )

        if evaluation_run_id:
            record_evaluation_attempt(conn,evaluation_run_id,position_id,correct,attempted_uci)
        if correct and not evaluation_run_id:
            conn.execute("""
                UPDATE training_positions
                SET attempts = attempts + 1,
                    correct_attempts = correct_attempts + 1,
                    learned = 1
                WHERE id = ?
            """, (position_id,))

            # Learned state is curriculum-level. Exact duplicate puzzle states
            # across source games/jobs are retired together so progress accumulates.
            _set_account_position_learned(conn, row['account_id'], row, True)
            _set_opening_position_group_learned(conn, row, str(payload.get('opening_key') or '').strip(), True)
        elif not evaluation_run_id:
            conn.execute(
                'UPDATE training_positions SET attempts = attempts + 1 WHERE id = ?',
                (position_id,),
            )
        conn.commit()

        if not correct:
            return jsonify({
                'legal': True,
                'correct': False,
                'learned': False,
                'attempted_move_uci': attempted_uci,
                'attempted_move_san': attempted_san,
                'attempted_fen': attempted_fen,
                'move_eval_cp': move_eval_cp,
                'move_mate': move_mate,
                'best_gap_cp': best_gap_cp,
                'improvement_cp': improvement_cp,
            })

        concepts = _position_concepts(conn, [position_id]).get(position_id, [])
        accepted_move_explanation = None
        if accepted_alternative:
            try:
                _, accepted_move_explanation = generate_coaching_text(
                    fen=row['fen'],
                    previous_fen=row['previous_fen'],
                    opponent_move_uci=row['opponent_move_uci'],
                    opponent_move_san=row['opponent_move_san'],
                    played_move_uci=row['played_move_uci'],
                    played_move_san=row['played_move_san'],
                    best_move_uci=attempted_uci,
                    best_move_san=attempted_san,
                    category=row['category'],
                    labels=concepts,
                    mate_before=row['mate_before'],
                )
            except Exception:
                accepted_move_explanation = (
                    f'{attempted_san} is accepted as a near-optimal alternative. '
                    f'The engine still prefers {row["best_move_san"] or row["best_move_uci"]}; '
                    'use the yellow and green highlights to compare the two ideas.'
                )

        return jsonify({
            'legal': True,
            'correct': True,
            'learned': True,
            'attempted_move_uci': attempted_uci,
            'attempted_move_san': attempted_san,
            'attempted_fen': attempted_fen,
            'accepted_alternative': accepted_alternative,
            'move_eval_cp': move_eval_cp,
            'move_mate': move_mate,
            'best_gap_cp': best_gap_cp,
            'improvement_cp': improvement_cp,
            'best_move_uci': row['best_move_uci'],
            'best_move_san': row['best_move_san'],
            'played_move_san': row['played_move_san'],
            'eval_before_cp': row['eval_before_cp'],
            'eval_after_cp': row['eval_after_cp'],
            'mate_before': row['mate_before'],
            'mate_after': row['mate_after'],
            'centipawn_loss': row['centipawn_loss'],
            'difficulty_score': row['difficulty_score'],
            'estimated_rating': row['estimated_rating'],
            'concepts': concepts,
            'taxonomy': _position_taxonomies(conn, [position_id]).get(position_id),
            'coach_explanation': row['coach_explanation'],
            'accepted_move_explanation': accepted_move_explanation,
        })


@app.post('/api/positions/<int:position_id>/player/clock-out')
def clock_out_player_session(position_id):
    """End the current tracked attempt cycle without changing puzzle progress.

    A user may continue solving with tracking off; that play still updates
    the standard learned/attempt counters, but never enters Player reports.
    """
    with connect() as conn:
        row = conn.execute('SELECT id FROM training_positions WHERE id=?', (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        abandon_player_session(conn, position_id)
        conn.commit()
    return jsonify({'ok': True})


@app.post('/api/positions/<int:position_id>/reset')
def reset_training_position(position_id):
    payload = request.get_json(silent=True) or {}
    with connect() as conn:
        row = conn.execute('''
            SELECT tp.id, tp.job_id, tp.game_id, tp.fen, tp.played_move_uci, tp.best_move_uci, tp.opening_key, j.account_id
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        ''', (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404

        abandon_player_session(conn, position_id)
        _set_account_position_learned(conn, row['account_id'], row, False)
        _set_opening_position_group_learned(conn, row, str(payload.get('opening_key') or '').strip(), False)
        conn.commit()
    return jsonify({'ok': True, 'learned': False})


def _enrich_saved_variations(position_id):
    """Lazily add engine continuations for older already-solved puzzles.

    No game reimport is needed. If Stockfish cannot run, the original
    board-grounded coaching text is still returned.
    """
    with connect() as conn:
        row = conn.execute('SELECT * FROM training_positions WHERE id = ?', (position_id,)).fetchone()
    if row is None or not row['learned'] or (row['best_pv_uci'] and row['played_pv_uci']):
        return
    pov = chess.BLACK if row['user_color'] == 'black' else chess.WHITE
    updates = {}
    try:
        if not row['best_pv_uci']:
            best = evaluate_move_quality(row['fen'], row['best_move_uci'], pov)
            if best.get('pv_uci'):
                updates['best_pv_uci'] = json.dumps(best['pv_uci'][:12])
        if not row['played_pv_uci']:
            if row['played_move_uci'] == row['best_move_uci'] and (updates.get('best_pv_uci') or row['best_pv_uci']):
                updates['played_pv_uci'] = updates.get('best_pv_uci') or row['best_pv_uci']
            else:
                played = evaluate_move_quality(row['fen'], row['played_move_uci'], pov)
                if played.get('pv_uci'):
                    updates['played_pv_uci'] = json.dumps(played['pv_uci'][:12])
    except (FileNotFoundError, chess.engine.EngineError, RuntimeError, ValueError, OSError):
        pass
    if not updates:
        return
    with connect() as conn:
        conn.execute('''UPDATE training_positions
                        SET best_pv_uci = COALESCE(best_pv_uci, ?),
                            played_pv_uci = COALESCE(played_pv_uci, ?)
                        WHERE id = ?''',
                     (updates.get('best_pv_uci'), updates.get('played_pv_uci'), position_id))
        refreshed = conn.execute('SELECT * FROM training_positions WHERE id = ?', (position_id,)).fetchone()
        _refresh_position_labels(conn, position_id, refreshed, regenerate_copy=False)
        conn.commit()


@app.post('/api/jobs/<int:job_id>/refresh-metadata')
def refresh_job_metadata(job_id):
    """Legacy endpoint: redirect clients to the serialized process scheduler."""
    return jsonify({'error':'Use Refresh on the Process page for asynchronous metadata rebuilds.',
                    'process_url':url_for('processes',job_id=job_id)}), 410


@app.get('/api/jobs/<int:job_id>/motif-enrichment')
def motif_enrichment_status(job_id):
    """Show missing PV coverage without triggering a full game reanalysis."""
    with connect() as conn:
        job = conn.execute('SELECT id FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404
        total = conn.execute('SELECT COUNT(*) AS n FROM training_positions WHERE job_id = ?', (job_id,)).fetchone()['n']
        missing = conn.execute('''
            SELECT COUNT(*) AS n FROM training_positions
            WHERE job_id = ? AND (best_pv_uci IS NULL OR played_pv_uci IS NULL)
        ''', (job_id,)).fetchone()['n']
    return jsonify({'total': total, 'remaining': missing, 'enriched': total - missing})


@app.post('/api/jobs/<int:job_id>/motif-enrichment')
def enrich_job_motifs(job_id):
    """Analyze missing PVs in small batches, then rebuild lesson ownership.

    Existing evaluations, imports, position IDs, attempts and learned status
    stay unchanged. The browser requests subsequent batches explicitly.
    """
    payload = request.get_json(silent=True) or {}
    try:
        batch_size = max(1, min(3, int(payload.get('batch_size', 2))))
    except (TypeError, ValueError):
        batch_size = 2
    with connect() as conn:
        job = conn.execute('SELECT status FROM analysis_jobs WHERE id = ?', (job_id,)).fetchone()
        if job is None:
            return jsonify({'error': 'Game list not found'}), 404
        if job['status'] in ('running', 'retrieving'):
            return jsonify({'error': 'Pause the ongoing game evaluation before enriching lesson motifs.'}), 409
        positions = conn.execute('''
            SELECT id, fen, best_move_uci, played_move_uci, user_color,
                   best_pv_uci, played_pv_uci
            FROM training_positions
            WHERE job_id = ? AND (best_pv_uci IS NULL OR played_pv_uci IS NULL)
            ORDER BY id ASC LIMIT ?
        ''', (job_id, batch_size)).fetchall()

    updated = 0
    for row in positions:
        pov = chess.WHITE if row['user_color'] == 'white' else chess.BLACK
        best_raw = row['best_pv_uci']
        played_raw = row['played_pv_uci']
        try:
            if not best_raw:
                result = evaluate_move_quality(row['fen'], row['best_move_uci'], pov)
                if not result.get('pv_uci'):
                    raise RuntimeError('Stockfish returned no best-move continuation')
                best_raw = json.dumps(result['pv_uci'][:12])
            if not played_raw:
                if row['played_move_uci'] == row['best_move_uci']:
                    played_raw = best_raw
                else:
                    result = evaluate_move_quality(row['fen'], row['played_move_uci'], pov)
                    if not result.get('pv_uci'):
                        raise RuntimeError('Stockfish returned no game-move continuation')
                    played_raw = json.dumps(result['pv_uci'][:12])
        except (FileNotFoundError, chess.engine.EngineError, RuntimeError, ValueError, OSError) as exc:
            return jsonify({'error': f'Engine enrichment stopped: {exc}', 'updated': updated}), 503
        with connect() as conn:
            conn.execute('''
                UPDATE training_positions SET best_pv_uci = ?, played_pv_uci = ?
                WHERE id = ?
            ''', (best_raw, played_raw, row['id']))
            refreshed = conn.execute('SELECT * FROM training_positions WHERE id = ?', (row['id'],)).fetchone()
            _refresh_position_labels(conn, row['id'], refreshed, regenerate_copy=False)
            conn.commit()
        updated += 1

    status_response = motif_enrichment_status(job_id)
    info = status_response.get_json()
    return jsonify({**info, 'updated': updated})


@app.get('/player')
def player_view():
    """Learning outcomes and attempt history; separate from coaching quality."""
    return render_template('player.html')


@app.get('/api/player/summary')
def player_report():
    with connect() as conn:
        data = player_summary(conn, request.args)
        data['facets'] = player_facets(conn)
    return jsonify(data)


@app.get('/api/player/<string:kind>.csv')
def player_csv(kind):
    if kind not in ('sessions', 'attempts'):
        return jsonify({'error': 'Unknown Player export'}), 404
    with connect() as conn:
        rows = player_export_rows(conn, request.args, kind=kind)
    return send_file(io.BytesIO(player_csv_data(rows, kind=kind)),
                     mimetype='text/csv; charset=utf-8',
                     as_attachment=True, download_name=f'chess_player_{kind}.csv')


@app.post('/api/player/records/reset')
def player_reset_records():
    """Delete Player activity history only, optionally for one game list."""
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'RESET PLAYER':
        return jsonify({'error': 'Explicit RESET PLAYER confirmation is required.'}), 400
    raw_job = payload.get('job_id')
    try:
        job_id = int(raw_job) if raw_job not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid game list ID'}), 400
    if job_id is not None and job_id <= 0:
        return jsonify({'error': 'Invalid game list ID'}), 400
    with connect() as conn:
        if job_id is not None and not conn.execute(
            'SELECT 1 FROM analysis_jobs WHERE id=?', (job_id,)
        ).fetchone():
            return jsonify({'error': 'Game list not found'}), 404
        deleted = reset_player_records(conn, job_id)
        conn.commit()
    return jsonify({'ok': True, 'job_id': job_id, 'deleted': deleted})


@app.get('/coach')
def coach_view():
    """Coaching quality and feedback reporting, separate from Process."""
    return render_template('analytics.html')


@app.get('/analytics')
def analytics():
    """Preserve old bookmarks while making Coach the canonical view."""
    return redirect(url_for('coach_view'), code=302)


@app.get('/api/analytics/feedback')
def analytics_feedback():
    with connect() as conn:
        rows = report_rows(conn, request.args)
        facets = report_facets(conn)
        change_rates = taxonomy_change_rates(conn, request.args)
        charts = {
            'changes': coaching_metric_chart(conn, request.args, metric='changes',
                         group_by=request.args.get('chart_changes_group', 'motif')),
            'approval': coaching_metric_chart(conn, request.args, metric='approval',
                          group_by=request.args.get('chart_approval_group', 'feedback_area')),
        }
    # Historical motif thumbs remain in CSV and regression evidence, not the UI.
    visible_rows = [r for r in rows if r['feedback_type'] != 'motif']
    summary = report_summary(visible_rows)
    # Full evidence belongs in CSV. Avoid sending large JSON PV/critical
    # event blobs to the dashboard for each item on every filter change.
    recent_fields = ('feedback_type', 'rating', 'username', 'date_range',
                     'job_id', 'position_id', 'message_id', 'continuation_key', 'lesson_name',
                     'primary_motif_name', 'opening_name', 'opening_eco',
                     'selected_taxonomy_name', 'selected_taxonomy_key', 'content_snapshot',
                     'learning_mode', 'move_number', 'updated_at')
    return jsonify({**summary, 'facets': facets, 'taxonomy_change_rates': change_rates, 'charts': charts,
                    'recent': [{**{k: row.get(k) for k in recent_fields},
                                'current_taxonomy_change_status': current_taxonomy_status(row)}
                               for row in visible_rows[:80]]})


@app.get('/api/coach/taxonomy.csv')
def coach_taxonomy_csv():
    """Every solved position and its current per-field change status."""
    with connect() as conn:
        rows = solved_taxonomy_rows(conn, request.args)
    return send_file(
        io.BytesIO(solved_taxonomy_csv(rows)), mimetype='text/csv; charset=utf-8',
        as_attachment=True, download_name='chess_coaching_taxonomy.csv',
    )


@app.get('/api/analytics/feedback/history')
def feedback_history_events():
    """Immutable event history for one position, including vote withdrawals."""
    position = request.args.get('position_id', type=int)
    if not position:
        return jsonify({'error':'position_id required'}),400
    with connect() as conn:
        if not conn.execute('SELECT 1 FROM training_positions WHERE id=?',(position,)).fetchone():
            return jsonify({'error':'Position not found'}),404
        records = conn.execute('''SELECT e.id,e.created_at,e.feedback_type,e.rating,e.coaching_version,
            e.classifier_version,e.taxonomy_version,e.lesson_key,e.content_snapshot,
            e.suggested_text,e.suggested_motif_key,e.model_key,e.selected_key,
            e.source_message_id,e.position_key,e.continuation_id,fc.move_key AS continuation_key
          FROM feedback_events e JOIN feedback_position_sources fps ON fps.position_key=e.position_key
          LEFT JOIN feedback_continuations fc ON fc.continuation_id=e.continuation_id
          WHERE fps.position_id=? ORDER BY e.id''',(position,)).fetchall()
    return jsonify({'events':[dict(r) for r in records]})


@app.get('/api/analytics/feedback.csv')
def analytics_feedback_csv():
    with connect() as conn:
        rows = report_rows(conn, {**request.args.to_dict(), 'history': 'all'})
    return send_file(
        io.BytesIO(csv_bytes(rows)), mimetype='text/csv; charset=utf-8',
        as_attachment=True, download_name='chess_coaching_feedback.csv',
    )


@app.get('/api/coach/regression.csv')
def coach_regression_csv():
    """User-corrected downvotes, ready for human review and regression fixtures."""
    with connect() as conn:
        rows = regression_candidate_rows(report_rows(conn, request.args))
    return send_file(
        io.BytesIO(csv_bytes(rows)), mimetype='text/csv; charset=utf-8',
        as_attachment=True, download_name='chess_regression_candidates.csv',
    )


@app.post('/api/coach/feedback/reset')
def coach_reset_feedback():
    """Clear saved thumbs ratings without affecting positions or analysis."""
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'RESET FEEDBACK':
        return jsonify({'error': 'Explicit RESET FEEDBACK confirmation is required.'}), 400
    raw_job = payload.get('job_id')
    try:
        job_id = int(raw_job) if raw_job not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid game list ID'}), 400
    with connect() as conn:
        if job_id is not None:
            if not conn.execute('SELECT 1 FROM analysis_jobs WHERE id=?', (job_id,)).fetchone():
                return jsonify({'error': 'Game list not found'}), 404
            positions = conn.execute('''DELETE FROM position_feedback
                WHERE position_id IN (SELECT id FROM training_positions WHERE job_id=?)''', (job_id,)).rowcount
            continuations = conn.execute('''DELETE FROM continuation_explanation_feedback
                WHERE position_id IN (SELECT id FROM training_positions WHERE job_id=?)''', (job_id,)).rowcount
            coaching = conn.execute('''DELETE FROM coach_message_feedback
                WHERE position_id IN (SELECT id FROM training_positions WHERE job_id=?)''', (job_id,)).rowcount
            taxonomy = conn.execute('''DELETE FROM position_taxonomy_feedback
                WHERE position_id IN (SELECT id FROM training_positions WHERE job_id=?)''', (job_id,)).rowcount
        else:
            positions = conn.execute('DELETE FROM position_feedback').rowcount
            continuations = conn.execute('DELETE FROM continuation_explanation_feedback').rowcount
            coaching = conn.execute('DELETE FROM coach_message_feedback').rowcount
            taxonomy = conn.execute('DELETE FROM position_taxonomy_feedback').rowcount
        if job_id is not None:
            events = conn.execute('''DELETE FROM feedback_events WHERE source_position_id IN
                (SELECT id FROM training_positions WHERE job_id=?)''',(job_id,)).rowcount
        else:
            events = conn.execute('DELETE FROM feedback_events').rowcount
        conn.commit()
    return jsonify({'ok': True, 'job_id': job_id,
                    'deleted': {'feedback_history_events': events,
                                'position_explanation_motif': positions,
                                'continuation_explanations': continuations,
                                'chat_coaching': coaching, 'taxonomy_selections': taxonomy}})


@app.route('/api/positions/<int:position_id>/feedback', methods=['GET', 'POST'])
def position_feedback(position_id):
    payload=request.get_json(silent=True) or {} if request.method=='POST' else {}
    requested_run=payload.get('evaluation_run_id') if request.method=='POST' else request.args.get('evaluation_run_id')
    try: run_id=int(requested_run) if requested_run else None
    except (TypeError,ValueError):return jsonify({'error':'Invalid evaluation run'}),400
    with connect() as conn:
        if run_id:
            state=run_position(conn,run_id,position_id)
            if not state or state['status']!='solved':
                return jsonify({'error':'Solve this evaluation position before rating'}),403
            position_model=conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',(position_id,)).fetchone()
            if not position_model or position_model['coaching_version']!=state['coaching_version']:
                return jsonify({'error':'Historical evaluation is read-only under a different current model'}),409
        if request.method == 'GET':
            if not conn.execute('SELECT 1 FROM training_positions WHERE id = ?', (position_id,)).fetchone():
                return jsonify({'error': 'Position not found'}), 404
            return jsonify({'ratings': position_votes(conn, position_id, run_id),
                            'corrections': position_feedback_details(conn, position_id, run_id),
                            'continuation_ratings': continuation_votes(conn, position_id, run_id),
                            'continuation_corrections': continuation_feedback_details(conn, position_id, run_id),
                            'motif_options': motif_feedback_options(conn, position_id),
                            'taxonomy_feedback': taxonomy_feedback_choices(conn, position_id, run_id)})
        category = str(payload.get('category') or '')
        if category in ('explanation', 'continuation'):
            version = conn.execute('SELECT coaching_version FROM training_positions WHERE id=?',
                                   (position_id,)).fetchone()
            if version and version['coaching_version'] != COACHING_VERSION:
                return jsonify({'error':'Refresh coaching before rating newly generated explanations.'}), 409
        try:
            rating = int(payload.get('rating'))
        except (ValueError, TypeError):
            return jsonify({'error': 'Rating must be -1, 0, or 1'}), 400
        try:
            if category == 'continuation':
                continuation_ratings = record_continuation_vote(
                    conn, position_id, payload.get('continuation_key'), rating,
                    lesson_key=payload.get('lesson_key') or '',
                    text=payload.get('content_snapshot') or '',
                    suggested_text=payload.get('suggested_text'),evaluation_run_id=run_id)
                return jsonify({'ok': True, 'ratings': position_votes(conn, position_id, run_id),
                                'corrections': position_feedback_details(conn, position_id, run_id),
                                'continuation_ratings': continuation_ratings,
                                'continuation_corrections': continuation_feedback_details(conn, position_id, run_id)})
            ratings = record_position_vote(
                conn, position_id, category, rating,
                lesson_key=payload.get('lesson_key') or '',
                text=payload.get('content_snapshot') or '',
                suggested_text=payload.get('suggested_text'),
                suggested_motif_key=payload.get('suggested_motif_key'), evaluation_run_id=run_id,
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
    with connect() as conn:
        details = position_feedback_details(conn, position_id, run_id)
    return jsonify({'ok': True, 'ratings': ratings, 'corrections': details})


@app.post('/api/positions/<int:position_id>/taxonomy-feedback')
def set_position_taxonomy_feedback(position_id):
    payload = request.get_json(silent=True) or {}
    try: run_id=int(payload.get('evaluation_run_id') or 0) or None
    except (TypeError,ValueError):return jsonify({'error':'Invalid evaluation run'}),400
    try:
        with connect() as conn:
            if run_id:
                state=run_position(conn,run_id,position_id)
                if not state or state['status']!='solved':
                    return jsonify({'error':'Solve this evaluation position before rating'}),403
            result = save_taxonomy_feedback(conn, position_id,
                payload.get('field'), payload.get('selected_key'),evaluation_run_id=run_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    return jsonify({'ok': True, 'taxonomy_feedback': result})


@app.get('/api/positions/<int:position_id>/solution')
def position_solution(position_id):
    run_id=request.args.get('evaluation_run_id',type=int)
    # The lazy PV-enrichment path can also rebuild coaching text. Do not let
    # it bypass an explicit coaching-cache clear before Coaching refresh.
    with connect() as check_conn:
        pending = check_conn.execute('''SELECT mp.status FROM training_positions tp
            LEFT JOIN metadata_processes mp ON mp.job_id=tp.job_id
            WHERE tp.id=?''', (position_id,)).fetchone()
    if not pending or pending['status'] != 'needs_refresh':
        _enrich_saved_variations(position_id)
    with connect() as conn:
        row = conn.execute('SELECT * FROM training_positions WHERE id = ?', (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        evaluation_solved=False
        if run_id:
            state=run_position(conn,run_id,position_id,row['job_id'])
            if state is None:return jsonify({'error':'Position not in evaluation run'}),404
            evaluation_solved=state['status']=='solved'
            if state['coaching_version']!=row['coaching_version']:
                return jsonify({'error':'This evaluation belongs to an earlier model; review its saved snapshot in Coach'}),409
        if (run_id and not evaluation_solved) or (not run_id and not row['learned']):
            return jsonify({'error': 'Solve the position before viewing the solution'}), 403
        concepts = _position_concepts(conn, [position_id]).get(position_id, [])
        taxonomy = _position_taxonomies(conn, [position_id]).get(position_id)

    return jsonify({
        'best_move_uci': row['best_move_uci'],
        'best_move_san': row['best_move_san'],
        'played_move_san': row['played_move_san'],
        'eval_before_cp': row['eval_before_cp'],
        'eval_after_cp': row['eval_after_cp'],
        'mate_before': row['mate_before'],
        'mate_after': row['mate_after'],
        'centipawn_loss': row['centipawn_loss'],
        'difficulty_score': row['difficulty_score'],
        'estimated_rating': row['estimated_rating'],
        'concepts': concepts,
        'taxonomy': taxonomy,
        'coach_explanation': row['coach_explanation'],
        'historical_match': row['historical_match'],
        'user_color': row['user_color'],
        'evaluation_perspective': 'user',
    })


@app.post('/api/positions/<int:position_id>/coach/solve-recap')
def position_solve_recap(position_id):
    """Publish cached post-solve coaching, idempotently, off the move path.

    This endpoint never invokes Stockfish and cannot reveal a solution to an
    unsolved position. Uncached lines retain the short evaluation returned by
    the existing attempt verifier, for a future bounded re-probe workflow.
    """
    payload = request.get_json(silent=True) or {}
    with connect() as conn:
        row = conn.execute('''SELECT tp.*, j.account_id FROM training_positions tp
            JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=?''', (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        eval_run_id=payload.get('evaluation_run_id')
        if eval_run_id:
            try: state=run_position(conn,int(eval_run_id),position_id,row['job_id'])
            except (TypeError,ValueError): state=None
            if not state or state['status']!='solved':
                return jsonify({'error':'Evaluation position has not been solved.'}),409
        if row['coaching_version'] != COACHING_VERSION:
            return jsonify({'error': 'Coaching cache needs a refresh before new explanation messages can be generated.'}), 409
        try:
            recap = save_solved_recap(conn, row, session_key=payload.get('session_key'),
                                      evaluation_solved=bool(eval_run_id))
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    return jsonify({'ok': True, 'message': recap})


@app.get('/api/positions/<int:position_id>/coach')
def position_coach_history(position_id):
    evaluation_run_id=request.args.get('run_id',type=int)
    with connect() as conn:
        row = conn.execute("""
            SELECT tp.*, j.account_id
            FROM training_positions tp JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        """, (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        state=run_position(conn,evaluation_run_id,position_id,row['job_id']) if evaluation_run_id else None
        if evaluation_run_id and state is None:
            return jsonify({'error':'Position not in evaluation run'}),404
        evaluation_solved=bool(state['status']=='solved') if state else bool(row['learned'])
        if row['learned'] and not evaluation_run_id:
            refresh_saved_recaps(conn, row)
        history = coach_history(conn, position_id, row['account_id'])
        # Old solved recaps stay in the database for historical audit/ratings,
        # but must never be displayed as the current coaching model's advice.
        def current_recap(message):
            try:
                payload = json.loads(message.get('structured_json') or '{}')
            except (TypeError, ValueError, AttributeError):
                return True
            return (payload.get('kind') != 'solved_attempt_recap'
                    or payload.get('coaching_version') == row['coaching_version'])
        history = [m for m in history if current_recap(m)]
        if evaluation_run_id:
            # Evaluate exclusively within this run. No old chat history,
            # previous model recap or previous evaluation solve is inherited.
            key_prefix=f'eval_{evaluation_run_id}_'
            scoped=[]
            if evaluation_solved:
                for message in history:
                    try: meta=json.loads(message.get('structured_json') or '{}')
                    except (TypeError,ValueError,AttributeError): continue
                    if (meta.get('kind')=='solved_attempt_recap'
                        and str(meta.get('session_key') or '').startswith(key_prefix)):
                        scoped.append(message)
            history=scoped
        elif not evaluation_solved:
            # Ordinary unsolved puzzles also suppress earlier solve recaps.
            def post_solve_only(message):
                try:
                    kind = json.loads(message.get('structured_json') or '{}').get('kind')
                except (TypeError, ValueError, AttributeError):
                    return False
                return kind in ('solved_attempt_recap', 'historical_reference',
                                'brilliant_reference')
            history = [m for m in history if not post_solve_only(m)]
    return jsonify({'messages': history})


@app.post('/api/positions/<int:position_id>/historical-coach')
def position_historical_coach(position_id):
    """Save one historic-coach message per (game list, historic game).

    Opening similarity is labeled as related, not as an exact position match.
    Multiple calls or revisits do not create duplicate coaching messages.
    """
    payload = request.get_json(silent=True) or {}
    with connect() as conn:
        row = conn.execute('''SELECT tp.id, tp.job_id, tp.learned, tp.opening_name,
                tp.historical_match, j.account_id
            FROM training_positions tp JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?''', (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        if not row['learned']:
            return jsonify({'shown': False, 'reason': 'unsolved'})
        match = None
        try:
            saved = json.loads(row['historical_match'] or 'null')
            if isinstance(saved, dict) and saved.get('match_type') == 'exact_position':
                match = saved
        except (ValueError, TypeError):
            pass
        # Only mention related openings from opening-specific playlists.
        if not match and payload.get('opening_playlist') is True:
            references = famous_for_opening(row['opening_name'] or '')
            if references:
                match = dict(references[0], match_type='related_opening')
        if not match:
            return jsonify({'shown': False, 'reason': 'no-reference'})
        classic = next((c for c in CLASSICS if c['key'] == match.get('key')), None)
        if not classic:
            return jsonify({'shown': False, 'reason': 'unrecognized-reference'})
        seen = conn.execute('''SELECT message_id FROM coach_proactive_history
            WHERE job_id = ? AND classic_key = ?''', (row['job_id'], classic['key'])).fetchone()
        if seen:
            return jsonify({'shown': False, 'reason': 'already-shared'})
        exact = match['match_type'] == 'exact_position'
        if exact:
            content = (f"Chess history connection: this position appeared in "
                f"{classic['title']} ({classic['year']}), played by {classic['players']}. "
                f"{classic['lesson']} Want to explore how the game continued?")
        else:
            content = (f"Opening connection: {classic['players']} played {classic['title']} "
                f"({classic['year']}) in this opening family. {classic['lesson']} "
                f"This is a related opening, not necessarily the same board position.")
        reference = {'title': classic['title'], 'source_url': classic['source_url'],
                     'match_type': match['match_type']}
        thread_id = get_or_create_thread(conn, position_id, row['account_id'])
        cursor = conn.execute('''INSERT INTO coach_messages
            (thread_id, role, content, structured_json) VALUES (?, 'assistant', ?, ?)''',
            (thread_id, content, json.dumps({'kind': 'historical_reference',
                                             'historical_reference': reference})))
        try:
            conn.execute('''INSERT INTO coach_proactive_history
                (job_id, classic_key, position_id, message_id) VALUES (?,?,?,?)''',
                (row['job_id'], classic['key'], position_id, cursor.lastrowid))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return jsonify({'shown': False, 'reason': 'already-shared'})
        return jsonify({'shown': True, 'message_id': cursor.lastrowid,
                        'content': content, 'reference': reference})


@app.post('/api/positions/<int:position_id>/brilliant-coach')
def position_brilliant_coach(position_id):
    """Offer a relevant creative move from the user's saved games, after solving.

    Brilliant is an analysis label, not necessarily a PGN double-exclamation.
    """
    with connect() as conn:
        current = conn.execute('''SELECT tp.id, tp.job_id, tp.game_id, tp.learned,
                j.account_id FROM training_positions tp
                JOIN analysis_jobs j ON j.id=tp.job_id WHERE tp.id=?''',
                (position_id,)).fetchone()
        if not current:
            return jsonify({'shown': False, 'reason': 'not-found'}), 404
        if not current['learned']:
            return jsonify({'shown': False, 'reason': 'unsolved'})
        count = conn.execute('SELECT COUNT(*) FROM coach_proactive_spotlights WHERE job_id=?',
                             (current['job_id'],)).fetchone()[0]
        if count >= 3:
            return jsonify({'shown': False, 'reason': 'spotlight-limit'})
        row = conn.execute('''
            SELECT tp.id, tp.played_move_san, tp.opponent, tp.opening_name,
                lc.name AS motif_name, tp.game_date,
                CASE WHEN pc_current.concept_key IS NOT NULL THEN 1 ELSE 0 END AS motif_match
            FROM training_positions tp
            LEFT JOIN position_concepts pc ON pc.position_id=tp.id AND pc.is_primary=1
            LEFT JOIN learning_concepts lc ON lc.key=pc.concept_key
            LEFT JOIN position_concepts pc_current
                ON pc_current.position_id=? AND pc_current.is_primary=1
                    AND pc_current.concept_key=pc.concept_key
            WHERE tp.job_id=? AND tp.id != ?
                AND tp.game_id IS NOT NULL AND tp.game_id != COALESCE(?, '')
                AND (tp.learning_mode='brilliant' OR tp.category='brilliant_move')
                AND tp.played_move_uci IS NOT NULL AND tp.played_move_san IS NOT NULL
                AND tp.centipawn_loss BETWEEN 0 AND 45
                AND NOT EXISTS (SELECT 1 FROM coach_proactive_spotlights s
                                WHERE s.job_id=tp.job_id AND s.recommended_position_id=tp.id)
            ORDER BY motif_match DESC, tp.centipawn_loss ASC, tp.id ASC LIMIT 1''',
            (position_id, current['job_id'], position_id, current['game_id'])).fetchone()
        if row is None:
            return jsonify({'shown': False, 'reason': 'no-relevant-move'})
        motif = (f" It connects with {row['motif_name'].lower()}." if row['motif_match'] and row['motif_name'] else '')
        opponent = f" against {row['opponent']}" if row['opponent'] else ''
        opening = f" in the {row['opening_name']}" if row['opening_name'] else ''
        content = (f"A strong move from your own games: you played {row['played_move_san']}"
                   f"{opening}{opponent}.{motif} Review that position and see why its continuation works.")
        reference = {'title': f"Review {row['played_move_san']}",
                     'url': url_for('trainer', job_id=current['job_id'], position=row['id']),
                     'position_id': row['id']}
        thread_id = get_or_create_thread(conn, position_id, current['account_id'])
        try:
            cursor = conn.execute('INSERT INTO coach_messages(thread_id, role, content, structured_json) VALUES (?,?,?,?)',
                                  (thread_id, 'assistant', content,
                                   json.dumps({'kind':'brilliant_reference', 'brilliant_reference':reference})))
            conn.execute('INSERT INTO coach_proactive_spotlights(job_id, recommended_position_id, at_position_id, message_id) VALUES (?,?,?,?)',
                         (current['job_id'], row['id'], position_id, cursor.lastrowid))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return jsonify({'shown': False, 'reason': 'already-shared'})
        return jsonify({'shown': True, 'content': content, 'reference':reference,
                        'message_id':cursor.lastrowid})


@app.post('/api/positions/<int:position_id>/coach')
def position_coach_message(position_id):
    payload = request.get_json(force=True)
    dialogue_context = payload.get('dialogue_context')
    if not isinstance(dialogue_context, dict):
        dialogue_context = {}
    text = str(payload.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Message is required'}), 400
    if len(text) > 2000:
        return jsonify({'error': 'Message is too long'}), 400

    with connect() as conn:
        row = conn.execute("""
            SELECT tp.*, j.account_id
            FROM training_positions tp JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        """, (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404
        if row['coaching_version'] != COACHING_VERSION:
            return jsonify({'error':'Coaching cache needs a refresh before Coach chat can be used.'}), 409
        try:
            result = handle_coach_message(
                conn, row, text, payload.get('fen'), dialogue_context
            )
        except Exception as exc:
            return jsonify({'error': f'Coach could not analyze that message: {exc}'}), 500
    return jsonify(result)


@app.post('/api/coach/messages/<int:message_id>/feedback')
def coach_message_feedback(message_id):
    payload = request.get_json(force=True)
    try:
        rating = int(payload.get('rating'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Rating must be -1, 0, or 1'}), 400
    if rating not in (-1, 0, 1):
        return jsonify({'error': 'Rating must be -1, 0, or 1'}), 400

    suggested_text = payload.get('suggested_text')
    if suggested_text is not None:
        if not isinstance(suggested_text, str) or len(suggested_text) > 6000:
            return jsonify({'error': 'Correction must be at most 6000 characters'}), 400
        suggested_text = suggested_text.strip()
    if rating == 1:
        suggested_text = None

    with connect() as conn:
        row = conn.execute('''
            SELECT cm.id, cm.role, ct.account_id, ct.position_id, tp.coaching_version
            FROM coach_messages cm
            JOIN coach_threads ct ON ct.id = cm.thread_id
            LEFT JOIN training_positions tp ON tp.id = ct.position_id
            WHERE cm.id = ?
        ''', (message_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Coach message not found'}), 404
        if row['role'] != 'assistant':
            return jsonify({'error': 'Only coach responses can be rated'}), 400
        snapshot = conn.execute('''SELECT cm.content,cm.structured_json,cm.thread_id,
            (SELECT q.content FROM coach_messages q WHERE q.thread_id=cm.thread_id
             AND q.role='user' AND q.id<cm.id ORDER BY q.id DESC LIMIT 1) AS question
            FROM coach_messages cm WHERE cm.id=?''', (message_id,)).fetchone()
        try:
            snapshot_metadata = json.loads(snapshot['structured_json'] or '{}')
        except (ValueError, TypeError):
            snapshot_metadata = {}
        if (snapshot_metadata.get('kind') == 'solved_attempt_recap'
                and snapshot_metadata.get('coaching_version') != row['coaching_version']):
            return jsonify({'error': 'This message belongs to an earlier coaching model. Refresh coaching to rate the current explanation.'}), 409
        previous = conn.execute('SELECT suggested_text FROM coach_message_feedback WHERE message_id=?',
                                (message_id,)).fetchone()
        effective_correction = (suggested_text if suggested_text is not None else
                                 (previous['suggested_text'] if previous and rating==-1 else None))
        try: evaluation_run_id=int(payload.get('evaluation_run_id') or 0) or None
        except (TypeError,ValueError):return jsonify({'error':'Invalid evaluation run'}),400
        if evaluation_run_id:
            state=run_position(conn,evaluation_run_id,row['position_id'])
            if not state or state['status']!='solved':
                return jsonify({'error':'This evaluation has not been solved'}),403
        append_feedback(conn,row['position_id'],'coaching',rating,
            evaluation_run_id=evaluation_run_id,
            lesson_key=str(payload.get('lesson_key') or '')[:150],
            content_snapshot=snapshot['content'],coaching_version=row['coaching_version'],
            suggested_text=effective_correction if rating==-1 else None,
            message_id=message_id,chat_user_message=snapshot['question'],
            chat_structured_json=snapshot['structured_json'])
        if rating == 0:
            # Remove the whole record, including any user correction, when a
            # selected thumb is clicked a second time.
            conn.execute('DELETE FROM coach_message_feedback WHERE message_id = ?', (message_id,))
            conn.commit()
            return jsonify({'ok': True, 'message_id': message_id, 'rating': 0,
                            'suggested_text': None})
        conn.execute('''
            INSERT INTO coach_message_feedback
                (message_id, account_id, position_id, rating, lesson_key, suggested_text, coaching_version_at_vote)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                rating = excluded.rating,
                lesson_key = excluded.lesson_key,
                coaching_version_at_vote = excluded.coaching_version_at_vote,
                suggested_text = CASE
                    WHEN excluded.rating = 1 THEN NULL
                    WHEN excluded.suggested_text IS NOT NULL THEN excluded.suggested_text
                    WHEN coach_message_feedback.rating = -1 THEN coach_message_feedback.suggested_text
                    ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
        ''', (message_id, row['account_id'], row['position_id'], rating,
              str(payload.get('lesson_key') or '')[:150], suggested_text, row['coaching_version']))
        conn.commit()
    with connect() as conn:
        updated = conn.execute('SELECT suggested_text FROM coach_message_feedback WHERE message_id=?', (message_id,)).fetchone()
    return jsonify({'ok': True, 'message_id': message_id, 'rating': rating,
                    'suggested_text': updated['suggested_text'] if updated else None})


@app.post('/api/engine/evaluate')
def engine_evaluate():
    payload = request.get_json(force=True)
    try:
        position_id = int(payload.get('position_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Position id is required'}), 400

    with connect() as conn:
        row = conn.execute('''
            SELECT id, learned, user_color, fen, game_pgn, mistake_ply
            FROM training_positions WHERE id = ?
        ''', (position_id,)).fetchone()

    if row is None:
        return jsonify({'error': 'Position not found'}), 404

    # Live review access is intentionally independent of the persistent
    # learned flag. The client only exposes this control after the puzzle has
    # been solved in the current review session; unchecking "Position learned"
    # merely schedules the puzzle to reappear later and must not terminate
    # Stockfish exploration of the board already on screen.

    # Analyze exactly what the user is looking at.  A solved puzzle may be
    # continued into hypothetical lines, so the client can send the displayed
    # FEN directly.  History reconstruction remains as a backward-compatible
    # fallback for ordinary game navigation.
    fen = payload.get('fen') or row['fen']
    try:
        chess.Board(fen)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid board position'}), 400

    history_ply = payload.get('history_ply')
    if not payload.get('fen') and row['game_pgn'] and row['mistake_ply'] and history_ply is not None:
        try:
            desired_ply = max(0, min(int(history_ply), int(row['mistake_ply']) - 1))
            game = chess.pgn.read_game(io.StringIO(row['game_pgn']))
            if game is not None:
                board = game.board()
                for ply, move in enumerate(game.mainline_moves(), start=1):
                    if ply > desired_ply:
                        break
                    board.push(move)
                fen = board.fen()
        except (TypeError, ValueError):
            pass

    try:
        # UI evaluations use the conventional White point of view: positive
        # favors White and negative favors Black, regardless of the learner's color.
        result = evaluate_fen(fen, chess.WHITE)
        result['evaluation_perspective'] = 'white'
    except (FileNotFoundError, chess.engine.EngineError, RuntimeError) as exc:
        return jsonify({'error': str(exc)}), 503
    return jsonify(result)


@app.post('/api/engine/move')
def engine_move():
    """Apply one legal move to a solved position's analysis board."""
    payload = request.get_json(force=True)
    try:
        position_id = int(payload.get('position_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Position id is required'}), 400

    with connect() as conn:
        row = conn.execute(
            'SELECT id, learned FROM training_positions WHERE id = ?',
            (position_id,),
        ).fetchone()
    if row is None:
        return jsonify({'error': 'Position not found'}), 404

    # As with evaluation, the persistent learned flag is curriculum state, not
    # a kill-switch for an active review session. The trainer UI gates access
    # until the position has been solved, and can continue the temporary line
    # after the learner marks the puzzle for future review.

    fen = str(payload.get('fen') or '').strip()
    requested_move = str(payload.get('move') or '').lower().strip()
    try:
        board = chess.Board(fen)
    except ValueError:
        return jsonify({'error': 'Invalid board position'}), 400

    resolved = None
    try:
        candidate = chess.Move.from_uci(requested_move)
        if candidate in board.legal_moves:
            resolved = candidate
    except ValueError:
        candidate = None

    if resolved is None and len(requested_move) == 4:
        promotion_moves = [m for m in board.legal_moves if m.uci().startswith(requested_move)]
        if promotion_moves:
            resolved = next((m for m in promotion_moves if m.promotion == chess.QUEEN), promotion_moves[0])

    if resolved is None:
        return jsonify({'error': 'Move is not legal in this position'}), 400

    san = board.san(resolved)
    board.push(resolved)
    return jsonify({
        'legal': True,
        'move_uci': resolved.uci(),
        'move_san': san,
        'fen': board.fen(),
        'turn': 'white' if board.turn == chess.WHITE else 'black',
        'legal_moves': [move.uci() for move in board.legal_moves],
    })


@app.post('/api/positions/<int:position_id>/learned')
def mark_learned(position_id):
    payload = request.get_json(force=True)
    learned = 1 if payload.get('learned') else 0
    with connect() as conn:
        row = conn.execute("""
            SELECT tp.id, tp.job_id, tp.game_id, tp.fen, tp.played_move_uci, tp.best_move_uci, tp.opening_key, j.account_id
            FROM training_positions tp
            JOIN analysis_jobs j ON j.id = tp.job_id
            WHERE tp.id = ?
        """, (position_id,)).fetchone()
        if row is None:
            return jsonify({'error': 'Position not found'}), 404

        # Return other positions in this game list whose learned flags are
        # synchronized. The trainer uses these IDs to invalidate cached solved
        # boards when an opening position appears in multiple games.
        affected_ids = {position_id}
        if row['fen'] and row['best_move_uci']:
            same_move_rows = conn.execute('''
                SELECT id FROM training_positions
                WHERE job_id = ? AND fen = ? AND best_move_uci = ?
            ''', (row['job_id'], row['fen'], row['best_move_uci'])).fetchall()
            affected_ids.update(record['id'] for record in same_move_rows)
        opening_key = str(payload.get('opening_key') or '').strip()
        if opening_key and opening_key == row['opening_key']:
            related_rows = conn.execute('''
                SELECT id, fen FROM training_positions
                WHERE job_id = ? AND opening_key = ?
            ''', (row['job_id'], opening_key)).fetchall()
            identity = board_identity(row['fen'])
            affected_ids.update(record['id'] for record in related_rows
                                if board_identity(record['fen']) == identity)

        # An explicit manual learned/unlearned toggle ends any unfinished
        # attempt cycle; the next solve will be a new practice session.
        for affected in affected_ids:
            abandon_player_session(conn, affected)
        _set_account_position_learned(conn, row['account_id'], row, bool(learned))
        _set_opening_position_group_learned(conn, row, opening_key, bool(learned))
        conn.commit()
    return jsonify({'ok': True, 'learned': bool(learned),
                    'affected_position_ids': sorted(affected_ids)})


def pause_interrupted_jobs_on_startup():
    """Boot idle. Persist unfinished tasks as paused; never start an engine implicitly.

    A game-list's analysis state is a historical process record, not a startup
    instruction. Operators can explicitly Resume from Process when ready.
    """
    with connect() as conn:
        # Preserve a restart requested just before app shutdown; on boot it
        # becomes a paused fresh pass, rather than resuming the old cursor.
        pending_restarts = conn.execute("SELECT id FROM analysis_jobs WHERE status='restarting'").fetchall()
        for restart in pending_restarts:
            restart_analysis(conn, restart['id'], get_settings(conn), queued=False)
        conn.execute("""UPDATE analysis_jobs SET status='paused'
            WHERE status IN ('queued','retrieving','running')""")
        conn.execute("""UPDATE retrieval_processes SET status='paused',
            updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')""")
        conn.execute("""UPDATE analysis_jobs SET status='paused' WHERE status='waiting_for_games'""")
        conn.execute("""UPDATE metadata_processes SET status='paused',
            updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')""")
        conn.commit()


if __name__ == '__main__':
    init_db()
    import_existing_json_if_present()
    backfill_learning_concepts()
    backfill_adaptive_concepts()
    backfill_taxonomy_paths()
    backfill_difficulty_estimates()
    backfill_coaching_texts()
    pause_interrupted_jobs_on_startup()
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
