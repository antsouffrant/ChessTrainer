// Regression: unlearning must invalidate the stored solved FEN, even when the
// position remains in the same pinned training playlist for backward review.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/trainer.js', 'utf8');
const saved = new Map();
const cards = [
  {id:7, learned:1, review_best_fen:'reviewed-7', best_move_uci:'b1c3'},
  {id:8, learned:1, review_best_fen:'reviewed-8', best_move_uci:'g1f3'},
];
const session = {'7':{fen:'solved-7',uci:'b1c3'}, '8':{fen:'solved-8',uci:'g1f3'}};
const checkbox = {checked:false, handlers:{}, addEventListener(name, fn) {this.handlers[name]=fn;}};
const feedback = {className:'',textContent:'',classList:{remove(){},add(){}}};
const ctx = {
 positions:cards, sessionSolvedMoves:session, sessionUrl:'/trainer/1', jobId:1,
 trainingPlaylistKey:'test-playlist', localStorage:{setItem:(k,v)=>saved.set(k,JSON.parse(v))},
 learnedCheckbox:checkbox, currentPosition:()=>cards[0], openingKey:'open',
 fetch:async()=>({ok:true,json:async()=>({ok:true,learned:false,affected_position_ids:[7,8]})}),
 feedbackEl:feedback, displayedPositionId:7, solved:true, currentIndex:0,
 showPosition:async()=>{ctx.solved=Boolean(cards[0].learned);ctx.displayedPositionId=7;},
 learnedToggleWrapEl:null, solvedPositionControlsEl:null,engineToggleEl:{checked:false,disabled:false},
 engineToggleWrapEl:null, updateHistoryUI:()=>{},updateNavigationMeta:()=>{},
 JSON, Set,Number,String,Boolean,
};
vm.createContext(ctx);
const fstart=src.indexOf('function keepPlaylistSnapshot() {');
const fend=src.indexOf('// An explicit lesson or position link', fstart);
assert(fstart>=0 && fend>fstart);
vm.runInContext(src.slice(fstart,fend),ctx);
const hstart=src.indexOf("learnedCheckbox.addEventListener('change', async () => {");
const hend=src.indexOf('\n\n\ncoachChatEl?.addEventListener',hstart);
assert(hstart>=0 && hend>hstart);
vm.runInContext(src.slice(hstart,hend),ctx);
(async()=>{
 await checkbox.handlers.change();
 assert.equal(cards[0].learned,0);
 assert.equal(cards[1].learned,0,'equivalent opening records should synchronize');
 assert.equal(ctx.solved,false,'unlearn restores active training state');
 assert.equal(session['7'],undefined,'accepted move removed from session');
 assert.equal(session['8'],undefined,'equivalent move removed from session');
 assert.deepEqual(Object.keys(saved.get('test-playlist').solvedMoves),[]);
 assert.deepEqual(Object.keys(ctx.savedPlaylist.solvedMoves),[], 'in-memory snapshot cannot restore old solve');
 assert.match(feedback.textContent,/practice again/);
 // The restored board is unsolved even when an old session accidentally still
 // contains a move: the stored learned flag takes precedence.
 assert.match(src,/const savedSolve = p\.learned \? \(sessionSolvedMoves\[String\(p\.id\)\] \|\| null\) : null;/);
 assert.match(src,/solved = Boolean\(p\.learned\);/);
 console.log('Unlearn / Last position restoration: passed');
})().catch(e=>{console.error(e);process.exit(1)});
