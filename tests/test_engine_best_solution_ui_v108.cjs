const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const js=fs.readFileSync('static/trainer.js','utf8');
const html=fs.readFileSync('templates/trainer.html','utf8');
const css=fs.readFileSync('static/styles.css','utf8');
const app=fs.readFileSync('app.py','utf8');
function extract(name) {
  const at=js.indexOf(`function ${name}(`);
  assert.ok(at>=0,`Function ${name} missing`);
  let start=js.indexOf('{',at), depth=0, end=-1;
  // Keep tests focused on methods with no JS template strings containing braces.
  for(let i=start;i<js.length;i++) {
    if(js[i]==='{')depth++;
    if(js[i]==='}'&&--depth===0){end=i;break;}
  }
  assert.ok(end>start);
  return js.slice(at,end+1);
}
// The simple brace extractor handles these two functions (no template literals).
function extractFixed(name) {
  const re=new RegExp(`function ${name}\\([^\\n]*\\) \\{[\\s\\S]*?\\n\\}`);
  const match=js.match(re);
  assert.ok(match,`Missing ${name}`);
  return match[0];
}
test('solved details table contains Opening above Engine preference',()=>{
  const solution=html.split('<div id="solution"')[1].split('</div>\n\n')[0];
  assert.ok(solution.indexOf('id="solved-opening-row"')<solution.indexOf('Engine preference'));
  assert.doesNotMatch(html,/class="solved-opening hidden"/);
  assert.match(js,/solvedOpeningRowEl\?\.classList\.toggle\('hidden', !opening\)/);
  assert.match(js,/solvedOpeningRowEl\?\.classList\.add\('hidden'\)/);
});
test('Gold accepted alternative is separate from green engine-best on both solve and review',()=>{
  const marks=[];
  const ctx={solutionBestMoveUci:'e2e4',solvingMoveUci:'e2e3',highlight:(sq,color)=>marks.push([sq,color]),currentPosition:()=>({fen:'8/8/8/8/8/8/4P3/4K2k w - - 0 1'}),boardEl:null,renderEngineBestPreview:()=>{}};
  vm.createContext(ctx);
  vm.runInContext(extractFixed('highlightSolvedMoveComparison'),ctx);
  ctx.highlightSolvedMoveComparison();
  assert.deepEqual(marks,[['e2','near-optimal'],['e3','near-optimal'],['e2','correct'],['e4','correct']]);
  marks.length=0;
  ctx.solvingMoveUci='e2e4';ctx.highlightSolvedMoveComparison();
  assert.deepEqual(marks,[['e2','correct'],['e4','correct']]);
  assert.match(css,/\.square\.near-optimal\.correct\s*\{/);
  assert.match(js,/renderBoard\(position, solvingMoveFen \|\| solvedReviewFen, true\)/);
  assert.match(js,/renderBoard\(currentPosition\(\), solvedReviewFen, true\)/);
  assert.match(js,/highlightSolvedMoveComparison\(\);/);
  assert.match(app,/'best_fen': best_fen/);
  assert.match(app,/'best_fen': _canonical_review_fen\(row\['fen'\], row\['best_move_uci'\]\)/);
  assert.match(app,/FROM evaluation_attempts/);
  assert.match(app,/card\['accepted_move_uci'\] = accepted\['move_uci'\]/);
  assert.match(js,/p\.accepted_move_uci \|\| p\.best_move_uci/);
});
test('Best move explanation always describes engine primary, not an accepted alternative',()=>{
  const classes={toggle(){}};
  const ctx={
    coachAttemptCommentsEl:{replaceChildren(){},classList:classes,childElementCount:0},
    coachPositionReviewEl:{},coachChatEl:{scrollTop:1},
    coachSolutionLabelEl:{textContent:'',dataset:{}},coachTextEl:{textContent:''},
    solutionBestMoveUci:'e2e4',solutionBestMoveSan:'e4',displayedPositionId:17,
    currentPosition:()=>({best_move_uci:'e2e4',best_move_san:'e4',coach_explanation:'e4 wins the central tempo.',coaching_version:'unknown generation'}),
    attemptNotesFromRecap:s=>s.attempt_comments,updatePositionRatingUI(){},loadPositionRatings(){},
    document:{querySelectorAll:()=>[]},
  };
  vm.createContext(ctx);vm.runInContext(extractFixed('renderCoachAttemptComments'),ctx);
  ctx.renderCoachAttemptComments({attempt_comments:[
    {origin:'solving',move_uci:'d2d4',move_san:'d4',correct:true,text:'d4 is also playable.'}
  ]},17);
  assert.equal(ctx.coachSolutionLabelEl.textContent,'Best move · e4');
  assert.equal(ctx.coachSolutionLabelEl.dataset.fromRecap,'0');
  assert.equal(ctx.coachTextEl.textContent,'e4 wins the central tempo.');
  ctx.renderCoachAttemptComments({attempt_comments:[
    {origin:'solving',move_uci:'e2e4',move_san:'e4',correct:true,text:'e4 gains space.'}
  ]},17);
  assert.equal(ctx.coachSolutionLabelEl.dataset.fromRecap,'1');
  assert.equal(ctx.coachTextEl.textContent,'e4 gains space.');
  assert.doesNotMatch(js,/result\.accepted_alternative && result\.accepted_move_explanation/);
});
test('Three coach message types have parallel names without changing feedback identities',()=>{
  assert.match(html,/Coach · Best move/);
  assert.match(html,/id="coach-solution-label">Best move/);
  assert.match(js,/'Game move' : 'Attempted move'/);
  assert.match(js,/votes\.dataset\.feedbackCategory = 'continuation'/);
  assert.match(js,/votes\.dataset\.continuationKey = note\.origin === 'game'/);
});
