const jobId = window.TRAINER_JOB_ID;
const conceptKey = window.TRAINER_CONCEPT || '';
const openingKey = window.TRAINER_OPENING || '';
const openingVariation = window.TRAINER_VARIATION || '';
const requestedPositionId = Number(window.TRAINER_POSITION_ID || 0) || null;
const trainerLearningMode = window.TRAINER_LEARNING_MODE || '';
const trainerSort = window.TRAINER_SORT || 'rating-asc';
const trainerListingScope = Boolean(window.TRAINER_LISTING_SCOPE);
const trainerRatingMin = Number(window.TRAINER_RATING_MIN || 0) || null;
const trainerRatingMax = Number(window.TRAINER_RATING_MAX || 0) || null;
const trainingStateKey = `pct-training-${jobId}`;
const trainingPlaylistKey = `${trainingStateKey}-playlist`;
const initialQuery = new URLSearchParams(location.search);
const benchmarkQueue = initialQuery.get('benchmark') === '1';
const evaluationRunId = Number(window.TRAINER_EVALUATION_RUN_ID || 0) || null;
// Evaluation feedback must remain visible; hover-only thumbs can look disabled.
if (evaluationRunId) document.documentElement.classList.add('evaluation-feedback-mode');
const forceNewPlaylist = initialQuery.get('new_playlist') === '1';
const trainerContextFilter = initialQuery.get('context') || '';
const trainerMoveTypeFilter = initialQuery.get('move_type') || '';
// Remove the one-shot launch flag so refreshes and Resume lesson restore
// this playlist instead of accidentally creating another one.
const sessionQuery = new URLSearchParams(location.search);
sessionQuery.delete('new_playlist');
const sessionUrl = `${location.pathname}${sessionQuery.toString() ? `?${sessionQuery.toString()}` : ''}`;
let savedPlaylist = null;
try { savedPlaylist = JSON.parse(localStorage.getItem(trainingPlaylistKey) || 'null'); } catch (_) {}
if (forceNewPlaylist || savedPlaylist?.url !== sessionUrl) savedPlaylist = null;
let playlistPinned = false;
let positionsRequestPending = false;
function keepPlaylistSnapshot() {
  // Evaluation membership and solved progress live in SQLite, not in the
  // ordinary training playlist's browser storage.
  if (evaluationRunId || !positions.length) return;
  savedPlaylist = {
    url: sessionUrl, ids: positions.map(p => Number(p.id)), solvedMoves: sessionSolvedMoves
  };
  localStorage.setItem(trainingPlaylistKey, JSON.stringify(savedPlaylist));
}

// The browser's solved-move snapshot is only valid while the position remains
// learned. When the user unlearns it, clear that snapshot (including equivalent
// opening-game records) before the card can be restored by Last position.
function reconcilePlaylistLearnedState(positionId, learned, affectedPositionIds = []) {
  const ids = new Set([Number(positionId), ...affectedPositionIds.map(Number)]);
  for (const item of positions) {
    if (ids.has(Number(item.id))) item.learned = learned ? 1 : 0;
  }
  if (!learned) {
    for (const id of ids) delete sessionSolvedMoves[String(id)];
  }
  keepPlaylistSnapshot();
}

// An explicit lesson or position link wins over the saved session.
const hasExplicitTrainingTarget = Boolean(conceptKey || openingKey || openingVariation || requestedPositionId || trainerLearningMode || trainerListingScope || trainerRatingMin || trainerRatingMax || trainerContextFilter || trainerMoveTypeFilter || benchmarkQueue || new URLSearchParams(location.search).has('sort'));
let savedTraining = null;
try { savedTraining = JSON.parse(localStorage.getItem(`${trainingStateKey}-state`) || 'null'); } catch (_) {}
function isEvaluationResumeUrl(url) {
  if (typeof url !== 'string') return false;
  try {
    const candidate = new URL(url, location.origin);
    return candidate.origin === location.origin &&
      candidate.pathname === `/trainer/${jobId}` &&
      (candidate.searchParams.has('benchmark') || candidate.searchParams.has('run_id'));
  } catch (_) { return false; }
}
// Upgrade browsers that cached the old evaluation as their last training
// playlist. That saved URL must never override Training, Lessons, or Openings.
if (isEvaluationResumeUrl(savedTraining?.url) || isEvaluationResumeUrl(localStorage.getItem(trainingStateKey))) {
  localStorage.removeItem(trainingStateKey);
  localStorage.removeItem(`${trainingStateKey}-state`);
  savedTraining = null;
}
if (!hasExplicitTrainingTarget && savedTraining?.url?.startsWith(`/trainer/${jobId}`) &&
    !isEvaluationResumeUrl(savedTraining.url) && savedTraining.url !== `${location.pathname}${location.search}`) {
  location.replace(savedTraining.url);
}
const resumePositionId = !forceNewPlaylist && !requestedPositionId && savedTraining?.url === sessionUrl ? Number(savedTraining.positionId) || null : null;
function rememberTraining(positionId) {
  // Only ordinary lessons/openings/training become the default resume target.
  // Evaluations are always launched explicitly from Process/Coach/featured tiles.
  if (evaluationRunId) return;
  const url = sessionUrl;
  localStorage.setItem(trainingStateKey, url);
  localStorage.setItem(`${trainingStateKey}-state`, JSON.stringify({url, positionId}));
}
let requestedPositionPending = requestedPositionId || resumePositionId;
let positions = [];
// Only playlist IDs/status are loaded up front. Full cards are fetched in small
// immutable chunks as needed; loaded cards are never discarded (unlimited review).
const POSITION_CHUNK_SIZE = 20;
const positionChunkRequests = new Map();
let positionDisplayToken = 0;
let hudHasLoaded = false;
let sessionSolvedMoves = {};
try {
  if (savedPlaylist?.url === sessionUrl && savedPlaylist?.solvedMoves) {
    sessionSolvedMoves = savedPlaylist.solvedMoves;
  }
} catch (_) { /* Existing playlists need no migration. */ }
let currentIndex = 0;
let selectedSquare = null;
let solved = false;
// Feedback confirmation belongs to a specific evaluation run AND position;
// solving alone never implies the evaluation has been reviewed.
const evaluationFeedbackSavedByPosition = new Map();
function evaluationFeedbackSaved() {
  return Boolean(evaluationRunId && solved &&
    evaluationFeedbackSavedByPosition.get(Number(currentPosition()?.id || 0)));
}
function updateEvaluationFeedbackState(positionId, saved) {
  if (!evaluationRunId || !positionId) return;
  evaluationFeedbackSavedByPosition.set(Number(positionId), Boolean(saved));
  // Avoid delayed network responses from unlocking a different puzzle.
  if (Number(currentPosition()?.id) === Number(positionId)) updateNavigationMeta();
}
let inputLocked = true;
// Active learning time is measured only while the training tab is visible and
// focused. No DB session is created until the user submits a legal move.
// Persist the clock-in preference across game lists and browser sessions.
// Turning this off suppresses Player events, never normal puzzle completion.
const playerTrackingStorageKey = 'pct-player-tracking-enabled';
let learningTrackingEnabled = evaluationRunId ? false : localStorage.getItem(playerTrackingStorageKey) !== '0';
const playerTrackingToggleEl = document.getElementById('player-tracking-toggle');
const playerTrackingLabelEl = document.getElementById('player-tracking-label');
let playerClockOutRequest = Promise.resolve();
let restartTrackedSession = !learningTrackingEnabled;
let learningClockPositionId = null;
let learningClockElapsedMs = 0;
let learningClockSince = null;
function learningClockCanRun() {
  return learningTrackingEnabled && document.visibilityState !== 'hidden' && (!document.hasFocus || document.hasFocus());
}
function learningClockPause() {
  if (learningClockSince !== null) {
    learningClockElapsedMs += Math.max(0, performance.now() - learningClockSince);
    learningClockSince = null;
  }
}
function learningClockResume() {
  if (learningClockPositionId && learningClockSince === null && learningClockCanRun())
    learningClockSince = performance.now();
}
function learningClockStart(positionId) {
  learningClockPause();
  learningClockPositionId = positionId;
  learningClockElapsedMs = 0;
  learningClockSince = null;
  learningClockResume();
}
function learningClockSnapshot() {
  learningClockPause();
  return Math.round(learningClockElapsedMs) / 1000;
}
function learningClockCommit() {
  learningClockElapsedMs = 0;
  learningClockSince = null;
  learningClockResume();
}
// Clocking out ends any incomplete recorded attempt cycle. Clocking back in
// creates a new session on the next legal attempt; earlier data is preserved.
function updatePlayerTrackingUI() {
  if (playerTrackingToggleEl) playerTrackingToggleEl.checked = learningTrackingEnabled;
  if (playerTrackingLabelEl) playerTrackingLabelEl.textContent = learningTrackingEnabled ? 'Player stats on' : 'Player stats off';
}
function setPlayerTrackingEnabled(enabled) {
  if (learningTrackingEnabled === enabled) return;
  learningClockPause();
  learningTrackingEnabled = enabled;
  // An evaluation always starts with tracking off, without overwriting the normal preference.
  if (!evaluationRunId) localStorage.setItem(playerTrackingStorageKey, enabled ? '1' : '0');
  learningClockElapsedMs = 0;
  if (!enabled) {
    restartTrackedSession = true;
    learningClockSince = null;
    const positionId = learningClockPositionId;
    if (positionId) {
      playerClockOutRequest = playerClockOutRequest.catch(() => {}).then(() =>
        fetch(`/api/positions/${positionId}/player/clock-out`, {method:'POST', keepalive:true,
          headers:{'Content-Type':'application/json'}, body:JSON.stringify({evaluation_run_id:evaluationRunId})})
      ).catch(() => {});
    }
  } else {
    learningClockResume();
  }
  updatePlayerTrackingUI();
}
updatePlayerTrackingUI();
playerTrackingToggleEl?.addEventListener('change', () => setPlayerTrackingEnabled(playerTrackingToggleEl.checked));
if (typeof document.addEventListener === 'function') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') learningClockPause();
    else learningClockResume();
  });
}
if (typeof window.addEventListener === 'function') {
  window.addEventListener('blur', learningClockPause);
  window.addEventListener('focus', learningClockResume);
  window.addEventListener('pagehide', learningClockPause);
}

let positionsTimer = null;
let hudTimer = null;
let previewTimers = [];
let displayedPositionId = null;
let currentContext = null;
let historyPly = 0;
let analysisComplete = false;
const contextCache = new Map();
const engineEvalCache = new Map();
let engineRequestToken = 0;
let showingSolvedMove = false;
let displayedFen = '';
let analysisLegalMoves = [];
let analysisTurn = null;
let analysisLineDepth = 0;
let analysisLineUci = [];
let analysisLineSan = [];
// Temporary review branch. Analysis moves are session-local but survive history
// navigation so the arrow keys behave like a real analysis board.
let reviewStage = 'history'; // history | solved | analysis
let analysisBase = null;
let analysisFrames = [];
let analysisCursor = 0;
let analysisActionToken = 0;
let solvingMoveUci = null;
let solvingMoveSan = null;
let solvingMoveFen = null;
let solutionBestMoveUci = null;
let solutionBestMoveSan = null;
let solvedReviewFen = null; // Board after the actual accepted move; engine-best remains a visual annotation.

const boardEl = document.getElementById('chessboard');
const feedbackEl = document.getElementById('feedback');
const feedbackMessageEl = document.getElementById('feedback-message');
const illegalMoveAlertEl = document.getElementById('illegal-move-alert');
let illegalMoveAlertTimeout = null;
function showIllegalMoveAlert(message = 'That move is not legal. Try another move.') {
  if (!illegalMoveAlertEl) return;
  illegalMoveAlertEl.textContent = message;
  illegalMoveAlertEl.classList.remove('hidden');
  if (illegalMoveAlertTimeout) clearTimeout(illegalMoveAlertTimeout);
  illegalMoveAlertTimeout = setTimeout(() => {
    illegalMoveAlertEl.classList.add('hidden');
    illegalMoveAlertEl.textContent = '';
    illegalMoveAlertTimeout = null;
  }, 2500);
}
function hideIllegalMoveAlert() {
  if (illegalMoveAlertTimeout) clearTimeout(illegalMoveAlertTimeout);
  illegalMoveAlertTimeout = null;
  illegalMoveAlertEl?.classList.add('hidden');
  if (illegalMoveAlertEl) illegalMoveAlertEl.textContent = '';
}

const solutionEl = document.getElementById('solution');
const learnedCheckbox = document.getElementById('learned-checkbox');
const learnedToggleWrapEl = document.getElementById('learned-toggle-wrap');
const opponentMoveEl = document.getElementById('opponent-move');
const boardMarkEl = document.getElementById('board-feedback-mark');
const pgnMovesEl = document.getElementById('pgn-moves');
const historyBackEl = document.getElementById('history-back');
const historyForwardEl = document.getElementById('history-forward');
const historyStatusEl = document.getElementById('history-status');
const nextButtonEl = document.getElementById('next-button');
const gameShareRootEl = document.getElementById('game-share');
const gameShareToggleEl = document.getElementById('game-share-toggle');
const gameShareMenuEl = document.getElementById('game-share-menu');
const gameShareMessageEl = document.getElementById('game-share-message');
const shareCopyPgnEl = document.getElementById('share-copy-pgn');
const shareDownloadPgnEl = document.getElementById('share-download-pgn');
const shareCopyLichessEl = document.getElementById('share-copy-lichess');
const shareOpenLichessEl = document.getElementById('share-open-lichess');
const gameShareCache = new Map();
let activeGameShare = null;

const lessonsIndexUrl = `/lessons/${jobId}`;
function updateAnalysisIndicator() {
  const active = analysisModeActive();
  document.querySelector('.board-top-rim')?.classList.toggle('analysis-active', active);
  if (active) historyStatusEl.textContent = 'Analysis mode';
}

const engineToggleEl = document.getElementById('engine-toggle');
const engineToggleWrapEl = document.getElementById('engine-toggle-wrap');
const engineEvalEl = document.getElementById('engine-eval');
const engineArrowEl = document.getElementById('engine-arrow');
const engineArrowShapeEl = document.getElementById('engine-arrow-shape');
const taskHeadingEl = document.getElementById('task-heading');
const coachTextEl = document.getElementById('coach-text');
const categoryEl = document.getElementById('category');
const hintToggleEl = document.getElementById('hint-toggle');
const hintTextEl = document.getElementById('trainer-hint-text');
const coachChatEl = document.getElementById('coach-chat');
const coachPositionReviewEl = document.getElementById('coach-position-review');
const coachAttemptCommentsEl = document.getElementById('coach-attempt-comments');
const coachSolutionLabelEl = document.getElementById('coach-solution-label');
const solvedOpeningEl = document.getElementById('solved-opening');
const solvedOpeningRowEl = document.getElementById('solved-opening-row');
const coachFormEl = document.getElementById('coach-form');
const coachInputEl = document.getElementById('coach-input');
const coachSendEl = document.getElementById('coach-send');
const coachModeNoteEl = document.getElementById('coach-mode-note');
const coachConceptEventEl = document.getElementById('coach-concept-event');
const coachReadinessWarningEl = document.getElementById('coach-readiness-warning');
const coachRecapWarningEl = document.getElementById('coach-recap-warning');
const refreshPositionEl = document.getElementById('refresh-position-button');
const solvedPositionControlsEl = document.getElementById('solved-position-controls');
const trainerRootEl = document.getElementById('trainer-root');
const coachPanelEl = document.querySelector('.coach-panel');
let coachThreadReadyPositionId = null;
const historicCoachRequests = new Set();
const brilliantCoachRequests = new Set();
const proactiveCoachRequests = new Map();
const coachSolveSessionKeys = new Map();
const coachAttemptLogFailures = new Map();
let coachThreadLoadSerial = 0;
function coachSolveSessionKey(positionId) {
  const id = Number(positionId || 0);
  if (!coachSolveSessionKeys.has(id)) {
    const token = (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function')
      ? crypto.randomUUID().replaceAll('-', '')
      : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
    coachSolveSessionKeys.set(id, evaluationRunId ? `eval_${evaluationRunId}_${token}` : token);
    coachAttemptLogFailures.delete(id);
  }
  return coachSolveSessionKeys.get(id);
}
function coachingAvailableForPosition(position) {
  // Legacy cards without a readiness field remain usable; the server guards
  // every vote against an actually stale per-position model.
  return Boolean(position && position.coaching_ready !== false);
}
function displayCoachRefreshWarning(position) {
  if (!coachReadinessWarningEl) return;
  coachReadinessWarningEl.replaceChildren();
  const unavailable = Boolean(position && !coachingAvailableForPosition(position));
  coachReadinessWarningEl.classList.toggle('hidden', !unavailable);
  coachRecapWarningEl?.classList.add('hidden');
  if (!unavailable) return;
  const storedVersion = position.coaching_version || 'not refreshed';
  const activeVersion = position.active_coaching_version || 'current';
  const text = document.createElement('span');
  const cached = Boolean(position?.coach_explanation && position?.feedback_message_id);
  text.textContent = cached
    ? `Cached coaching from ${storedVersion} (active: ${activeVersion}). You can still rate or edit feedback on displayed messages; refresh coaching for new current-model advice and chat. `
    : `No saved coaching message is available for this position (saved: ${storedVersion}; active: ${activeVersion}). Refresh coaching to generate explanations. `;
  const processLink = document.createElement('a');
  processLink.href = `/processes?job_id=${jobId}`;
  processLink.textContent = 'Open Process to refresh coaching';
  coachReadinessWarningEl.append(text, processLink);
}
function showCoachRecapIssue(positionId, message) {
  if (!coachRecapWarningEl || Number(displayedPositionId) !== Number(positionId)) return;
  coachRecapWarningEl.textContent = `Attempted-move coaching could not be loaded: ${message}. Verified move attempts remain saved.`;
  coachRecapWarningEl.classList.remove('hidden');
}
function preserveCoachReviewInThread() {
  if (!coachChatEl) return;
  // Chronological teaching order is solution -> attempts -> original game.
  // prepend in reverse order because the thread is already populated.
  if (coachAttemptCommentsEl) coachChatEl.prepend(coachAttemptCommentsEl);
  if (coachPositionReviewEl) coachChatEl.prepend(coachPositionReviewEl);
}
function attemptNotesFromRecap(structured) {
  if (!structured || structured.kind !== 'solved_attempt_recap') return [];
  if (Array.isArray(structured.attempt_comments)) return structured.attempt_comments;
  // Older v77 recaps already saved their complete, verified attempt evidence.
  // Render them as separate comments without requiring new engine work.
  const attempts = Array.isArray(structured.attempts) ? structured.attempts : [];
  return attempts.map(attempt => {
    const san = attempt.move_san || attempt.move_uci || 'Move';
    const correct = Boolean(attempt.correct);
    let text;
    if (correct) text = structured.model_explanation || `${san} solved the position.`;
    else if (attempt.best_reply_san)
      text = `After ${san}, your opponent can respond with ${attempt.best_reply_san}. The saved evidence does not yet establish a specific tactical consequence.`;
    else text = `${san} was evaluated, but no detailed tactical continuation was retained.`;
    return {move_san:san, move_uci:attempt.move_uci, correct, text,
      cached:Boolean(attempt.from_saved_line)};
  });
}
function explanationPackageSnapshot() {
  // The solving thumbs must never rate another attempted continuation.
  return coachTextEl?.textContent?.trim() || '';
}
function renderCoachAttemptComments(recap, positionId = null) {
  if (!coachAttemptCommentsEl || !coachPositionReviewEl) return;
  if (positionId !== null && Number(displayedPositionId) !== Number(positionId)) return;
  let structured = recap;
  if (recap && typeof recap.structured_json === 'string') {
    try { structured = JSON.parse(recap.structured_json); } catch (_) { structured = {}; }
  }
  const notes = attemptNotesFromRecap(structured);
  const recapVersion = structured?.coaching_version || 'unknown generation';
  const isHistorical = Boolean(recapVersion !== currentPosition()?.coaching_version);
  coachAttemptCommentsEl.replaceChildren();
  const solutionNote = notes.find(note => note.origin === 'solving') || notes.find(note => note.correct && note.origin !== 'game');
  // A near-optimal accepted move can be the final correct attempt without being
  // Stockfish's primary choice. Never put that alternate line in Best move.
  const engineBestUci = solutionBestMoveUci || currentPosition()?.best_move_uci || '';
  const recapMatchesBest = Boolean(solutionNote?.move_uci && engineBestUci && solutionNote.move_uci === engineBestUci);
  if (coachSolutionLabelEl) {
    coachSolutionLabelEl.textContent = `Best move · ${solutionBestMoveSan || currentPosition()?.best_move_san || engineBestUci || '—'}`;
    coachSolutionLabelEl.dataset.fromRecap = (recapMatchesBest && !isHistorical) ? '1' : '0';
  }
  // A move attempted twice in the same session is the same continuation, not
  // two independently judged chess claims. The last verified note wins.
  const attempts = new Map();
  for (const note of notes.filter(entry => entry.origin !== 'solving' && entry.origin !== 'game' && !entry.correct)) {
    if (note.move_uci) attempts.set(note.move_uci, note);
  }
  // Legacy stored recaps may contain duplicates. Prefer an attempted learning
  // message, even if that move also appears as the original game move.
  const nonGames = [...attempts.values()];
  const attemptedRoots = new Set(nonGames.map(note => note.move_uci));
  const game = notes.find(entry => entry.origin === 'game' &&
    !attemptedRoots.has(entry.move_uci) && entry.move_uci !== solutionNote?.move_uci);
  for (const note of [...nonGames, ...(game ? [game] : [])]) {
    const key = note.move_uci;
    const section = document.createElement('div');
    section.className = 'coach-message assistant coach-continuation-message' + (note.origin === 'game' ? ' coach-game-message' : ' coach-learning-message');
    const title = document.createElement('div');
    title.className = 'coach-message-label';
    const purpose = note.origin === 'game' ? (note.purpose || (note.correct ? 'explanation' : 'learning')) : 'learning';
    title.textContent = `${note.origin === 'game' ? 'Game move' : 'Attempted move'} · ${note.move_san || key} · ${purpose === 'learning' ? 'Learning' : 'Explanation'}${isHistorical ? ` · Saved ${recapVersion}` : ''}`;
    const bubble = document.createElement('div');
    bubble.className = 'coach-message-body rate-hover-zone explanation-feedback-area';
    const copy = document.createElement('p');
    copy.className = 'coach-text';
    copy.textContent = note.text || 'No continuation-specific explanation was retained.';
    const votes = document.createElement('div');
    votes.className = 'inline-feedback-votes';
    votes.dataset.feedbackCategory = 'continuation';
    votes.dataset.continuationKey = note.origin === 'game' ? `game:${key}` : key;
    if (note.feedback_message_id) votes.dataset.feedbackMessageId = String(note.feedback_message_id);
    votes.setAttribute('role', 'group');
    votes.setAttribute('aria-label', `Was the coaching for ${note.move_san || key} helpful?`);
    votes.innerHTML = `<span class="rating-prompt">Helpful explanation?</span>
      <button type="button" class="inline-rating-button" data-rating="1" aria-label="Helpful explanation" title="Helpful explanation">👍</button>
      <button type="button" class="inline-rating-button" data-rating="-1" aria-label="Unhelpful explanation" title="Unhelpful explanation">👎</button>
      <button type="button" class="feedback-edit-correction hidden" aria-label="Edit suggested correction" title="Edit suggested correction">Edit suggestion</button>`;
    bubble.append(copy, votes);
    section.append(title, bubble);
    coachAttemptCommentsEl.append(section);
  }
  coachAttemptCommentsEl.classList.toggle('hidden', !coachAttemptCommentsEl.childElementCount);
  if (coachTextEl) {
    if (recapMatchesBest && !isHistorical && solutionNote.text) coachTextEl.textContent = solutionNote.text;
    else coachTextEl.textContent = currentPosition()?.coach_explanation ||
      'No verified explanation of the engine’s preferred move is available.';
    explainedPositionId = Number(displayedPositionId);
  }
  const solvingId = (recapMatchesBest && !isHistorical && solutionNote?.feedback_message_id) || currentPosition()?.feedback_message_id;
  document.querySelectorAll('.inline-feedback-votes[data-feedback-category="explanation"]').forEach(group => {
    if (solvingId) group.dataset.feedbackMessageId = String(solvingId);
    else delete group.dataset.feedbackMessageId;
  });
  void loadPositionRatings(Number(displayedPositionId));
  updatePositionRatingUI();
  if (notes.length && coachChatEl) coachChatEl.scrollTop = 0;
}
function clearCoachAttemptComments() {
  const positionMessageId = currentPosition()?.feedback_message_id;
  document.querySelectorAll('.inline-feedback-votes[data-feedback-category="explanation"]').forEach(group => {
    if (positionMessageId) group.dataset.feedbackMessageId = String(positionMessageId);
    else delete group.dataset.feedbackMessageId;
  });
  if (coachAttemptCommentsEl) {
    coachAttemptCommentsEl.replaceChildren();
    coachAttemptCommentsEl.classList.add('hidden');
  }
  if (coachSolutionLabelEl) {
    coachSolutionLabelEl.textContent = 'Best move';
    delete coachSolutionLabelEl.dataset.fromRecap;
  }
}
async function publishPostSolveCoach(position) {
  if (!position || !coachChatEl) return;
  const positionId = Number(position.id);
  const sessionKey = coachSolveSessionKey(positionId);
  try {
    const response = await fetch(`/api/positions/${positionId}/coach/solve-recap`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({session_key: sessionKey, evaluation_run_id: evaluationRunId})
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      showCoachRecapIssue(positionId, failure.error || `HTTP ${response.status}`);
      return;
    }
    const result = await response.json();
    if (displayedPositionId !== positionId) return;
    coachRecapWarningEl?.classList.add('hidden');
    const message = result.message;
    if (!message) {
      showCoachRecapIssue(positionId, 'The server returned no saved recap.');
      return;
    }
    if (coachThreadReadyPositionId !== positionId) {
      // A history load may have started before the solved recap was committed.
      // It is not an authoritative acknowledgement of THIS solve. Always
      // render the fresh recap returned by POST after the thread settles.
      await loadCoachThread(position);
      if (Number(displayedPositionId) !== positionId) return;
    }
    // POST returned the exact session's recap: never replace it with a stale
    // history snapshot from a concurrently loading thread.
    renderCoachAttemptComments(message, positionId);
    const meta = (() => {
      try { return JSON.parse(message.structured_json || '{}'); }
      catch (_) { return {}; }
    })();
    const wrongCount = (meta.attempts || []).filter(attempt => !attempt.correct).length;
    const learningCount = attemptNotesFromRecap(meta).filter(note =>
      !note.correct && note.origin !== 'game' && note.origin !== 'solving').length;
    if (wrongCount && !learningCount) {
      showCoachRecapIssue(positionId, `${wrongCount} wrong move(s) were saved, but their coaching notes were not returned.`);
    } else if (coachAttemptLogFailures.get(positionId)) {
      showCoachRecapIssue(positionId, `${coachAttemptLogFailures.get(positionId)} move(s) were verified but not saved as coach attempts; this recap may omit them.`);
    }
  } catch (error) {
    // A network or recap failure must not erase the learner's verified moves.
    showCoachRecapIssue(positionId, error?.message || 'Network request failed');
  }
}

const fmtCount = value => window.pctFormatCount ? window.pctFormatCount(value) : String(Number(value || 0));
let trainerKeyboardArmed = false;
let boardGridOrientation = null;
let renderedBoardMap = {};
let boardInteractive = false;
let boardDragController = null;
const boardSquares = new Map();

const PRE_MOVE_PAUSE_MS = 650;
const RETRY_PRE_MOVE_PAUSE_MS = 250;
const MOVE_ANIMATION_MS = 140;
const LAST_MOVE_HIGHLIGHT_MS = 500;
const WRONG_FEEDBACK_MS = 450;

const PIECES = {
  'K':'fa-chess-king', 'Q':'fa-chess-queen', 'R':'fa-chess-rook',
  'B':'fa-chess-bishop', 'N':'fa-chess-knight', 'P':'fa-chess-pawn',
  'k':'fa-chess-king', 'q':'fa-chess-queen', 'r':'fa-chess-rook',
  'b':'fa-chess-bishop', 'n':'fa-chess-knight', 'p':'fa-chess-pawn'
};

function categoryLabel(value) {
  return {
    missed_checkmate: 'Missed Checkmate',
    allowed_checkmate: 'Allowed Checkmate',
    threw_away_win: 'Winning → Losing Position',
    blundered_draw: 'Drawn → Losing Position',
    blundered_into_loss: 'Playable → Losing Position',
    squandered_advantage: 'Reduced Advantage',
    major_blunder: 'Major Blunder',
    blundered_win: 'Winning Position · Weakened',
    excellent_move: 'Excellent Move',
    brilliant_move: 'Brilliant / Creative Move',
    opposition_opportunity: 'Opponent Opportunity'
  }[value] || String(value || 'Training Position').replaceAll('_',' ');
}

function learningModeMeta(value, category='') {
  if (value === 'blunders') return {label:'Blunder / missed opportunity', tone:'blunder', icon:'!'};
  if (value === 'mistakes') return {label:'Consequential mistake', tone:'mistake'};
  return {
    excellent: {label:'Correct / excellent', tone:'correct'},
    brilliant: {label:'Creative / brilliant', tone:'brilliant'},
    opposition: {label:'Opponent opportunity', tone:'opposition'}
  }[value] || {label:'Training position', tone:'training'};
}

function renderConcepts(concepts = [], taxonomy = null) {
  if (taxonomy && currentPosition()) currentPosition().taxonomy = taxonomy;
  const el = document.getElementById('lesson-concepts');
  if (!el) return;
  el.replaceChildren();
  if (!concepts.length && !taxonomy?.levels?.length) {
    el.classList.add('hidden');
    updatePositionRatingUI();
    return;
  }
  if (taxonomy?.motif_key) {
    // The taxonomy itself is also the feedback interface after solving.
    // All selections are stored separately; the source analysis stays intact.
    renderTaxonomyPills();
  } else {
    for (const concept of concepts.filter(concept => concept.is_primary)) {
      const chip = document.createElement('span');
      chip.className = 'lesson-concept-chip primary';
      chip.textContent = concept.name;
      el.appendChild(chip);
    }
  }
  el.classList.remove('hidden');
  updatePositionRatingUI();
}

// Feedback belongs to the position, not a transient playlist or render cycle.
const positionRatings = new Map();
const positionCorrections = new Map();
const continuationRatings = new Map();
const continuationCorrections = new Map();
const displayedMessageRatings = new Map();
const displayedMessageCorrections = new Map();
const taxonomyFeedbackRecords = new Map();
const taxonomyFeedbackEl = document.getElementById('taxonomy-feedback');
const taxonomyFeedbackStatusEl = document.getElementById('taxonomy-feedback-status');
let suggestedMotifOptions = [];
const correctionDialog = document.getElementById('coaching-correction-dialog');
const correctionForm = document.getElementById('coaching-correction-form');
let correctionTarget = null;

function nextFeedbackRating(currentRating, clickedRating) {
  return Number(currentRating) === Number(clickedRating) ? 0 : Number(clickedRating);
}


function closeCorrectionDialog() {
  if (correctionDialog?.open) correctionDialog.close();
  correctionTarget = null;
}
function openCorrectionDialog(category, targetId, existing = {}, snapshot = '', continuationKey = '', messageSnapshotId = null) {
  if (!correctionDialog || !['position', 'explanation', 'coaching', 'continuation'].includes(category)) return;
  correctionTarget = {category, targetId, snapshot, continuationKey, messageSnapshotId};
  const position = category === 'position';
  const names = {position:'Improve this training position',
                 explanation:'Suggest a better explanation', continuation:'Improve this continuation', coaching:'Suggest a better coach response'};
  document.getElementById('coaching-correction-title').textContent = names[category];
  document.getElementById('coaching-correction-help').textContent = position
    ? 'What is wrong with this training position, or how could it be more useful?'
    : 'What should the coach have said instead? Your wording will be saved alongside the original response.';
  const textInput = document.getElementById('coaching-correction-text');
  textInput.required = true;
  textInput.value = existing.suggested_text || '';
  document.getElementById('coaching-correction-error').hidden = true;
  if (!correctionDialog.open) correctionDialog.showModal();
  requestAnimationFrame(() => textInput.focus());
}
correctionDialog?.addEventListener('close', () => { correctionTarget = null; });
document.getElementById('coaching-correction-close')?.addEventListener('click', closeCorrectionDialog);
document.getElementById('coaching-correction-skip')?.addEventListener('click', closeCorrectionDialog);
correctionForm?.addEventListener('submit', async event => {
  event.preventDefault();
  if (!correctionTarget) return;
  const {category, targetId, snapshot, continuationKey, messageSnapshotId} = correctionTarget;
  const value = document.getElementById('coaching-correction-text').value.trim();
  if (!value) return;
  const btn = document.getElementById('coaching-correction-save');
  const err = document.getElementById('coaching-correction-error');
  btn.disabled = true; err.hidden = true;
  try {
    const chat = category === 'coaching';
    const url = chat ? `/api/coach/messages/${targetId}/feedback` : `/api/positions/${targetId}/feedback`;
    const payload = {rating: -1, evaluation_run_id:evaluationRunId, lesson_key: new URLSearchParams(location.search).get('concept') || ''};
    if (!chat) {
      payload.category = category;
      payload.content_snapshot = snapshot;
      if (category === 'continuation') payload.continuation_key = continuationKey;
      if (messageSnapshotId) payload.message_snapshot_id = messageSnapshotId;
    }
    payload.suggested_text = value;
    const response = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save correction');
    if (evaluationRunId) updateEvaluationFeedbackState(Number(currentPosition()?.id), data.evaluation_feedback_saved === true);
    if (chat) {
      const element = document.querySelector(`.coach-response-feedback[data-message-id="${targetId}"]`);
      if (element) element.dataset.suggestedText = data.suggested_text || '';
    } else {
      if (messageSnapshotId) {
        displayedMessageRatings.set(targetId, data.message_ratings || {});
        displayedMessageCorrections.set(targetId, data.message_corrections || {});
      } else {
        positionRatings.set(targetId, data.ratings || {});
        positionCorrections.set(targetId, data.corrections || {});
      }
      if (!messageSnapshotId && category === 'continuation') {
        continuationRatings.set(targetId, data.continuation_ratings || {});
        continuationCorrections.set(targetId, data.continuation_corrections || {});
      }
      if (Number(currentPosition()?.id) === targetId) updatePositionRatingUI();
    }
    closeCorrectionDialog();
  } catch (e) {err.textContent = e.message || 'Could not save correction'; err.hidden = false;}
  finally {btn.disabled = false;}
});
let ratingRequestSerial = 0;
let explainedPositionId = null;
function positionSolvedForRating() {
  const p = currentPosition();
  // Benchmark completion belongs to the evaluation run, never global learning.
  return Boolean(p && (evaluationRunId ? solved : (solved || Number(p.learned) === 1)));
}
function solvingExplanationReadyForRating() {
  const p = currentPosition();
  if (!p || !positionSolvedForRating() || Number(displayedPositionId) !== Number(p.id)) return false;
  if (coachPositionReviewEl?.classList.contains('hidden')) return false;
  const text = explanationPackageSnapshot();
  // The old explainedPositionId marker can become stale when the coach thread
  // is replaced asynchronously (or a run-scoped recap loads after the solve).
  // Judge the *currently displayed* post-solve text instead.
  return Boolean(text && !/^Watch the last move[,\s]/i.test(text) &&
    !/^Find a strong move\.?$/i.test(text));
}
function setRatingFeedbackStatus(group, message, isError = false) {
  if (!group) return;
  let status = group.querySelector('.inline-rating-status');
  if (!status && message) {
    status = document.createElement('span');
    status.className = 'inline-rating-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    group.append(status);
  }
  if (!status) return;
  status.textContent = message || '';
  status.classList.toggle('error', Boolean(isError));
  status.classList.toggle('hidden', !message);
}
// A taxonomy pill is a native select with a visible pill label.  A native menu
// provides keyboard/touch support, while the pill always displays the coach's
// current label or the user's proposed replacement without adding a second row.
const taxonomyFieldNames = {context:'Position context', move_type:'Move type', motif:'Learning motif'};
let taxonomyWriteQueue = Promise.resolve();
function taxonomyPillOptions(field, p, record) {
  const choices = record.options || {};
  const defaults = field === 'context'
    ? [{key:'attack',name:'Attacking Plans'}, {key:'defend',name:'Defensive Resources'}]
    : field === 'move_type'
      ? [{key:'none',name:'No tactical/strategic qualifier'}, {key:'tactical',name:'Tactical Calculation'},
         {key:'strategic',name:'Strategic Comprehension'}]
      : suggestedMotifOptions.length ? suggestedMotifOptions
      : (p.concepts || []).map(c => ({key:c.key,name:c.name}));
  const options = choices[field] || defaults;
  const predicted = record.predicted || {};
  const model = predicted[field] || (field === 'move_type' ? p.taxonomy?.move_type_key || 'none'
    : field === 'context' ? p.taxonomy?.context_key : p.taxonomy?.motif_key) || '';
  const chosen = record.selected?.[field] || '';
  const modelName = p.taxonomy?.[field === 'motif' ? 'motif_name' : field === 'context' ? 'context_name' : 'move_type_name'];
  const byKey = new Map(options.map(option => [option.key, option.name]));
  if (model && !byKey.has(model)) byKey.set(model, modelName || model);
  if (chosen && !byKey.has(chosen)) byKey.set(chosen, chosen);
  return {choices:byKey,model,chosen,display:byKey.get(chosen || model) || modelName || 'Select motif'};
}
function createTaxonomyPill(field, position, record, optional=false) {
  const {choices,model,chosen,display} = taxonomyPillOptions(field,position,record);
  const pill = document.createElement('span');
  const corrected = Boolean(chosen && chosen !== model);
  pill.className = `lesson-concept-chip taxonomy-${field} taxonomy-pill${field === 'motif' ? ' primary' : ''}`
    + (corrected ? ' taxonomy-pill-edited' : chosen ? ' taxonomy-pill-confirmed' : '')
    + (optional ? ' taxonomy-pill-optional' : '');
  const label = document.createElement('span');
  label.className = 'taxonomy-pill-label';
  label.textContent = optional ? (chosen === 'none' ? 'No qualifier' : '+ Move type') : display;
  const chevron = document.createElement('span');
  chevron.className = 'taxonomy-pill-chevron';
  chevron.textContent = '⌄';
  chevron.setAttribute('aria-hidden','true');
  const select = document.createElement('select');
  select.className = 'taxonomy-feedback-select taxonomy-pill-native-select';
  select.dataset.taxonomyField = field;
  select.setAttribute('aria-label',`Review ${taxonomyFieldNames[field]}; ${chosen ? 'feedback: '+display : 'coach: '+display}`);
  select.title = `${taxonomyFieldNames[field]}: ${display}. Coach: ${choices.get(model) || model}. Select to provide feedback.`;
  select.add(new Option(`Use coach's label: ${choices.get(model) || model} (clear feedback)`,''));
  for (const [key,name] of [...choices].sort((a,b) =>
    Number(a[0].startsWith('evaluation_')) - Number(b[0].startsWith('evaluation_')) ||
    a[1].localeCompare(b[1], undefined, {sensitivity:'base'}))) {
    select.add(new Option(key === model ? `Confirm coach: ${name}` : name,key));
  }
  select.value = chosen;
  select.addEventListener('change', () => updateTaxonomyFeedbackChoice(select));
  pill.append(label,chevron,select);
  return pill;
}
function renderTaxonomyPills() {
  const p = currentPosition();
  const el = document.getElementById('lesson-concepts');
  if (!el || !p?.taxonomy?.motif_key) return;
  const record = taxonomyFeedbackRecords.get(Number(p.id)) || {};
  const move = taxonomyPillOptions('move_type',p,record);
  const hasQualifier = Boolean((move.chosen || move.model) && (move.chosen || move.model) !== 'none');
  el.replaceChildren();
  const path = ['context',...(hasQualifier ? ['move_type'] : []),'motif'];
  for (const [i,field] of path.entries()) {
    if (i) {
      const arrow = document.createElement('span');
      arrow.className = 'taxonomy-separator';
      arrow.textContent = '›';
      arrow.setAttribute('aria-hidden','true');
      el.appendChild(arrow);
    }
    el.appendChild(createTaxonomyPill(field,p,record));
  }
  if (!hasQualifier) el.appendChild(createTaxonomyPill('move_type',p,record,true));
  el.classList.remove('hidden');
}
function updateTaxonomyFeedbackUI(force=false) {
  if (!force && document.activeElement?.matches?.('.taxonomy-pill-native-select')) return;
  const p = currentPosition();
  const ready = positionSolvedForRating() && Boolean(p?.taxonomy?.motif_key);
  taxonomyFeedbackEl?.classList.toggle('hidden', !ready);
  if (!ready) return;
  if (taxonomyFeedbackStatusEl && taxonomyFeedbackStatusEl.dataset.positionId !== String(p.id)) {
    taxonomyFeedbackStatusEl.dataset.positionId = String(p.id);
    taxonomyFeedbackStatusEl.textContent = 'Select a learning pill to suggest a label. Changes affect feedback only, not the coach\'s analysis.';
  }
  renderTaxonomyPills();
}

async function updateTaxonomyFeedbackChoice(select) {
  const id = Number(currentPosition()?.id || 0);
  if (!id || !positionSolvedForRating()) return;
  const field = select.dataset.taxonomyField;
  const selectedKey = select.value;
  const previous = taxonomyFeedbackRecords.get(id)?.selected?.[field] || '';
  ++ratingRequestSerial; // An older feedback GET must not overwrite this selection.
  select.disabled = true;
  if (taxonomyFeedbackStatusEl) taxonomyFeedbackStatusEl.textContent = 'Saving taxonomy feedback…';
  const save = async () => {
    const response = await fetch(`/api/positions/${id}/taxonomy-feedback`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({field,selected_key:selectedKey,evaluation_run_id:evaluationRunId})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save taxonomy feedback');
    taxonomyFeedbackRecords.set(id, data.taxonomy_feedback);
    return data;
  };
  try {
    // Serialize rapid changes to different pills on one position, preserving
    // the server's authoritative selection snapshot across the three fields.
    const task = taxonomyWriteQueue.then(save,save);
    taxonomyWriteQueue = task.catch(() => {});
    await task;
    if (Number(currentPosition()?.id) !== id) return;
    if (evaluationRunId) updateEvaluationFeedbackState(id, data.evaluation_feedback_saved === true);
    if (taxonomyFeedbackStatusEl) taxonomyFeedbackStatusEl.textContent = selectedKey
      ? "Feedback saved. Select any pill again to change or clear your answer. The coach's analysis is unchanged."
      : "Feedback cleared for this field. The coach's original label is shown again.";
  } catch (error) {
    select.value = previous;
    if (Number(currentPosition()?.id) === id && taxonomyFeedbackStatusEl)
      taxonomyFeedbackStatusEl.textContent = error.message || 'Could not save taxonomy feedback';
  } finally {
    select.disabled = false;
    if (Number(currentPosition()?.id) === id) updateTaxonomyFeedbackUI(true);
  }
}

function updatePositionRatingUI() {
  const p = currentPosition();
  const ratings = positionRatings.get(Number(p?.id)) || {};
  const ready = positionSolvedForRating();
  updateTaxonomyFeedbackUI();
  document.querySelectorAll('.inline-feedback-votes[data-feedback-category]').forEach(group => {
    const category = group.dataset.feedbackCategory;
    const key = group.dataset.continuationKey;
    const messageId = Number(group.dataset.feedbackMessageId || (category === 'explanation' ? p?.feedback_message_id : 0));
    const messageVote = messageId ? (displayedMessageRatings.get(Number(p?.id)) || {})[String(messageId)] : undefined;
    const voted = messageId
      ? Number(messageVote || 0)
      : category === 'continuation' ? Number((continuationRatings.get(Number(p?.id)) || {})[key] || 0)
      : Number(ratings[category] || 0);
    const eligible = ready &&
      (!['explanation','continuation'].includes(category) || Boolean(messageId)) &&
      (category !== 'explanation' || solvingExplanationReadyForRating());
    group.classList.toggle('hidden', !eligible);
    group.querySelectorAll('[data-rating]').forEach(button => {
      const selected = eligible && voted === Number(button.dataset.rating);
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', String(selected));
      button.title = selected ? 'Remove this rating' : button.getAttribute('aria-label');
    });
    group.querySelector('.feedback-edit-correction')?.classList.toggle(
      'hidden', !eligible || voted !== -1);
  });
}
async function loadPositionRatings(positionId) {
  const id = Number(positionId || 0);
  if (!id) return;
  const serial = ++ratingRequestSerial;
  try {
    const response = await fetch(`/api/positions/${id}/feedback${evaluationRunId ? `?evaluation_run_id=${evaluationRunId}` : ""}`);
    if (!response.ok) return;
    const data = await response.json();
    if (serial !== ratingRequestSerial) return; // An earlier read must not erase a newly saved vote.
    positionRatings.set(id, data.ratings || {});
    positionCorrections.set(id, data.corrections || {});
    continuationRatings.set(id, data.continuation_ratings || {});
    continuationCorrections.set(id, data.continuation_corrections || {});
    displayedMessageRatings.set(id, data.message_ratings || {});
    displayedMessageCorrections.set(id, data.message_corrections || {});
    if (data.taxonomy_feedback) taxonomyFeedbackRecords.set(id, data.taxonomy_feedback);
    if (evaluationRunId) updateEvaluationFeedbackState(id, data.evaluation_feedback_saved === true);
    if (Array.isArray(data.motif_options)) suggestedMotifOptions = data.motif_options;
    if (Number(currentPosition()?.id) === id) updatePositionRatingUI();
  } catch (_) { /* Unavailable votes must not block training. */ }
}
async function ratePositionFeedback(button) {
  const position = currentPosition();
  const id = Number(position?.id || 0);
  if (!id || !positionSolvedForRating()) return;
  const group = button.closest('[data-feedback-category]');
  const category = group?.dataset.feedbackCategory;
  const chosenRating = Number(button.dataset.rating);
  if (!['position', 'explanation', 'continuation'].includes(category) || ![-1, 1].includes(chosenRating)) return;
  const messageId = Number(group.dataset.feedbackMessageId ||
    (category === 'explanation' ? position.feedback_message_id : 0));
  if (['explanation','continuation'].includes(category) && !messageId) return;
  const key = group.dataset.continuationKey || '';
  // Each failed continuation owns its vote and correction, independently of
  // solving and of all other attempted moves.
  const priorRating = messageId
    ? Number((displayedMessageRatings.get(id) || {})[String(messageId)] || 0)
    : category === 'continuation' ? Number((continuationRatings.get(id) || {})[key] || 0)
    : Number(positionRatings.get(id)?.[category] || 0);
  const rating = nextFeedbackRating(priorRating, chosenRating);
  const buttons = [...group.querySelectorAll('[data-rating]')];
  ++ratingRequestSerial; // Invalidate any in-flight GET from an earlier render.
  buttons.forEach(item => item.disabled = true);
  setRatingFeedbackStatus(group, '');
  try {
    const response = await fetch(`/api/positions/${id}/feedback`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        category, rating, evaluation_run_id:evaluationRunId, lesson_key: new URLSearchParams(location.search).get('concept') || '',
        content_snapshot: category === 'explanation' ? explanationPackageSnapshot()
          : category === 'continuation' ? group.closest('.coach-message')?.querySelector('.coach-text')?.textContent || '' : '',
        continuation_key: category === 'continuation' ? key : undefined,
        message_snapshot_id: messageId || undefined
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not save rating');
    if (evaluationRunId) updateEvaluationFeedbackState(id, data.evaluation_feedback_saved === true);
    if (messageId) {
      displayedMessageRatings.set(id, data.message_ratings || {});
      displayedMessageCorrections.set(id, data.message_corrections || {});
    } else {
      positionRatings.set(id, data.ratings || {});
      positionCorrections.set(id, data.corrections || {});
    }
    if (!messageId && category === 'continuation') {
      continuationRatings.set(id, data.continuation_ratings || {});
      continuationCorrections.set(id, data.continuation_corrections || {});
    }
    if (Number(currentPosition()?.id) === id) updatePositionRatingUI();
    group.title = rating === 0 ? 'Rating removed.' : rating === 1
      ? 'Helpful rating saved; any correction was removed.' : 'Rating saved — you can suggest an improvement.';
    // Explicit confirmation is useful when the thumbs are always visible in a
    // benchmark; it also distinguishes a saved vote from a failed request.
    setRatingFeedbackStatus(group, rating === 0 ? 'Rating withdrawn' : 'Rating saved');
    if (rating === -1) openCorrectionDialog(category, id,
      messageId ? (displayedMessageCorrections.get(id) || {})[String(messageId)] || {}
        : category === 'continuation' ? (continuationCorrections.get(id) || {})[key] || {}
        : positionCorrections.get(id)?.[category] || {},
      category === 'explanation' ? explanationPackageSnapshot()
        : category === 'continuation' ? group.closest('.coach-message')?.querySelector('.coach-text')?.textContent || '' : '', key, messageId);
    else if (correctionTarget?.targetId === id && correctionTarget?.category === category &&
             (category !== 'continuation' || correctionTarget.continuationKey === key)) closeCorrectionDialog();
  } catch (err) {
    const message = err.message || 'Could not save rating';
    group.title = message;
    setRatingFeedbackStatus(group, message, true);
    // A failed request never changes the selected vote state.
    if (Number(currentPosition()?.id) === id) updatePositionRatingUI();
  } finally {
    buttons.forEach(item => item.disabled = false);
  }
}

function handleExplanationFeedbackClick(event) {
  const group = event.target.closest('.inline-feedback-votes[data-feedback-category]');
  if (!group) return;
  const edit = event.target.closest('.feedback-edit-correction');
  if (edit && !edit.disabled) {
    const id = Number(currentPosition()?.id || 0);
    const category = group.dataset.feedbackCategory;
    const key = group.dataset.continuationKey || '';
    const messageId = Number(group.dataset.feedbackMessageId ||
      (category === 'explanation' ? currentPosition()?.feedback_message_id : 0));
    const rating = messageId ? (displayedMessageRatings.get(id) || {})[String(messageId)]
      : category === 'continuation' ? (continuationRatings.get(id) || {})[key]
      : positionRatings.get(id)?.[category];
    if (id && Number(rating || 0) === -1) {
      openCorrectionDialog(category, id,
        messageId ? (displayedMessageCorrections.get(id) || {})[String(messageId)] || {}
          : category === 'continuation' ? (continuationCorrections.get(id) || {})[key] || {}
          : positionCorrections.get(id)?.[category] || {},
        category === 'explanation' ? explanationPackageSnapshot()
          : category === 'continuation' ? group.closest('.coach-message')?.querySelector('.coach-text')?.textContent || '' : '', key, messageId);
    }
    return;
  }
  const button = event.target.closest('[data-rating]');
  if (button && !button.disabled) ratePositionFeedback(button);
}
document.addEventListener('click', event => {
  if (event.target.closest('.inline-feedback-votes[data-feedback-category]'))
    handleExplanationFeedbackClick(event);
});

function parseFen(fen) {
  const board = {};
  const rows = fen.split(' ')[0].split('/');
  rows.forEach((row, r) => {
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) file += Number(ch);
      else {
        const square = 'abcdefgh'[file] + (8 - r);
        board[square] = ch;
        file += 1;
      }
    }
  });
  return board;
}

function squaresForOrientation(color) {
  const orientation = String(color || '').toLowerCase() === 'black' ? 'black' : 'white';
  const files = orientation === 'black' ? 'hgfedcba' : 'abcdefgh';
  const ranks = orientation === 'black' ? [1,2,3,4,5,6,7,8] : [8,7,6,5,4,3,2,1];
  const out = [];
  for (const rank of ranks) for (const file of files) out.push(`${file}${rank}`);
  return out;
}


function isPieceForColor(piece, color) {
  if (!piece || !color) return false;
  const isWhite = piece === piece.toUpperCase();
  return color === 'white' ? isWhite : !isWhite;
}

function analysisModeActive() {
  return solved && Boolean(engineToggleEl?.checked);
}

function fenTurnColor(fen) {
  // The solved board shows the *result* of the accepted move the user played,
  // so the next piece to move may belong to the opponent, not the learner.
  const turn = String(fen || '').split(/\s+/)[1];
  return turn === 'w' ? 'white' : turn === 'b' ? 'black' : null;
}

function interactionColor(position) {
  if (!solved) return position.user_color;
  return analysisModeActive() ? (analysisTurn || fenTurnColor(currentDisplayedFen())) : fenTurnColor(currentDisplayedFen());
}

function clearPreviewTimers() {
  previewTimers.forEach(timer => clearTimeout(timer));
  previewTimers = [];
  boardEl.querySelectorAll('.moving-piece').forEach(el => el.remove());
}

function clearBoardMark() {
  boardMarkEl.className = 'board-feedback-mark hidden';
  boardMarkEl.textContent = '';
}

function showBoardMark(kind) {
  boardMarkEl.className = `board-feedback-mark ${kind}`;
  boardMarkEl.textContent = kind === 'correct' ? '✓' : '×';
}

function ensureBoardGrid(position) {
  const orientation = String(position.user_color || '').toLowerCase() === 'black' ? 'black' : 'white';
  if (boardGridOrientation === orientation && boardSquares.size === 64) return orientation;
  boardGridOrientation = orientation;
  boardSquares.clear();
  boardEl.innerHTML = '';
  boardEl.dataset.orientation = orientation;
  boardEl.classList.toggle('black-orientation', orientation === 'black');
  const fragment = document.createDocumentFragment();
  for (const squareName of squaresForOrientation(orientation)) {
    const fileIndex = squareName.charCodeAt(0) - 97;
    const rank = Number(squareName[1]);
    const square = document.createElement('div');
    square.className = `square ${(fileIndex + rank) % 2 === 1 ? 'dark' : 'light'}`;
    square.dataset.square = squareName;
    const coordinate = document.createElement('span');
    coordinate.className = 'square-coordinate';
    const file = squareName[0], rankLabel = squareName[1];
    const fileEdge = orientation === 'black' ? '8' : '1';
    const rankEdge = orientation === 'black' ? 'h' : 'a';
    coordinate.textContent = rankLabel === fileEdge ? file : (file === rankEdge ? rankLabel : '');
    square.appendChild(coordinate);
    boardSquares.set(squareName, square);
    fragment.appendChild(square);
  }
  boardEl.appendChild(fragment);
  return orientation;
}

function updatePieceOnSquare(square, squareName, pieceCode, canInteract, activeColor) {
  let piece = square.querySelector('.piece');
  if (!pieceCode) { if (piece) piece.remove(); return; }
  const isWhitePiece = pieceCode === pieceCode.toUpperCase();
  const className = `piece fa-solid ${PIECES[pieceCode]} ${isWhitePiece ? 'white-piece' : 'black-piece'}`;
  if (!piece) { piece = document.createElement('i'); piece.setAttribute('aria-hidden', 'true'); square.appendChild(piece); }
  if (piece.className !== className) piece.className = className;
  piece.style.visibility = '';
  piece.style.transform = '';
  piece.dataset.from = squareName;
  // Pointer-based dragging supports mouse and touch without interfering with
  // the existing click-piece/click-destination move entry.
  piece.draggable = false;
}

function renderBoard(position, fen = position.fen, interactive = true) {
  boardDragController?.cancel();
  displayedFen = fen;
  const board = parseFen(fen);
  ensureBoardGrid(position);
  hideEngineArrow();
  boardEl.querySelectorAll('.moving-piece, .best-move-preview').forEach(el => el.remove());
  // A solved position is ready for a new branch even before Stockfish is
  // explicitly enabled. Its first move will enable analysis automatically.
  const canInteract = Boolean(interactive && (solved
    ? (analysisModeActive() ? (analysisTurn || fenTurnColor(fen)) : fenTurnColor(fen))
    : !inputLocked));
  const activeColor = interactionColor(position);
  renderedBoardMap = board;
  boardInteractive = Boolean(canInteract);
  boardEl.classList.toggle('is-interactive', boardInteractive);
  for (const [squareName, square] of boardSquares.entries()) {
    square.classList.remove('selected','legal-target','correct','wrong','near-optimal','last-move');
    updatePieceOnSquare(square, squareName, board[squareName], canInteract, activeColor);
  }
}

function activateSolvedBoardAnalysis({deferEvaluation = false} = {}) {
  if (!solved || engineToggleEl.disabled || engineToggleEl.checked) return false;
  engineToggleEl.checked = true;
  clearBoardMark();
  updateHistoryUI();
  engineEvalEl.textContent = '…';
  // An engine response can re-render the board and cancel an ongoing drag.
  // In that case playAnalysisMove() requests the fresh evaluation after drop.
  if (!deferEvaluation) refreshEngineEvaluation();
  return true;
}

// Drag-and-drop and click-to-move must both use the same legal-move resolver.
// The pointer controller waits for real movement before starting a drag, so
// taps/clicks are left intact and dragging works on touch screens too.
boardDragController = window.installBoardPointerDrag(boardEl, {
  canStart: from => boardInteractive &&
    isPieceForColor(renderedBoardMap[from], interactionColor(currentPosition())),
  onStart: from => {
    activateSolvedBoardAnalysis({deferEvaluation: true});
    selectedSquare = from;
    paintSelection();
  },
  onDrop: (from, to) => {
    const legalMove = boardInteractive ? resolveBoardMove(from, to) : null;
    selectedSquare = null;
    paintSelection();
    if (legalMove) submitBoardMove(from, to, legalMove);
    else if (analysisModeActive()) refreshEngineEvaluation();
  },
  onCancel: () => {
    selectedSquare = null;
    paintSelection();
    if (analysisModeActive()) refreshEngineEvaluation();
  }
});
boardEl.addEventListener('click', event => {
  const square = event.target.closest?.('.square');
  if (!square || !boardInteractive) return;
  handleSquareClick(square.dataset.square, renderedBoardMap);
});

function animateMove(position, from, to, onComplete, cancellable = true) {
  const fromEl = boardEl.querySelector(`[data-square="${from}"]`);
  const toEl = boardEl.querySelector(`[data-square="${to}"]`);
  const pieceEl = fromEl ? fromEl.querySelector('.piece') : null;
  const capturedEl = toEl ? toEl.querySelector('.piece') : null;

  if (!fromEl || !toEl || !pieceEl) {
    onComplete();
    return;
  }

  const boardRect = boardEl.getBoundingClientRect();
  const fromRect = fromEl.getBoundingClientRect();
  const toRect = toEl.getBoundingClientRect();
  const moving = pieceEl.cloneNode(true);
  moving.classList.add('moving-piece');
  moving.draggable = false;
  moving.style.left = `${fromRect.left - boardRect.left}px`;
  moving.style.top = `${fromRect.top - boardRect.top}px`;
  moving.style.width = `${fromRect.width}px`;
  moving.style.height = `${fromRect.height}px`;
  moving.style.transitionDuration = `${MOVE_ANIMATION_MS}ms`;
  boardEl.appendChild(moving);
  pieceEl.style.visibility = 'hidden';
  if (capturedEl && capturedEl !== pieceEl) capturedEl.style.visibility = 'hidden';

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      moving.style.transform = `translate(${toRect.left - fromRect.left}px, ${toRect.top - fromRect.top}px)`;
    });
  });

  const timer = setTimeout(onComplete, MOVE_ANIMATION_MS);
  if (cancellable) previewTimers.push(timer);
}


function escapeCoachHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function coachMessageHtml(message) {
  const role = message.role === 'user' ? 'user' : 'assistant';
  const label = role === 'user' ? 'You' : 'Coach';
  let verdict = '';
  let historicalLink = '';
  let brilliantLink = '';
  let historical = false;
  let brilliant = false;
  let solvedRecap = false;
  let generatedWith = message.generation_version || '';
  try {
    const structured = typeof message.structured_json === 'string'
      ? JSON.parse(message.structured_json || '{}')
      : (message.structured_json || {});
    generatedWith = generatedWith || structured.coaching_version || '';
    const claims = structured.claims || [];
    if (role === 'assistant' && claims.length && claims[0].verdict) {
      const v = claims[0].verdict;
      verdict = `<span class="coach-verdict ${escapeCoachHtml(v)}">${escapeCoachHtml(v)}</span>`;
    }
    const reference = structured.historical_reference;
    historical = role === 'assistant' && structured.kind === 'historical_reference';
    brilliant = role === 'assistant' && structured.kind === 'brilliant_reference';
    solvedRecap = role === 'assistant' && structured.kind === 'solved_attempt_recap';
    // Only an HTTPS link is allowed in the stored history message. Text and
    // href attributes are escaped; other coaching text stays plain text.
    if (historical && reference && /^https:\/\/[^\s<>"']+$/.test(String(reference.source_url || ''))) {
      historicalLink = `<a class="historic-coach-link" href="${escapeCoachHtml(reference.source_url)}" target="_blank" rel="noopener noreferrer">Explore ${escapeCoachHtml(reference.title || 'the game')} ↗</a>`;
    }
    const own = structured.brilliant_reference;
    // Only accept trainer URLs the app itself can create; never render an
    // arbitrary URL from stored conversation data as a clickable link.
    if (brilliant && own && /^\/trainer\/\d+\?position=\d+$/.test(String(own.url || ''))) {
      brilliantLink = `<a class="historic-coach-link" href="${escapeCoachHtml(own.url)}">${escapeCoachHtml(own.title || 'Review this position')} ↗</a>`;
    }
  } catch (_) {}
  // Stored session recaps are expanded into separate, independently rated
  // continuation cards above, avoiding a duplicate combined chat paragraph.
  if (solvedRecap) return '';
  const messageId = Number(message.id || 0);
  const rating = Number(message.feedback_rating || 0);
  const feedback = role === 'assistant' && messageId && !historical && !brilliant && !solvedRecap
    ? `<div class="coach-response-feedback" data-message-id="${messageId}" data-suggested-text="${escapeCoachHtml(message.feedback_suggested_text || '')}" aria-label="Rate this coaching response">
         <button type="button" class="coach-feedback-button${rating === 1 ? ' active' : ''}" data-rating="1" title="Helpful coaching response" aria-label="Thumbs up" aria-pressed="${rating === 1}">👍</button>
         <button type="button" class="coach-feedback-button${rating === -1 ? ' active' : ''}" data-rating="-1" title="Unhelpful coaching response" aria-label="Thumbs down" aria-pressed="${rating === -1}">👎</button>
         <button type="button" class="feedback-edit-correction${rating === -1 ? '' : ' hidden'}" title="Edit your suggestion" aria-label="Edit coaching suggestion">Edit suggestion</button>
       </div>`
    : '';
  return `<div class="coach-message ${role}${historical ? ' historic-coach-message' : ''}${brilliant ? ' brilliant-coach-message' : ''}"${messageId ? ` data-message-id="${messageId}"` : ''}><div class="coach-message-label">${historical ? 'Coach · Chess history' : brilliant ? 'Coach · From your games' : solvedRecap ? 'Coach · Your attempted moves' : label}${role === 'assistant' && generatedWith ? ` · ${escapeCoachHtml(generatedWith)}` : ''}</div>${verdict}<div class="coach-message-body">${escapeCoachHtml(message.content)}${historicalLink || brilliantLink ? `<div class="historic-coach-link-row">${historicalLink || brilliantLink}</div>` : ''}</div>${feedback}</div>`;
}

// The server stores each historical reference as an ordinary coach message,
// and records a single event per game list and historic game. The chat keeps
// that first introduction; navigating among solved cards never repeats it.
async function maybeOfferHistoricalCoach(position) {
  if (!coachChatEl || !position || !solved || !position.learned ||
      displayedPositionId !== position.id || coachThreadReadyPositionId !== position.id ||
      historicCoachRequests.has(position.id)) return;
  historicCoachRequests.add(position.id);
  try {
    const response = await fetch(`/api/positions/${position.id}/historical-coach`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({opening_playlist: Boolean(openingKey)})
    });
    if (!response.ok) return;
    const result = await response.json();
    if (!result.shown || displayedPositionId !== position.id || coachThreadReadyPositionId !== position.id) return;
    appendCoachMessage('assistant', result.content, {
      kind: 'historical_reference', historical_reference: result.reference
    }, result.message_id);
    return true;
  } catch (_) {
    // Proactive context is optional; an unavailable database does not block training.
  }
}

// Propose at most a few distinct creative moves per game list, not on every
// revisit. The server owns the once-per-source-game deduplication.
async function maybeOfferBrilliantCoach(position) {
  if (!coachChatEl || !position || !solved || !position.learned ||
      displayedPositionId !== position.id || coachThreadReadyPositionId !== position.id ||
      brilliantCoachRequests.has(position.id)) return;
  brilliantCoachRequests.add(position.id);
  try {
    const response = await fetch(`/api/positions/${position.id}/brilliant-coach`, {method:'POST'});
    if (!response.ok) return;
    const result = await response.json();
    if (!result.shown || displayedPositionId !== position.id || coachThreadReadyPositionId !== position.id) return;
    appendCoachMessage('assistant', result.content, {
      kind:'brilliant_reference', brilliant_reference:result.reference
    }, result.message_id);
  } catch (_) {
    // Review suggestions are optional and must never block training.
  }
}

function maybeOfferProactiveCoach(position) {
  if (!position || !coachChatEl || !solved || !position.learned || evaluationRunId || !coachingAvailableForPosition(position)) return Promise.resolve();
  if (proactiveCoachRequests.has(position.id)) return proactiveCoachRequests.get(position.id);
  const promise = maybeOfferHistoricalCoach(position).then(shown => {
    if (!shown && displayedPositionId === position.id) return maybeOfferBrilliantCoach(position);
  });
  proactiveCoachRequests.set(position.id, promise);
  return promise;
}

function updateCoachMode() {
  if (!coachModeNoteEl || !coachInputEl) return;
  const available = coachingAvailableForPosition(currentPosition());
  coachInputEl.disabled = !available;
  if (coachSendEl) coachSendEl.disabled = !available;
  if (!available) {
    coachModeNoteEl.textContent = 'Chess training remains available. Refresh coaching for this position before chatting or rating its explanations.';
    coachInputEl.placeholder = 'Coaching requires a current-model refresh…';
    return;
  }
  if (solved) {
    coachModeNoteEl.textContent = 'Solved: ask why, test a move or variation, or explore a learning motif.';
    coachInputEl.placeholder = 'Try: Why is this better? What if d6? Show me a pin.';
  } else {
    coachModeNoteEl.textContent = 'Ask about a candidate move; the engine preference stays hidden until solve.';
    coachInputEl.placeholder = 'Ask naturally about a move or idea you are considering…';
  }
}

async function loadCoachThread(position) {
  if (!coachChatEl || !position) return;
  const threadRequest = ++coachThreadLoadSerial;
  coachThreadReadyPositionId = null;
  if (!coachingAvailableForPosition(position) || !position?.coach_explanation) {
    // No saved messages or generated prose is available for this position.
    coachChatEl.innerHTML = '<div class="coach-empty">Coaching messages require a refresh for this game list.</div>';
    preserveCoachReviewInThread();
    clearCoachAttemptComments();
    coachThreadReadyPositionId = position.id;
    updatePositionRatingUI();
    updateCoachMode();
    return;
  }
  coachConceptEventEl?.classList.add('hidden');
  coachChatEl.innerHTML = '<div class="coach-empty">Loading coaching thread…</div>';
  let lastRecap = null;
  try {
    const response = await fetch(`/api/positions/${position.id}/coach${evaluationRunId ? `?run_id=${evaluationRunId}` : ""}`, {cache: "no-store"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load coach');
    if (displayedPositionId !== position.id || threadRequest !== coachThreadLoadSerial) return;
    const messages = result.messages || [];
    lastRecap = solved ? [...messages].reverse().find(message => {
      try { return JSON.parse(message.structured_json || '{}').kind === 'solved_attempt_recap'; }
      catch (_) { return false; }
    }) : null;
    const visibleMessages = messages.map(coachMessageHtml).filter(Boolean);
    if (!visibleMessages.length) {
      coachChatEl.innerHTML = solved && coachPositionReviewEl ? '' : `<div class="coach-empty">${solved
        ? 'Ask about a move, line, plan, or concept. Try: <em>“What if Nc3?”</em>'
        : 'Ask about a candidate move or idea. The coach can test your move without revealing the engine preference.'}</div>`;
    } else {
      coachChatEl.innerHTML = visibleMessages.join('');
      coachChatEl.scrollTop = coachChatEl.scrollHeight;
    }
  } catch (error) {
    if (displayedPositionId !== position.id || threadRequest !== coachThreadLoadSerial) return;
    coachChatEl.innerHTML = `<div class="coach-empty">Coach history unavailable: ${escapeCoachHtml(error.message)}</div>`;
  }
  if (displayedPositionId !== position.id || threadRequest !== coachThreadLoadSerial) return;
  preserveCoachReviewInThread();
  if (solved) renderCoachAttemptComments(lastRecap, position.id);
  coachThreadReadyPositionId = position.id;
  // Fetching/rebuilding the thread detaches the static explanation bubble;
  // restore its thumbs state after reattaching it, including Last Position.
  updatePositionRatingUI();
  updateCoachMode();
  if (solved) void maybeOfferProactiveCoach(position);
}

function appendCoachMessage(role, content, structured = null, messageId = null, feedbackRating = null) {
  if (!coachChatEl) return;
  coachChatEl.querySelector('.coach-empty')?.remove();
  coachChatEl.insertAdjacentHTML('beforeend', coachMessageHtml({
    id: messageId,
    role,
    content,
    feedback_rating: feedbackRating,
    structured_json: structured ? JSON.stringify(structured) : null,
  }));
  coachChatEl.scrollTop = coachChatEl.scrollHeight;
}

function coachDialogueContext(position) {
  const targetPly = contextTargetPly();
  let stage = 'puzzle';
  if (solved || solvingMoveUci) stage = 'post_solution';
  if (reviewStage === 'analysis' && analysisLineDepth > 0) stage = 'analysis_continuation';
  else if (reviewStage === 'history' && currentContext?.available && historyPly < targetPly) stage = 'game_history';

  return {
    stage,
    puzzle_fen: position?.fen || '',
    displayed_fen: currentDisplayedFen(),
    solving_move_uci: solvingMoveUci,
    solving_move_san: solvingMoveSan,
    solving_fen: solvingMoveFen,
    best_move_uci: solutionBestMoveUci,
    best_move_san: solutionBestMoveSan,
    analysis_line_uci: [...analysisLineUci],
    analysis_line_san: [...analysisLineSan],
    analysis_line_depth: analysisLineDepth,
    history_ply: historyPly,
    target_history_ply: targetPly,
    engine_review_active: Boolean(engineToggleEl?.checked),
    session_solved: Boolean(solved),
  };
}

async function sendCoachMessage(event) {
  event?.preventDefault();
  const position = currentPosition();
  const text = coachInputEl?.value.trim();
  if (!position || !text || !coachFormEl) return;
  appendCoachMessage('user', text);
  coachInputEl.value = '';
  coachFormEl.classList.add('sending');
  if (coachSendEl) coachSendEl.textContent = 'Thinking…';
  try {
    const response = await fetch(`/api/positions/${position.id}/coach`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        text,
        fen: currentDisplayedFen(),
        dialogue_context: coachDialogueContext(position),
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Coach could not respond');
    appendCoachMessage('assistant', result.reply || 'I could not form a useful conclusion.', {claims: result.claims || []}, result.message_id);
    const updates = result.concept_updates || [];
    if (coachConceptEventEl && updates.length) {
      const promoted = updates.find(item => ['personal','promoted'].includes(item.status));
      const latest = promoted || updates[updates.length - 1];
      coachConceptEventEl.textContent = promoted
        ? `Personal lesson learned · ${latest.name || 'New concept'} · ${latest.games || 0} games matched. It will be used by future analysis passes.`
        : `Candidate concept saved · ${latest.name || 'New concept'} · ${latest.games || 0} matching game(s) found so far.`;
      coachConceptEventEl.classList.remove('hidden');
    }
  } catch (error) {
    appendCoachMessage('assistant', `I could not verify that yet: ${error.message}`);
  } finally {
    coachFormEl.classList.remove('sending');
    if (coachSendEl) coachSendEl.textContent = 'Send';
    coachInputEl?.focus();
  }
}

function currentPosition() {
  return positions[currentIndex];
}

// Hints are pre-solve guidance, not coaching explanations. The latter may
// live inside a hidden post-solve chat message when Adaptive Coach is enabled.
function resetHint() {
  if (hintTextEl) {
    hintTextEl.textContent = '';
    hintTextEl.classList.add('hidden');
  }
  if (hintToggleEl) {
    hintToggleEl.textContent = 'Show hint';
    hintToggleEl.setAttribute('aria-expanded', 'false');
  }
}

function toggleHint() {
  if (solved || !hintToggleEl || !hintTextEl || !currentPosition()) return;
  if (hintToggleEl.getAttribute('aria-expanded') === 'true') {
    resetHint();
    return;
  }
  hintTextEl.textContent = String(currentPosition().coach_prompt || '').trim()
    || 'Read the position, identify the opponent’s threat, and find a strong response.';
  hintTextEl.classList.remove('hidden');
  hintToggleEl.textContent = 'Hide hint';
  hintToggleEl.setAttribute('aria-expanded', 'true');
}

function setShareLink(link, url) {
  if (!link) return;
  link.classList.toggle('unavailable', !url);
  link.setAttribute('aria-disabled', String(!url));
  link.href = url || '#';
  if (!url) link.removeAttribute('download');
}

function closeGameShare() {
  if (!gameShareMenuEl || !gameShareToggleEl) return;
  gameShareMenuEl.hidden = true;
  gameShareToggleEl.setAttribute('aria-expanded', 'false');
}

function resetGameShare() {
  activeGameShare = null;
  closeGameShare();
  if (shareCopyPgnEl) shareCopyPgnEl.disabled = true;
  if (shareCopyLichessEl) shareCopyLichessEl.disabled = true;
  setShareLink(shareDownloadPgnEl, null);
  setShareLink(shareOpenLichessEl, null);
  if (gameShareMessageEl) gameShareMessageEl.textContent = '';
}

function renderGameShare(share) {
  activeGameShare = share;
  const hasPgn = Boolean(share?.pgn);
  const hasLichess = Boolean(share?.lichess_url);
  shareCopyPgnEl.disabled = !hasPgn;
  shareCopyLichessEl.disabled = !hasLichess;
  setShareLink(shareDownloadPgnEl, hasPgn ? share.download_url : null);
  if (hasPgn) shareDownloadPgnEl.download = share.filename || 'chess-game.pgn';
  setShareLink(shareOpenLichessEl, hasLichess ? share.lichess_url : null);
  if (gameShareMessageEl) gameShareMessageEl.textContent = !hasPgn && !hasLichess
    ? 'The original PGN and Lichess link are unavailable for this position.'
    : !hasLichess ? 'No original Lichess game URL is recorded.' : '';
}

async function openGameShare() {
  const position = currentPosition();
  if (!position || !gameShareMenuEl || !gameShareToggleEl) return;
  if (!gameShareMenuEl.hidden) { closeGameShare(); return; }
  gameShareMenuEl.hidden = false;
  gameShareToggleEl.setAttribute('aria-expanded', 'true');
  gameShareMessageEl.textContent = 'Loading original game…';
  const positionId = Number(position.id);
  if (gameShareCache.has(positionId)) {
    renderGameShare(gameShareCache.get(positionId));
    return;
  }
  try {
    const response = await fetch(`/api/positions/${positionId}/share`);
    const share = await response.json();
    if (!response.ok) throw new Error(share.error || 'Unable to load game details.');
    gameShareCache.set(positionId, share);
    // A quick Last/Next click must never expose a different game's PGN.
    if (Number(currentPosition()?.id) === positionId) renderGameShare(share);
  } catch (error) {
    if (Number(currentPosition()?.id) === positionId) gameShareMessageEl.textContent = error.message || 'Share options unavailable.';
  }
}

async function copyShareText(text, successMessage) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const temporary = document.createElement('textarea');
      temporary.value = text;
      temporary.style.cssText = 'position:fixed;left:-9999px;top:0;';
      document.body.appendChild(temporary);
      temporary.select();
      const copied = document.execCommand('copy');
      temporary.remove();
      if (!copied) throw new Error('Copy not supported');
    }
    gameShareMessageEl.textContent = successMessage;
  } catch (_) {
    gameShareMessageEl.textContent = 'Could not copy automatically. Try opening the link or downloading the PGN.';
  }
}

gameShareToggleEl?.addEventListener('click', openGameShare);
shareCopyPgnEl?.addEventListener('click', () => {
  if (activeGameShare?.pgn) copyShareText(activeGameShare.pgn, 'Original game PGN copied.');
});
shareCopyLichessEl?.addEventListener('click', () => {
  if (activeGameShare?.lichess_url) copyShareText(activeGameShare.lichess_url, 'Lichess game link copied.');
});
document.addEventListener('pointerdown', event => {
  if (gameShareMenuEl && !gameShareMenuEl.hidden && !gameShareRootEl?.contains(event.target)) closeGameShare();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && gameShareMenuEl && !gameShareMenuEl.hidden) {
    closeGameShare();
    gameShareToggleEl?.focus();
  }
});

function contextTargetPly() {
  return currentContext?.available ? Number(currentContext.target_history_ply || 0) : 0;
}

function fenAtHistoryPly(ply) {
  if (!currentContext?.available) return currentPosition()?.fen;
  if (ply <= 0) return currentContext.initial_fen;
  const move = currentContext.moves[ply - 1];
  return move ? move.fen_after : currentContext.target_fen;
}

function syncAnalysisLineState() {
  const active = analysisFrames.slice(0, analysisCursor);
  analysisLineUci = active.map(frame => frame.moveUci);
  analysisLineSan = active.map(frame => frame.moveSan || frame.moveUci);
  analysisLineDepth = active.length;
}

function clearAnalysisBranch() {
  analysisBase = null;
  analysisFrames = [];
  analysisCursor = 0;
  analysisLegalMoves = [];
  analysisTurn = null;
  syncAnalysisLineState();
}

function sameAnalysisOrigin() {
  if (!analysisBase) return false;
  return analysisBase.stage === reviewStage
    && Number(analysisBase.historyPly) === Number(historyPly)
    && analysisBase.fen === currentDisplayedFen();
}

function prepareAnalysisBranch() {
  if (reviewStage === 'analysis') return;
  if (!sameAnalysisOrigin()) {
    analysisBase = {
      fen: currentDisplayedFen(),
      historyPly,
      stage: reviewStage,
      status: historyStatusEl?.textContent || 'Analysis position',
    };
    analysisFrames = [];
    analysisCursor = 0;
    syncAnalysisLineState();
  }
}

function updateHistoryUI() {
  const target = contextTargetPly();
  let canBack = Boolean(currentContext?.available && historyPly > 0);
  let canForward = Boolean(currentContext?.available && historyPly < target);

  if (reviewStage === 'solved') {
    canBack = Boolean(currentContext?.available);
    canForward = Boolean(analysisBase?.stage === 'solved' && analysisFrames.length);
  } else if (reviewStage === 'analysis') {
    canBack = true;
    canForward = analysisCursor < analysisFrames.length;
  } else if (reviewStage === 'history' && historyPly === target && solvedReviewFen) {
    // The solved move is a virtual review node after the canonical puzzle FEN.
    canForward = true;
  }

  historyBackEl.disabled = !canBack;
  historyForwardEl.disabled = !canForward;

  if (reviewStage === 'analysis') {
    const frame = analysisFrames[Math.max(0, analysisCursor - 1)];
    historyStatusEl.textContent = frame
      ? `Analysis line · ${frame.moveSan || frame.moveUci} · ${analysisCursor}/${analysisFrames.length}`
      : 'Analysis line';
  } else if (reviewStage === 'solved') {
    historyStatusEl.textContent = 'Solved position';
  } else if (!currentContext?.available) {
    historyStatusEl.textContent = 'Game history unavailable for this older position';
  } else if (historyPly === target) {
    historyStatusEl.textContent = 'Training position';
  } else if (historyPly === 0) {
    historyStatusEl.textContent = 'Starting position';
  } else {
    const move = currentContext.moves[historyPly - 1];
    const notation = move.color === 'white' ? `${move.move_number}. ${move.san}` : `${move.move_number}... ${move.san}`;
    historyStatusEl.textContent = `After ${notation}`;
  }

  updateAnalysisIndicator();
  pgnMovesEl.querySelectorAll('.pgn-move').forEach(el => {
    el.classList.toggle('current', Number(el.dataset.ply) === historyPly);
  });
}

function setHistoryPly(ply) {
  if (!currentContext?.available) return;
  reviewStage = 'history';
  showingSolvedMove = false;
  analysisLegalMoves = [];
  analysisTurn = null;
  clearPreviewTimers();
  clearBoardMark();
  selectedSquare = null;
  const target = contextTargetPly();
  historyPly = Math.max(0, Math.min(Number(ply), target));
  inputLocked = historyPly !== target || solved;
  const canInteract = (!solved && historyPly === target) || analysisModeActive();
  renderBoard(currentPosition(), fenAtHistoryPly(historyPly), solved || canInteract);
  clearHighlights();
  updateHistoryUI();

  if (!solved) {
    feedbackEl.className = 'feedback neutral';
  feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = historyPly === target
      ? ''
      : 'Reviewing the game. Move forward to return to the puzzle.';
    feedbackEl.classList.toggle('hidden', historyPly === target);
  } else if (engineToggleEl.checked) {
    refreshEngineEvaluation();
  }
}

function showSolvedReviewPosition() {
  if (!solvedReviewFen) return false;
  reviewStage = 'solved';
  showingSolvedMove = true;
  historyPly = contextTargetPly();
  analysisLegalMoves = [];
  analysisTurn = null;
  selectedSquare = null;
  clearBoardMark();
  clearHighlights();
  renderBoard(currentPosition(), solvedReviewFen, true);
  highlightSolvedMoveComparison();
  updateHistoryUI();
  if (engineToggleEl.checked) refreshEngineEvaluation();
  return true;
}

function showAnalysisCursor(cursor) {
  if (!analysisBase) return false;
  const nextCursor = Math.max(0, Math.min(Number(cursor), analysisFrames.length));
  analysisCursor = nextCursor;
  syncAnalysisLineState();
  selectedSquare = null;
  clearBoardMark();
  clearHighlights();

  if (nextCursor === 0) {
    reviewStage = analysisBase.stage;
    historyPly = Number(analysisBase.historyPly || 0);
    showingSolvedMove = reviewStage === 'solved';
    analysisLegalMoves = [];
    analysisTurn = null;
    renderBoard(currentPosition(), analysisBase.fen, true);
    if (reviewStage === 'solved') highlightSolvedMoveComparison();
  } else {
    const frame = analysisFrames[nextCursor - 1];
    reviewStage = 'analysis';
    historyPly = Number(analysisBase.historyPly || historyPly);
    showingSolvedMove = false;
    analysisLegalMoves = Array.isArray(frame.legalMoves) ? frame.legalMoves : [];
    analysisTurn = frame.turn || null;
    renderBoard(currentPosition(), frame.fen, true);
  }
  updateHistoryUI();
  if (engineToggleEl.checked) refreshEngineEvaluation();
  return true;
}

function navigateReview(delta) {
  const direction = delta < 0 ? -1 : 1;

  if (reviewStage === 'analysis') {
    if (direction < 0) return showAnalysisCursor(analysisCursor - 1);
    if (analysisCursor < analysisFrames.length) return showAnalysisCursor(analysisCursor + 1);
    return false;
  }

  // A stored temporary branch is replayable from the exact board where it began.
  if (direction > 0 && sameAnalysisOrigin() && analysisFrames.length) {
    return showAnalysisCursor(1);
  }

  if (reviewStage === 'solved') {
    if (direction < 0) {
      setHistoryPly(contextTargetPly());
      return true;
    }
    return false;
  }

  if (!currentContext?.available) return false;
  const target = contextTargetPly();
  if (direction > 0 && historyPly >= target && solvedReviewFen) {
    return showSolvedReviewPosition();
  }
  setHistoryPly(historyPly + direction);
  return true;
}

function renderPgnContext() {
  pgnMovesEl.innerHTML = '';
  if (!currentContext?.available || !currentContext.moves.length) {
    pgnMovesEl.innerHTML = '<span class="muted">Full move history is available after regenerating positions with this build.</span>';
    updateHistoryUI();
    return;
  }

  currentContext.moves.forEach(move => {
    if (move.color === 'white') {
      const number = document.createElement('span');
      number.className = 'pgn-number';
      number.textContent = `${move.move_number}.`;
      pgnMovesEl.appendChild(number);
    }

    const token = document.createElement('button');
    token.type = 'button';
    token.className = 'pgn-move';
    token.dataset.ply = move.ply;
    token.textContent = move.san;
    token.title = `Show position after ${move.san}`;
    token.addEventListener('click', () => setHistoryPly(move.ply));
    pgnMovesEl.appendChild(token);
  });

  updateHistoryUI();
}

async function loadGameContext(position) {
  if (contextCache.has(position.id)) return contextCache.get(position.id);
  const response = await fetch(`/api/positions/${position.id}/game-context`);
  const context = await response.json();
  contextCache.set(position.id, context);
  return context;
}

function finishOpponentPreview(position, from, to) {
  historyPly = currentContext?.available ? contextTargetPly() : 0;
  inputLocked = solved;
  renderBoard(position, position.fen, !solved);
  highlight(from, 'last-move');
  highlight(to, 'last-move');
  const colorLabel = position.user_color === 'white' ? 'White' : 'Black';
  opponentMoveEl.textContent = `Opponent played ${position.opponent_move_san || position.opponent_move_uci}. ${colorLabel} to play.`;
  opponentMoveEl.classList.remove('hidden');
  updateHistoryUI();

  previewTimers.push(setTimeout(() => {
    boardEl.querySelectorAll('.square.last-move').forEach(el => el.classList.remove('last-move'));
  }, LAST_MOVE_HIGHLIGHT_MS));
}

function previewOpponentMove(position, retry = false) {
  clearPreviewTimers();
  selectedSquare = null;
  inputLocked = true;
  opponentMoveEl.classList.remove('hidden');

  let previousFen = position.previous_fen;
  let moveUci = position.opponent_move_uci;
  let moveSan = position.opponent_move_san;

  if (currentContext?.available && currentContext.moves.length) {
    const target = contextTargetPly();
    const lastMove = currentContext.moves[target - 1];
    if (lastMove) {
      previousFen = lastMove.fen_before;
      moveUci = lastMove.uci;
      moveSan = lastMove.san;
      historyPly = Math.max(0, target - 1);
    }
  }

  if (!previousFen || !moveUci) {
    inputLocked = solved;
    renderBoard(position, position.fen, !solved);
    updateHistoryUI();
    return;
  }

  const from = moveUci.slice(0, 2);
  const to = moveUci.slice(2, 4);
  renderBoard(position, previousFen, false);
  opponentMoveEl.textContent = `Opponent to move: ${moveSan || moveUci}`;
  renderPgnContext();

  const pause = retry ? RETRY_PRE_MOVE_PAUSE_MS : PRE_MOVE_PAUSE_MS;
  previewTimers.push(setTimeout(() => {
    animateMove(position, from, to, () => finishOpponentPreview(position, from, to));
  }, pause));
}

function currentLegalMoves() {
  // Context moves belong to the original puzzle FEN, not necessarily to the
  // displayed solved position. Never use them for a post-solve first move.
  if (solved) return analysisModeActive() && Array.isArray(analysisLegalMoves) ? analysisLegalMoves : [];
  return Array.isArray(currentContext?.legal_moves) ? currentContext.legal_moves : [];
}

function resolveLegalMove(from, to) {
  if (!from || !to || from === to) return null;
  const prefix = `${from}${to}`.toLowerCase();
  const matches = currentLegalMoves().filter(move => move.startsWith(prefix));
  if (!matches.length) return null;
  return matches.find(move => move.length === 4)
    || matches.find(move => move.endsWith('q'))
    || matches[0];
}

function resolveBoardMove(from, to) {
  if (!from || !to || from === to) return null;
  // After solving, Stockfish has not yet populated legal moves. The server
  // validates this provisional UCI move (including automatic queen promotion)
  // without requiring the learner to flip the toggle manually.
  return resolveLegalMove(from, to) || (solved && !currentLegalMoves().length ? `${from}${to}` : null);
}

function legalTargetsFrom(squareName) {
  return currentLegalMoves()
    .filter(move => move.startsWith(squareName))
    .map(move => move.slice(2, 4));
}

function handleSquareClick(squareName, board) {
  if (!boardInteractive) return;
  const position = currentPosition();
  const activeColor = interactionColor(position);
  if (!selectedSquare) {
    if (!isPieceForColor(board[squareName], activeColor)) return;
    activateSolvedBoardAnalysis();
    selectedSquare = squareName;
    paintSelection();
    return;
  }
  if (selectedSquare === squareName) {
    selectedSquare = null;
    paintSelection();
    return;
  }

  // Clicking another friendly piece changes the selected piece instead of
  // treating the interaction as an attempted move.
  if (isPieceForColor(board[squareName], activeColor)) {
    selectedSquare = squareName;
    paintSelection();
    return;
  }

  const legalMove = resolveBoardMove(selectedSquare, squareName);
  if (!legalMove) {
    showIllegalMoveAlert(analysisModeActive()
      ? 'That move is not legal in this analysis position.'
      : 'That move is not legal. Keep looking.');
    paintSelection();
    return;
  }
  submitBoardMove(selectedSquare, squareName, legalMove);
}

function paintSelection() {
  const legalTargets = new Set(selectedSquare ? legalTargetsFrom(selectedSquare) : []);
  boardEl.querySelectorAll('.square').forEach(el => {
    el.classList.toggle('selected', el.dataset.square === selectedSquare);
    el.classList.toggle('legal-target', legalTargets.has(el.dataset.square));
  });
}

function clearHighlights() {
  boardEl.querySelectorAll('.square').forEach(el => el.classList.remove('selected','legal-target','correct','wrong','near-optimal','last-move'));
}

function highlight(squareName, className) {
  const el = boardEl.querySelector(`[data-square="${squareName}"]`);
  if (el) el.classList.add(className);
}

function highlightSolvedMoveComparison(bestUci = solutionBestMoveUci, acceptedUci = solvingMoveUci) {
  const best = String(bestUci || '');
  const accepted = String(acceptedUci || '');
  // Gold = the accepted move actually on the board. Green = an engine-best annotation.
  if (accepted.length >= 4 && best.length >= 4 && accepted !== best) {
    highlight(accepted.slice(0, 2), 'near-optimal');
    highlight(accepted.slice(2, 4), 'near-optimal');
  }
  if (best.length >= 4) {
    highlight(best.slice(0, 2), 'correct');
    highlight(best.slice(2, 4), 'correct');
  }
  // Only an alternative solve needs a translucent best-move piece: do not
  // replace the accepted piece or alter the accepted FEN. This annotation is
  // decorative, so it cannot be dragged or interpreted as a second piece.
  if (best.length >= 4 && accepted.length >= 4 && accepted !== best) {
    renderEngineBestPreview(currentPosition(), best);
  }
}

function renderEngineBestPreview(position, bestUci) {
  if (!position?.fen || !bestUci || bestUci.length < 4 || !boardEl) return;
  const original = parseFen(position.fen);
  let piece = original[bestUci.slice(0, 2)];
  if (!piece || !PIECES[piece]) return;
  // Engine promotions must show the promoted piece, not the original pawn.
  if (bestUci.length === 5 && /[qrbn]/i.test(bestUci[4])) {
    piece = piece === piece.toUpperCase() ? bestUci[4].toUpperCase() : bestUci[4].toLowerCase();
  }
  const target = boardEl.querySelector(`[data-square="${bestUci.slice(2, 4)}"]`);
  if (!target) return;
  target.querySelector('.best-move-preview')?.remove();
  const preview = document.createElement('i');
  preview.className = `best-move-preview fa-solid ${PIECES[piece]}`;
  if (target.querySelector('.piece')) preview.classList.add('has-occupant');
  preview.setAttribute('aria-hidden', 'true');
  preview.title = `Engine best: ${solutionBestMoveSan || bestUci}`;
  target.appendChild(preview);
}

function evalLabel(cp, mate) {
  if (mate !== null && mate !== undefined) return mate > 0 ? `M${mate}` : `-M${Math.abs(mate)}`;
  if (cp === null || cp === undefined) return '—';
  return `${cp >= 0 ? '+' : ''}${(cp / 100).toFixed(2)}`;
}

function whitePov(cp, mate, sourcePerspective = 'white', userColor = currentPosition()?.user_color) {
  if (sourcePerspective !== 'user' || userColor !== 'black') return {cp, mate};
  return {
    cp: cp === null || cp === undefined ? cp : -cp,
    mate: mate === null || mate === undefined ? mate : -mate,
  };
}

function currentDisplayedFen() {
  return displayedFen || currentPosition()?.fen || '';
}

function hideEngineArrow() {
  if (!engineArrowEl) return;
  engineArrowEl.classList.add('hidden');
}

function drawEngineArrow(uci) {
  hideEngineArrow();
  if (!uci || uci.length < 4) return;
  const fromEl = boardEl.querySelector(`[data-square="${uci.slice(0, 2)}"]`);
  const toEl = boardEl.querySelector(`[data-square="${uci.slice(2, 4)}"]`);
  if (!fromEl || !toEl) return;

  const wrapRect = boardEl.parentElement.getBoundingClientRect();
  const boardRect = boardEl.getBoundingClientRect();
  const fromRect = fromEl.getBoundingClientRect();
  const toRect = toEl.getBoundingClientRect();

  // The arrow is constructed explicitly rather than with an SVG marker. This
  // keeps the shaft visible even for a one-square move and avoids marker
  // clipping/oversizing at the edge of the board.
  const pad = 12;
  const svgWidth = boardRect.width + pad * 2;
  const svgHeight = boardRect.height + pad * 2;
  engineArrowEl.style.left = `${boardRect.left - wrapRect.left - pad}px`;
  engineArrowEl.style.top = `${boardRect.top - wrapRect.top - pad}px`;
  engineArrowEl.style.width = `${svgWidth}px`;
  engineArrowEl.style.height = `${svgHeight}px`;
  engineArrowEl.setAttribute('viewBox', `0 0 ${svgWidth} ${svgHeight}`);

  const sx = fromRect.left - boardRect.left + fromRect.width / 2 + pad;
  const sy = fromRect.top - boardRect.top + fromRect.height / 2 + pad;
  const tx = toRect.left - boardRect.left + toRect.width / 2 + pad;
  const ty = toRect.top - boardRect.top + toRect.height / 2 + pad;
  const dx = tx - sx;
  const dy = ty - sy;
  const distance = Math.hypot(dx, dy) || 1;
  const ux = dx / distance;
  const uy = dy / distance;
  const nx = -uy;
  const ny = ux;
  const squareSize = Math.min(fromRect.width, fromRect.height);

  // Begin just beyond the visual edge of the source piece, then carry the
  // arrow all the way to the center of the destination square. The piece
  // radius is estimated from the square because Font Awesome glyph bounds
  // are not exposed reliably by the browser.
  const pieceRadius = squareSize * 0.30;
  const sourceGap = Math.min(squareSize * 0.05, 5);
  const startInset = pieceRadius + sourceGap;
  const headLength = Math.min(squareSize * 0.42, 31);
  const headHalfWidth = Math.min(squareSize * 0.32, 24);

  const startX = sx + ux * startInset;
  const startY = sy + uy * startInset;
  const tipX = tx;
  const tipY = ty;
  const baseX = tipX - ux * headLength;
  const baseY = tipY - uy * headLength;
  const shaftHalfWidth = Math.min(squareSize * 0.105, 8);

  // Render the shaft and arrowhead as one filled polygon. A single shape keeps
  // the gold translucent color uniform at the neck instead of darkening where
  // separate semi-transparent SVG elements overlap.
  if (engineArrowShapeEl) {
    const startLeftX = startX + nx * shaftHalfWidth;
    const startLeftY = startY + ny * shaftHalfWidth;
    const neckLeftX = baseX + nx * shaftHalfWidth;
    const neckLeftY = baseY + ny * shaftHalfWidth;
    const headLeftX = baseX + nx * headHalfWidth;
    const headLeftY = baseY + ny * headHalfWidth;
    const headRightX = baseX - nx * headHalfWidth;
    const headRightY = baseY - ny * headHalfWidth;
    const neckRightX = baseX - nx * shaftHalfWidth;
    const neckRightY = baseY - ny * shaftHalfWidth;
    const startRightX = startX - nx * shaftHalfWidth;
    const startRightY = startY - ny * shaftHalfWidth;
    engineArrowShapeEl.setAttribute('points', [
      `${startLeftX},${startLeftY}`,
      `${neckLeftX},${neckLeftY}`,
      `${headLeftX},${headLeftY}`,
      `${tipX},${tipY}`,
      `${headRightX},${headRightY}`,
      `${neckRightX},${neckRightY}`,
      `${startRightX},${startRightY}`
    ].join(' '));
  }

  engineArrowEl.classList.remove('hidden');
}
async function refreshEngineEvaluation() {
  hideEngineArrow();
  if (!solved || !engineToggleEl.checked) {
    engineEvalEl.textContent = '—';
    analysisLegalMoves = [];
    analysisTurn = null;
    return;
  }

  const fen = currentDisplayedFen();
  if (!fen) return;
  const position = currentPosition();
  const cacheKey = `${position.id}|${fen}`;
  const token = ++engineRequestToken;
  engineEvalEl.textContent = '…';

  let result = engineEvalCache.get(cacheKey);
  if (!result) {
    try {
      const response = await fetch('/api/engine/evaluate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({position_id: position.id, history_ply: historyPly, fen})
      });
      result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Engine unavailable');
      engineEvalCache.set(cacheKey, result);
    } catch (error) {
      if (token === engineRequestToken) engineEvalEl.textContent = 'offline';
      return;
    }
  }

  if (token !== engineRequestToken || !engineToggleEl.checked || !solved) return;
  analysisLegalMoves = Array.isArray(result.legal_moves) ? result.legal_moves : [];
  analysisTurn = result.turn || null;
  engineEvalEl.textContent = evalLabel(result.eval_cp, result.mate);

  // Re-render the same displayed position only to enable the correct side to
  // move in analysis mode; never snap back to the original training FEN.
  renderBoard(position, fen, true);
  drawEngineArrow(result.best_move_uci);
}

async function playAnalysisMove(from, to, legalMove) {
  if (!analysisModeActive() || !legalMove) return;
  hideIllegalMoveAlert();
  const position = currentPosition();
  const startingFen = currentDisplayedFen();
  prepareAnalysisBranch();
  const actionToken = ++analysisActionToken;
  selectedSquare = null;
  clearHighlights();
  hideEngineArrow();
  boardInteractive = false;
  boardEl.classList.remove('is-interactive');
  // Ignore any older response from an explicit engine evaluation.
  engineRequestToken += 1;

  const animationPromise = new Promise(resolve => animateMove(position, from, to, resolve, false));
  let response;
  let result;
  try {
    response = await fetch('/api/engine/move', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({position_id: position.id, fen: startingFen, move: legalMove})
    });
    result = await response.json();
    if (!response.ok || !result.legal) throw new Error(result.error || 'Illegal analysis move');
    await animationPromise;
  } catch (error) {
    await animationPromise;
    // Unlearning/resetting or otherwise leaving analysis intentionally cancels
    // the move. Do not replace the board with a stale error message.
    if (actionToken !== analysisActionToken || displayedPositionId !== position.id || !analysisModeActive()) return;
    showIllegalMoveAlert('That move is not legal, or could not be played. Try another move.');
    // The board must remain usable even if the first post-solve move was
    // illegal or the server was temporarily unavailable.
    renderBoard(position, startingFen, true);
    refreshEngineEvaluation();
    return;
  }

  if (actionToken !== analysisActionToken || displayedPositionId !== position.id || !analysisModeActive()) return;
  if (analysisCursor < analysisFrames.length) analysisFrames = analysisFrames.slice(0, analysisCursor);
  analysisFrames.push({
      fen: result.fen,
      moveUci: result.move_uci || legalMove,
      moveSan: result.move_san || legalMove,
      legalMoves: Array.isArray(result.legal_moves) ? result.legal_moves : [],
      turn: result.turn || null,
    });
  analysisCursor = analysisFrames.length;
  reviewStage = 'analysis';
  syncAnalysisLineState();
  analysisLegalMoves = Array.isArray(result.legal_moves) ? result.legal_moves : [];
  analysisTurn = result.turn || null;
  renderBoard(position, result.fen, true);
  updateHistoryUI();
  refreshEngineEvaluation();
}

function submitBoardMove(from, to, legalMove) {
  if (solved && !analysisModeActive()) activateSolvedBoardAnalysis({deferEvaluation: true});
  if (analysisModeActive()) return playAnalysisMove(from, to, legalMove);
  return attemptMove(from, to, legalMove);
}

function renderSolvedDetails(result) {
  updateCoachMode();
  if (taskHeadingEl) taskHeadingEl.textContent = 'Position solved.';
  coachPositionReviewEl?.classList.remove('hidden');
  preserveCoachReviewInThread();
  if (solvedOpeningEl) {
    const opening = String(currentPosition()?.opening_name || '').trim();
    solvedOpeningEl.textContent = opening;
    solvedOpeningRowEl?.classList.toggle('hidden', !opening);
  }
  if (coachSolutionLabelEl && coachSolutionLabelEl.dataset.fromRecap !== '1') {
    coachSolutionLabelEl.textContent = `Best move · ${result.best_move_san || result.best_move_uci || solutionBestMoveSan || currentPosition()?.best_move_san || '—'}`;
  }
  resetHint();
  if (hintToggleEl) hintToggleEl.classList.add('hidden');
  const modeMeta = learningModeMeta(currentPosition()?.learning_mode, currentPosition()?.category);
  if (categoryEl) {
    const position = currentPosition();
    categoryEl.textContent = categoryLabel(position?.category).toUpperCase();
    categoryEl.className = `eyebrow result-category mode-${modeMeta.tone}`;
    categoryEl.classList.remove('hidden');
  }
  if (coachTextEl && coachSolutionLabelEl?.dataset.fromRecap !== '1') {
    coachTextEl.textContent = result.coach_explanation || currentPosition()?.coach_explanation ||
      'No verified coaching explanation is available. Run Coaching refresh before rating the explanation.';
    coachTextEl.classList.remove('hidden');
    explainedPositionId = Number(currentPosition()?.id);
  }
  document.getElementById('best-move').textContent = result.best_move_san || result.best_move_uci || '—';
  const beforeWhite = whitePov(result.eval_before_cp, result.mate_before, result.evaluation_perspective || 'user', result.user_color || currentPosition()?.user_color);
  const afterWhite = whitePov(result.eval_after_cp, result.mate_after, result.evaluation_perspective || 'user', result.user_color || currentPosition()?.user_color);
  document.getElementById('evaluation').textContent = `${evalLabel(beforeWhite.cp, beforeWhite.mate)} → ${evalLabel(afterWhite.cp, afterWhite.mate)}`;
  const gameMoves = openingKey ? currentPosition()?.game_moves : null;
  const moveListEl = document.getElementById('played-moves-list');
  moveListEl.replaceChildren();
  const entries = Array.isArray(gameMoves) && gameMoves.length
    ? gameMoves : [{san:result.played_move_san || currentPosition()?.played_move_san || '—', game_count:1}];
  for (const entry of entries) {
    const line = document.createElement('div');
    line.className = 'played-move-entry';
    const san = document.createElement('strong');
    san.textContent = entry.san || entry.uci || '—';
    line.append(san);
    if (Number(entry.game_count) > 1) {
      const freq = document.createElement('small');
      freq.textContent = `${entry.game_count} games`;
      line.append(freq);
    }
    moveListEl.append(line);
  }
  document.getElementById('puzzle-rating').textContent = result.estimated_rating ? `≈ ${result.estimated_rating}` : '—';
  renderConcepts(result.concepts || currentPosition()?.concepts || [], result.taxonomy || currentPosition()?.taxonomy);
  updatePositionRatingUI();
  solutionEl.classList.remove('hidden');
  maybeOfferProactiveCoach(currentPosition());
}

async function loadSolvedDetails(position) {
  try {
    const response = await fetch(`/api/positions/${position.id}/solution${evaluationRunId ? `?evaluation_run_id=${evaluationRunId}` : ""}`);
    if (!response.ok) return;
    const result = await response.json();
    if (displayedPositionId === position.id && solved) {
      solutionBestMoveUci = result.best_move_uci || solutionBestMoveUci;
      solutionBestMoveSan = result.best_move_san || solutionBestMoveSan;
      // A late /solution response must never replace an accepted-move board.
      solvedReviewFen = solvingMoveFen || solvedReviewFen || result.best_fen || null;
      // Older saved solves do not retain an accepted alternative separately.
      // Use the engine solution as the best available solving-move context.
      if (!solvingMoveUci && result.best_move_uci) {
        solvingMoveUci = result.best_move_uci;
        solvingMoveSan = result.best_move_san || null;
      }
      renderSolvedDetails(result);
    }
  } catch (_) {
    // Leave the review board usable even if solution metadata cannot be loaded.
  }
}

async function attemptMove(from, to, legalMove = null) {
  if (inputLocked || solved || from === to) return;
  const position = currentPosition();
  const moveUci = legalMove || resolveLegalMove(from, to);
  if (!moveUci) return;

  hideIllegalMoveAlert();
  inputLocked = true;
  selectedSquare = null;
  clearHighlights();
  boardInteractive = false;
  const animationPromise = new Promise(resolve => animateMove(position, from, to, resolve, false));
  const trackLearning = learningTrackingEnabled;
  const startNewLearningSession = trackLearning && restartTrackedSession;
  const activeSecondsDelta = trackLearning ? learningClockSnapshot() : null;

  let response;
  let result;
  try {
    // Do not accidentally merge a new clocked-in session with the session
    // terminated by a previous toggle-off request.
    await playerClockOutRequest.catch(() => {});
    response = await fetch(`/api/positions/${position.id}/attempt`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({move: moveUci, opening_key:openingKey, lesson_key:conceptKey,
        track_learning:trackLearning, start_new_learning_session:startNewLearningSession,
        active_seconds_delta:activeSecondsDelta,
        coach_session_key:coachChatEl ? coachSolveSessionKey(position.id) : null,
        evaluation_run_id:evaluationRunId})
    });
    result = await response.json();
  } catch (_) {
    await animationPromise;
    inputLocked = false;
    learningClockResume();
    renderBoard(position, position.fen, true);
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = 'Could not submit the move. Try again.';
    return;
  }

  await animationPromise;
  if (displayedPositionId !== position.id) return;
  if (!response.ok) {
    inputLocked = false;
    learningClockResume();
    renderBoard(position, position.fen, true);
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = result.error || 'Could not verify that move. Try again.';
    return;
  }
  if (!result.legal) {
    learningClockResume();
    inputLocked = false;
    renderBoard(position, position.fen, true);
    showIllegalMoveAlert('That move is not legal. Keep looking.');
    return;
  }

  // The legal move has already animated while server verification ran. Finalize
  // captures/castling/promotion from the authoritative returned FEN.
  if (displayedPositionId !== position.id) return;

  if (trackLearning && result.legal) restartTrackedSession = false;
  learningClockCommit();
  // Coach evidence recording is independent of optional Player statistics.
  // Surface a missing session receipt immediately instead of discovering the
  // absence only after the puzzle is solved.
  if (coachChatEl && result.coach_attempt_logged === false) {
    coachAttemptLogFailures.set(Number(position.id),
      (coachAttemptLogFailures.get(Number(position.id)) || 0) + 1);
    showCoachRecapIssue(position.id, 'This move was verified but its coaching attempt was not saved. The recap may be incomplete.');
  }
  if (!result.correct) {
      renderBoard(position, result.attempted_fen, false);
      highlight(to, 'wrong');
      showBoardMark('wrong');
      feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
      feedbackMessageEl.textContent = 'Not quite — try again.';

      previewTimers.push(setTimeout(() => {
        if (displayedPositionId !== position.id || solved) return;
        clearBoardMark();
        previewOpponentMove(position, true);
      }, WRONG_FEEDBACK_MS));
      return;
    }

  learningClockPause();
  learningClockPositionId = null;
  solved = true;
    inputLocked = true;
    showingSolvedMove = true;
    position.learned = 1;
    solvingMoveUci = result.attempted_move_uci || moveUci;
    solvingMoveSan = result.attempted_move_san || null;
    solvingMoveFen = result.attempted_fen || null;
    // Keep the exact accepted move and resulting FEN for unlimited review,
    // even when the user visits other positions or resumes this playlist.
    sessionSolvedMoves[String(position.id)] = {
      uci: solvingMoveUci, san: solvingMoveSan, fen: solvingMoveFen,
      best_fen: result.best_fen || null
    };
    keepPlaylistSnapshot();
    solutionBestMoveUci = result.best_move_uci || null;
    solutionBestMoveSan = result.best_move_san || null;
    solvedReviewFen = solvingMoveFen || result.best_fen || null;
    clearAnalysisBranch();
    reviewStage = 'solved';
    historyPly = contextTargetPly();
    learnedCheckbox.checked = true;
    // The board must show the move the player actually made. Engine-best is
    // only a green annotation, even when the server accepts an alternative.
    renderBoard(position, solvingMoveFen || solvedReviewFen, true);
    updateHistoryUI();
    highlightSolvedMoveComparison();
    showBoardMark('correct');
    feedbackEl.className = 'feedback good';
  feedbackEl.classList.remove('hidden');
    // Keep the green success strip one line beside the position thumbs.
    // Detailed acceptance wording is still available as a tooltip.
    feedbackMessageEl.title = result.accepted_alternative
      ? (evaluationRunId ? 'Strong move — accepted for this evaluation.' : 'Strong move — accepted as near-optimal and position marked learned.')
      : (evaluationRunId ? 'Correct — recorded for this evaluation.' : 'Correct — position marked learned.');
    feedbackMessageEl.textContent = result.accepted_alternative ? '✓ Solved · strong move' : '✓ Solved';

    position.estimated_rating = result.estimated_rating ?? position.estimated_rating;
    position.difficulty_score = result.difficulty_score ?? position.difficulty_score;
    renderSolvedDetails(result);
    updatePositionRatingUI();
    loadPositionRatings(position.id);
    loadSolvedDetails(position);
    void publishPostSolveCoach(position);
    engineToggleEl.disabled = false;
    if (engineToggleWrapEl) engineToggleWrapEl.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    if (learnedToggleWrapEl && !evaluationRunId) learnedToggleWrapEl.classList.remove('hidden');
    updateNavigationMeta();
}


async function refreshCurrentPosition() {
  const position = currentPosition();
  if (!position || !refreshPositionEl || evaluationRunId) return;
  refreshPositionEl.disabled = true;
  const originalLabel = refreshPositionEl.textContent;
  refreshPositionEl.textContent = 'Resetting…';
  try {
    const response = await fetch(`/api/positions/${position.id}/reset`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({opening_key:openingKey})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not reset puzzle');
    position.learned = 0;
    delete sessionSolvedMoves[String(position.id)];
    coachSolveSessionKeys.delete(Number(position.id));
    coachAttemptLogFailures.delete(Number(position.id));
    keepPlaylistSnapshot();
    solved = false;
    showingSolvedMove = false;
    solvingMoveUci = null;
    solvingMoveSan = null;
    solvingMoveFen = null;
    solvedReviewFen = null;
    solutionBestMoveUci = null;
    solutionBestMoveSan = null;
    analysisActionToken += 1;
    clearAnalysisBranch();
    reviewStage = 'history';
    learnedCheckbox.checked = false;
    learnedToggleWrapEl?.classList.add('hidden');
    solvedPositionControlsEl?.classList.add('hidden');
    engineToggleEl.checked = false;
    engineToggleEl.disabled = true;
    engineEvalEl.textContent = '—';
    hideEngineArrow();
    clearHighlights();
    clearBoardMark();
    await showPosition(currentIndex);
  } catch (error) {
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = error.message || 'Could not reset this puzzle.';
  } finally {
    refreshPositionEl.disabled = false;
    refreshPositionEl.textContent = originalLabel;
  }
}

async function rateCoachResponse(button) {
  const container = button.closest('.coach-response-feedback');
  const messageId = Number(container?.dataset.messageId || 0);
  const chosenRating = Number(button.dataset.rating || 0);
  if (!messageId || ![-1, 1].includes(chosenRating)) return;
  const priorRating = Number(container.querySelector('.coach-feedback-button.active')?.dataset.rating || 0);
  const rating = nextFeedbackRating(priorRating, chosenRating);
  const buttons = [...container.querySelectorAll('.coach-feedback-button')];
  buttons.forEach(item => item.disabled = true);
  setRatingFeedbackStatus(container, '');
  try {
    const response = await fetch(`/api/coach/messages/${messageId}/feedback`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({rating, evaluation_run_id:evaluationRunId, lesson_key: new URLSearchParams(location.search).get('concept') || ''})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save feedback');
    if (evaluationRunId) updateEvaluationFeedbackState(Number(currentPosition()?.id), result.evaluation_feedback_saved === true);
    buttons.forEach(item => {
      const selected = Number(item.dataset.rating) === rating;
      item.classList.toggle('active', selected);
      item.setAttribute('aria-pressed', String(selected));
      item.title = selected ? 'Remove this rating' : item.getAttribute('aria-label');
    });
    container.classList.toggle('saved', rating !== 0);
    container.dataset.suggestedText = result.suggested_text || '';
    container.querySelector('.feedback-edit-correction')?.classList.toggle('hidden', rating !== -1);
    container.title = rating === 0 ? 'Rating removed.' : rating === 1
      ? 'Helpful rating saved; correction cleared.' : 'Unhelpful rating saved.';
    setRatingFeedbackStatus(container, rating === 0 ? 'Rating withdrawn' : 'Rating saved');
    if (rating === -1) openCorrectionDialog('coaching', messageId, {suggested_text: container.dataset.suggestedText});
    else if (correctionTarget?.category === 'coaching' && correctionTarget?.targetId === messageId) closeCorrectionDialog();
  } catch (error) {
    container.classList.add('error');
    setRatingFeedbackStatus(container, error.message || 'Could not save coaching feedback', true);
  } finally {
    buttons.forEach(item => item.disabled = false);
  }
}

// Lesson completion is calculated from the *pinned playlist*, so reviewing a
// previously solved card never reduces the denominator or shifts the bar.
function updateLessonProgress() {
  const fill = document.getElementById('lesson-progress-fill');
  const count = document.getElementById('lesson-progress-count');
  const remaining = document.getElementById('lesson-progress-remaining');
  const track = document.getElementById('lesson-progress-track');
  if (!fill || !count || !remaining || !track) return;
  const total = positions.length;
  const learned = positions.reduce((sum, item) => sum + (Boolean(Number(item.learned)) ? 1 : 0), 0);
  const pending = total - learned;
  const percent = total ? Math.round(100 * learned / total) : 0;
  fill.style.width = `${percent}%`;
  track.setAttribute('aria-valuenow', String(percent));
  track.setAttribute('aria-valuetext', `${learned} of ${total} positions learned`);
  count.textContent = total ? `${learned} of ${total} learned · ${percent}%` : 'No positions in playlist';
  remaining.textContent = total ? (pending ? `${pending} remaining` : 'Lesson complete') : '';
}

async function hydratePositionChunk(index) {
  if (!positions.length || index < 0 || index >= positions.length) return;
  if (positions[index]?.fen) return;
  const start = Math.floor(index / POSITION_CHUNK_SIZE) * POSITION_CHUNK_SIZE;
  if (!positionChunkRequests.has(start)) {
    const promise = (async () => {
      const chunk = positions.slice(start, start + POSITION_CHUNK_SIZE);
      const ids = chunk.filter(p => !p.fen).map(p => Number(p.id));
      if (!ids.length) return;
      const response = await fetch(`/api/jobs/${jobId}/positions/playlist`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({position_ids: ids, opening_key: openingKey, evaluation_run_id: typeof evaluationRunId !== 'undefined' ? evaluationRunId : null})
      });
      if (!response.ok) throw new Error('Could not load this group of training positions');
      const hydrated = await response.json();
      const byId = new Map(hydrated.map(card => [Number(card.id), card]));
      for (let i = start; i < Math.min(start + POSITION_CHUNK_SIZE, positions.length); i++) {
        const existing = positions[i];
        const complete = byId.get(Number(existing.id));
        if (complete) positions[i] = {...existing, ...complete};
      }
    })().finally(() => positionChunkRequests.delete(start));
    positionChunkRequests.set(start, promise);
  }
  await positionChunkRequests.get(start);
  if (!positions[index]?.fen) throw new Error('Training position is no longer available');
}

function queueNearbyPositions(index) {
  // Only prefetch near a batch boundary; do not compete with the initial
  // board, history or coaching requests for network/SQLite resources.
  if (index % POSITION_CHUNK_SIZE < POSITION_CHUNK_SIZE - 5) return;
  const next = Math.floor(index / POSITION_CHUNK_SIZE + 1) * POSITION_CHUNK_SIZE;
  if (next >= positions.length || positions[next]?.fen) return;
  const run = () => hydratePositionChunk(next).catch(() => {});
  if ('requestIdleCallback' in window) window.requestIdleCallback(run, {timeout: 1500});
  else setTimeout(run, 350);
}

function updateNavigationMeta() {
  updateLessonProgress();
  document.getElementById('counter').textContent = positions.length ? `${currentIndex + 1} / ${positions.length}` : '0 / 0';
  document.getElementById('previous-button').disabled = currentIndex === 0;
  const evaluationReady = !evaluationRunId || evaluationFeedbackSaved();
  nextButtonEl.disabled = !positions.length || !evaluationReady || (!solved && currentIndex >= positions.length - 1);
  if (evaluationRunId) {
    const indicator = document.getElementById('evaluation-saved-indicator');
    indicator?.classList.toggle('hidden', !evaluationReady);
    nextButtonEl.title = evaluationReady ? '' : 'Solve this evaluation position and save feedback before continuing.';
  }
  nextButtonEl.textContent = solved && currentIndex >= positions.length - 1 ? (openingKey?'Back to openings →':'Back to lessons →') : 'Next position →';
}

async function showPosition(index) {
  if (!positions.length) return;
  resetHint();
  hintToggleEl?.classList.add('hidden');
  const token = ++positionDisplayToken;
  learningClockPause();
  learningClockPositionId = null;
  const chosenIndex = Math.max(0, Math.min(index, positions.length - 1));
  currentIndex = chosenIndex;
  if (evaluationRunId) evaluationFeedbackSavedByPosition.set(Number(positions[chosenIndex].id), false);
  // Prevent an earlier puzzle's delayed context/solution from painting over
  // this card while its next chunk is in flight.
  displayedPositionId = null;
  explainedPositionId = null;
  ++ratingRequestSerial;
  inputLocked = true;
  solved = false;
  updateNavigationMeta();
  if (!positions[chosenIndex]?.fen) {
    pgnMovesEl.innerHTML = '<span class="muted">Loading position…</span>';
    boardEl.classList.add('position-loading');
    inputLocked = true;
    try { await hydratePositionChunk(chosenIndex); }
    catch (error) {
      if (token === positionDisplayToken) {
        boardEl.classList.remove('position-loading');
        feedbackEl.className = 'feedback bad';
        feedbackEl.classList.remove('hidden');
        feedbackMessageEl.textContent = error.message || 'Could not load this position.';
      }
      return;
    }
  }
  if (token !== positionDisplayToken) return;
  boardEl.classList.remove('position-loading');
  const p = positions[chosenIndex];
  resetGameShare();
  displayedPositionId = p.id;
  clearCoachAttemptComments(); // prevents reusing another puzzle's message identity
  displayCoachRefreshWarning(p);
  rememberTraining(p.id);
  selectedSquare = null;
  // Learned is the authoritative status. A stale saved solving move must
  // never resurrect a position explicitly marked for practice again.
  if (!p.learned && sessionSolvedMoves[String(p.id)]) {
    delete sessionSolvedMoves[String(p.id)];
    keepPlaylistSnapshot();
  }
  const savedSolve = p.learned ? (sessionSolvedMoves[String(p.id)] || null) : null;
  // Accepted move wins over the engine's canonical result. The latter is only
  // a fallback for legacy learned positions without a recorded actual solve.
  const restoredSolvedFen = (p.learned ? (savedSolve?.fen || p.accepted_fen || p.review_best_fen) : null)
    || savedSolve?.best_fen || null;
  solved = Boolean(p.learned);
  inputLocked = true;
  currentContext = null;
  historyPly = 0;
  showingSolvedMove = Boolean(solved && restoredSolvedFen);
  displayedFen = '';
  analysisActionToken += 1;
  clearAnalysisBranch();
  reviewStage = solved && restoredSolvedFen ? 'solved' : 'history';
  solvingMoveUci = savedSolve?.uci || (solved ? (p.accepted_move_uci || p.best_move_uci) : null);
  solvingMoveSan = savedSolve?.san || (solved ? (p.accepted_move_san || p.best_move_san) : null);
  solvingMoveFen = savedSolve?.fen || p.accepted_fen || restoredSolvedFen || null;
  solvedReviewFen = solvingMoveFen || restoredSolvedFen;
  solutionBestMoveUci = p.best_move_uci || null;
  solutionBestMoveSan = p.best_move_san || null;
  clearPreviewTimers();
  clearHighlights();
  clearBoardMark();
  engineRequestToken += 1;
  engineToggleEl.checked = false;
  engineToggleEl.disabled = true;
  if (engineToggleWrapEl) engineToggleWrapEl.classList.add('hidden');
  engineEvalEl.textContent = '—';
  hideEngineArrow();
  document.getElementById('puzzle-rating').textContent = '—';
  feedbackEl.className = solved ? 'feedback good' : 'feedback neutral';
  feedbackEl.classList.remove('hidden');
  feedbackMessageEl.title = solved ? (evaluationRunId ? 'Already solved in this evaluation run.' : 'Already learned. Review the game or move to another puzzle.') : '';
  feedbackMessageEl.textContent = solved ? '✓ Solved' : '';
  feedbackEl.classList.toggle('hidden', !solved);
  solutionEl.classList.add('hidden');
  coachThreadReadyPositionId = null;
  renderConcepts([]);
  updatePositionRatingUI();
  loadPositionRatings(p.id);
  learnedCheckbox.checked = Boolean(p.learned);
  if (evaluationRunId) { learnedCheckbox.disabled = true; } 
  if (learnedToggleWrapEl) learnedToggleWrapEl.classList.add('hidden');
  solvedPositionControlsEl?.classList.add('hidden');
  pgnMovesEl.innerHTML = '<span class="muted">Loading game history…</span>';

  if (categoryEl) {
    categoryEl.textContent = categoryLabel(p.category).toUpperCase();
    categoryEl.className = `eyebrow result-category mode-${learningModeMeta(p.learning_mode, p.category).tone} hidden`;
  }
  document.getElementById('position-title').textContent = p.opponent ? `vs. ${p.opponent}` : '—';
  document.getElementById('date-chip').textContent = p.game_date || 'Unknown date';
  const colorLabel = p.user_color === 'white' ? 'White' : 'Black';
  document.getElementById('move-chip').textContent = `Move ${p.move_number}`;

  if (taskHeadingEl) taskHeadingEl.textContent = 'Find a strong move.';
  coachPositionReviewEl?.classList.add('hidden');
  clearCoachAttemptComments();
  solvedOpeningRowEl?.classList.add('hidden');
  if (coachTextEl) {
    coachTextEl.textContent = 'Watch the last move, then find a strong response.';
    coachTextEl.classList.toggle('hidden', Boolean(coachPositionReviewEl));
  }
  resetHint();
  hintToggleEl?.classList.toggle('hidden', solved);
  updateNavigationMeta();
  updateCoachMode();
  // Draw the actual board and restore solved feedback BEFORE fetching the
  // full game history, coaching thread, or slow engine explanations.
  renderBoard(p, restoredSolvedFen || p.fen, solved);
  if (solved) {
    highlightSolvedMoveComparison();
    showBoardMark('correct');
    feedbackEl.className = 'feedback good';
    feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = '✓ Solved.';
    solutionEl.classList.remove('hidden');
    if (p.estimated_rating) document.getElementById('puzzle-rating').textContent = `≈ ${p.estimated_rating}`;
    renderConcepts(p.concepts || [], p.taxonomy);
    updatePositionRatingUI();
    engineToggleEl.disabled = false;
    engineToggleWrapEl?.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    if (!evaluationRunId) learnedToggleWrapEl?.classList.remove('hidden');
    // Hydrated playlist cards already contain the persisted explanation. Show
    // it immediately on Last/Next navigation, before the solution endpoint
    // returns, so a slow or failed request cannot strand a learned card with
    // the unsolved prompt and disabled explanation feedback.
    renderSolvedDetails(p);
    loadSolvedDetails(p);
  }
  loadCoachThread(p);

  const context = await loadGameContext(p);
  if (token !== positionDisplayToken || displayedPositionId !== p.id) return;
  currentContext = context;
  historyPly = context?.available ? Number(context.target_history_ply || 0) : 0;
  renderPgnContext();
  queueNearbyPositions(chosenIndex);

  if (!solved) learningClockStart(p.id);
  if (solved) {
    inputLocked = true;
    updateHistoryUI();
    // Solved state and the green board check survive history loading.
    if (reviewStage === 'solved') showBoardMark('correct');
    updateNavigationMeta();
    return;
  }

  hideIllegalMoveAlert();
  feedbackEl.className = 'feedback neutral';
  feedbackMessageEl.textContent = '';
  feedbackEl.classList.add('hidden');
  previewOpponentMove(p, false);
}

async function loadPositions(preservePosition = true) {
  // Keep the playlist unchanged after it has been created. Updating "learned"
  // marks progress for future playlists, not deletion from this session.
  if (positionsRequestPending || (playlistPinned && positions.length)) return;
  positionsRequestPending = true;
  try {
    let fresh;
    if (!benchmarkQueue && savedPlaylist?.ids?.length) {
      if (savedPlaylist.solvedMoves) sessionSolvedMoves = savedPlaylist.solvedMoves;
      const response = await fetch(`/api/jobs/${jobId}/positions/manifest`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({position_ids:savedPlaylist.ids})
      });
      if (response.ok) {
        fresh = await response.json();
        if (!fresh.length) fresh = null; // Reimported/deleted positions: build fresh.
      }
      savedPlaylist = null; // Use the snapshot only once during initial load.
    }
    if (!fresh) {
      const params = new URLSearchParams();
      if (conceptKey) params.set('concept', conceptKey);
      if (trainerContextFilter) params.set('context', trainerContextFilter);
      if (trainerMoveTypeFilter) params.set('move_type', trainerMoveTypeFilter);
      if (openingKey) params.set('opening', openingKey);
      if (openingVariation) params.set('variation', openingVariation);
      if (trainerLearningMode) params.set('learning_mode', trainerLearningMode);
      if (trainerSort) params.set('sort', trainerSort);
      if (trainerListingScope) params.set('listing', '1');
      if (trainerRatingMin !== null) params.set('rating_min', String(trainerRatingMin));
      if (trainerRatingMax !== null) params.set('rating_max', String(trainerRatingMax));
      if (requestedPositionPending) params.set('position_id', requestedPositionPending);
      if (benchmarkQueue) {params.set('benchmark','1'); if (evaluationRunId) params.set('run_id',String(evaluationRunId));}
      const query = params.toString() ? `?${params.toString()}` : '';
      const response = await fetch(`/api/jobs/${jobId}/positions/manifest${query}`);
      if (!response.ok) throw new Error('Could not load training positions');
      fresh = await response.json();
    }
    positions = fresh;
    if (positions.length) {
      playlistPinned = true;
      // Save the exact membership and order before any position is learned.
      keepPlaylistSnapshot();
      if (forceNewPlaylist) history.replaceState(history.state, '', sessionUrl);
    }
    if (!positions.length) {
      displayedPositionId = null;
      document.getElementById('position-title').textContent = 'No confirmed positions yet';
      feedbackMessageEl.textContent = analysisComplete ? 'Playlist complete. Choose another lesson.' : 'Analysis is still running. This page will update automatically.';
      updateNavigationMeta();
    } else if (!preservePosition || displayedPositionId === null) {
      const requestedIndex = requestedPositionPending ? positions.findIndex(p => Number(p.id) === requestedPositionPending) : -1;
      await showPosition(requestedIndex >= 0 ? requestedIndex : 0);
      requestedPositionPending = null;
    } else {
      const sameIndex = positions.findIndex(p => p.id === displayedPositionId);
      if (sameIndex === -1) await showPosition(Math.min(currentIndex, positions.length - 1));
      else { currentIndex = sameIndex; updateNavigationMeta(); }
    }
    if (!positions.length && !analysisComplete) {
      clearTimeout(positionsTimer);
      positionsTimer = setTimeout(() => loadPositions(true), 6500);
    }
  } catch (error) {
    feedbackEl.className = 'feedback bad';
    feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = error.message || 'Could not load training playlist.';
  } finally { positionsRequestPending = false; }
}

function processStateName(status) {
  return ({running:'Running',retrieving:'Retrieving',queued:'Queued',restarting:'Restarting',paused:'Paused',complete:'Complete',error:'Failed',stopped:'Stopped'})[status] || 'Not started';
}

async function updateJobHud() {
  // Process status is a different concern from puzzle/evaluation readouts. Do
  // not show training statistics if they are unrelated to the active worker.
  const [jobResponse, processResponse] = await Promise.all([
    fetch(`/api/jobs/${jobId}`, {cache:'no-store'}),
    fetch('/api/processes', {cache:'no-store'})
  ]);
  if (!jobResponse.ok) throw new Error('Game-list status unavailable');
  const job = await jobResponse.json();
  let processRows = [];
  if (processResponse.ok) {
    const json = await processResponse.json();
    processRows = json.processes || [];
  }
  // This dashboard is global: show the active worker even if the learner is
  // training a different list. Running takes priority over queued/paused.
  const priority = value => ['running','retrieving','restarting'].includes(value) ? 3
    : value === 'queued' ? 2 : value === 'paused' ? 1 : 0;
  const candidates = [];
  for (const row of processRows) {
    candidates.push({kind:'refresh',status:String(row.refresh_status || 'idle'),row});
    candidates.push({kind:'analysis',status:String(row.analysis_status || 'idle'),row});
  }
  candidates.sort((a,b) => priority(b.status)-priority(a.status)
    || Number(b.row.id === Number(jobId))-Number(a.row.id === Number(jobId)));
  const selectedProcess = candidates.find(candidate => priority(candidate.status) > 0);
  const kind = selectedProcess?.kind || null;
  const status = selectedProcess?.status || 'idle';
  const details = selectedProcess?.row || {};
  const title = document.getElementById('hud-status');
  const metrics = document.getElementById('hud-metrics');
  const idleCopy = document.getElementById('hud-idle-copy');
  const progress = document.getElementById('hud-progress');
  const progressTrack = document.getElementById('hud-cycle-track');
  const progressFill = document.getElementById('hud-progress-bar');
  const progressLabel = document.getElementById('hud-cycle-label');
  const progressValue = document.getElementById('hud-cycle-percent');
  const progressDetail = document.getElementById('hud-cycle-detail');
  const dot = document.getElementById('hud-dot');
  const metric = (number, label) => `<div><span>${fmtCount(number ?? 0)}</span><small>${label}</small></div>`;
  if (!kind) {
    title.textContent = 'Process · Idle';
    idleCopy.classList.remove('hidden');
    metrics.innerHTML = '';
    progress.classList.add('hidden');
    dot.className = 'hud-dot idle';
  } else {
    idleCopy.classList.add('hidden');
    progress.classList.remove('hidden');
    const isRefresh = kind === 'refresh';
    title.textContent = `${isRefresh ? 'Metadata refresh' : 'Analysis'} · ${processStateName(status)}`;
    dot.className = `hud-dot ${status}`;
    const count = isRefresh ? Math.max(0, Number(details.processed)||0) : Math.max(0, Number(details.games_processed)||0);
    const total = isRefresh ? Math.max(0, Number(details.total)||0) : Math.max(0, Number(details.games_retrieved)||0);
    const pass = Math.max(1, Number(details.current_pass)||1);
    const passes = Math.max(1, Number(details.max_passes)||1);
    const pct = total ? Math.min(100, Math.round(count/total*100)) : 0;
    metrics.innerHTML = isRefresh
      ? metric(count, 'Positions checked') + metric(details.updated, 'Metadata updated') + metric(details.failed, 'Refresh failures')
      : metric(count, 'Games screened') + metric(details.games_screened, 'Games evaluated') + metric(details.positions_found, 'Positions found');
    progressLabel.textContent = isRefresh ? 'Metadata refresh' : `Evaluation cycle · Pass ${pass}/${passes}`;
    progressValue.textContent = total ? `${pct}%` : '—';
    const listName = details.source_type === 'opposition' ? details.source_username : details.username;
    progressDetail.textContent = `${listName || 'Game list'} #${details.id}: ${fmtCount(count)} / ${fmtCount(total)} ${isRefresh ? 'positions checked' : 'games screened'}${status==='paused'?' · Paused':''}`;
    progressTrack.setAttribute('aria-valuenow', String(pct));
    progressTrack.setAttribute('aria-label', isRefresh ? 'Metadata refresh progress' : 'Current evaluation pass progress');
    progressFill.style.width = `${pct}%`;
  }
  const wasComplete = analysisComplete;
  analysisComplete = ['complete','error','stopped'].includes(job.status);
  if (analysisComplete && !wasComplete) loadPositions(true).catch(() => {});
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => updateJobHud().catch(() => {}), 5000);
}

async function navigatePuzzle(direction) {
  if (evaluationRunId && direction > 0 && !evaluationFeedbackSaved()) return;
  if (direction > 0 && solved && currentIndex === positions.length - 1) {
    // Evaluation completion never retires an unrelated ordinary playlist.
    // A completed evaluation is available later only via Coach comparisons.
    if (!evaluationRunId) {
      localStorage.removeItem(trainingStateKey);
      localStorage.removeItem(`${trainingStateKey}-state`);
      localStorage.removeItem(trainingPlaylistKey);
    }
    location.assign(openingKey ? `/openings/${jobId}` : lessonsIndexUrl);
    return;
  }
  // Do not retire solved cards. The learner can review every earlier position
  // in this exact session; learned cards disappear only on a fresh playlist.
  await showPosition(currentIndex + direction);
}

document.getElementById('previous-button').addEventListener('click', () => navigatePuzzle(-1));
document.getElementById('next-button').addEventListener('click', () => navigatePuzzle(1));
refreshPositionEl?.addEventListener('click', refreshCurrentPosition);
historyBackEl.addEventListener('click', () => navigateReview(-1));
historyForwardEl.addEventListener('click', () => navigateReview(1));
if (hintToggleEl) hintToggleEl.addEventListener('click', toggleHint);
engineToggleEl.addEventListener('change', () => {
  selectedSquare = null;
  clearHighlights();
  trainerKeyboardArmed = true; // User-enabled Stockfish must not disable board arrows.
  if (engineToggleEl.checked) {
    clearBoardMark();
    updateHistoryUI();
    refreshEngineEvaluation();
  } else {
    engineRequestToken += 1;
    analysisActionToken += 1;
    analysisLegalMoves = [];
    analysisTurn = null;
    engineEvalEl.textContent = '—';
    hideEngineArrow();
    // Preserve the temporary line and current board; only live engine input stops.
    renderBoard(currentPosition(), currentDisplayedFen(), true);
    updateHistoryUI();
  }
});

window.addEventListener('resize', () => {
  if (solved && engineToggleEl.checked) refreshEngineEvaluation();
});

function isEditableKeyboardTarget(target) {
  if (target?.isContentEditable) return true;
  const editor = target?.closest?.('input, textarea, select, [role="textbox"], [contenteditable]:not([contenteditable="false"])');
  if (!editor) return false;
  if (String(editor.tagName || '').toLowerCase() === 'input') {
    const kind = String(editor.type || 'text').toLowerCase();
    // The user may keep the Stockfish analysis toggle focused. It is not a
    // text editor and must not claim board review arrow-key shortcuts.
    return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range'].includes(kind);
  }
  return true;
}

function isCoachInteraction(target) {
  return Boolean(target?.closest?.('.coach-panel, .game-share, .coaching-correction-dialog')) ||
    isEditableKeyboardTarget(target);
}

function chessKeyboardContextActive(event) {
  // Any open feedback dialog or focused text field owns arrow keys, even if a
  // previous interaction armed the board for review navigation.
  return trainerKeyboardArmed && !correctionDialog?.open &&
    !isCoachInteraction(event?.target) && !isCoachInteraction(document.activeElement) &&
    !event?.isComposing;
}

trainerRootEl?.addEventListener('pointerdown', event => {
  // Almost the entire trainer surface arms left/right review. The adaptive
  // coach is the deliberate exception because its text cursor owns the keys.
  trainerKeyboardArmed = !isCoachInteraction(event.target);
  if (trainerKeyboardArmed && isCoachInteraction(document.activeElement)) {
    document.activeElement?.blur?.();
  }
});

coachPanelEl?.addEventListener('focusin', () => { trainerKeyboardArmed = false; });
boardEl?.addEventListener('pointerdown', event => {
  // Focusing a parent element during a press on a chess piece can interrupt
  // the platform's pointer/drag gesture on some browsers.
  if (!boardInteractive || !event.target.closest?.('.piece')) boardEl.focus({preventScroll: true});
});
pgnMovesEl?.addEventListener('pointerdown', () => pgnMovesEl.focus({preventScroll: true}));

document.addEventListener('keydown', e => {
  if (!chessKeyboardContextActive(e)) return;
  if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  e.preventDefault();
  if (e.key === 'ArrowLeft' && e.shiftKey && currentIndex > 0) navigatePuzzle(-1);
  else if (e.key === 'ArrowRight' && e.shiftKey && currentIndex < positions.length - 1) navigatePuzzle(1);
  else if (e.key === 'ArrowLeft') navigateReview(-1);
  else if (e.key === 'ArrowRight') navigateReview(1);
});

learnedCheckbox.addEventListener('change', async () => {
  if (!positions.length) return;
  const p = currentPosition();
  const requested = learnedCheckbox.checked;
  try {
    const response = await fetch(`/api/positions/${p.id}/learned`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({learned: requested, opening_key:openingKey})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not update learned state');
    reconcilePlaylistLearnedState(p.id, requested, result.affected_position_ids || []);
    learnedCheckbox.checked = requested;

    if (!requested) {
      // Reopen this exact playlist card as a puzzle. Its solved FEN, green
      // check, and remembered accepted move must not survive unlearning or
      // reappear after navigating forward and back.
      await showPosition(currentIndex);
      if (displayedPositionId === p.id && !solved) {
        feedbackEl.className = 'feedback neutral';
        feedbackEl.classList.remove('hidden');
        feedbackMessageEl.textContent = 'Marked for practice again. Solve this position anew.';
      }
      return;
    }

    // Checking a solved card retains the accepted move and review state.
    solved = true;
    if (!evaluationRunId) learnedToggleWrapEl?.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    engineToggleEl.disabled = false;
    engineToggleWrapEl?.classList.remove('hidden');
    updateHistoryUI();
    updateNavigationMeta();
    feedbackEl.className = 'feedback good';
    feedbackEl.classList.remove('hidden');
    feedbackMessageEl.title = 'Position learned. It will stay out of the active training mix unless you reset it later.';
    feedbackMessageEl.textContent = '✓ Solved';
    updatePositionRatingUI();
    if (engineToggleEl.checked) refreshEngineEvaluation();
  } catch (error) {
    learnedCheckbox.checked = !requested;
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackMessageEl.textContent = error.message || 'Could not update learned state.';
  }
});



coachChatEl?.addEventListener('click', event => {
  const edit = event.target.closest('.feedback-edit-correction');
  if (edit) {
    const group = edit.closest('.coach-response-feedback');
    const messageId = Number(group?.dataset.messageId || 0);
    if (messageId && group.querySelector('.coach-feedback-button[data-rating="-1"].active')) {
      openCorrectionDialog('coaching', messageId, {suggested_text: group.dataset.suggestedText || ''});
    }
    return;
  }
  const button = event.target.closest('.coach-feedback-button');
  if (button) rateCoachResponse(button);
});

coachFormEl?.addEventListener('submit', sendCoachMessage);
coachInputEl?.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendCoachMessage(event);
  }
});

// Critical path: playlist manifest → first card → board and controls.
// Only then fetch the lower-priority Process dashboard data.
loadPositions(false).finally(() => {
  if (!hudHasLoaded) {
    hudHasLoaded = true;
    setTimeout(() => updateJobHud().catch(() => {}), 200);
  }
});

// The analysis dashboard is a small graph launcher until explicitly expanded.
(function initializeAnalysisDashboard() {
  const hud = document.getElementById('analysis-hud');
  const toggle = document.getElementById('hud-toggle');
  const body = document.getElementById('hud-body');
  if (!hud || !toggle || !body) return;
  const storageKey = `chess-analysis-hud-expanded:${jobId}`;
  let expanded = false;
  try { expanded = localStorage.getItem(storageKey) === 'true'; } catch (_) { /* Private browsing */ }
  const render = () => {
    hud.classList.toggle('collapsed', !expanded);
    body.hidden = !expanded;
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.setAttribute('aria-label', expanded ? 'Minimize Process dashboard' : 'Expand Process dashboard');
    toggle.title = expanded ? 'Minimize Process dashboard' : 'Show Process dashboard';
  };
  toggle.addEventListener('click', () => {
    expanded = !expanded;
    try { localStorage.setItem(storageKey, String(expanded)); } catch (_) { /* Storage unavailable */ }
    render();
  });
  render();
})();
