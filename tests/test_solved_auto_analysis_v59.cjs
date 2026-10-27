// A solved training board should accept the FIRST drag or click-and-move and
// switch to Analysis automatically, without an extra user toggle or engine eval.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/trainer.js', 'utf8');
function extract(name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^\\n]*\\) \\{[\\s\\S]*?\\n\\}`));
  assert.ok(match, `Missing ${name}`);
  return match[0];
}
const calls = [];
const engineToggleEl = {checked:false,disabled:false};
const sandbox = {
  solved:true, inputLocked:true, boardInteractive:true, selectedSquare:null,
  analysisTurn:null, analysisLegalMoves:[], currentContext:{legal_moves:['g1f3']},
  engineToggleEl, engineEvalEl:{textContent:'—'},
  currentDisplayedFen: () => '8/8/8/8/8/8/4p3/4K3 b - - 0 1',
  currentPosition: () => ({user_color:'white'}),
  paintSelection: () => calls.push('selection'),
  refreshEngineEvaluation: () => calls.push('evaluation-request'),
  clearBoardMark: () => calls.push('mark-clear'),
  updateHistoryUI: () => calls.push('status-update'),
  playAnalysisMove: (...args) => {calls.push(['analysis',...args]);return Promise.resolve();},
  attemptMove: (...args) => {calls.push(['puzzle',...args]);return Promise.resolve();},
  renderedBoardMap: {e2:'p'},
  isPieceForColor: (piece,color) => piece==='p' && color==='black',
  currentLegalMoves: null,
  feedbackEl: {className:'',classList:{remove(){}}},feedbackMessageEl:{textContent:''},
};
vm.createContext(sandbox);
for (const name of ['fenTurnColor','analysisModeActive','interactionColor',
                    'currentLegalMoves','resolveLegalMove','resolveBoardMove',
                    'activateSolvedBoardAnalysis','submitBoardMove','handleSquareClick']) {
  vm.runInContext(extract(name),sandbox);
}
assert.equal(sandbox.interactionColor(sandbox.currentPosition()),'black',
  'Solved board should use FEN side to move, not the learner color');
assert.equal(sandbox.currentLegalMoves().length,0,
  'Do not use the original puzzle legal moves on its solved FEN');
assert.equal(sandbox.resolveBoardMove('e2','e1'),'e2e1',
  'The server should validate the provisional first move');
// Simulate two-click interaction on the solved board, including an opposing
// piece (learner is White, but Black now moves in the displayed FEN).
sandbox.handleSquareClick('e2',sandbox.renderedBoardMap);
assert.equal(sandbox.selectedSquare,'e2');
assert.equal(engineToggleEl.checked,true,'Selecting a solved-board piece turns on Stockfish');
sandbox.handleSquareClick('e1',sandbox.renderedBoardMap);
assert.equal(engineToggleEl.checked,true,'Auto-enable analysis on the first move');
assert.ok(calls.some(c=>Array.isArray(c) && c.join('|')==='analysis|e2|e1|e2e1'));
assert.ok(!calls.some(c=>Array.isArray(c) && c[0]==='puzzle'),
  'Never re-submit a solved position as a puzzle attempt');
assert.equal(sandbox.engineEvalEl.textContent,'…');
// Toggle already enabled: subsequent moves stay in the same analysis branch.
calls.length=0;
sandbox.submitBoardMove('e1','d1','e1d1');
assert.ok(calls.some(c=>Array.isArray(c) && c[0]==='analysis'));
assert.equal(calls.filter(c=>c==='status-update').length,0);
// Unsolved puzzles retain strict attempt handling and never auto-enable.
sandbox.solved=false;
engineToggleEl.checked=false;
calls.length=0;
sandbox.submitBoardMove('g1','f3','g1f3');
assert.equal(engineToggleEl.checked,false);
assert.ok(calls.some(c=>Array.isArray(c) && c[0]==='puzzle'));
// Rendering the solved board must enable pointer input despite inputLocked.
sandbox.solved=true;
sandbox.inputLocked=true;
sandbox.boardInteractive=false;
engineToggleEl.checked=false;
sandbox.boardDragController = {cancel(){}};
sandbox.boardEl = {
  classList:{toggle(name,enabled){calls.push([name,Boolean(enabled)]);}},
  querySelectorAll(){return [];},
};
sandbox.boardSquares = new Map();
sandbox.parseFen = () => ({e2:'p'});
sandbox.ensureBoardGrid = () => 'white';
sandbox.hideEngineArrow = () => {};
sandbox.updatePieceOnSquare = () => {};
vm.runInContext(extract('renderBoard'),sandbox);
sandbox.renderBoard(sandbox.currentPosition(),sandbox.currentDisplayedFen(),true);
assert.equal(sandbox.boardInteractive,true);
assert.equal(sandbox.renderedBoardMap.e2,'p');
assert.match(source,/onDrop: \(from, to\) => \{\s*const legalMove = boardInteractive \? resolveBoardMove\(from, to\)/,
 'Drag-and-drop should use the same first-move resolver as clicks');
assert.match(source,/renderBoard\(position, solvingMoveFen \|\| solvedReviewFen, true\)/,
 'The actual accepted move should become the interactive solved board');
assert.match(source,/renderBoard\(p, restoredSolvedFen \|\| p\.fen, solved\)/,
 'Returning to solved cards should restore automatic analysis entry');
assert.match(source,/refreshEngineEvaluation\(\);\s*return;\s*\}\s*\n\s*if \(actionToken/,
 'Illegal first moves should restore the analysis board');
console.log('PASS: post-solve click/drag, FEN turn, automatic analysis and unsolved isolation');
