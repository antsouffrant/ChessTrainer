(() => {
  const root = document.getElementById('process-root');
  const list = document.getElementById('process-list');
  const feedback = document.getElementById('process-feedback');
  const selected = Number(root?.dataset.selectedJob || 0);
  let busy = false;
  const fmt = n => window.pctFormatCount(n || 0);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const stateLabel = s => ({retrieving:'Retrieving games',queued:'Queued',running:'Running',paused:'Paused',stopped:'Stopped',complete:'Complete',error:'Error',superseded:'Superseded',idle:'Not started'})[s] || s || 'Not started';
  function panel(j, kind) {
    const analysis = kind === 'analyze';
    const status = (analysis ? j.analysis_status : j.refresh_status) || 'idle';
    const pct = analysis
      ? Math.min(100, Math.round((Number(j.games_processed||0) / Math.max(1, Number(j.games_retrieved||0))) * 100))
      : Math.min(100, Math.round((Number(j.processed||0) / Math.max(1, Number(j.total||0))) * 100));
    const value = analysis
      ? `Pass ${j.current_pass || 1}/${j.max_passes || 1} · ${fmt(j.games_processed)} / ${fmt(j.games_retrieved)} games`
      : `${fmt(j.processed)} / ${fmt(j.total)} positions · ${fmt(j.updated)} updated`;
    // Always render a stable set of controls, including before a job starts.
    const active = ['queued','running','retrieving'].includes(status);
    const paused = status === 'paused';
    const mainCommand = paused ? 'resume' : 'start';
    const playText = paused ? 'Resume' : (analysis ? (status === 'complete' ? 'Analyze again' : 'Start analysis') : (status === 'complete' ? 'Refresh again' : 'Start refresh'));
    const controls = `
      <button type="button" class="secondary-button process-media-button process-play" data-process-action="${kind}" data-command="${mainCommand}" data-job-id="${j.id}" title="${playText}" aria-label="${playText}" ${active?'disabled':''}><i class="fa-solid fa-play" aria-hidden="true"></i></button>
      <button type="button" class="secondary-button process-media-button" data-process-action="${kind}" data-command="pause" data-job-id="${j.id}" title="Pause ${analysis?'analysis':'refresh'}" aria-label="Pause ${analysis?'analysis':'refresh'}" ${active?'':'disabled'}><i class="fa-solid fa-pause" aria-hidden="true"></i></button>
      <button type="button" class="secondary-button process-media-button" data-process-action="${kind}" data-command="stop" data-job-id="${j.id}" title="Stop ${analysis?'analysis':'refresh'}" aria-label="Stop ${analysis?'analysis':'refresh'}" ${(active||paused)?'':'disabled'}><i class="fa-solid fa-stop" aria-hidden="true"></i></button>`;
    // Old failures are historical records, not evidence of a presently locked DB.
    const error = analysis ? j.analysis_error : j.refresh_error;
    const busyFailure = /database (is )?(locked|busy)/i.test(String(error || ''));
    const errorText = status === 'error' && error
      ? `<p class="process-error-history">${busyFailure ? 'The previous attempt was interrupted by database contention.' : 'Previous attempt failed: ' + esc(error)} Select ${analysis?'Start analysis':'Start refresh'} to retry.</p>`
      : '';
    return `<div class="process-task">
      <div class="process-task-heading"><h3>${analysis ? 'Analysis' : 'Metadata refresh'}</h3><span class="process-state ${esc(status)}">${stateLabel(status)}</span></div>
      <div class="process-progress" role="progressbar" aria-label="${analysis ? 'Evaluation progress' : 'Refresh progress'}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><span style="width:${pct}%"></span></div>
      <p class="process-detail">${esc(value)}</p>
      ${errorText}
      <div class="process-task-actions">${controls}</div></div>`;
  }
  async function update() {
    if (busy) return;
    try {
      const response = await fetch('/api/processes', {cache:'no-store'});
      if (!response.ok) {
        if (response.status === 503) { feedback.textContent = 'Status is temporarily busy; retrying automatically.'; feedback.classList.remove('hidden'); return; }
        throw new Error('Unable to load process status.');
      }
      const data = await response.json();
      feedback.classList.add('hidden');
      const jobs = data.processes || [];
      list.innerHTML = jobs.length ? jobs.map(j => `
        <article class="process-card glass ${j.id === selected ? 'process-highlight' : ''}">
          <div class="process-card-heading"><div><span class="eyebrow">GAME LIST #${j.id}</span><h2>${esc(j.source_type === 'opposition' ? 'Opposition · ' + (j.source_username || j.username) : j.username + ' · ' + j.date_range)}</h2></div>
          <a class="secondary-button" href="/trainer/${j.id}">Training →</a></div>
          <div class="process-task-grid">${panel(j,'refresh')}${panel(j,'analyze')}</div>
        </article>`).join('') : `<div class="glass process-card">No saved game lists yet. <a href="/">Go Home</a> to import games.</div>`;
    } catch (error) { feedback.textContent = error.message; feedback.classList.remove('hidden'); }
  }
  list.addEventListener('click', async event => {
    const button = event.target.closest('[data-process-action]');
    if (!button || button.disabled || busy) return;
    const job = Number(button.dataset.jobId), kind = button.dataset.processAction, command = button.dataset.command;
    let path = `/api/jobs/${job}/process/${kind}`;
    let body = '{}';
    if (command === 'pause' || command === 'stop') path = kind === 'analyze' && command === 'pause'
        ? `/api/jobs/${job}/pause` : `${path}/${command}`;
    if (command === 'resume') {
      if (kind === 'analyze') path = `/api/jobs/${job}/resume`;
      else body = JSON.stringify({resume:true});
    }
    busy = true;
    button.disabled = true;
    feedback.classList.add('hidden');
    try {
      const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Process update failed.');
    } catch (err) { feedback.textContent = err.message; feedback.classList.remove('hidden'); }
    finally { busy = false; await update(); }
  });
  update();
  setInterval(() => {if (!document.hidden) update();}, 2500);
})();
