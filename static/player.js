/* Player activity dashboard. No data is collected merely by opening this view. */
(() => {
  const root = document.getElementById('player-hub');
  if (!root) return;
  const form = document.getElementById('player-filters');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n || 0).toLocaleString();
  let initialized = false;
  let token = 0;
  function query() {
    const p = new URLSearchParams(new FormData(form));
    for (const k of [...p.keys()]) if (!p.get(k)) p.delete(k);
    return p.toString();
  }
  function options(key, values) {
    const control = form.elements[key];
    const saved = new Set([...control.selectedOptions].map(o => o.value).filter(Boolean));
    for (const item of values || []) {
      const option = new Option(item.label || item.value, String(item.value));
      option.selected = saved.has(option.value);
      control.add(option);
    }
  }
  function value(id, text) { document.getElementById(id).textContent = text; }
  function bars(id, data, nameKey, countKey) {
    const root = document.getElementById(id);
    if (!data?.length) { root.innerHTML = '<p class="player-empty">No practice sessions yet.</p>'; return; }
    const max = Math.max(1, ...data.map(x => Number(x[countKey] || 0)));
    root.innerHTML = data.map(row => `<div class="player-bar-row"><span class="player-bar-label" title="${escape(row[nameKey])}">${escape(row[nameKey])}</span><div class="player-bar-track"><div class="player-bar-fill" style="width:${100 * Number(row[countKey] || 0) / max}%"></div></div><b>${fmt(row[countKey])}</b></div>`).join('');
  }
  function breakdown(id, data) {
    const root = document.getElementById(id);
    if (!data?.length) { root.innerHTML = '<p class="player-empty">No positions in this group.</p>'; return; }
    root.innerHTML = `<div class="player-table-scroll"><table class="player-table"><thead><tr><th>Group</th><th>Learned</th><th>1st try</th><th>Attempts/solve</th><th>Avg time</th></tr></thead><tbody>${data.map(x => `<tr><td>${escape(x.name)}</td><td>${fmt(x.learned_positions)} / ${fmt(x.total_positions)}</td><td>${x.first_try_rate==null?'—':`${x.first_try_rate}%`}</td><td>${x.avg_attempts_per_solve ?? '—'}</td><td>${x.avg_solve_seconds == null ? '—' : `${x.avg_solve_seconds}s`}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function draw(data) {
    const r = data.overview;
    value('player-total', fmt(r.total_positions));
    value('player-learned', fmt(r.learned_positions));
    value('player-learned-detail', r.total_positions ? `${(100*r.learned_positions/r.total_positions).toFixed(1)}% of positions` : 'No positions yet');
    value('player-attempted', fmt(r.attempted_positions));
    value('player-attempts-detail', `${fmt(r.total_attempts)} legal moves · ${fmt(r.attempted_sessions)} sessions`);
    value('player-first-try', r.first_try_rate == null ? '—' : `${r.first_try_rate}%`);
    value('player-first-detail', `${fmt(r.first_encounter_solves)} first-try solves / ${fmt(r.attempted_positions)} first encounters`);
    value('player-avg-attempts', r.avg_attempts_per_solve == null ? '—' : String(r.avg_attempts_per_solve));
    value('player-solved-detail', `${fmt(r.solved_sessions)} solved practice sessions`);
    value('player-avg-time', r.avg_solve_seconds == null ? '—' : `${r.avg_solve_seconds}s`);
    value('player-time-detail', `${fmt(r.timed_solves)} timed solves · ${fmt(r.excluded_solve_times)} excluded`);
    bars('player-attempt-hist', data.histogram, 'label', 'count');
    const trend = document.getElementById('player-progress-time');
    const activity = data.over_time.filter(x => x.solves).slice(-35);
    const highest = Math.max(1, ...activity.map(x => x.solves));
    trend.innerHTML = activity.length ? activity.map(x => {
      const pct = x.first_encounters ? (100 * x.first_encounter_solves / x.first_encounters).toFixed(0) : '—';
      return `<div class="player-bar-row"><span class="player-bar-label">${escape(x.date)}</span><div class="player-bar-track"><div class="player-bar-fill" style="width:${100*x.solves/highest}%"></div></div><b title="${fmt(x.first_try_solves)} first-try solves · ${pct}% first-try rate">${fmt(x.solves)} <small>(${pct}%)</small></b></div>`;
    }).join('') : '<p class="player-empty">No completed practice sessions yet.</p>';
    breakdown('player-by-motif', data.by_motif);
    breakdown('player-by-opening', data.by_opening);
    breakdown('player-by-mode', data.by_mode);
    const recent = document.getElementById('player-recent');
    recent.innerHTML = data.recent?.length ? data.recent.map(s => `<tr><td><a href="/trainer/${encodeURIComponent(s.job_id)}?position=${encodeURIComponent(s.position_id)}">#${fmt(s.position_id)}</a></td><td>${escape(s.motif_name || 'Unclassified')}</td><td>${fmt(s.attempts)}</td><td>${s.solved_at ? (s.first_try_solved ? 'Solved first try' : 'Solved') : (s.abandoned_at ? 'Reset / abandoned' : 'In progress')}</td><td>${s.solve_seconds == null ? (s.solved_at ? 'Excluded' : '—') : `${s.solve_seconds}s`}</td><td>${escape(String(s.started_at).slice(0,16))}</td></tr>`).join('') : '<tr><td colspan="6" class="player-empty">No attempted positions yet.</td></tr>';
  }
  async function refresh() {
    const ticket = ++token;
    const params = query();
    for (const kind of ['attempts','sessions']) document.getElementById(`player-${kind==='attempts'?'attempt':'session'}-export`).href = `/api/player/${kind}.csv${params ? '?'+params : ''}`;
    document.getElementById('player-loading').classList.remove('hidden');
    document.getElementById('player-error').classList.add('hidden');
    try {
      const response = await fetch(`/api/player/summary${params ? '?'+params : ''}`, {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load learning progress');
      if (ticket !== token) return;
      if (!initialized) {
        options('job_id', data.facets.game_lists);
        options('opening_key', data.facets.openings);
        options('primary_motif_key', data.facets.motifs);
        options('learning_mode', data.facets.learning_modes);
        initialized = true;
      }
      draw(data);
      document.getElementById('player-results').classList.remove('hidden');
    } catch (error) {
      if (ticket === token) {
        value('player-error', error.message);
        document.getElementById('player-error').classList.remove('hidden');
      }
    } finally { if (ticket === token) document.getElementById('player-loading').classList.add('hidden'); }
  }
  const resetRecords = document.getElementById('player-reset-records');
  if (resetRecords) resetRecords.addEventListener('click', async () => {
    const jobs = [...form.elements.job_id.selectedOptions].map(o => o.value).filter(Boolean);
    if (jobs.length > 1) {
      window.alert('Choose at most one game list before resetting Player history. Multi-select remains available for reporting and CSV exports.');
      return;
    }
    const selectedJob = jobs[0] || '';
    const scope = selectedJob
      ? `ALL Player solve sessions and move attempts in game list #${selectedJob}`
      : 'ALL Player solve sessions and move attempts across EVERY game list';
    if (!window.confirm(`Permanently delete ${scope}? This ignores motif/opening/mode/position filters. Learned puzzle status, analysis and Coach feedback will be kept. Download both Player CSV exports first if you want a backup.`)) return;
    const typed = window.prompt('Type RESET PLAYER to confirm irreversible deletion of practice history:');
    if (typed !== 'RESET PLAYER') return;
    resetRecords.disabled = true;
    document.getElementById('player-error').classList.add('hidden');
    try {
      const response = await fetch('/api/player/records/reset', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({job_id: selectedJob || null, confirmation: typed})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not reset Player records');
      await refresh();
      document.getElementById('player-reset-note').textContent =
        `Player history reset: ${fmt(result.deleted.sessions)} sessions and ${fmt(result.deleted.attempts)} attempt events deleted. Learned status, training positions, and Coach feedback were preserved.`;
    } catch (error) {
      value('player-error', error.message);
      document.getElementById('player-error').classList.remove('hidden');
    } finally { resetRecords.disabled = false; }
  });
  form.addEventListener('change', refresh);
  form.addEventListener('reset', () => setTimeout(refresh, 0));
  refresh();
})();
