const detailJobId = window.LESSON_DETAIL_JOB_ID;
const detailConcept = window.LESSON_DETAIL_CONCEPT;
const detailName = window.LESSON_DETAIL_NAME;
const detailIsOpening = Boolean(window.LESSON_DETAIL_IS_OPENING);
const detailScopeParameter = detailIsOpening ? 'opening' : 'concept';
const detailScopeQuery = () => {
  const motif = detailIsOpening
    ? (document.getElementById('position-concept-filter')?.value || '')
    : (document.getElementById('position-concept-filter')?.value || detailConcept);
  const context = document.getElementById('position-context-filter')?.value || 'all';
  const type = document.getElementById('position-move-type-filter')?.value || 'all';
  return {
    ...(detailIsOpening ? {opening:detailConcept, ...(motif ? {variation:motif} : {})}
      : (motif === 'all' ? {} : {concept:motif})),
    ...(context !== 'all' ? {context} : {}),
    ...(type !== 'all' ? {move_type:type} : {}),
  };
};
const detailDescriptor = detailIsOpening ? 'opening' : 'lesson';
const ratingFloor = Number(window.LESSON_DETAIL_RATING_MIN || 600);
const ratingCeiling = Number(window.LESSON_DETAIL_RATING_MAX || 2400);
let positionCatalog = [];
let lessonSummary = {total:0, learned:0, unlearned:0, percent_learned:0};
let pageState = {page:1, per_page:16, pages:1, filtered_total:0, has_previous:false, has_next:false};
let trainableTotal = 0;
const detailStateKey = `pct-${detailIsOpening?'opening':'lesson'}-${detailJobId}`;
const lessonFilterStateKey = `${detailStateKey}-${encodeURIComponent(detailConcept)}-state`;
const previousLesson = localStorage.getItem(detailStateKey);
if (previousLesson && previousLesson !== location.pathname) {
  localStorage.removeItem(`pct-training-${detailJobId}`);
  localStorage.removeItem(`pct-training-${detailJobId}-state`);
}

let restoredDetailState = null;
try { restoredDetailState = JSON.parse(localStorage.getItem(lessonFilterStateKey) || 'null'); } catch (_) {}
function rememberLesson() {
  localStorage.setItem(detailStateKey, location.pathname);
  const get = id => document.getElementById(id)?.value;
  localStorage.setItem(lessonFilterStateKey, JSON.stringify({status:get('position-status-filter'), mode:get('position-mode-filter'), sort:get('position-sort'), min:get('position-rating-min'), max:get('position-rating-max'), page:pageState.page, variation:detailIsOpening?get('position-concept-filter'):'', motif:!detailIsOpening?get('position-concept-filter'):'', context:get('position-context-filter'), moveType:get('position-move-type-filter')}));
}
const draftLearned = new Map(); // id -> {value, original, learning_mode, estimated_rating}
const selectedPositionIds = new Set();
const selectionRecords = new Map(); // selected position metadata, including off-page positions
const fmtCount = value => window.pctFormatCount ? window.pctFormatCount(value) : String(Number(value || 0));

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
}
function pieceGlyph(ch) { return {K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'}[ch] || ''; }
function fenSquares(fen) {
  const squares=Array(64).fill(''); const rows=String(fen||'').split(' ')[0].split('/');
  rows.forEach((row,rankIndex)=>{ let file=0; for(const ch of row){ if(/\d/.test(ch)) file+=Number(ch); else { if(file<8) squares[rankIndex*8+file]=ch; file+=1; } } });
  return squares;
}
function miniBoardHtml(position) {
  const squares=fenSquares(position.fen); const reverse=position.user_color==='black'; const indices=[...Array(64).keys()]; if(reverse) indices.reverse();
  return `<div class="mini-board ${reverse?'black-view':''}" aria-label="Position thumbnail">${indices.map(i=>{const rank=Math.floor(i/8),file=i%8,dark=(rank+file)%2===1,p=squares[i];return `<span class="mini-square ${dark?'dark':'light'}"><b class="mini-piece ${p&&p===p.toUpperCase()?'white':'black'}">${pieceGlyph(p)}</b></span>`;}).join('')}</div>`;
}
function categoryLabel(value) {
  const labels = {
    threw_away_win: 'Winning → Losing Position', blundered_draw: 'Drawn → Losing Position',
    blundered_into_loss: 'Playable → Losing Position', blundered_win: 'Winning Position · Weakened',
    squandered_advantage: 'Reduced Advantage', missed_checkmate: 'Missed Checkmate',
    allowed_checkmate: 'Allowed Checkmate'
  };
  return labels[value] || String(value||'training position').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
}
function learningModeMeta(value, category='') {
  if (value === 'blunders') return {label:'Blunder / missed opportunity', tone:'blunder', icon:'!'};
  if (value === 'mistakes') return {label:'Consequential mistake', icon:'!', tone:'mistake'};
  return {
    excellent: {label:'Correct / excellent', icon:'✓', tone:'correct'},
    brilliant: {label:'Creative / brilliant', icon:'✦', tone:'brilliant'},
    opposition: {label:'Opponent opportunity', icon:'⌖', tone:'opposition'}
  }[value] || {label:'Training', icon:'•', tone:'training'};
}
function draftFor(position) { return draftLearned.get(Number(position.id)); }
function learnedValue(position) { const draft=draftFor(position); return draft ? draft.value : Boolean(position.learned); }
function draftAppliesToSummary(draft) {
  const mode = document.getElementById('position-mode-filter')?.value || 'all';
  const min = Number(document.getElementById('position-rating-min')?.value || ratingFloor);
  const max = Number(document.getElementById('position-rating-max')?.value || ratingCeiling);
  return (mode === 'all' || draft.learning_mode === mode)
    && draft.estimated_rating !== null && draft.estimated_rating >= min && draft.estimated_rating <= max;
}
function draftLearnedDelta() {
  let delta=0;
  for(const d of draftLearned.values()) if (draftAppliesToSummary(d)) delta += (d.value?1:0) - (d.original?1:0);
  return delta;
}
function setDraftLearned(id, requested, original, learningMode, estimatedRating) {
  id = Number(id);
  if (Boolean(requested) === Boolean(original)) draftLearned.delete(id);
  else draftLearned.set(id, {value:Boolean(requested), original:Boolean(original), learning_mode:learningMode || 'mistakes', estimated_rating:estimatedRating === null || estimatedRating === undefined ? null : Number(estimatedRating)});
}
function updateSelectionControls() {
  const count = selectedPositionIds.size;
  const note = document.getElementById('position-selection-count');
  if (note) note.textContent = `${fmtCount(count)} selected${count?' · across matching pages':''}`;
  for (const id of ['position-mark-learned','position-mark-unlearned','position-clear-selection']) {
    const button = document.getElementById(id);
    if (button) button.disabled = !count;
  }
  const allButton = document.getElementById('position-select-all');
  if (allButton) allButton.textContent = `Select all filtered (${fmtCount(pageState.filtered_total)})`;
}
function updateSummary() {
  const total=Number(lessonSummary.total||0); const learned=Math.max(0,Math.min(total,Number(lessonSummary.learned||0)+draftLearnedDelta()));
  const pct=total?Math.round((learned/total)*100):0;
  const avg=Number.isFinite(Number(lessonSummary.average_rating)) ? Math.round(Number(lessonSummary.average_rating)) : null;
  document.getElementById('detail-position-count').textContent=fmtCount(total);
  document.getElementById('detail-learned-count').textContent=fmtCount(learned);
  document.getElementById('detail-open-count').textContent=fmtCount(Math.max(0,total-learned));
  document.getElementById('detail-average-rating').textContent=avg?`≈ ${fmtCount(avg)}`:'—';
  document.getElementById('detail-completion-label').textContent=`${pct}% complete`;
  document.getElementById('detail-completion-count').textContent=`${fmtCount(learned)} of ${fmtCount(total)} position${total===1?'':'s'} learned`;
  document.getElementById('detail-completion-bar').style.width=`${pct}%`;
  document.querySelector('.lesson-completion-track')?.setAttribute('aria-valuenow',String(pct));
}
function updateSaveState() {
  const n=draftLearned.size, button=document.getElementById('position-save-progress'), note=document.getElementById('position-save-note');
  button.disabled=!n; note.textContent=n?`${n} unsaved change${n===1?'':'s'}.`:'No unsaved changes.';
  updateTrainLessonButton();
}
function adjustedTrainableTotal() {
  const status = document.getElementById('position-status-filter')?.value || 'all';
  if (status === 'learned') return 0;
  const mode = document.getElementById('position-mode-filter')?.value || 'all';
  const ratingMin = Number(document.getElementById('position-rating-min')?.value || ratingFloor);
  const ratingMax = Number(document.getElementById('position-rating-max')?.value || ratingCeiling);
  let total = Number(trainableTotal || 0);
  for (const draft of draftLearned.values()) {
    if (mode !== 'all' && draft.learning_mode !== mode) continue;
    if (draft.estimated_rating === null || draft.estimated_rating < ratingMin || draft.estimated_rating > ratingMax) continue;
    total += (draft.value ? 0 : 1) - (draft.original ? 0 : 1);
  }
  return Math.max(0, total);
}
function updateTrainLessonButton() {
  const button=document.getElementById('detail-train-lesson');
  if(!button)return;
  const mode=document.getElementById('position-mode-filter')?.value || 'all';
  const sort=document.getElementById('position-sort')?.value || 'rating-asc';
  const ratingMin=Number(document.getElementById('position-rating-min')?.value || ratingFloor);
  const ratingMax=Number(document.getElementById('position-rating-max')?.value || ratingCeiling);
  const count=adjustedTrainableTotal();
  const params=new URLSearchParams({...detailScopeQuery(), sort, listing:'1', new_playlist:'1', rating_min:String(ratingMin), rating_max:String(ratingMax)});
  if(mode!=='all')params.set('learning_mode',mode);
  button.href=`/trainer/${detailJobId}?${params.toString()}`;
  button.textContent=`Train ${detailDescriptor} (${fmtCount(count)})`;
  button.classList.toggle('disabled',count===0);
  button.setAttribute('aria-disabled',count===0?'true':'false');
}
function updatePagination() {
  const prev=document.getElementById('position-page-previous'), next=document.getElementById('position-page-next'), summary=document.getElementById('position-page-summary');
  prev.disabled=!pageState.has_previous; next.disabled=!pageState.has_next;
  const start=pageState.filtered_total ? (pageState.page-1)*pageState.per_page+1 : 0;
  const end=Math.min(pageState.page*pageState.per_page,pageState.filtered_total);
  summary.textContent=`Page ${fmtCount(pageState.page)} of ${fmtCount(pageState.pages)} · ${fmtCount(start)}–${fmtCount(end)} of ${fmtCount(pageState.filtered_total)} matching`;
}
function renderPositions(partial = false) {
  const grid=document.getElementById('position-grid');
  if(!positionCatalog.length){ grid.innerHTML=`<div class="lesson-empty"><p class="muted">No positions match this filter.</p></div>`; if (!partial) { updateSummary(); updateSaveState(); updatePagination(); updateSelectionControls(); } return; }
  grid.innerHTML=positionCatalog.map(position=>{
    const concepts=(position.concepts||[]).slice(0,4), learned=learnedValue(position), attempts=Number(position.attempts||0);
    const listingParams=new URLSearchParams({...detailScopeQuery(),position:String(position.id),listing:'1',new_playlist:'1',sort:document.getElementById('position-sort').value,rating_min:document.getElementById('position-rating-min').value,rating_max:document.getElementById('position-rating-max').value});
    const chosenMode=document.getElementById('position-mode-filter').value;
    if(chosenMode!=='all')listingParams.set('learning_mode',chosenMode);
    const href=`/trainer/${detailJobId}?${listingParams}`;
    const modeMeta=learningModeMeta(position.learning_mode, position.category);
    return `<article class="position-tile ${learned?'learned':''}" data-position-id="${position.id}" data-href="${href}">
      <div class="position-tile-topline"><label class="position-select-control" title="Select for bulk learning-status changes"><input type="checkbox" class="position-select-toggle" aria-label="Select position" ${selectedPositionIds.has(Number(position.id))?'checked':''}><span>Select</span></label><div class="position-tile-badges"><span class="position-status-badge ${learned?'learned':'open'}">${learned?'✓ Learned':'To train'}</span><span class="position-mode-badge mode-${escapeHtml(modeMeta.tone)}" title="Learning mode: ${escapeHtml(modeMeta.label)}">${modeMeta.icon} ${escapeHtml(modeMeta.label)}</span></div>${draftFor(position)?'<span class="position-draft-badge">Unsaved</span>':''}</div>
      <button class="position-open-button" type="button" aria-label="Open training position">${miniBoardHtml(position)}<div class="position-tile-body">
        <div class="position-tile-title"><strong>${escapeHtml(position.opponent?`vs. ${position.opponent}`:'Training position')}</strong><span>Move ${escapeHtml(position.move_number||'—')}</span></div>
        <div class="position-tile-meta"><span>${escapeHtml(categoryLabel(position.category))}</span><span>${position.estimated_rating?`≈ ${fmtCount(position.estimated_rating)}`:'Rating —'}</span><span>${fmtCount(attempts)} attempt${attempts===1?'':'s'}</span>${detailIsOpening?`<span>${escapeHtml(position.opening_variation||'Main line')}</span>`:''}</div>
        <div class="position-concepts">${position.historical_match ? `<div class="historic-position-badge">♜ Historic-game position match</div>` : ''}${(position.taxonomy?.levels||concepts.filter(c=>c.is_primary)).map(c=>`<span class="position-concept-chip ${c.level==='motif'||c.is_primary?'primary':''}">${escapeHtml(c.name)}</span>`).join('<span class="taxonomy-separator">›</span>')||'<span class="position-concept-chip">General calculation</span>'}</div>
      </div></button>
      <label class="position-status-toggle"><input type="checkbox" class="position-learned-toggle" ${learned?'checked':''}><span>Learned</span></label>
    </article>`;
  }).join('');
  grid.querySelectorAll('.position-tile').forEach(tile=>{
    const id=Number(tile.dataset.positionId); tile.querySelector('.position-open-button')?.addEventListener('click',()=>{window.location.href=tile.dataset.href;});
    tile.querySelector('.position-select-toggle')?.addEventListener('change',event=>{
      const position = positionCatalog.find(p=>Number(p.id)===id);
      if (!position) return;
      if (event.target.checked) {
        selectedPositionIds.add(id);
        selectionRecords.set(id, {learned:Boolean(position.learned), learning_mode:position.learning_mode, estimated_rating:position.estimated_rating});
      } else {
        selectedPositionIds.delete(id);
        selectionRecords.delete(id);
      }
      updateSelectionControls();
    });
    tile.querySelector('.position-learned-toggle')?.addEventListener('change',event=>{
      const position=positionCatalog.find(p=>Number(p.id)===id); if(!position)return; const requested=event.target.checked, original=Boolean(position.learned);
      setDraftLearned(id, requested, original, position.learning_mode, position.estimated_rating);
      updateSummary(); updateSaveState(); renderPositions();
    });
  });
  if (!partial) { updateSummary(); updateSaveState(); updatePagination(); updateSelectionControls(); }
}
async function saveLearningProgress() {
  if(!draftLearned.size)return true; const button=document.getElementById('position-save-progress'),note=document.getElementById('position-save-note'); button.disabled=true; button.textContent='Saving…'; note.textContent='Saving learning progress…';
  try { const updates=[...draftLearned.entries()].map(([position_id,d])=>({position_id,learned:d.value})); const response=await fetch(`/api/jobs/${detailJobId}/positions/status-batch`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates})}); const result=await response.json(); if(!response.ok)throw new Error(result.error||'Could not save learning progress'); draftLearned.clear(); selectedPositionIds.clear(); selectionRecords.clear(); detailSummaryCache.clear(); await refreshLessonDetail(); return true; }
  catch(error){note.textContent=error.message||'Could not save learning progress.';button.disabled=false; return false;} finally{button.textContent=detailIsOpening?'Save opening':'Save lesson';}
}
async function resetLesson() {
  if(!window.confirm(`Reset ${detailName}? All learned positions in this ${detailDescriptor} will become available to train again.`))return; const button=document.getElementById('detail-reset-lesson'); button.disabled=true;button.textContent='Resetting…';
  try{const response=await fetch(`/api/jobs/${detailJobId}/${detailIsOpening?'openings':'lessons'}/${encodeURIComponent(detailConcept)}/reset`,{method:'POST'});const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not reset lesson');draftLearned.clear();selectedPositionIds.clear();selectionRecords.clear();detailSummaryCache.clear();pageState.page=1;await refreshLessonDetail();}
  catch(error){window.alert(error.message||'Could not reset lesson.');}finally{button.disabled=false;button.textContent=detailIsOpening?'Reset opening':'Reset lesson';}
}
// Filtered counts are independent of the current page. Fetch at the same time
// as the first 16 cards, and reuse the counts while paging the same filter.
const detailSummaryCache = new Map();
let detailQuerySequence = 0;
async function getDetailJson(query, phase) {
  const params = new URLSearchParams(query);
  params.set('phase', phase);
  const response = await fetch(`/api/jobs/${detailJobId}/position-library?${params}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Could not load lesson positions');
  return payload;
}
async function refreshLessonDetail() {
  const sequence = ++detailQuerySequence;
  const status=document.getElementById('position-status-filter').value;
  const mode=document.getElementById('position-mode-filter').value;
  const sort=document.getElementById('position-sort').value;
  const ratingMin=Number(document.getElementById('position-rating-min')?.value || ratingFloor);
  const ratingMax=Number(document.getElementById('position-rating-max')?.value || ratingCeiling);
  const query=new URLSearchParams({...detailScopeQuery(),status,learning_mode:mode,sort,page:String(pageState.page),rating_min:String(ratingMin),rating_max:String(ratingMax)});
  const summaryKey=new URLSearchParams({...detailScopeQuery(),status,learning_mode:mode,rating_min:String(ratingMin),rating_max:String(ratingMax)}).toString();
  const cached=detailSummaryCache.get(summaryKey);
  // Start BOTH requests immediately. Handle errors as values to prevent an
  // unhandled rejection while the other response is still loading.
  const summaryTask=(cached ? Promise.resolve(cached) : getDetailJson(query,'summary'))
    .then(value=>({ok:true,value}),error=>({ok:false,error}));
  document.getElementById('position-page-summary').textContent='Loading positions…';
  const pageData=await getDetailJson(query,'page');
  if(sequence!==detailQuerySequence)return;
  rememberLesson();
  positionCatalog=pageData.items||[];
  pageState={...pageState,...pageData.pagination};
  renderPositions(true);
  document.getElementById('position-page-previous').disabled=!pageState.has_previous;
  document.getElementById('position-page-next').disabled=!pageState.has_next;
  document.getElementById('position-page-summary').textContent='Updating filtered totals…';

  const summaryResult=await summaryTask;
  if(sequence!==detailQuerySequence)return;
  if(!summaryResult.ok) {
    document.getElementById('position-page-summary').textContent='Positions loaded · statistics unavailable';
    return;
  }
  const summaryData=summaryResult.value;
  detailSummaryCache.set(summaryKey,summaryData);
  lessonSummary=summaryData.summary||lessonSummary;
  trainableTotal=Number(summaryData.trainable_total||0);
  pageState={...pageState,...summaryData.pagination};
  if(Number(query.get('page'))>pageState.pages){
    pageState.page=pageState.pages;
    await refreshLessonDetail();
    return;
  }
  updateSummary();updateSaveState();updatePagination();updateSelectionControls();
}

async function selectAllFiltered() {
  const button = document.getElementById('position-select-all');
  button.disabled = true;
  button.textContent = 'Selecting…';
  try {
    const query = new URLSearchParams({
      ...detailScopeQuery(),
      status:document.getElementById('position-status-filter').value,
      learning_mode:document.getElementById('position-mode-filter').value,
      rating_min:document.getElementById('position-rating-min').value,
      rating_max:document.getElementById('position-rating-max').value,
      include_selection:'1', page:'1'
    });
    const response = await fetch(`/api/jobs/${detailJobId}/position-library?${query}`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not select positions');
    selectedPositionIds.clear();
    selectionRecords.clear();
    for (const p of result.selection_items || []) {
      const id = Number(p.id);
      selectedPositionIds.add(id);
      selectionRecords.set(id, {learned:Boolean(p.learned), learning_mode:p.learning_mode, estimated_rating:p.estimated_rating});
    }
    renderPositions();
  } catch (error) { window.alert(error.message || 'Could not select positions.'); }
  finally { button.disabled = false; updateSelectionControls(); }
}
function setSelectedLearningStatus(learned) {
  for (const id of selectedPositionIds) {
    const record = selectionRecords.get(id);
    if (!record) continue;
    setDraftLearned(id, learned, record.learned, record.learning_mode, record.estimated_rating);
  }
  renderPositions();
}
function clearSelection() {
  selectedPositionIds.clear();
  selectionRecords.clear();
  renderPositions();
}
let ratingRefreshTimer=null;
function syncRatingFilter(changed='') {
  const minEl=document.getElementById('position-rating-min'), maxEl=document.getElementById('position-rating-max'), label=document.getElementById('rating-filter-value');
  if(!minEl||!maxEl)return;
  let min=Number(minEl.value), max=Number(maxEl.value);
  if(min>max){ if(changed==='min') max=min; else min=max; minEl.value=String(min); maxEl.value=String(max); }
  if(label)label.textContent=`${fmtCount(min)}–${fmtCount(max)}`;
}
function scheduleRatingQuery(changed){
  syncRatingFilter(changed); pageState.page=1; clearTimeout(ratingRefreshTimer);
  ratingRefreshTimer=setTimeout(()=>refreshLessonDetail().catch(showLoadError),120);
}
function changeQuery(){pageState.page=1;refreshLessonDetail().catch(showLoadError);}
function showLoadError(error){document.getElementById('position-grid').innerHTML=`<div class="lesson-empty"><p class="muted">${escapeHtml(error.message||'Could not load lesson.')}</p></div>`;}
if (restoredDetailState) {
  for (const [id, value] of [['position-status-filter',restoredDetailState.status],['position-mode-filter',restoredDetailState.mode],['position-sort',restoredDetailState.sort],['position-concept-filter',detailIsOpening?restoredDetailState.variation:restoredDetailState.motif],['position-context-filter',restoredDetailState.context],['position-move-type-filter',restoredDetailState.moveType],['position-rating-min',restoredDetailState.min],['position-rating-max',restoredDetailState.max]]) {
    const element=document.getElementById(id);
    if (element && value !== undefined && value !== null && (element.tagName !== 'SELECT' || [...element.options].some(option=>option.value===String(value)))) element.value=String(value);
  }
  pageState.page=Math.max(1,Number(restoredDetailState.page)||1);
}
localStorage.setItem(detailStateKey, location.pathname);
syncRatingFilter();
// Respect restored cross-lesson scope before the first API request.
if (!detailIsOpening) {
  const currentMotif = document.getElementById('position-concept-filter')?.value;
  if (currentMotif === 'all') {
    const heading = document.getElementById('lesson-detail-title');
    if (heading) heading.textContent = 'All learning motifs';
    const reset = document.getElementById('detail-reset-lesson');
    if (reset) reset.disabled = true;
  }
}
document.getElementById('position-rating-min')?.addEventListener('input',()=>scheduleRatingQuery('min'));
document.getElementById('position-rating-max')?.addEventListener('input',()=>scheduleRatingQuery('max'));
function syncLessonMotifScope() {
  if (detailIsOpening) return;
  const motif = document.getElementById('position-concept-filter')?.value || detailConcept;
  const heading = document.getElementById('lesson-detail-title');
  if (heading) heading.textContent = motif === 'all' ? 'All learning motifs' : detailName;
  const reset = document.getElementById('detail-reset-lesson');
  if (reset) {
    reset.disabled = motif === 'all';
    reset.title = motif === 'all'
      ? 'Choose an individual primary motif before resetting its lesson.'
      : 'Reset the current lesson’s learned positions.';
  }
}
document.getElementById('position-concept-filter')?.addEventListener('change',event=>{
  if (!detailIsOpening) {
    const next = String(event.target.value || '').trim();
    if (next && next !== 'all' && next !== detailConcept) {
      window.location.href = `/lessons/${detailJobId}/${encodeURIComponent(next)}`;
      return;
    }
  }
  syncLessonMotifScope();
  changeQuery();
});
document.getElementById('position-context-filter')?.addEventListener('change',changeQuery);
document.getElementById('position-move-type-filter')?.addEventListener('change',changeQuery);
document.getElementById('position-status-filter')?.addEventListener('change',changeQuery);
document.getElementById('position-mode-filter')?.addEventListener('change',changeQuery);
document.getElementById('position-sort')?.addEventListener('change',changeQuery);
document.getElementById('position-save-progress')?.addEventListener('click',saveLearningProgress);
document.getElementById('position-select-all')?.addEventListener('click',selectAllFiltered);
document.getElementById('position-mark-learned')?.addEventListener('click',()=>setSelectedLearningStatus(true));
document.getElementById('position-mark-unlearned')?.addEventListener('click',()=>setSelectedLearningStatus(false));
document.getElementById('position-clear-selection')?.addEventListener('click',clearSelection);
document.getElementById('detail-reset-lesson')?.addEventListener('click',resetLesson);
document.getElementById('detail-train-lesson')?.addEventListener('click',async event=>{
  const button=event.currentTarget;
  if(button.getAttribute('aria-disabled')==='true'){event.preventDefault();return;}
  if(draftLearned.size){
    event.preventDefault();
    const target=button.href;
    if(await saveLearningProgress()) window.location.href=target;
  }
});
document.getElementById('position-page-previous')?.addEventListener('click',()=>{if(pageState.has_previous){pageState.page-=1;refreshLessonDetail().catch(showLoadError);}});
document.getElementById('position-page-next')?.addEventListener('click',()=>{if(pageState.has_next){pageState.page+=1;refreshLessonDetail().catch(showLoadError);}});
refreshLessonDetail().catch(showLoadError);

document.addEventListener('pct:metadata-refreshed', event => {
  if (Number(event.detail?.jobId) === Number(detailJobId)) {
    detailSummaryCache.clear();
    refreshLessonDetail().catch(showLoadError);
  }
});
