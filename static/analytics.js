/* v48 — filterable learning-quality dashboard; same filters drive API & CSV. */
(() => {
  const root = document.getElementById('feedback-analytics');
  if (!root) return;
  const form = document.getElementById('analytics-filters');
  const loading = document.getElementById('analytics-loading');
  const results = document.getElementById('analytics-results');
  const error = document.getElementById('analytics-error');
  const download = document.getElementById('analytics-export');
  const regressionDownload = document.getElementById('coach-regression-export');
  const taxonomyDownload = document.getElementById('coach-taxonomy-export');
  const fmt = n => Number(n || 0).toLocaleString();
  const escape = text => String(text ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const title = {position:'Position',explanation:'Explanation',coaching:'Chat coaching',taxonomy_context:'Position context',taxonomy_move_type:'Move type',taxonomy_motif:'Learning motif'};
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
  const chartGroupNames = {opening:'opening',motif:'primary learning motif',lesson:'lesson',version:'coach version',
    context:'position context',move_type:'move type',learning_mode:'learning mode',game_list:'game list',
    taxonomy_field:'taxonomy field',feedback_area:'feedback area',continuation_kind:'continuation / message type'};
  function percent(n) { return n == null ? '—' : `${Number(n).toFixed(1)}%`; }
  function drawRateChart(data, metric) {
    const chart = data.charts?.[metric] || {};
    const isChange = metric === 'changes';
    const label = isChange ? 'Change rate' : 'Approval rate';
    const target = document.getElementById(isChange ? 'coach-changes-chart' : 'coach-approval-chart');
    const help = document.getElementById(isChange ? 'coach-changes-help' : 'coach-approval-help');
    const groupName = chartGroupNames[chart.group_by] || 'category';
    const caveat = chart.historical_version_note
      ? (isChange ? ' Changes use current classifications only; historic rates cannot be reconstructed.'
        : ' Historical approvals use versions saved at feedback time.') : '';
    help.textContent = isChange
      ? `Change rate by ${groupName}: positions with any corrected taxonomy label / all solved positions in each category. A position counts once.${caveat}`
      : chart.group_by === 'continuation_kind'
        ? `Approval rate by ${groupName}: independently approved continuations or coach messages / individually rated continuations or coach messages. Unrated messages are excluded.${caveat}`
        : `Approval rate by ${groupName}: positions with any thumbs-up / positions with thumbs feedback in each category. Unrated positions are excluded.${caveat}`;
    if (!chart.rows?.length) {
      target.innerHTML = '<p class="analytics-empty">No solved positions or rated feedback match these filters.</p>';
      return;
    }
    target.innerHTML = chart.rows.map(row => {
      const value = row.rate == null ? null : Math.max(0, Math.min(100, Number(row.rate)));
      const count = `${fmt(row.numerator)} / ${fmt(row.denominator)}`;
      const segments = value == null
        ? '<span class="comparison-unrated"></span>'
        : `<span class="comparison-segment comparison-${isChange ? 'change' : 'approval'}" style="width:${value}%"></span><span class="comparison-remaining" style="width:${100 - value}%"></span>`;
      return `<div class="coach-metric-row">
        <div class="coach-metric-category">${escape(row.name)}</div>
        <div class="comparison-bar" role="img" aria-label="${label} for ${escape(row.name)}: ${percent(value)}, ${count}">${segments}</div>
        <strong class="coach-metric-value">${percent(value)}</strong>
        <small class="coach-metric-count">${count}</small>
      </div>`;
    }).join('') + (chart.groups_count > chart.rows.length
      ? `<p class="analytics-empty">Showing ${chart.rows.length} of ${fmt(chart.groups_count)} groups. Narrow the filters to see others.</p>` : '');
  }
  function draw(data) {
    document.getElementById('analytics-total').textContent = fmt(data.overall.total);
    document.getElementById('analytics-total-detail').textContent =
      data.overall.total ? `${fmt(data.thumbs?.total)} thumb ratings · ${fmt(data.taxonomy?.total)} taxonomy selections` : 'No feedback yet';
    for (const type of ['position','explanation','taxonomy_context','taxonomy_move_type','taxonomy_motif']) {
      const card = document.querySelector(`[data-score="${type}"]`);
      const stat = data.categories[type] || {total:0,up_pct:null,up:0,down:0};
      if (type.startsWith('taxonomy_')) {
        const changes = data.taxonomy_change_rates?.[type.slice('taxonomy_'.length)] || {};
        card.querySelector('strong').textContent = changes.change_pct == null ? '—' : `${changes.change_pct.toFixed(1)}%`;
        card.querySelector('small').textContent = `${fmt(changes.changed)} changed · ${fmt(changes.unchanged)} unchanged / ${fmt(changes.solved)} solved`;
        card.querySelector('.analytics-score-track > span').style.width = `${changes.change_pct ?? 0}%`;
      } else {
        card.querySelector('strong').textContent = stat.up_pct == null ? '—' : `${stat.up_pct.toFixed(1)}%`;
        card.querySelector('small').textContent = `${fmt(stat.total)} ratings · ${fmt(stat.up)} up · ${fmt(stat.down)} down`;
        card.querySelector('.analytics-score-track > span').style.width = `${stat.up_pct ?? 0}%`;
      }
    }
    drawRateChart(data, 'changes');
    drawRateChart(data, 'approval');
    document.getElementById('analytics-record-count').textContent = `${fmt(data.overall.total)} matching feedback records`;
    const body = document.querySelector('#analytics-records tbody');
    if (!data.recent.length) {
      body.innerHTML = '<tr><td colspan="8" class="analytics-empty">No feedback yet for these filters. Rate a solved position or chat response in Training to begin.</td></tr>';
      return;
    }
    body.innerHTML = data.recent.map(r => {
      const label = `${r.username} · ${r.date_range} (#${r.job_id})`;
      const opening = r.opening_name || r.opening_eco || '—';
      const lesson = r.lesson_name || '—';
      const motif = r.primary_motif_name && r.primary_motif_name !== lesson ? `<small>Motif: ${escape(r.primary_motif_name)}</small>` : '';
      const when = r.updated_at ? escape(String(r.updated_at).slice(0, 16)) : '—';
      const taxonomy = r.feedback_type.startsWith('taxonomy_');
      const correction = taxonomy ? r.selected_taxonomy_name || r.selected_taxonomy_key : r.suggested_motif_name || r.suggested_text;
      const continuation = r.feedback_type === 'explanation' && r.continuation_key
        ? `<small>${r.continuation_key === 'solving' ? 'Solving continuation' : `Earlier move · ${escape(r.continuation_key)}`}</small>` : '';
      return `<tr><td>${escape(title[r.feedback_type] || r.feedback_type)}${continuation}</td>
        <td><span class="analytics-vote ${r.rating === 1 ? 'positive':'negative'}">${taxonomy
          ? (r.current_taxonomy_change_status === 'changed' ? 'Changed' : 'Unchanged') : (r.rating === 1 ? '👍 Yes' : '👎 No')}</span></td>
        <td class="coach-correction-preview" title="${escape(correction || '')}">${escape(String(correction || '—').slice(0, 130))}</td>
        <td>${escape(label)}</td><td>${escape(lesson)}${motif}</td><td>${escape(opening)}</td>
        <td><a href="/trainer/${encodeURIComponent(r.job_id)}?position=${encodeURIComponent(r.position_id)}">#${fmt(r.position_id)}</a>
        <small>${escape(r.learning_mode || '')}${r.move_number ? ` · move ${fmt(r.move_number)}` : ''}</small></td>
        <td>${when}</td></tr>`;
    }).join('');
  }
  async function update() {
    const token = ++requestToken;
    const query = params().toString();
    const chartQuery = new URLSearchParams(params());
    chartQuery.set('chart_changes_group', document.getElementById('coach-changes-group').value);
    chartQuery.set('chart_approval_group', document.getElementById('coach-approval-group').value);
    download.href = '/api/analytics/feedback.csv' + (query ? `?${query}` : '');
    if (regressionDownload) regressionDownload.href = '/api/coach/regression.csv' + (query ? `?${query}` : '');
    if (taxonomyDownload) taxonomyDownload.href = '/api/coach/taxonomy.csv' + (query ? `?${query}` : '');
    error.classList.add('hidden');
    loading.textContent = 'Loading feedback…';
    loading.classList.remove('hidden');
    try {
      const response = await fetch('/api/analytics/feedback?' + chartQuery.toString(), {cache:'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to load feedback');
      if (token !== requestToken) return;
      if (!loadedFacets) {
        fillFacet('job_id', data.facets.game_lists);
        fillFacet('lesson_key', data.facets.lessons);
        fillFacet('opening_key', data.facets.openings);
        fillFacet('primary_motif_key', data.facets.motifs);
        fillFacet('learning_mode', data.facets.learning_modes);
        fillFacet('current_context_key', data.facets.contexts);
        fillFacet('current_move_type_key', data.facets.move_types);
        fillFacet('coaching_version', data.facets.coaching_versions);
        fillFacet('position_category', data.facets.position_categories);
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
  const resetFeedback = document.getElementById('coach-reset-feedback');
  if (resetFeedback) resetFeedback.addEventListener('click', async () => {
    const selectedJob = form.elements.job_id.value;
    const scope = selectedJob
      ? `all saved ratings and taxonomy selections for game list #${selectedJob}`
      : 'ALL saved ratings and taxonomy selections across EVERY game list';
    if (!window.confirm(`Permanently delete ${scope}? Training positions and analysis are kept. Export CSV first if you want a backup.`)) return;
    const typed = window.prompt('Type RESET FEEDBACK to confirm this irreversible rating reset:');
    if (typed !== 'RESET FEEDBACK') return;
    resetFeedback.disabled = true;
    error.classList.add('hidden');
    try {
      const response = await fetch('/api/coach/feedback/reset', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({job_id:selectedJob || null, confirmation:typed})
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || 'Reset failed');
      loadedFacets = false;
      await update();
      document.getElementById('coach-reset-note').textContent =
        `Feedback reset: ${fmt(body.deleted.position_explanation_motif + (body.deleted.continuation_explanations || 0) + body.deleted.chat_coaching + (body.deleted.taxonomy_selections || 0))} records deleted. Analysis and positions were kept.`;
    } catch (err) {
      error.textContent = err.message;
      error.classList.remove('hidden');
    } finally { resetFeedback.disabled = false; }
  });
  document.getElementById('coach-changes-group').addEventListener('change', update);
  document.getElementById('coach-approval-group').addEventListener('change', update);
  form.addEventListener('change', update);
  form.addEventListener('reset', () => window.setTimeout(update, 0));
  update();
})();
