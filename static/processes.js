/* v52 – Pause preserves the checkpoint; Restart re-evaluates saved games. */
(() => {
  const root = document.getElementById('process-root');
  const list = document.getElementById('process-list');
  const feedback = document.getElementById('process-feedback');
  if (!root || !list) return;
  const selected = Number(root.dataset.selectedJob || 0);
  let busy = false;
  const fmt = n => Number(n || 0).toLocaleString();
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const active = s => ['queued','running','retrieving','restarting'].includes(s);
  const label = s => ({waiting_for_games:'Waiting for retrieval', queued:'Queued',running:'Running',restarting:'Restarting',
    paused:'Paused',stopped:'Stopped',complete:'Complete',error:'Error',superseded:'Superseded',
    idle:'Not started'})[s] || s || 'Not started';
  const hasSavedBatch = j => !j.retrieval_status || j.retrieval_status === 'complete';
  const isAnalyzing = j => active(j.analysis_status);
  const isRefreshing = j => active(j.refresh_status);
  const isRetrieving = j => !hasSavedBatch(j) && active(j.retrieval_status);
  const canAnalyze = j => hasSavedBatch(j) && !isAnalyzing(j) && !isRefreshing(j);
  const canRefresh = j => hasSavedBatch(j) && !isAnalyzing(j) && !isRefreshing(j);
  const canRestart = j => hasSavedBatch(j) && !isRefreshing(j) && j.analysis_status !== 'restarting';

  function currentProcess(j) {
    if (!hasSavedBatch(j)) return {kind:'retrieve',status:j.retrieval_status};
    if (isRefreshing(j)) return {kind:'refresh',status:j.refresh_status};
    if (isAnalyzing(j)) return {kind:'analyze',status:j.analysis_status};
    if (j.analysis_status === 'paused') return {kind:'analyze',status:'paused'};
    if (j.refresh_status === 'paused') return {kind:'refresh',status:'paused'};
    return {kind:null,status:'idle'};
  }

  function stage(j, kind) {
    const retrieval = kind === 'retrieve';
    const analysis = kind === 'analyze';
    const status = retrieval ? (j.retrieval_status || 'complete') : (analysis ? j.analysis_status : j.refresh_status) || 'idle';
    const count = retrieval ? Number(j.bytes_downloaded||0) : Number(analysis ? j.games_processed||0 : j.processed||0);
    const total = retrieval ? Number(j.bytes_total||0) : Number(analysis ? j.games_retrieved||0 : j.total||0);
    const percentage = status === 'restarting' ? 0 : status === 'complete' ? 100 : total > 0 ? Math.max(0,Math.min(100,Math.round(count*100/total))) : 0;
    const description = analysis && status === 'restarting' ? 'Stopping the current engine, clearing previous positions and coaching metadata, then reanalyzing saved games' : retrieval ? (!j.retrieval_status ? 'Existing saved PGN – no new download needed' :
        status === 'complete' ? `${fmt(j.games_retrieved)} games saved locally` :
        status === 'error' ? 'Retrieval failed: ' + esc(j.retrieval_error||'Unknown error') :
        `${(count/1048576).toFixed(1)} MB downloaded${total ? ' / '+(total/1048576).toFixed(1)+' MB' : ''}`)
      : analysis ? `Pass ${fmt(j.current_pass || 1)} of ${fmt(j.max_passes || 1)} · ${fmt(count)} / ${fmt(total)} games` :
        `${fmt(count)} / ${fmt(total)} positions · ${fmt(j.updated)} updated`;
    const error = analysis ? j.analysis_error : j.refresh_error;
    const databaseBusy = /database (is )?(locked|busy)/i.test(String(error||''));
    const errorMessage = status === 'error' && error ? `<p class="process-error-history">The previous attempt failed: ${databaseBusy ? 'temporary database contention' : esc(error)}. Select ${analysis ? 'Start analysis' : 'Start refresh'} to retry.</p>` : '';
    return `<section class="process-task ${active(status)?'process-task-live':''}" aria-label="${kind} stage">
      <div class="process-task-heading"><h3>${retrieval?'Retrieval':analysis?'Analysis':'Metadata refresh'}</h3>
        <span class="process-state ${esc(status)}">${!j.retrieval_status && retrieval ? 'Saved' : label(status)}</span></div>
      <div class="process-progress ${retrieval && active(status) && !total ? 'indeterminate':''}" role="progressbar"
        aria-label="${kind} progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percentage}"><span style="width:${percentage}%"></span></div>
      <p class="process-detail">${description}</p>${errorMessage}</section>`;
  }

  function renderControls(j) {
    const current = currentProcess(j);
    const running = active(current.status);
    const paused = current.status === 'paused';
    const kind = current.kind;
    const transport = (verb, title, enabled, icon) => `<button type="button" class="secondary-button process-media-button ${verb==='start'?'process-play':''}"
      data-process-action="${kind || 'analyze'}" data-command="${verb}" data-job-id="${j.id}"
      aria-label="${title}" title="${title}" ${enabled?'':'disabled'}>
      <i class="fa-solid fa-${icon}" aria-hidden="true"></i><span>${title}</span></button>`;
    const title = kind === 'retrieve' ? 'retrieval' : kind === 'refresh' ? 'refresh' : 'analysis';
    const startText = kind === 'retrieve' ? 'Retry retrieval' : `Resume ${title}`;
    const command = paused && kind !== 'retrieve' ? 'resume' : 'start';
    const controls = transport(command, startText, !!kind && !running &&
      (!hasSavedBatch(j) || paused), 'play') +
      transport('pause',`Pause ${title}`,!!kind && running && current.status !== 'restarting','pause') +
      `<button type="button" class="secondary-button process-media-button process-restart"
        data-process-action="analyze" data-command="restart" data-job-id="${j.id}"
        aria-label="Restart analysis" title="Clear this list’s analysis and training history; reanalyze saved games with current settings"
        ${canRestart(j)?'':'disabled'}><i class="fa-solid fa-rotate-right" aria-hidden="true"></i><span>Restart analysis</span></button>`;
    const analysisText = j.analysis_status === 'complete' ? 'Analyze again · next pass' :
      j.analysis_status === 'paused' || j.analysis_status === 'stopped' || j.analysis_status === 'error' ? 'Resume analysis' : 'Start analysis';
    const refreshText = j.refresh_status === 'complete' ? 'Refresh again' : 'Start refresh';
    const detail = isRetrieving(j) ? 'Retrieving games' : j.analysis_status === 'restarting' ? 'Restarting analysis' : isAnalyzing(j) ? 'Analyzing games' :
      isRefreshing(j) ? 'Refreshing metadata' : kind && paused ? `${title[0].toUpperCase()+title.slice(1)} paused` :
      hasSavedBatch(j) ? 'Ready for processing' : 'Retrieval interrupted';
    const action = (actionName,txt,enabled) => `<button type="button" class="secondary-button process-operation"
      data-process-action="${actionName}" data-command="start" data-job-id="${j.id}" ${enabled?'':'disabled'}>${txt}</button>`;
    return `<div class="process-control-bar"><div class="process-control-context"><span class="eyebrow">CURRENT PROCESS</span>
      <strong>${detail}</strong><small>Controls apply only to this game list’s current task.</small></div>
      <div class="process-task-actions">${controls}</div>
      <div class="process-operation-actions">${action('analyze',analysisText,canAnalyze(j))}${action('refresh',refreshText,canRefresh(j))}</div></div>`;
  }

  function renderJob(j) {
    const ready = Number(j.has_training_positions||0) > 0 && hasSavedBatch(j) && j.analysis_status !== 'restarting';
    const summary = !hasSavedBatch(j) ? (active(j.retrieval_status)?'Retrieving games':`Retrieval ${label(j.retrieval_status).toLowerCase()}`) :
      j.analysis_status === 'restarting' ? 'Restarting analysis' : isAnalyzing(j) ? 'Analyzing games' : isRefreshing(j) ? 'Refreshing' :
      ready ? 'Ready to train' : j.analysis_status === 'complete' ? 'No training positions found' : 'Awaiting training positions';
    return `<article class="process-card glass ${j.id===selected?'process-highlight':''}" data-process-job="${j.id}">
      <header class="process-card-heading"><div><span class="eyebrow">GAME LIST #${j.id}</span>
        <h2>${esc(j.source_type === 'opposition' ? 'Opposition · '+(j.source_username||j.username) : j.username+' · '+j.date_range)}</h2>
        <p class="process-card-meta">${fmt(j.games_retrieved)} saved games · ${fmt(j.positions_found)} training positions</p></div>
        <div class="process-card-summary"><span class="process-state">${summary}</span>
          ${ready?`<a class="secondary-button" href="/trainer/${j.id}">Training →</a>`:''}</div></header>
      <div class="process-task-grid">${stage(j,'retrieve')}${stage(j,'analyze')}${stage(j,'refresh')}</div>
      ${renderControls(j)}</article>`;
  }

  async function update() {
    if (busy) return;
    try {
      const res = await fetch('/api/processes',{cache:'no-store'});
      if (!res.ok) throw new Error(res.status===503?'Status temporarily busy; retrying automatically.':'Could not load processes.');
      const jobs = (await res.json()).processes||[];
      if (feedback) feedback.classList.add('hidden');
      list.innerHTML = jobs.length ? jobs.map(renderJob).join('') :
        '<div class="glass process-card">No game lists yet. <a href="/">Import games on Home</a>.</div>';
    } catch(err) { if(feedback) {feedback.textContent=err.message;feedback.classList.remove('hidden');} }
  }
  list.addEventListener('click',async event=>{
    const button=event.target.closest('[data-process-action]');
    if(!button || button.disabled || busy) return;
    const job=Number(button.dataset.jobId),kind=button.dataset.processAction,command=button.dataset.command;
    let url=`/api/jobs/${job}/process/${kind}`;
    let body='{}';
    if(command==='restart') {
      if(typeof window !== 'undefined' && typeof window.confirm === 'function' &&
         !window.confirm('Restart this game list from scratch? Its training positions, learned progress, explanations, motifs, and position/chat feedback will be permanently deleted. The downloaded PGN is kept. Download the Coach CSV first if you need the old feedback.')) return;
      url=`/api/jobs/${job}/process/analyze/restart`;
    } else if(command==='pause' || command==='stop') {
      url=kind==='analyze' && command==='pause' ? `/api/jobs/${job}/pause` : `${url}/${command}`;
    } else if(command==='resume') {
      if(kind==='analyze') url=`/api/jobs/${job}/resume`;
      else body=JSON.stringify({resume:true});
    }
    busy=true;button.disabled=true;
    if(feedback) feedback.classList.add('hidden');
    try {
      const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body});
      const data=await res.json();
      if(!res.ok) throw new Error(data.error||'Unable to update process.');
    } catch(err) {if(feedback){feedback.textContent=err.message;feedback.classList.remove('hidden');}}
    finally {busy=false;await update();}
  });
  update();
  setInterval(()=>{if(!document.hidden) update();},2500);
})();
