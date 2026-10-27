// The gate applies to the button and every forward navigation path.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/trainer.js','utf8');
const view = fs.readFileSync('templates/trainer.html','utf8');
const css = fs.readFileSync('static/styles.css','utf8');
const app = fs.readFileSync('app.py','utf8');
function method(name, async=false) {
  const start=src.indexOf(`${async?'async ':''}function ${name}(`);
  assert(start>=0,`Missing ${name}`);
  let depth=0, opened=false;
  for(let i=src.indexOf('{',start);i<src.length;i++){
    if(src[i]==='{'){++depth;opened=true;}
    if(src[i]==='}'&& --depth===0&&opened)return src.slice(start,i+1);
  }
  throw new Error('Unterminated '+name);
}
assert.match(view,/id="evaluation-saved-indicator"[^>]*hidden[^>]*>✓ Evaluation saved</);
assert.doesNotMatch(view,/Evaluation progress is saved separately from Position learned/);
assert.match(css,/\.evaluation-progress-note[^\n]*white-space:nowrap/);
assert.match(src,/evaluationFeedbackSavedByPosition/);
assert.match(src,/data\.evaluation_feedback_saved === true/);
assert.match(app,/evaluation_feedback_saved\(conn, position_id, run_id\)/);
for(const version of ['coaching_pipeline','coaching_pipeline/'])assert(!src.includes(version));
const evaluator=[method('evaluationFeedbackSaved'),method('updateNavigationMeta'),method('navigatePuzzle',true)].join('\n');
async function check({evaluationRunId=17, solved=true, feedback=false, last=false}={}) {
  const label={classList:{hidden:null,toggle(cls,val){this.hidden=val;}}};
  const button={disabled:false,textContent:'',title:''};
  const calls={navigated:false, advanced:false};
  const ctx={
    evaluationRunId,solved,openingKey:'',jobId:4,lessonsIndexUrl:'/lessons/4',
    currentIndex:0,positions: last?[{id:7}]:[{id:7},{id:8}],
    evaluationFeedbackSavedByPosition:new Map([[7,feedback]]),
    currentPosition:()=>({id:7}),nextButtonEl:button,
    updateLessonProgress:()=>{},document:{getElementById:id=>id==='counter'?{textContent:''}:id==='previous-button'?{disabled:false}:label},
    location:{assign:()=>{calls.navigated=true;}},localStorage:{removeItem:()=>{}},
    trainingStateKey:'key',trainingPlaylistKey:'playlist',showPosition:async()=>{calls.advanced=true;}
  };
  vm.runInNewContext(evaluator+';this.updateNavigationMeta=updateNavigationMeta;this.navigatePuzzle=navigatePuzzle;',ctx);
  ctx.updateNavigationMeta();
  const disabled=button.disabled;
  await ctx.navigatePuzzle(1);
  return {disabled,labelVisible:label.classList.hidden===false,...calls};
}
(async()=>{
  const pending=await check({solved:false,feedback:true});
  assert.equal(pending.disabled,true);
  assert.equal(pending.advanced,false);
  const notRated=await check({solved:true,feedback:false});
  assert.equal(notRated.disabled,true);
  assert.equal(notRated.labelVisible,false);
  assert.equal(notRated.advanced,false);
  const rated=await check({solved:true,feedback:true});
  assert.equal(rated.disabled,false);
  assert.equal(rated.labelVisible,true);
  assert.equal(rated.advanced,true);
  const finish=await check({solved:true,feedback:false,last:true});
  assert.equal(finish.navigated,false);
  const final=await check({solved:true,feedback:true,last:true});
  assert.equal(final.navigated,true);
  const normal=await check({evaluationRunId:null,solved:false,feedback:false});
  assert.equal(normal.disabled,false,'ordinary training navigation is unchanged');
  console.log('v96 evaluation saved/navigation gating tests passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
