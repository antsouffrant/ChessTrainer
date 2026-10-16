"""Single readiness rule for Home, Process and API controls."""
def list_state(retrieval_status, analysis_status, positions_found):
    count = int(positions_found or 0)
    if retrieval_status in ('queued', 'running') or analysis_status == 'waiting_for_games':
        return 'retrieving'
    if retrieval_status and retrieval_status != 'complete':
        return 'retrieval_' + retrieval_status
    if analysis_status == 'restarting':
        return 'analyzing'
    if count > 0:
        return 'ready'
    if analysis_status in ('queued', 'running', 'retrieving', 'restarting'):
        return 'analyzing'
    if analysis_status == 'complete':
        return 'empty'
    if analysis_status in ('error', 'paused', 'stopped', 'superseded'):
        return 'analysis_' + analysis_status
    return 'analyzing'
