// Regression for accepted-but-non-optimal moves: the physical board always
// displays the player's accepted move; the engine-best piece is an overlay.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const src=fs.readFileSync('static/trainer.js','utf8');
const css=fs.readFileSync('static/styles.css','utf8');
const app=fs.readFileSync('app.py','utf8');
const functionText=name=>{
  const m=src.match(new RegExp(`function ${name}\\([^\\n]*\\) \\{[\\s\\S]*?\\n\\}`));
  assert.ok(m,`Function ${name} missing`);return m[0];
};

test('accepted board takes priority immediately after a correct alternative',()=>{
  assert.match(src,/solvedReviewFen = solvingMoveFen \|\| result\.best_fen \|\| null/);
  assert.match(src,/renderBoard\(position, solvingMoveFen \|\| solvedReviewFen, true\)/);
  assert.doesNotMatch(src,/renderBoard\(position, result\.best_fen \|\| result\.attempted_fen/);
  assert.match(src,/solvedReviewFen = solvingMoveFen \|\| solvedReviewFen \|\| result\.best_fen/);
});
test('the accepted board is restored after leaving/returning to a solved card',()=>{
  assert.match(src,/const restoredSolvedFen = \(p\.learned \? \(savedSolve\?\.fen \|\| p\.accepted_fen \|\| p\.review_best_fen\) : null\)/);
  assert.match(src,/solvedReviewFen = solvingMoveFen \|\| restoredSolvedFen/);
  assert.match(src,/renderBoard\(currentPosition\(\), solvedReviewFen, true\)/);
  assert.match(app,/card\['accepted_fen'\] = accepted_board\.fen\(\)/, 'evaluation reload must include the actual accepted FEN');
  assert.match(app,/session_key NOT GLOB 'eval_\*'/, 'ordinary training resume must not restore an evaluation-only solve');
  assert.match(app,/item\['accepted_fen'\] = board\.fen\(\)/, 'ordinary training resume must recover the accepted FEN');
});
test('green engine piece is a non-interactive ghost, not a physical board piece',()=>{
  const marks=[];
  const pieces={};
  const dest={pieces:[], querySelector(sel){return sel==='.piece'?null:null;},appendChild(el){this.pieces.push(el)}};
  const board={querySelector(selector){return selector==='[data-square="e4"]'?dest:null}};
  const doc={createElement(tag){assert.equal(tag,'i');return {className:'',title:'',attrs:{},classList:{add(v){this[v]=true;}},setAttribute(k,v){this.attrs[k]=v}};}};
  const ctx={solutionBestMoveUci:'e2e4',solutionBestMoveSan:'e4',solvingMoveUci:'e2e3',
    highlight:(...args)=>marks.push(args),currentPosition:()=>({fen:'7k/8/8/8/8/8/4P3/4K3 w - - 0 1'}),
    boardEl:board,document:doc,parseFen:()=>({e2:'P'}),PIECES:{P:'fa-chess-pawn'},
    String};
  vm.createContext(ctx);
  for(const name of ['renderEngineBestPreview','highlightSolvedMoveComparison'])vm.runInContext(functionText(name),ctx);
  ctx.highlightSolvedMoveComparison();
  assert.deepEqual(marks,[['e2','near-optimal'],['e3','near-optimal'],['e2','correct'],['e4','correct']]);
  assert.equal(dest.pieces.length,1);
  assert.match(dest.pieces[0].className,/best-move-preview fa-solid fa-chess-pawn/);
  assert.equal(dest.pieces[0].attrs['aria-hidden'],'true');
  assert.match(css,/\.square \.best-move-preview \{/);
  assert.match(css,/pointer-events: none/);
});
test('occupied optimal square keeps its real piece visible underneath a small badge',()=>{
  const square={children:[],querySelector(s){return s==='.piece'?{}:null},appendChild(p){this.children.push(p)}};
  const ctx={boardEl:{querySelector:()=>square},parseFen:()=>({a2:'P'}),PIECES:{P:'pawn'},
    solutionBestMoveSan:'a4',document:{createElement:()=>({className:'',classList:{add(label){this.added=label;}},setAttribute(){},title:''})}};
  vm.createContext(ctx);vm.runInContext(functionText('renderEngineBestPreview'),ctx);
  ctx.renderEngineBestPreview({fen:'any'},'a2a4');
  assert.equal(square.children[0].classList.added,'has-occupant');
  assert.match(css,/\.best-move-preview\.has-occupant/);
});
