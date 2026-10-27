const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root,'static/trainer.js'),'utf8');
const css = fs.readFileSync(path.join(root,'static/styles.css'),'utf8');
const app = fs.readFileSync(path.join(root,'app.py'),'utf8');

function between(start, end) {
  const a=source.indexOf(start); const b=source.indexOf(end,a);
  assert.ok(a>=0 && b>a,`Missing ${start} or ${end}`);
  return source.slice(a,b);
}

test('fresh solved-session recap wins over a concurrent older history response', async () => {
  const snippet = between('async function publishPostSolveCoach(position)', 'const fmtCount =');
  // Simulate the specific race: the old thread load has not finished when
  // POST returns the newly committed recap.
  const shown=[]; const issues=[];
  const context = {
    coachChatEl:{}, displayedPositionId:31, coachThreadReadyPositionId:null,
    coachRecapWarningEl:{classList:{add(){}}}, coachAttemptLogFailures:new Map(),
    evaluationRunId:null,
    coachSolveSessionKey:()=> 'session_new',
    currentPosition:()=>({id:31}),
    fetch:async()=>({ok:true,json:async()=>({message:{id:501,structured_json:JSON.stringify({
      kind:'solved_attempt_recap',attempts:[{correct:0},{correct:1}],
      attempt_comments:[{correct:false,origin:'attempt',move_uci:'e2e4',text:'Learning'}]
    })}})}),
    loadCoachThread:async()=> {context.coachThreadReadyPositionId=31; shown.push('old history');},
    renderCoachAttemptComments:(msg,id)=>shown.push(`fresh ${msg.id} ${id}`),
    attemptNotesFromRecap:x=>x.attempt_comments,
    showCoachRecapIssue:(id,msg)=>issues.push(msg),
    Number,JSON,Map,console,
  };
  vm.createContext(context);
  vm.runInContext(snippet+'\nthis.publishPostSolveCoach = publishPostSolveCoach;',context);
  await context.publishPostSolveCoach({id:31});
  assert.deepEqual(shown,['old history','fresh 501 31']);
  assert.deepEqual(issues,[]);
});

test('missing attempt receipts and unavailable recap notes report a visible diagnostic',async()=>{
  assert.match(app,/coach_attempt_logged = record_board_attempt\(/);
  assert.equal((app.match(/'coach_attempt_logged': coach_attempt_logged/g)||[]).length,2);
  assert.match(source,/coachAttemptLogFailures\.set\(Number\(position\.id\)/);
  assert.match(source,/wrongCount && !learningCount/);
  assert.match(source,/threadRequest !== coachThreadLoadSerial/g);
});

test('filter dropdown surface remains above metric card stacking contexts',()=>{
  assert.match(css,/\.analytics-filters, \.player-filters\s*\{\s*position:relative;\s*z-index:30;\s*overflow:visible;/);
  assert.match(css,/\.pct-multiselect\[open\]\s*\{\s*z-index:200;/);
});
