/* Home game-list buttons launch work only when the process queue is idle.
   If a job is underway, Process owns all control (pause/resume/restart). */
const activeProcessStatuses = new Set(['queued', 'running', 'retrieving', 'restarting']);
let homeProcessLaunchPending = false;
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-process-start]');
  if (!button || button.disabled || homeProcessLaunchPending) return;
  const id = Number(button.dataset.jobId);
  const action = button.dataset.processStart;
  if (!Number.isInteger(id) || !['refresh', 'analyze'].includes(action)) return;
  const processUrl = `/processes?job_id=${id}`;
  homeProcessLaunchPending = true;
  button.disabled = true;
  try {
    // One centralized process worker handles analysis and metadata refresh.
    // Never submit a competing start request when a job is already active.
    const statusResponse = await fetch('/api/processes', {cache:'no-store'});
    if (!statusResponse.ok) {
      window.location.assign(processUrl);
      return;
    }
    const data = await statusResponse.json();
    const target = (data.processes || []).find(job => Number(job.id) === id);
    const busy = target && (
      (target.retrieval_status && target.retrieval_status !== 'complete') ||
      target.analysis_status === 'waiting_for_games' ||
      activeProcessStatuses.has(target.analysis_status) ||
      activeProcessStatuses.has(target.refresh_status)
    );
    if (busy) {
      window.location.assign(processUrl);
      return;
    }
    const response = await fetch(`/api/jobs/${id}/process/${action}`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'
    });
    // Another tab can start work between the status check and this POST.
    // Redirect to Process to resolve conflicts using its controls.
    if (response.status === 409 || response.status === 503) {
      window.location.assign(processUrl);
      return;
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not start ${action}.`);
    window.location.assign(processUrl);
  } catch (error) {
    alert(error.message || 'Could not start process.');
  } finally {
    homeProcessLaunchPending = false;
    button.disabled = false;
  }
});
