/* Preserve initial SSR readiness, then update Home from persisted process state. */
(() => {
  const cards = [...document.querySelectorAll('[data-home-job]')];
  if (!cards.length) return;
  const human = {
    retrieving: 'Retrieving games…', analyzing: 'Analyzing games…', ready: 'Ready',
    empty: 'Analysis complete · no training positions found',
    retrieval_error: 'Retrieval failed · open Process',
    retrieval_paused: 'Retrieval interrupted · open Process',
    retrieval_stopped: 'Retrieval stopped · open Process',
    analysis_error: 'Analysis failed · open Process',
    analysis_paused: 'Analysis paused · open Process',
    analysis_stopped: 'Analysis stopped · open Process',
    analysis_superseded: 'Superseded game list'
  };
  const statusFor = j => {
    const n = Number(j.has_training_positions || 0);
    const r = j.retrieval_status;
    if (r === 'queued' || r === 'running' || j.analysis_status === 'waiting_for_games') return 'retrieving';
    if (r && r !== 'complete') return `retrieval_${r}`;
    if (n > 0) return 'ready';
    if (['queued','running','retrieving'].includes(j.analysis_status)) return 'analyzing';
    if (j.analysis_status === 'complete') return 'empty';
    if (['error','paused','stopped','superseded'].includes(j.analysis_status)) return `analysis_${j.analysis_status}`;
    return 'analyzing';
  };
  async function sync() {
    try {
      const response = await fetch('/api/processes', {cache:'no-store'});
      if (!response.ok) return;
      const rows = (await response.json()).processes || [];
      const byId = new Map(rows.map(j => [Number(j.id), j]));
      for (const card of cards) {
        const job = byId.get(Number(card.dataset.homeJob));
        if (!job) continue;
        const state = statusFor(job);
        card.dataset.homeState = state;
        const actions = card.querySelector('.game-list-index-links');
        actions?.classList.toggle('game-list-ready', state === 'ready');
        card.querySelectorAll('.game-list-training-action').forEach(anchor => {
          if (state === 'ready') {
            anchor.href = anchor.dataset.readyHref;
            anchor.removeAttribute('aria-disabled');
            anchor.removeAttribute('tabindex');
          } else {
            anchor.removeAttribute('href');
            anchor.setAttribute('aria-disabled', 'true');
            anchor.setAttribute('tabindex', '-1');
          }
        });
        const active = v => ['queued','running','retrieving'].includes(v);
        const retrievalBlocked = !!job.retrieval_status && job.retrieval_status !== 'complete';
        const controlsBlocked = retrievalBlocked || job.analysis_status === 'waiting_for_games' ||
          active(job.analysis_status) || active(job.refresh_status);
        card.querySelectorAll('[data-process-start]').forEach(button => {
          button.disabled = controlsBlocked;
        });
        const label = card.querySelector('[data-list-status]');
        if (label) label.textContent = state === 'ready' && ['queued','running'].includes(job.analysis_status)
          ? 'Ready · analyzing games' : (human[state] || 'Preparing game list…');
        const count = card.querySelector('[data-list-count]');
        if (count) count.textContent = `${Number(job.games_retrieved || 0).toLocaleString()} games · ${Number(job.positions_found || 0).toLocaleString()} positions`;
      }
    } catch (_) { /* Keep the server-rendered status during a temporary outage. */ }
  }
  sync();
  setInterval(() => { if (!document.hidden) sync(); }, 2500);
})();
