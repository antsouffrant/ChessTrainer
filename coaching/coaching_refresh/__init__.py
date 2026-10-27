"""Stage 6 — refresh lifecycle, invalidation and exact version-scoped cache.

The SQLite connection and transaction belong to the caller. Historical
feedback, solved progress and fixed benchmark cohorts are not invalidated.
"""


def rebuild_position(conn, position_id):
    from .coaching_copy_refresh import rebuild_coaching_copy
    return rebuild_coaching_copy(conn, position_id)


def preserve_previous(conn, position_id):
    from .coaching_copy_refresh import preserve_previous_coaching_copy
    return preserve_previous_coaching_copy(conn, position_id)


def refresh_batch(conn, job_id, *args, **kwargs):
    from .metadata_refresh import refresh_metadata_batch
    return refresh_metadata_batch(conn, job_id, *args, **kwargs)


def clear_cache(conn, job_id):
    from .coaching_cache import clear_coaching_cache
    return clear_coaching_cache(conn, job_id)


def model_version():
    """Single public policy for the versioned coaching/evaluation lifecycle."""
    from .version import COACHING_VERSION
    return COACHING_VERSION
