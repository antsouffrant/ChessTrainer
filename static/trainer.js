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
const forceNewPlaylist = initialQuery.get('new_playlist') === '1';
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
  if (!positions.length) return;
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
const hasExplicitTrainingTarget = Boolean(conceptKey || openingKey || openingVariation || requestedPositionId || trainerLearningMode || trainerListingScope || trainerRatingMin || trainerRatingMax || new URLSearchParams(location.search).has('sort'));
let savedTraining = null;
try { savedTraining = JSON.parse(localStorage.getItem(`${trainingStateKey}-state`) || 'null'); } catch (_) {}
if (!hasExplicitTrainingTarget && savedTraining?.url?.startsWith(`/trainer/${jobId}`) && savedTraining.url !== `${location.pathname}${location.search}`) {
  location.replace(savedTraining.url);
}
const resumePositionId = !forceNewPlaylist && !requestedPositionId && savedTraining?.url === sessionUrl ? Number(savedTraining.positionId) || null : null;
function rememberTraining(positionId) {
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
let inputLocked = true;
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

const boardEl = document.getElementById('chessboard');
const feedbackEl = document.getElementById('feedback');
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
const coachChatEl = document.getElementById('coach-chat');
const coachFormEl = document.getElementById('coach-form');
const coachInputEl = document.getElementById('coach-input');
const coachSendEl = document.getElementById('coach-send');
const coachModeNoteEl = document.getElementById('coach-mode-note');
const coachConceptEventEl = document.getElementById('coach-concept-event');
const refreshPositionEl = document.getElementById('refresh-position-button');
const solvedPositionControlsEl = document.getElementById('solved-position-controls');
const trainerRootEl = document.getElementById('trainer-root');
const coachPanelEl = document.querySelector('.coach-panel');
let coachThreadReadyPositionId = null;
const historicCoachRequests = new Set();
const brilliantCoachRequests = new Set();
const proactiveCoachRequests = new Map();
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
function learningModeLabel(value, category='') { return learningModeMeta(value, category).label; }

function renderConcepts(concepts = []) {
  const el = document.getElementById('lesson-concepts');
  if (!el) return;
  el.innerHTML = '';
  if (!concepts.length) {
    el.classList.add('hidden');
    return;
  }
  for (const concept of concepts) {
    const chip = document.createElement('span');
    chip.className = `lesson-concept-chip${concept.is_primary ? ' primary' : ''}`;
    chip.textContent = concept.name;
    chip.title = concept.evidence || concept.description || '';
    el.appendChild(chip);
  }
  el.classList.remove('hidden');
}

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

function isUsersPiece(piece, color) {
  if (!piece) return false;
  const isWhite = piece === piece.toUpperCase();
  return color === 'white' ? isWhite : !isWhite;
}

function isPieceForColor(piece, color) {
  if (!piece || !color) return false;
  const isWhite = piece === piece.toUpperCase();
  return color === 'white' ? isWhite : !isWhite;
}

function analysisModeActive() {
  return solved && Boolean(engineToggleEl?.checked);
}

function interactionColor(position) {
  return analysisModeActive() ? analysisTurn : position.user_color;
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
  boardEl.querySelectorAll('.moving-piece').forEach(el => el.remove());
  const canInteract = interactive && ((analysisModeActive() && analysisTurn) || (!solved && !inputLocked));
  const activeColor = interactionColor(position);
  renderedBoardMap = board;
  boardInteractive = Boolean(canInteract);
  boardEl.classList.toggle('is-interactive', boardInteractive);
  for (const [squareName, square] of boardSquares.entries()) {
    square.classList.remove('selected','legal-target','correct','wrong','near-optimal','last-move');
    updatePieceOnSquare(square, squareName, board[squareName], canInteract, activeColor);
  }
}

// Drag-and-drop and click-to-move must both use the same legal-move resolver.
// The pointer controller waits for real movement before starting a drag, so
// taps/clicks are left intact and dragging works on touch screens too.
boardDragController = window.installBoardPointerDrag(boardEl, {
  canStart: from => boardInteractive &&
    isPieceForColor(renderedBoardMap[from], interactionColor(currentPosition())),
  onStart: from => {
    selectedSquare = from;
    paintSelection();
  },
  onDrop: (from, to) => {
    const legalMove = boardInteractive ? resolveLegalMove(from, to) : null;
    selectedSquare = null;
    paintSelection();
    if (legalMove) submitBoardMove(from, to, legalMove);
  },
  onCancel: () => { selectedSquare = null; paintSelection(); }
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
  try {
    const structured = typeof message.structured_json === 'string'
      ? JSON.parse(message.structured_json || '{}')
      : (message.structured_json || {});
    const claims = structured.claims || [];
    if (role === 'assistant' && claims.length && claims[0].verdict) {
      const v = claims[0].verdict;
      verdict = `<span class="coach-verdict ${escapeCoachHtml(v)}">${escapeCoachHtml(v)}</span>`;
    }
    const reference = structured.historical_reference;
    historical = role === 'assistant' && structured.kind === 'historical_reference';
    brilliant = role === 'assistant' && structured.kind === 'brilliant_reference';
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
  const messageId = Number(message.id || 0);
  const rating = Number(message.feedback_rating || 0);
  const feedback = role === 'assistant' && messageId && !historical && !brilliant
    ? `<div class="coach-response-feedback" data-message-id="${messageId}" aria-label="Rate this coaching response">
         <button type="button" class="coach-feedback-button${rating === 1 ? ' active' : ''}" data-rating="1" title="Helpful coaching response" aria-label="Thumbs up">👍</button>
         <button type="button" class="coach-feedback-button${rating === -1 ? ' active' : ''}" data-rating="-1" title="Unhelpful coaching response" aria-label="Thumbs down">👎</button>
       </div>`
    : '';
  return `<div class="coach-message ${role}${historical ? ' historic-coach-message' : ''}${brilliant ? ' brilliant-coach-message' : ''}"${messageId ? ` data-message-id="${messageId}"` : ''}><div class="coach-message-label">${historical ? 'Coach · Chess history' : brilliant ? 'Coach · From your games' : label}</div>${verdict}<div class="coach-message-body">${escapeCoachHtml(message.content)}${historicalLink || brilliantLink ? `<div class="historic-coach-link-row">${historicalLink || brilliantLink}</div>` : ''}</div>${feedback}</div>`;
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
  if (!position || !coachChatEl || !solved || !position.learned) return Promise.resolve();
  if (proactiveCoachRequests.has(position.id)) return proactiveCoachRequests.get(position.id);
  const promise = maybeOfferHistoricalCoach(position).then(shown => {
    if (!shown && displayedPositionId === position.id) return maybeOfferBrilliantCoach(position);
  });
  proactiveCoachRequests.set(position.id, promise);
  return promise;
}

function updateCoachMode() {
  if (!coachModeNoteEl || !coachInputEl) return;
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
  coachThreadReadyPositionId = null;
  coachConceptEventEl?.classList.add('hidden');
  coachChatEl.innerHTML = '<div class="coach-empty">Loading coaching thread…</div>';
  try {
    const response = await fetch(`/api/positions/${position.id}/coach`);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not load coach');
    if (displayedPositionId !== position.id) return;
    const messages = result.messages || [];
    if (!messages.length) {
      coachChatEl.innerHTML = `<div class="coach-empty">${solved
        ? 'Ask about a move, line, plan, or concept. Try: <em>“What if Nc3?”</em>'
        : 'Ask about a candidate move or idea. The coach can test your move without revealing the engine preference.'}</div>`;
    } else {
      coachChatEl.innerHTML = messages.map(coachMessageHtml).join('');
      coachChatEl.scrollTop = coachChatEl.scrollHeight;
    }
  } catch (error) {
    if (displayedPositionId !== position.id) return;
    coachChatEl.innerHTML = `<div class="coach-empty">Coach history unavailable: ${escapeCoachHtml(error.message)}</div>`;
  }
  if (displayedPositionId !== position.id) return;
  coachThreadReadyPositionId = position.id;
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
  } else if (reviewStage === 'history' && historyPly === target && solvingMoveFen) {
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
  renderBoard(currentPosition(), fenAtHistoryPly(historyPly), canInteract);
  clearHighlights();
  updateHistoryUI();

  if (!solved) {
    feedbackEl.className = 'feedback neutral';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = historyPly === target
      ? ''
      : 'Reviewing the game. Move forward to return to the puzzle.';
    feedbackEl.classList.toggle('hidden', historyPly === target);
  } else if (engineToggleEl.checked) {
    refreshEngineEvaluation();
  }
}

function showSolvedReviewPosition() {
  if (!solvingMoveFen) return false;
  reviewStage = 'solved';
  showingSolvedMove = true;
  historyPly = contextTargetPly();
  analysisLegalMoves = [];
  analysisTurn = null;
  selectedSquare = null;
  clearBoardMark();
  clearHighlights();
  renderBoard(currentPosition(), solvingMoveFen, analysisModeActive());
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
    renderBoard(currentPosition(), analysisBase.fen, false);
  } else {
    const frame = analysisFrames[nextCursor - 1];
    reviewStage = 'analysis';
    historyPly = Number(analysisBase.historyPly || historyPly);
    showingSolvedMove = false;
    analysisLegalMoves = Array.isArray(frame.legalMoves) ? frame.legalMoves : [];
    analysisTurn = frame.turn || null;
    renderBoard(currentPosition(), frame.fen, analysisModeActive());
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
  if (direction > 0 && historyPly >= target && solvingMoveFen) {
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
  if (analysisModeActive()) return Array.isArray(analysisLegalMoves) ? analysisLegalMoves : [];
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

function legalTargetsFrom(squareName) {
  return currentLegalMoves()
    .filter(move => move.startsWith(squareName))
    .map(move => move.slice(2, 4));
}

function handleSquareClick(squareName, board) {
  if ((!analysisModeActive() && solved) || (!analysisModeActive() && inputLocked)) return;
  const position = currentPosition();
  const activeColor = interactionColor(position);
  if (!selectedSquare) {
    if (!isPieceForColor(board[squareName], activeColor)) return;
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

  const legalMove = resolveLegalMove(selectedSquare, squareName);
  if (!legalMove) {
    feedbackEl.className = 'feedback neutral';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = analysisModeActive()
      ? 'That move is not legal in this analysis position.'
      : 'That move is not legal. Keep looking.';
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
  const position = currentPosition();
  const startingFen = currentDisplayedFen();
  prepareAnalysisBranch();
  const actionToken = ++analysisActionToken;
  selectedSquare = null;
  clearHighlights();
  hideEngineArrow();
  boardInteractive = false;

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
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = 'Could not play that analysis move.';
    return;
  }

  if (actionToken !== analysisActionToken || displayedPositionId !== position.id || !analysisModeActive()) return;
  if (analysisCursor < analysisFrames.length) analysisFrames = analysisFrames.slice(0, analysisCursor);
  analysisFrames.push({
      fen: result.fen,
      moveUci: legalMove,
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
  if (analysisModeActive()) return playAnalysisMove(from, to, legalMove);
  return attemptMove(from, to, legalMove);
}

function renderSolvedDetails(result) {
  updateCoachMode();
  if (taskHeadingEl) taskHeadingEl.textContent = 'Why this works';
  if (hintToggleEl) hintToggleEl.classList.add('hidden');
  const modeMeta = learningModeMeta(currentPosition()?.learning_mode, currentPosition()?.category);
  if (categoryEl) {
    const position = currentPosition();
    categoryEl.textContent = categoryLabel(position?.category).toUpperCase();
    categoryEl.className = `eyebrow result-category mode-${modeMeta.tone}`;
    categoryEl.classList.remove('hidden');
  }
  if (coachTextEl) {
    coachTextEl.textContent = (result.accepted_alternative && result.accepted_move_explanation)
      ? result.accepted_move_explanation
      : (result.coach_explanation || 'Review how the move changes the threats, defenders, and resulting position.');
    coachTextEl.classList.remove('hidden');
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
  renderConcepts(result.concepts || currentPosition()?.concepts || []);
  solutionEl.classList.remove('hidden');
  maybeOfferProactiveCoach(currentPosition());
}

async function loadSolvedDetails(position) {
  try {
    const response = await fetch(`/api/positions/${position.id}/solution`);
    if (!response.ok) return;
    const result = await response.json();
    if (displayedPositionId === position.id && solved) {
      solutionBestMoveUci = result.best_move_uci || solutionBestMoveUci;
      solutionBestMoveSan = result.best_move_san || solutionBestMoveSan;
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

  inputLocked = true;
  selectedSquare = null;
  clearHighlights();
  boardInteractive = false;
  const animationPromise = new Promise(resolve => animateMove(position, from, to, resolve, false));

  let response;
  let result;
  try {
    response = await fetch(`/api/positions/${position.id}/attempt`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({move: moveUci, opening_key:openingKey})
    });
    result = await response.json();
  } catch (_) {
    await animationPromise;
    inputLocked = false;
    renderBoard(position, position.fen, true);
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = 'Could not submit the move. Try again.';
    return;
  }

  await animationPromise;
  if (displayedPositionId !== position.id) return;
  if (!response.ok) {
    inputLocked = false;
    renderBoard(position, position.fen, true);
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = result.error || 'Could not verify that move. Try again.';
    return;
  }
  if (!result.legal) {
    inputLocked = false;
    renderBoard(position, position.fen, true);
    feedbackEl.className = 'feedback neutral';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = 'That move is not legal. Keep looking.';
    return;
  }

  // The legal move has already animated while server verification ran. Finalize
  // captures/castling/promotion from the authoritative returned FEN.
  if (displayedPositionId !== position.id) return;

  if (!result.correct) {
      renderBoard(position, result.attempted_fen, false);
      highlight(to, 'wrong');
      showBoardMark('wrong');
      feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
      feedbackEl.textContent = 'Not quite — try again.';

      previewTimers.push(setTimeout(() => {
        if (displayedPositionId !== position.id || solved) return;
        clearBoardMark();
        previewOpponentMove(position, true);
      }, WRONG_FEEDBACK_MS));
      return;
    }

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
      uci: solvingMoveUci, san: solvingMoveSan, fen: solvingMoveFen
    };
    keepPlaylistSnapshot();
    solutionBestMoveUci = result.best_move_uci || null;
    solutionBestMoveSan = result.best_move_san || null;
    clearAnalysisBranch();
    reviewStage = 'solved';
    historyPly = contextTargetPly();
    learnedCheckbox.checked = true;
    renderBoard(position, result.attempted_fen, false);
    updateHistoryUI();
    if (result.accepted_alternative) {
      // Preserve the move the learner actually played in yellow while showing
      // the engine preference in green. Green is applied last and therefore
      // takes precedence on any shared source/destination square.
      highlight(from, 'near-optimal');
      highlight(to, 'near-optimal');
      const bestUci = String(result.best_move_uci || '');
      if (bestUci.length >= 4) {
        highlight(bestUci.slice(0, 2), 'correct');
        highlight(bestUci.slice(2, 4), 'correct');
      }
    } else {
      highlight(from, 'correct');
      highlight(to, 'correct');
    }
    showBoardMark('correct');
    feedbackEl.className = 'feedback good';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = result.accepted_alternative
      ? 'Strong move — accepted as near-optimal and position marked learned.'
      : 'Correct — position marked learned.';

    position.estimated_rating = result.estimated_rating ?? position.estimated_rating;
    position.difficulty_score = result.difficulty_score ?? position.difficulty_score;
    renderSolvedDetails(result);
    if (!result.accepted_alternative) loadSolvedDetails(position);
    engineToggleEl.disabled = false;
    if (engineToggleWrapEl) engineToggleWrapEl.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    if (learnedToggleWrapEl) learnedToggleWrapEl.classList.remove('hidden');
    updateNavigationMeta();
}


async function refreshCurrentPosition() {
  const position = currentPosition();
  if (!position || !refreshPositionEl) return;
  refreshPositionEl.disabled = true;
  const originalLabel = refreshPositionEl.textContent;
  refreshPositionEl.textContent = 'Resetting…';
  try {
    const response = await fetch(`/api/positions/${position.id}/reset`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({opening_key:openingKey})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not reset puzzle');
    position.learned = 0;
    delete sessionSolvedMoves[String(position.id)];
    keepPlaylistSnapshot();
    solved = false;
    showingSolvedMove = false;
    solvingMoveUci = null;
    solvingMoveSan = null;
    solvingMoveFen = null;
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
    feedbackEl.textContent = error.message || 'Could not reset this puzzle.';
  } finally {
    refreshPositionEl.disabled = false;
    refreshPositionEl.textContent = originalLabel;
  }
}

async function rateCoachResponse(button) {
  const container = button.closest('.coach-response-feedback');
  const messageId = Number(container?.dataset.messageId || 0);
  const rating = Number(button.dataset.rating || 0);
  if (!messageId || ![-1, 1].includes(rating)) return;
  const buttons = [...container.querySelectorAll('.coach-feedback-button')];
  buttons.forEach(item => item.disabled = true);
  try {
    const response = await fetch(`/api/coach/messages/${messageId}/feedback`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({rating})
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save feedback');
    buttons.forEach(item => item.classList.toggle('active', Number(item.dataset.rating) === rating));
    container.classList.add('saved');
    container.title = rating === 1
      ? 'Saved as helpful coaching feedback.'
      : 'Saved as unhelpful coaching feedback.';
  } catch (_) {
    container.classList.add('error');
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
        body: JSON.stringify({position_ids: ids, opening_key: openingKey})
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
  nextButtonEl.disabled = !positions.length || (!solved && currentIndex >= positions.length - 1);
  nextButtonEl.textContent = solved && currentIndex >= positions.length - 1 ? (openingKey?'Back to openings →':'Back to lessons →') : 'Next position →';
}

async function showPosition(index) {
  if (!positions.length) return;
  const token = ++positionDisplayToken;
  const chosenIndex = Math.max(0, Math.min(index, positions.length - 1));
  currentIndex = chosenIndex;
  // Prevent an earlier puzzle's delayed context/solution from painting over
  // this card while its next chunk is in flight.
  displayedPositionId = null;
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
        feedbackEl.textContent = error.message || 'Could not load this position.';
      }
      return;
    }
  }
  if (token !== positionDisplayToken) return;
  boardEl.classList.remove('position-loading');
  const p = positions[chosenIndex];
  resetGameShare();
  displayedPositionId = p.id;
  rememberTraining(p.id);
  selectedSquare = null;
  // Learned is the authoritative status. A stale saved solving move must
  // never resurrect a position explicitly marked for practice again.
  if (!p.learned && sessionSolvedMoves[String(p.id)]) {
    delete sessionSolvedMoves[String(p.id)];
    keepPlaylistSnapshot();
  }
  const savedSolve = p.learned ? (sessionSolvedMoves[String(p.id)] || null) : null;
  const restoredSolvedFen = savedSolve?.fen || (p.learned ? p.review_best_fen : null);
  solved = Boolean(p.learned);
  inputLocked = true;
  currentContext = null;
  historyPly = 0;
  showingSolvedMove = Boolean(solved && restoredSolvedFen);
  displayedFen = '';
  analysisActionToken += 1;
  clearAnalysisBranch();
  reviewStage = solved && restoredSolvedFen ? 'solved' : 'history';
  solvingMoveUci = savedSolve?.uci || (solved ? p.best_move_uci : null);
  solvingMoveSan = savedSolve?.san || (solved ? p.best_move_san : null);
  solvingMoveFen = restoredSolvedFen || null;
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
  feedbackEl.textContent = solved ? 'Already learned. Review the game or move to another puzzle.' : '';
  feedbackEl.classList.toggle('hidden', !solved);
  solutionEl.classList.add('hidden');
  coachThreadReadyPositionId = null;
  renderConcepts([]);
  learnedCheckbox.checked = Boolean(p.learned);
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
  if (coachTextEl) {
    coachTextEl.textContent = 'Watch the last move, then find a strong response.';
    coachTextEl.classList.remove('hidden');
  }
  if (hintToggleEl) {
    hintToggleEl.textContent = 'Show hint';
    hintToggleEl.classList.remove('hidden');
  }
  updateNavigationMeta();
  updateCoachMode();
  // Draw the actual board and restore solved feedback BEFORE fetching the
  // full game history, coaching thread, or slow engine explanations.
  renderBoard(p, restoredSolvedFen || p.fen, false);
  if (solved) {
    if (solvingMoveUci?.length >= 4) {
      highlight(solvingMoveUci.slice(0, 2), 'correct');
      highlight(solvingMoveUci.slice(2, 4), 'correct');
    }
    showBoardMark('correct');
    feedbackEl.className = 'feedback good';
    feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = '✓ Solved position — review the correct move or continue.';
    solutionEl.classList.remove('hidden');
    if (p.estimated_rating) document.getElementById('puzzle-rating').textContent = `≈ ${p.estimated_rating}`;
    renderConcepts(p.concepts || []);
    engineToggleEl.disabled = false;
    engineToggleWrapEl?.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    learnedToggleWrapEl?.classList.remove('hidden');
    loadSolvedDetails(p);
  }
  loadCoachThread(p);

  const context = await loadGameContext(p);
  if (token !== positionDisplayToken || displayedPositionId !== p.id) return;
  currentContext = context;
  historyPly = context?.available ? Number(context.target_history_ply || 0) : 0;
  renderPgnContext();
  queueNearbyPositions(chosenIndex);

  if (solved) {
    inputLocked = true;
    updateHistoryUI();
    // Solved state and the green board check survive history loading.
    if (reviewStage === 'solved') showBoardMark('correct');
    updateNavigationMeta();
    return;
  }

  feedbackEl.className = 'feedback neutral';
  feedbackEl.classList.remove('hidden');
  feedbackEl.textContent = '';
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
    if (savedPlaylist?.ids?.length) {
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
      if (openingKey) params.set('opening', openingKey);
      if (openingVariation) params.set('variation', openingVariation);
      if (trainerLearningMode) params.set('learning_mode', trainerLearningMode);
      if (trainerSort) params.set('sort', trainerSort);
      if (trainerListingScope) params.set('listing', '1');
      if (trainerRatingMin !== null) params.set('rating_min', String(trainerRatingMin));
      if (trainerRatingMax !== null) params.set('rating_max', String(trainerRatingMax));
      if (requestedPositionPending) params.set('position_id', requestedPositionPending);
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
      feedbackEl.textContent = analysisComplete ? 'Playlist complete. Choose another lesson.' : 'Analysis is still running. This page will update automatically.';
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
    feedbackEl.textContent = error.message || 'Could not load training playlist.';
  } finally { positionsRequestPending = false; }
}

function processStateName(status) {
  return ({running:'Running',retrieving:'Retrieving',queued:'Queued',paused:'Paused',complete:'Complete',error:'Failed',stopped:'Stopped'})[status] || 'Not started';
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
  const priority = value => ['running','retrieving'].includes(value) ? 3
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
  if (direction > 0 && solved && currentIndex === positions.length - 1) {
    // Exhaust the current snapshot only when the learner finishes its last card.
    localStorage.removeItem(trainingStateKey);
    localStorage.removeItem(`${trainingStateKey}-state`);
    localStorage.removeItem(trainingPlaylistKey);
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
if (hintToggleEl) {
  hintToggleEl.addEventListener('click', () => {
    if (solved || !coachTextEl) return;
    const showingHint = hintToggleEl.textContent === 'Hide hint';
    coachTextEl.textContent = showingHint
      ? 'Watch the last move, then find a strong response.'
      : (currentPosition()?.coach_prompt || 'Read the position, identify the opponent’s threat, and find a strong response.');
    hintToggleEl.textContent = showingHint ? 'Show hint' : 'Hide hint';
  });
}
engineToggleEl.addEventListener('change', () => {
  selectedSquare = null;
  clearHighlights();
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
    renderBoard(currentPosition(), currentDisplayedFen(), false);
    updateHistoryUI();
  }
});

window.addEventListener('resize', () => {
  if (solved && engineToggleEl.checked) refreshEngineEvaluation();
});

function isCoachInteraction(target) {
  return Boolean(target?.closest?.('.coach-panel, .game-share'));
}

function chessKeyboardContextActive() {
  return trainerKeyboardArmed && !isCoachInteraction(document.activeElement);
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
  if (!chessKeyboardContextActive()) return;
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
        feedbackEl.textContent = 'Marked for practice again. Solve this position anew.';
      }
      return;
    }

    // Checking a solved card retains the accepted move and review state.
    solved = true;
    learnedToggleWrapEl?.classList.remove('hidden');
    solvedPositionControlsEl?.classList.remove('hidden');
    engineToggleEl.disabled = false;
    engineToggleWrapEl?.classList.remove('hidden');
    updateHistoryUI();
    updateNavigationMeta();
    feedbackEl.className = 'feedback good';
    feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = 'Position learned. It will stay out of the active training mix unless you reset it later.';
    if (engineToggleEl.checked) refreshEngineEvaluation();
  } catch (error) {
    learnedCheckbox.checked = !requested;
    feedbackEl.className = 'feedback bad';
  feedbackEl.classList.remove('hidden');
    feedbackEl.textContent = error.message || 'Could not update learned state.';
  }
});



coachChatEl?.addEventListener('click', event => {
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
