/* v48 — filterable learning-quality dashboard; same filters drive API & CSV. */
(() => {
  const root = document.getElementById('feedback-analytics');
  if (!root) return;
  const form = document.getElementById('analytics-filters');
  const loading = document.getElementById('analytics-loading');
  const results = document.getElementById('analytics-results');
  const error = document.getElementById('analytics-error');
  const download = document.getElementById('analytics-export');
  const fmt = n => Number(n || 0).toLocaleString();
  const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const title = {position:'Position',explanation:'Explanation',motif:'Motif',coaching:'Chat coaching'};
  let loadedFacets = false;
  let requestToken = 0;
  function params() {
    const p = new URLSearchParams(new FormData(form));
    [...p.keys()].forEach(k => {if (!p.get(k)) p.delete(k);});
    return p;
  }
  function fillFacet(name, items) {
    const select = form.elements[name];
    if (!select) return;
    const prior = select.value;
    const first = select.options[0]?.textContent || 'All';
    select.replaceChildren(new Option(first, ''));
    for (const item of items || []) select.add(new Option(item.label, String(item.value)));
    if ([...select.options].some(o => o.value === prior)) select.value = prior;
  }
  function breakdownTable(rows) {
    if (!rows?.length) return '<p class="analytics-empty">No rated items match these filters.</p>';
    return `<div class="analytics-table-scroll"><table class="analytics-table"><thead><tr><th>Group</th><th>Ratings</th><th>👍 %</th></tr></thead><tbody>${rows.map(r =>
      `<tr><td>${escape(r.name)}</td><td>${fmt(r.total)}</td><td><div class="analytics-percent-row"><b>${r.up_pct?.toFixed(1) ?? '—'}${r.up_pct == null ? '' : '%'}</b><span class="analytics-mini-track"><span style="width:${r.up_pct ?? 0}%"></span></span></div></td></tr>`
    ).join('')}</tbody></table></div>`;
  }
  function draw(data) {
    document.getElementById('analytics-total').textContent = fmt(data.overall.total);
    document.getElementById('analytics-total-detail').textContent =
      data.overall.total ? `${data.overall.up_pct.toFixed(1)}% thumbs up · ${fmt(data.overall.down)} thumbs down` : 'No feedback yet';
    for (const type of ['position','explanation','motif','coaching']) {
      const card = document.querySelector(`[data-score="${type}"]`);
      const stat = data.categories[type] || {total:0,up_pct:null,up:0,down:0};
      card.querySelector('strong').textContent = stat.up_pct == null ? '—' : `${stat.up_pct.toFixed(1)}%`;
      card.querySelector('small').textContent = `${fmt(stat.total)} ratings · ${fmt(stat.up)} up · ${fmt(stat.down)} down`;
      card.querySelector('.analytics-score-track > span').style.width = `${stat.up_pct ?? 0}%`;
    }
    document.getElementById('analytics-motif-breakdown').innerHTML = breakdownTable(data.by_motif);
    document.getElementById('analytics-opening-breakdown').innerHTML = breakdownTable(data.by_opening);
    document.getElementById('analytics-lesson-breakdown').innerHTML = breakdownTable(data.by_lesson);
    document.getElementById('analytics-record-count').textContent = `${fmt(data.overall.total)} matching ratings`;
    const body = document.querySelector('#analytics-records tbody');
    if (!data.recent.length) {
      body.innerHTML = '<tr><td colspan="7" class="analytics-empty">No feedback yet for these filters. Rate a solved position or chat response in Training to begin.</td></tr>';
      return;
    }
    body.innerHTML = data.recent.map(r => {
      const label = `${r.username} · ${r.date_range} (#${r.job_id})`;
      const opening = r.opening_name || r.opening_eco || '—';
      const lesson = r.lesson_name || '—';
      const motif = r.primary_motif_name && r.primary_motif_name !== lesson ? `<small>Motif: ${escape(r.primary_motif_name)}</small>` : '';
      const when = r.updated_at ? escape(String(r.updated_at).slice(0, 16)) : '—';
      return `<tr><td>${escape(title[r.feedback_type] || r.feedback_type)}</td>
        <td><span class="analytics-vote ${r.rating === 1 ? 'positive':'negative'}">${r.rating === 1 ? '👍 Yes' : '👎 No'}</span></td>
        <td>${escape(label)}</td><td>${escape(lesson)}${motif}</td><td>${escape(opening)}</td>
        <td><a href="/trainer/${encodeURIComponent(r.job_id)}?position=${encodeURIComponent(r.position_id)}">#${fmt(r.position_id)}</a>
        <small>${escape(r.learning_mode || '')}${r.move_number ? ` · move ${fmt(r.move_number)}` : ''}</small></td>
        <td>${when}</td></tr>`;
    }).join('');
  }
  async function update() {
    const token = ++requestToken;
    const query = params().toString();
    download.href = '/api/analytics/feedback.csv' + (query ? `?${query}` : '');
    error.classList.add('hidden');
    loading.textContent = 'Loading feedback…';
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/analytics/feedback' + (query ? `?${query}` : ''), {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to load feedback');
      if (token !== requestToken) return;
      if (!loadedFacets) {
        fillFacet('job_id', data.facets.game_lists);
        fillFacet('lesson_key', data.facets.lessons);
        fillFacet('opening_key', data.facets.openings);
        fillFacet('primary_motif_key', data.facets.motifs);
        fillFacet('learning_mode', data.facets.learning_modes);
        loadedFacets = true;
      }
      draw(data);
      results.classList.remove('hidden');
    } catch (err) {
      if (token !== requestToken) return;
      error.textContent = err.message;
      error.classList.remove('hidden');
    } finally {
      if (token === requestToken) loading.classList.add('hidden');
    }
  }
  form.addEventListener('change', update);
  form.addEventListener('reset', () => window.setTimeout(update, 0));
  update();
})();
