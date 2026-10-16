const openingJobId = window.OPENING_JOB_ID;
const openingFmt = n => window.pctFormatCount ? window.pctFormatCount(n) : String(n || 0);
const openingEscape = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
function renderOpenings(openings) {
  document.getElementById('openings-count').textContent=openingFmt(openings.length);
  document.getElementById('openings-variations').textContent=openingFmt(openings.reduce((s,x)=>s+Number(x.variation_count||0),0));
  document.getElementById('openings-positions').textContent=openingFmt(openings.reduce((s,x)=>s+Number(x.position_count||0),0));
  document.getElementById('openings-learned').textContent=openingFmt(openings.reduce((s,x)=>s+Number(x.learned_positions||0),0));
  const target=document.getElementById('opening-list');
  if(!openings.length){target.innerHTML='<div class="lesson-empty glass"><h2>No opening positions yet</h2><p class="muted">Import or evaluate games first.</p></div>';return;}
  target.innerHTML=openings.map((item,index)=>{
    const name=openingEscape(item.name), count=Number(item.position_count||0), learned=Number(item.learned_positions||0);
    const percent=count?Math.round(100*learned/count):0;
    const href=`/openings/${openingJobId}/${encodeURIComponent(item.key)}`;
    return `<article class="lesson-card lesson-tile glass opening-tile" data-href="${href}" tabindex="0" aria-label="Open ${name} opening">
      <div class="lesson-rank">${index+1}</div><div class="lesson-card-main">
      <div class="lesson-family">${openingEscape(item.eco||'OPENING FAMILY')} · ${openingFmt(item.variation_count)} variation${Number(item.variation_count)===1?'':'s'}</div>
      <h2>${name}</h2>${item.classic_count?'<span class="opening-classic-label"><i class="fa-solid fa-landmark"></i> Classic game reference</span>':''}<p class="lesson-subtitle">Explore positions from move ${openingEscape(item.first_move||'—')} onward, across ${openingFmt(item.game_count)} games.</p>
      <div class="lesson-card-meta"><span><strong>${openingFmt(item.game_count)}</strong> games</span><span><strong>${openingFmt(count)}</strong> positions</span><span><strong>${openingFmt(learned)}</strong> learned</span><span><strong>${percent}%</strong> complete</span></div>
      <div class="lesson-progress"><span style="width:${percent}%"></span></div></div>
      <div class="lesson-tile-cta"><span>${openingFmt(learned)}/${openingFmt(count)}</span><small>learned</small><a class="lesson-play-button" href="${href}">Open opening →</a></div></article>`;
  }).join('');
  target.querySelectorAll('.opening-tile').forEach(tile=>{
    tile.addEventListener('click',event=>{if(!event.target.closest('a,button'))location.href=tile.dataset.href;});
    tile.addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' '){event.preventDefault();location.href=tile.dataset.href;}});
  });
}
async function refreshOpenings() {
  const response = await fetch(`/api/jobs/${openingJobId}/openings`);
  const openings = await response.json();
  if (!response.ok) throw new Error(openings.error || 'Could not load openings');
  renderOpenings(openings);
  try { sessionStorage.setItem(`pct-opening-tiles-${openingJobId}`, JSON.stringify(openings)); } catch (_) {}
}
// Cached tiles are only a fast visual preview; refresh from SQLite in all cases.
try {
  const cached = JSON.parse(sessionStorage.getItem(`pct-opening-tiles-${openingJobId}`) || 'null');
  if (Array.isArray(cached)) renderOpenings(cached);
} catch (_) {}
refreshOpenings().catch(err=>{document.getElementById('opening-list').innerHTML=`<div class="lesson-empty glass"><p>${openingEscape(err.message)}</p></div>`;});

// Resume the pinned opening playlist at the position last visited.
(function(){
  const button=document.getElementById('resume-opening-button');
  if(!button)return;
  try{
    const saved=JSON.parse(localStorage.getItem(`pct-training-${openingJobId}-state`)||'null');
    if(!saved || typeof saved.url!=='string')return;
    const target=new URL(saved.url, location.origin);
    if(target.origin!==location.origin || target.pathname!==`/trainer/${openingJobId}` || !target.searchParams.has('opening'))return;
    button.href=target.pathname+target.search;button.classList.remove('hidden');
  }catch(_){}
})();

// Refresh cards once the metadata-only rebuild has updated opening assignments.
document.addEventListener('pct:metadata-refreshed', event => {
  if (event.detail.jobId === openingJobId) refreshOpenings();
});
