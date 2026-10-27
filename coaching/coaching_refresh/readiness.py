"""Per-position coaching readiness; an evaluation alone does not prove whole-list readiness.

Never silently promote old model copy: a full Process coaching refresh owns the
versioned evidence rebuild.  Ordinary training attempts are unaffected.
"""


def coaching_ready(row, active_version):
    if row is None:
        return False
    try:
        return (row['coaching_version'] == active_version and
                bool(str(row['coach_explanation'] or '').strip()))
    except (KeyError, IndexError):
        return False


def coaching_refresh_error(row, active_version):
    """Stable error payload for recap and explanation-feedback endpoints."""
    try:
        saved = row['coaching_version'] if row is not None else None
        job_id = row['job_id'] if row is not None else None
    except (IndexError, KeyError):
        saved, job_id = None, None
    return {
        'error': ('Coaching is not ready for this position. Refresh coaching for '
                  'this game list from Process. Your legal training attempts remain saved.'),
        'code': 'coaching_refresh_required',
        'active_coaching_version': active_version,
        'position_coaching_version': saved,
        'job_id': job_id,
    }
