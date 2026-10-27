/* Fixed evaluation comparison view with side-by-side model summaries. */
(() => {
  const panel=document.getElementById('model-benchmark-panel');
  if (!panel) return;
  const job=panel.querySelector('#benchmark-job');
  const baseline=panel.querySelector('#benchmark-model-a');
  const against=panel.querySelector('#benchmark-model-b');
  const chart=panel.querySelector('#benchmark-model-chart');
  const history=panel.querySelector('#benchmark-evaluation-history');
  const summary=panel.querySelector('#benchmark-evaluation-summary');
  let availableRuns=[];
  let currentModel='';
  const note=panel.querySelector('#benchmark-chart-note');
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>Number(v||0).toLocaleString();
  const percent=v=>v==null?'—':`${Number(v).toFixed(1)}%`;
  const points=v=>v==null?'—':`${v>0?'+':''}${Number(v).toFixed(1)} pts`;
  let requestId=0;

  function options(node,values,selected) {
    node.replaceChildren(...values.map(([value,label])=>new Option(label,value)));
    if (values.some(([value])=>value===selected)) node.value=selected;
  }
  function modelTargets() {
    return [['all','All other models'], ...[...baseline.options].map(o=>o.value).filter(v=>v!==baseline.value).map(v=>[v,v])];
  }
  function runByVersion(version) {
    return availableRuns.find(r=>r.coaching_version===version) || null;
  }
  function delta(a,b) {
    if (a==null || b==null) return null;
    return Number(b) - Number(a);
  }
  function renderSummary(runs) {
    if (!runs.length) {
      summary.innerHTML='<p class="muted">No completed model evaluations yet.</p>';
      return;
    }
    const ordered=[...runs].sort((a,b)=>String(a.coaching_version).localeCompare(String(b.coaching_version), undefined, {numeric:true}));
    const metrics=[
      ['Evaluation progress', r=>`${num(r.solved)} / ${num(r.total)}`, r=>r.total?`${Math.round(100*r.solved/r.total)}% complete`:'—'],
      ['Positions with feedback', r=>`${num(r.feedback_positions)} / ${num(r.total)}`, null],
      ['Explanation approval', r=>percent(r.explanation_approval_pct), r=>`${num(r.explanation_ratings)} ratings`],
      ['Any taxonomy change', r=>percent(r.taxonomy_any_change_pct), r=>`${num(r.taxonomy_any_changed)}/${num(r.solved)} solved`],
      ['Context change', r=>percent(r.taxonomy_context_change_pct), r=>`${num(r.taxonomy_context_changed)}/${num(r.solved)}`],
      ['Move type change', r=>percent(r.taxonomy_move_type_change_pct), r=>`${num(r.taxonomy_move_type_changed)}/${num(r.solved)}`],
      ['Motif change', r=>percent(r.taxonomy_motif_change_pct), r=>`${num(r.taxonomy_motif_changed)}/${num(r.solved)}`],
    ];
    summary.innerHTML=`<div class="coach-summary-table-wrap"><table class="coach-summary-table">
      <thead><tr><th>Metric</th>${ordered.map(r=>{
        const done=r.solved===r.total && r.total>0;
        const state=r.coaching_version===currentModel
          ? `<span class="coach-summary-badge current">Current model</span>`
          : `<span class="coach-summary-badge frozen">Frozen</span>`;
        return `<th><div class="coach-summary-head"><div class="coach-summary-model">${escape(r.coaching_version)}</div>${state}<div class="coach-summary-run">Evaluation #${num(r.id)} · ${done?'Completed':'In progress'}</div></div></th>`;
      }).join('')}</tr></thead>
      <tbody>${metrics.map(([label,main,detail])=>`<tr><th scope="row">${escape(label)}</th>${ordered.map(r=>`<td><strong>${main(r)}</strong>${detail?`<small>${detail(r)}</small>`:''}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
  }

  function renderHistory(runs) {
    if (!runs.length) {
      history.innerHTML='<p class="muted">No evaluations have been created for this game list. Complete a Coaching refresh or start an evaluation in Process.</p>';
      return;
    }
    history.innerHTML=runs.map(r=>{
      const progress=r.total?100*r.solved/r.total:0;
      const done=r.solved===r.total && r.total>0;
      const status=done?'Completed':'In progress';
      return `<article class="coach-evaluation-card">
        <header><h4>${escape(r.coaching_version)} · Evaluation #${num(r.id)}</h4><span class="muted">${status}</span></header>
        <div class="muted">${escape(r.created_at||'')}</div>
        <div class="coach-evaluation-track" role="img" aria-label="${num(r.solved)} of ${num(r.total)} positions solved"><span style="width:${progress}%"></span></div>
        <dl><div><dt>Positions completed</dt><dd>${num(r.solved)} / ${num(r.total)}</dd></div>
            <div><dt>Feedback positions</dt><dd>${num(r.feedback_positions)} / ${num(r.total)}</dd></div>
            <div><dt>Explanation approval</dt><dd>${percent(r.explanation_approval_pct)} <small>(${num(r.explanation_ratings)} ratings)</small></dd></div>
            <div><dt>Any taxonomy change</dt><dd>${percent(r.taxonomy_any_change_pct)} <small>(${num(r.taxonomy_any_changed)}/${num(r.solved)} solved)</small></dd></div></dl>
        ${r.coaching_version===currentModel
          ? `<a class="secondary-button" href="/trainer/${encodeURIComponent(job.value)}?benchmark=1&amp;run_id=${encodeURIComponent(r.id)}">${done?'Review evaluation':'Continue evaluation'} →</a>`
          : '<span class="muted coach-evaluation-frozen"><i class="fa-solid fa-lock" aria-hidden="true"></i> Frozen · analytics only</span>'}
      </article>`;
    }).join('');
  }

  const outputRow=(label,value,count,denominator) => {
    const rate=value==null?0:Math.max(0,Math.min(100,Number(value)));
    return `<div class="benchmark-output-row"><span>${escape(label)}</span><div class="benchmark-output-track" role="img" aria-label="${escape(label)} ${percent(value)}"><span style="width:${rate}%"></span></div><strong>${percent(value)}</strong><small>${num(count)} / ${num(denominator)}</small></div>`;
  };
  const evalRow=(label,a,b,adetail,bdetail) => {
    const d=delta(a,b);
    return `<tr><th scope="row">${escape(label)}</th><td><strong>${percent(a)}</strong>${adetail?`<small>${adetail}</small>`:''}</td><td><strong>${percent(b)}</strong>${bdetail?`<small>${bdetail}</small>`:''}</td><td><strong>${points(d)}</strong></td></tr>`;
  };

  function renderComparisons(data) {
    if (!data.comparisons.length) {
      chart.innerHTML='<p class="muted">Add a second evaluated coaching version to compare model outputs on the same fixed benchmark positions.</p>';
      return;
    }
    chart.innerHTML=data.comparisons.map(c=>{
      const shared=c.shared_snapshots;
      const rated=c.paired_ratings;
      const runA=runByVersion(c.baseline);
      const runB=runByVersion(c.comparison);
      return `<article class="benchmark-comparison-card">
        <header class="benchmark-comparison-header"><div><h3>${escape(c.baseline)} <span aria-hidden="true">vs</span> ${escape(c.comparison)}</h3><p class="muted">${num(shared)}/${num(c.cohort_size)} paired snapshots · ${num(rated)} paired rated continuations · evaluation #${c.baseline_run_id||'—'} vs #${c.comparison_run_id||'—'}</p></div></header>
        <div class="benchmark-comparison-grid">
          <section class="benchmark-section">
            <div class="benchmark-section-heading"><h4>Evaluation results</h4><p class="muted">Side-by-side benchmark feedback on the fixed cohort.</p></div>
            ${(runA && runB) ? `<div class="coach-summary-table-wrap"><table class="benchmark-compare-table"><thead><tr><th>Metric</th><th>${escape(c.baseline)}</th><th>${escape(c.comparison)}</th><th>Δ</th></tr></thead><tbody>
              ${evalRow('Explanation approval', runA.explanation_approval_pct, runB.explanation_approval_pct, `${num(runA.explanation_ratings)} ratings`, `${num(runB.explanation_ratings)} ratings`)}
              ${evalRow('Any taxonomy change', runA.taxonomy_any_change_pct, runB.taxonomy_any_change_pct, `${num(runA.taxonomy_any_changed)}/${num(runA.solved)} solved`, `${num(runB.taxonomy_any_changed)}/${num(runB.solved)} solved`)}
              ${evalRow('Context change', runA.taxonomy_context_change_pct, runB.taxonomy_context_change_pct, `${num(runA.taxonomy_context_changed)}/${num(runA.solved)}`, `${num(runB.taxonomy_context_changed)}/${num(runB.solved)}`)}
              ${evalRow('Move type change', runA.taxonomy_move_type_change_pct, runB.taxonomy_move_type_change_pct, `${num(runA.taxonomy_move_type_changed)}/${num(runA.solved)}`, `${num(runB.taxonomy_move_type_changed)}/${num(runB.solved)}`)}
              ${evalRow('Motif change', runA.taxonomy_motif_change_pct, runB.taxonomy_motif_change_pct, `${num(runA.taxonomy_motif_changed)}/${num(runA.solved)}`, `${num(runB.taxonomy_motif_changed)}/${num(runB.solved)}`)}
            </tbody></table></div>` : '<p class="muted">Evaluation-level metrics are not available for one or both models.</p>'}
          </section>
          <section class="benchmark-section">
            <div class="benchmark-section-heading"><h4>Output differences</h4><p class="muted">How often the two models actually disagree on the same benchmark positions.</p></div>
            ${outputRow('Explanation text changed', c.explanation_change_pct, c.explanation_change_count, shared)}
            ${outputRow('Primary motif changed', c.motif_change_pct, c.motif_change_count, shared)}
            ${outputRow('Position context changed', c.context_change_pct, c.context_change_count, shared)}
            ${outputRow('Move type changed', c.move_type_change_pct, c.move_type_change_count, shared)}
            <div class="benchmark-inline-note"><strong>Matched explanation approval:</strong> ${escape(c.baseline)} ${percent(c.baseline_approval_pct)} vs ${escape(c.comparison)} ${percent(c.comparison_approval_pct)} on ${num(rated)} rated continuation pairs.</div>
          </section>
        </div>
      </article>`;
    }).join('');
  }

  async function fetchModels() {
    chart.replaceChildren();
    summary.replaceChildren();
    if (!job.value) {note.textContent='Select a game list to compare models on its fixed evaluation positions.'; return;}
    const res=await fetch(`/api/coach/benchmark-comparison?job_id=${encodeURIComponent(job.value)}`,{cache:'no-store'});
    const data=await res.json();
    if (!res.ok) throw Error(data.error||'Unable to load benchmark');
    availableRuns=data.evaluation_runs||[];
    currentModel=data.current_model||data.versions?.at(-1)||'';
    renderSummary(availableRuns);
    renderHistory(availableRuns);
    const previousA=baseline.value, previousB=against.value;
    options(baseline,data.versions.map(v=>[v,v]), data.versions.includes(previousA)?previousA:data.model_a);
    options(against,modelTargets(),previousB);
    await update();
  }

  async function update() {
    const id=++requestId;
    if (!job.value || !baseline.value) return;
    note.textContent='Loading comparison…';
    const params=new URLSearchParams({job_id:job.value, model_a:baseline.value, model_b:against.value||'all'});
    const res=await fetch(`/api/coach/benchmark-comparison?${params}`,{cache:'no-store'});
    const data=await res.json();
    if (id!==requestId) return;
    if (!res.ok) throw Error(data.error||'Unable to compare models');
    if (!data.versions.length) {
      summary.innerHTML='';
      chart.innerHTML='<p class="muted">No completed coaching benchmark snapshots yet. Run Coaching refresh from Process to create the first snapshot and evaluation run.</p>';
      note.textContent='No completed models';
      return;
    }
    availableRuns=data.evaluation_runs||[];
    currentModel=data.current_model||data.versions?.at(-1)||'';
    renderSummary(availableRuns);
    renderHistory(availableRuns);
    note.textContent=`${num(data.cohort_size)} permanently selected benchmark positions · ${num(data.versions.length)} coaching model snapshots · ${num(availableRuns.length)} model evaluations`;
    renderComparisons(data);
  }

  job.addEventListener('change',()=>fetchModels().catch(e=>{note.textContent=e.message;}));
  baseline.addEventListener('change',()=>{
    options(against,modelTargets(),against.value);
    update().catch(e=>{note.textContent=e.message;});
  });
  against.addEventListener('change',()=>{update().catch(e=>{note.textContent=e.message;});});
  fetch('/api/processes',{cache:'no-store'}).then(r=>r.json()).then(data=>{
    const jobs=(data.processes||[]).filter(j=>j.benchmark);
    options(job,[['','Choose a game list'], ...jobs.map(j=>[String(j.id),`#${j.id} · ${j.username||j.source_username||'Game list'} · ${j.date_range||''}`])], new URLSearchParams(location.search).get('job_id')||'');
    if (jobs.length && !job.value) job.value=String(jobs[0].id);
    return fetchModels();
  }).catch(e=>{note.textContent=`Benchmark unavailable: ${e.message}`;});
})();
