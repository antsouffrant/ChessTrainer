const lessonJobId = window.LESSON_JOB_ID;
const fmtCount = value => window.pctFormatCount ? window.pctFormatCount(value) : String(Number(value || 0));

function lessonStatusLabel(status) {
  return {
    queued: 'Queued', retrieving: 'Downloading game batch', running: 'Analysis in progress',
    paused: 'Analysis paused', complete: 'Analysis complete', error: 'Analysis stopped'
  }[status] || 'Analysis';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}


function renderLessons(lessons) {
  const list = document.getElementById('lesson-list');
  if (!lessons.length) {
    list.innerHTML = `<div class="lesson-empty glass"><h2>No lessons found</h2><p class="muted">This analysis did not produce any confirmed lesson positions.</p></div>`;
    return;
  }

  list.innerHTML = lessons.map((lesson, index) => {
    const games = Number(lesson.game_count || 0);
    const positions = Number(lesson.position_count || 0);
    const learned = Number(lesson.learned_positions || 0);
    const pct = positions ? Math.round((learned / positions) * 100) : 0;
    const detailHref = `/lessons/${lessonJobId}/${encodeURIComponent(lesson.key)}`;
    return `
      <article class="lesson-card lesson-tile glass" data-href="${detailHref}" tabindex="0" aria-label="Open ${escapeHtml(lesson.name)} lesson">
        <div class="lesson-rank">${index + 1}</div>
        <div class="lesson-card-main">
          <div class="lesson-family ${lesson.source !== 'built_in' ? 'personal' : ''}">${escapeHtml(lesson.family)}${lesson.source !== 'built_in' ? ' · PERSONAL' : ''}</div>
          <h2>${escapeHtml(lesson.name)}</h2>
          <p class="lesson-subtitle">${escapeHtml(lesson.description)}</p>
          <div class="lesson-card-meta"><span><strong>${fmtCount(games)}</strong> game${games === 1 ? '' : 's'}</span><span><strong>${fmtCount(positions)}</strong> position${positions === 1 ? '' : 's'}</span><span><strong>${fmtCount(learned)}</strong> learned</span><span><strong>${pct}%</strong> complete</span></div>
          <div class="lesson-progress" aria-label="${learned} of ${positions} learned"><span style="width:${pct}%"></span></div>
        </div>
        <div class="lesson-tile-cta">
          <span>${fmtCount(learned)}/${fmtCount(positions)}</span><small>learned</small>
          <a class="lesson-play-button" href="${detailHref}">Open lesson →</a>
        </div>
      </article>`;
  }).join('');

  list.querySelectorAll('.lesson-tile').forEach(tile => {
    const open = event => {
      if (event.target.closest('a,button')) return;
      window.location.href = tile.dataset.href;
    };
    tile.addEventListener('click', open);
    tile.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(event); }
    });
  });
}

async function toggleLessonAnalysis() {
  const button = document.getElementById('lesson-pause-button');
  if (!button) return;
  const action = button.dataset.action || 'pause';
  button.disabled = true;
  try {
    const response = await fetch(`/api/jobs/${lessonJobId}/${action}`, {method:'POST'});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Could not ${action} analysis`);
    await refreshLessonPage();
  } catch (error) { window.alert(error.message || 'Could not update analysis state.'); }
  finally { button.disabled = false; }
}

async function refreshLessonPage() {
  const [jobResponse, lessonResponse] = await Promise.all([
    fetch(`/api/jobs/${lessonJobId}`), fetch(`/api/jobs/${lessonJobId}/lessons`)
  ]);
  const job = await jobResponse.json();
  const lessons = await lessonResponse.json();

  document.getElementById('lesson-total').textContent = fmtCount(job.games_retrieved ?? 0);
  document.getElementById('lesson-screened').textContent = fmtCount(job.games_screened ?? 0);
  document.getElementById('lesson-analyzed').textContent = fmtCount(job.positions_analyzed ?? 0);
  document.getElementById('lesson-training').textContent = fmtCount(job.training_positions ?? 0);
  document.getElementById('lesson-learned').textContent = fmtCount(job.learned_positions ?? 0);
  document.getElementById('lesson-learned-pct').textContent = `${job.learned_pct ?? 0}%`;
  const statusLabel = lessonStatusLabel(job.status);
  document.getElementById('lesson-status-label').textContent = job.status === 'running'
    ? `${statusLabel} · pass ${job.current_pass || 1}/${job.max_passes || 1} · depth ${job.current_screen_depth || '—'}/${job.current_deep_depth || '—'}` : statusLabel;
  const pauseButton = document.getElementById('lesson-pause-button');
  if (pauseButton) {
    pauseButton.classList.toggle('hidden', ['complete','error','superseded'].includes(job.status));
    pauseButton.textContent = job.status === 'paused' ? 'Resume analysis' : 'Pause analysis';
    pauseButton.dataset.action = job.status === 'paused' ? 'resume' : 'pause';
  }
  document.getElementById('lesson-dot').className = `hud-dot ${job.status || ''}`;
  renderLessons(lessons);
  try { sessionStorage.setItem(`pct-lesson-tiles-${lessonJobId}`, JSON.stringify(lessons)); } catch (_) {}

  if (!['complete','error'].includes(job.status)) setTimeout(refreshLessonPage, 4000);
}


// Show the last tile snapshot immediately on return navigation, then refresh.
try {
  const cached = JSON.parse(sessionStorage.getItem(`pct-lesson-tiles-${lessonJobId}`) || 'null');
  if (Array.isArray(cached)) renderLessons(cached);
} catch (_) {}
refreshLessonPage();

// Show Resume lesson only for a saved lesson-specific trainer session in this game list.
(function setResumeLessonLink() {
  const button = document.getElementById('resume-lesson-button');
  if (!button) return;
  try {
    const saved = JSON.parse(localStorage.getItem(`pct-training-${lessonJobId}-state`) || 'null');
    if (!saved || typeof saved.url !== 'string') return;
    const url = new URL(saved.url, location.origin);
    if (url.origin !== location.origin || url.pathname !== `/trainer/${lessonJobId}` || !url.searchParams.get('concept')) return;
    if (saved.positionId && !url.searchParams.has('position_id')) {
      // Leave position selection to trainer's existing saved-position restoration.
    }
    button.href = url.pathname + url.search;
    button.classList.remove('hidden');
  } catch (_) { /* No resumable lesson session. */ }
})();


// A metadata refresh changes lesson membership; reload updated tiles in place.
document.addEventListener('pct:metadata-refreshed', event => {
  if (event.detail.jobId === lessonJobId) refreshLessonPage();
});
