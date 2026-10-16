"""Creation-only Lichess game retrieval; independent of Stockfish analysis."""
from __future__ import annotations

import json
import requests

from analysis import batch_path_for_job, count_games_in_batch, date_range_to_ms
from db import connect


class RetrievalCancelled(Exception):
    """A newer user action stopped or superseded the download."""


def retrieve_game_list(job_id: int, *, on_complete=None, request_get=None) -> None:
    """Download a fresh PGN atomically, then queue and launch analysis.

    Existing lists have no retrieval record, so this worker cannot accidentally
    re-download them. Cancellation and failures never publish a partial PGN.
    """
    request_get = request_get or requests.get
    temporary = None
    try:
        with connect() as conn:
            job = conn.execute('''SELECT j.*, a.username FROM analysis_jobs j
                                  JOIN accounts a ON a.id=j.account_id
                                  WHERE j.id=?''', (job_id,)).fetchone()
            task = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
            if not job or not task or task['status'] != 'queued' or job['status'] != 'waiting_for_games':
                return
            conn.execute("""UPDATE retrieval_processes SET status='running', error=NULL,
                started_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE job_id=? AND status='queued'""", (job_id,))
            conn.commit()
            username = job['source_username'] or job['username']
            perfs = json.loads(job['game_types'] or '[]')
            params = {'since': date_range_to_ms(job['date_range']), 'clocks':'false',
                      'opening':'false', 'evals':'false'}
            if perfs and 'all' not in perfs:
                params['perfType'] = ','.join(perfs)

        destination = batch_path_for_job(username, job_id)
        temporary = destination.with_suffix('.pgn.part')
        if temporary.exists():
            temporary.unlink()
        url = f'https://lichess.org/api/games/user/{username}'
        headers = {'Accept':'application/x-chess-pgn', 'User-Agent':'personal-chess-trainer/1.1'}
        downloaded = 0
        with request_get(url, params=params, headers=headers, stream=True, timeout=(15, 300)) as response:
            if response.status_code == 429:
                raise RuntimeError('Lichess rate limit reached. Try again after at least one minute.')
            response.raise_for_status()
            try:
                total = max(0, int(response.headers.get('Content-Length') or 0))
            except (ValueError, TypeError):
                total = 0
            with connect() as conn:
                conn.execute('UPDATE retrieval_processes SET bytes_total=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?', (total, job_id))
                conn.commit()
            with temporary.open('wb') as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    with connect() as conn:
                        state = conn.execute('''SELECT r.status, j.status AS job_status
                            FROM retrieval_processes r JOIN analysis_jobs j ON j.id=r.job_id
                            WHERE r.job_id=?''', (job_id,)).fetchone()
                        if not state or state['status'] != 'running' or state['job_status'] != 'waiting_for_games':
                            raise RetrievalCancelled()
                        output.write(chunk)
                        downloaded += len(chunk)
                        conn.execute('''UPDATE retrieval_processes SET bytes_downloaded=?,
                            updated_at=CURRENT_TIMESTAMP WHERE job_id=?''', (downloaded, job_id))
                        conn.commit()

        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError('No games were returned for the selected account, date range, and game types.')
        count = count_games_in_batch(temporary)
        if not count:
            raise RuntimeError('Lichess returned no PGN games for this game list.')
        with connect() as conn:
            state = conn.execute('''SELECT r.status, j.status AS job_status
                FROM retrieval_processes r JOIN analysis_jobs j ON j.id=r.job_id
                WHERE r.job_id=?''', (job_id,)).fetchone()
            if not state or state['status'] != 'running' or state['job_status'] != 'waiting_for_games':
                raise RetrievalCancelled()
            # Only completed batches are visible to the analysis process.
            temporary.replace(destination)
            conn.execute('''UPDATE retrieval_processes SET status='complete',error=NULL,
                finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE job_id=?''', (job_id,))
            conn.execute("""UPDATE analysis_jobs SET status='queued',games_retrieved=?,error=NULL
                WHERE id=? AND status='waiting_for_games'""", (count, job_id))
            conn.commit()
        if on_complete:
            on_complete(job_id)
    except RetrievalCancelled:
        return
    except Exception as exc:
        with connect() as conn:
            state = conn.execute('SELECT status FROM retrieval_processes WHERE job_id=?', (job_id,)).fetchone()
            if state and state['status'] == 'running':
                conn.execute('''UPDATE retrieval_processes SET status='error',error=?,
                    updated_at=CURRENT_TIMESTAMP WHERE job_id=?''', (str(exc), job_id))
                conn.execute("UPDATE analysis_jobs SET status='error',error=? WHERE id=? AND status='waiting_for_games'", (str(exc), job_id))
                conn.commit()
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
