// v92: a benchmark solve must expose independently rateable explanation cards.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/trainer.js', 'utf8');
const css = fs.readFileSync('static/styles.css', 'utf8');
const view = fs.readFileSync('templates/trainer.html', 'utf8');
function extractFunction(name) {
  const start = src.indexOf(`function ${name}(`);
  assert(start >= 0, `missing ${name}`);
  const open = src.indexOf('{', start);
  let depth = 0;
  for (let i=open; i<src.length; ++i) {
    if (src[i] === '{') depth++;
    if (src[i] === '}' && --depth === 0) return src.slice(start, i+1);
  }
  throw new Error(`unterminated ${name}`);
}
const functions = [extractFunction('positionSolvedForRating'),extractFunction('solvingExplanationReadyForRating')].join('\n');
function eligible({evaluationRunId=12,solved=true,learned=0,text='Nxd7 wins the rook',displayed=7,hidden=false}) {
  return vm.runInNewContext(`${functions}\nsolvingExplanationReadyForRating()`, {
    evaluationRunId, solved,
    currentPosition:()=>({id:7,learned}),
    displayedPositionId:displayed,
    coachPositionReviewEl:{classList:{contains:()=>hidden}},
    explanationPackageSnapshot:()=>text
  });
}
assert.equal(eligible({}),true,'a freshly solved evaluation must allow explanation votes');
assert.equal(eligible({solved:false,learned:1}),false,'global learned cannot unlock an unsolved evaluation');
assert.equal(eligible({displayed:8}),false,'cannot rate another position');
assert.equal(eligible({hidden:true}),false,'cannot rate a concealed coach card');
assert.equal(eligible({text:'Watch the last move, then find a strong response.'}),false,'cannot rate the pre-solve prompt');
assert.equal(eligible({text:''}),false,'cannot rate missing text');
assert.equal(eligible({evaluationRunId:null,solved:false,learned:1}),true,'ordinary learned review still allows rating');
assert.match(src,/category !== 'explanation' \|\| solvingExplanationReadyForRating\(\)/);
assert.match(src,/setRatingFeedbackStatus\(group, message, true\)/,'server errors are displayed');
assert.match(src,/evaluation-feedback-mode/);
assert.match(css,/\.evaluation-feedback-mode \.trainer-main \.rate-hover-zone \.inline-feedback-votes:not\(\.hidden\)/);
assert.match(view,/data-feedback-category="explanation"/);
assert.match(view,/data-feedback-category="position"/);
console.log('v92 evaluation explanation feedback UI tests passed');

// Exercise the actual click-to-POST handler with mocked browser primitives,
// not just the presence of buttons in markup. Both success and errors must
// provide visible feedback, and the run ID must reach the API.
function extractAsyncFunction(name) {
  const start = src.indexOf(`async function ${name}(`);
  assert(start >= 0, `missing ${name}`);
  const open = src.indexOf('{', start);
  let depth=0;
  for(let i=open; i<src.length; ++i) {
    if(src[i]==='{') depth++;
    if(src[i]==='}' && --depth===0) return src.slice(start,i+1);
  }
  throw new Error(`unterminated ${name}`);
}
const rateSource = extractAsyncFunction('ratePositionFeedback');
async function sendRating(responseValue) {
  const group = {
    dataset:{feedbackCategory:'explanation'},
    title:'', status:null,
    querySelectorAll:()=>[up,down],
    querySelector:()=>group.status,
    append:s=>{group.status=s;}
  };
  const up={dataset:{rating:'1'},disabled:false};
  const down={dataset:{rating:'-1'},disabled:false};
  const result={calls:[],uiUpdates:0};
  const context={
    currentPosition:()=>({id:10,feedback_message_id:73}), positionSolvedForRating:()=>true,
    coachingAvailableForPosition:()=>true,
    positionRatings:new Map(),positionCorrections:new Map(),
    continuationRatings:new Map(),continuationCorrections:new Map(),
    displayedMessageRatings:new Map(), displayedMessageCorrections:new Map(),
    ratingRequestSerial:0, evaluationRunId:12,
    nextFeedbackRating:()=>1,
    explanationPackageSnapshot:()=> 'Current model explanation',
    location:{search:''}, URLSearchParams,
    correctionTarget:null,
    setRatingFeedbackStatus:vm.runInNewContext(extractFunction('setRatingFeedbackStatus')+';setRatingFeedbackStatus',{document:{createElement:()=>({className:'',textContent:'',setAttribute(){},classList:{toggle(){}}})}}),
    fetch:async (url,params)=>{
      result.calls.push({url,body:JSON.parse(params.body)});
      return {ok:responseValue.ok,json:async ()=>responseValue.data};
    },
    updatePositionRatingUI:()=>{result.uiUpdates++;},
    updateEvaluationFeedbackState:()=>{},
    displayedPositionId:10,
    openCorrectionDialog:()=>{},closeCorrectionDialog:()=>{},
    console
  };
  vm.runInNewContext(rateSource+'\nthis.ratePositionFeedback=ratePositionFeedback;',context);
  const button={dataset:{rating:'1'},closest:()=>group};
  await context.ratePositionFeedback(button);
  return {result,group,up,down,context};
}
(async()=>{
  let response=await sendRating({ok:true,data:{ratings:{explanation:1},corrections:{}}});
  assert.equal(response.result.calls[0].body.evaluation_run_id,12);
  assert.equal(response.result.calls[0].body.content_snapshot,'Current model explanation');
  assert.equal(response.result.calls[0].body.category,'explanation');
  assert.equal(response.result.calls[0].body.rating,1);
  assert.equal(response.result.calls[0].body.message_snapshot_id,73);
  assert.equal(response.group.status.textContent,'Rating saved');
  assert.equal(response.up.disabled,false);
  response=await sendRating({ok:false,data:{error:'No stored message snapshot for this continuation.'}});
  assert.match(response.group.status.textContent,/stored message snapshot/);
  assert.equal(response.group.title,'No stored message snapshot for this continuation.');
  assert.equal(response.up.disabled,false);
  console.log('v92 evaluation POST feedback button tests passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
