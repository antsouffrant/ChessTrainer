/* One immutable cohort, multiple coaching versions; no fabricated approval votes. */
(() => {
  const panel=document.getElementById('model-benchmark-panel');
  if (!panel) return;
  const job=panel.querySelector('#benchmark-job');
  const baseline=panel.querySelector('#benchmark-model-a');
  const against=panel.querySelector('#benchmark-model-b');
  const chart=panel.querySelector('#benchmark-model-chart');
  const note=panel.querySelector('#benchmark-chart-note');
  const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=v=>Number(v||0).toLocaleString();
  const percent=v=>v==null?'—':`${Number(v).toFixed(1)}%`;
  let requestId=0;
  function options(node,values,selected) {
    node.replaceChildren(...values.map(([value,label])=>new Option(label,value)));
    if (values.some(([value])=>value===selected)) node.value=selected;
  }
  async function fetchModels() {
    chart.replaceChildren();
    if (!job.value) {note.textContent='Select a game list to compare models on its fixed evaluation positions.';return;}
    const res=await fetch(`/api/coach/benchmark-comparison?job_id=${encodeURIComponent(job.value)}`,{cache:'no-store'});
    const data=await res.json();
    if (!res.ok) throw Error(data.error||'Unable to load benchmark');
    const previousA=baseline.value, previousB=against.value;
    options(baseline,data.versions.map(v=>[v,v]), data.versions.includes(previousA)?previousA:data.model_a);
    options(against,[['all','All other models'],...data.versions.filter(v=>v!==baseline.value).map(v=>[v,v])],previousB);
    await update();
  }
  const bar=(label,value,count,denominator) => {
    const rate=value==null?0:Math.max(0,Math.min(100,Number(value)));
    return `<div class="benchmark-metric"><span>${escape(label)}</span><div class="benchmark-metric-track" role="img" aria-label="${escape(label)} ${percent(value)}">
      <span style="width:${rate}%"></span></div><strong>${percent(value)}</strong><small>${num(count)} / ${num(denominator)}</small></div>`;
  };
  async function update() {
    const id=++requestId;
    if (!job.value||!baseline.value) return;
    note.textContent='Loading comparison…';
    const params=new URLSearchParams({job_id:job.value,model_a:baseline.value,model_b:against.value||'all'});
    const res=await fetch(`/api/coach/benchmark-comparison?${params}`,{cache:'no-store'});
    const data=await res.json();
    if (id!==requestId) return;
    if (!res.ok) throw Error(data.error||'Unable to compare models');
    if (!data.versions.length) {
      chart.innerHTML='<p class="muted">No completed coaching benchmark snapshots yet. Run Coaching refresh from Process to create the first snapshot and evaluation run.</p>';
      note.textContent='No completed models';return;
    }
    note.textContent=`${num(data.cohort_size)} permanently selected benchmark positions · ${num(data.versions.length)} coaching model snapshots`;
    chart.innerHTML=data.comparisons.length?data.comparisons.map(c=>{
      const shared=c.shared_snapshots;
      const rated=c.paired_ratings;
      return `<article class="benchmark-pair">
        <header><h3>${escape(c.baseline)} <span aria-hidden="true">→</span> ${escape(c.comparison)}</h3>
          <span class="muted">${num(shared)}/${num(c.cohort_size)} paired snapshots · ${num(rated)} paired rated continuations</span></header>
        ${bar('Explanation changed',c.explanation_change_pct,c.explanation_change_count,shared)}
        ${bar('Primary motif changed',c.motif_change_pct,c.motif_change_count,shared)}
        ${bar('Position context changed',c.context_change_pct,c.context_change_count,shared)}
        ${bar('Move type changed',c.move_type_change_pct,c.move_type_change_count,shared)}
        <div class="benchmark-approval">
          <div><span>Matched explanation approval · Model A</span><strong>${percent(c.baseline_approval_pct)}</strong><small>${num(c.baseline_positive)}/${num(rated)} rated pairs</small></div>
          <div><span>Matched explanation approval · Comparison</span><strong>${percent(c.comparison_approval_pct)}</strong><small>${num(c.comparison_positive)}/${num(rated)} rated pairs</small></div>
          <div><span>Motif correction · A / Comparison</span><strong>${percent(c.motif_correction_pct_a)} / ${percent(c.motif_correction_pct_b)}</strong>
            <small>${num(c.motif_feedback_a)} / ${num(c.motif_feedback_b)} rated motifs, independently</small></div>
        </div></article>`;
    }).join(''):'<p class="muted">Select a different model. A comparison requires at least two version snapshots for this game list.</p>';
  }
  job.addEventListener('change',()=>fetchModels().catch(e=>{note.textContent=e.message;}));
  baseline.addEventListener('change',()=>{
    const oldB=against.value;
    options(against,[['all','All other models'],...[...baseline.options].map(o=>o.value).filter(v=>v!==baseline.value).map(v=>[v,v])],oldB);
    update().catch(e=>{note.textContent=e.message;});
  });
  against.addEventListener('change',()=>update().catch(e=>{note.textContent=e.message;}));
  fetch('/api/processes',{cache:'no-store'}).then(r=>r.json()).then(data=>{
    const jobs=(data.processes||[]).filter(j=>j.benchmark);
    options(job,[['','Choose a game list'],...jobs.map(j=>[String(j.id),`#${j.id} · ${j.username||j.source_username||'Game list'} · ${j.date_range||''}`])],
      new URLSearchParams(location.search).get('job_id')||'');
    if(jobs.length && !job.value)job.value=String(jobs[0].id);
    return fetchModels();
  }).catch(e=>{note.textContent=`Benchmark unavailable: ${e.message}`;});
})();
