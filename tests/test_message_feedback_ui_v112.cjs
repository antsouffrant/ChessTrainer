// Runtime contract: old-model explanation thumbs send server-issued identity.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const src = fs.readFileSync('static/trainer.js','utf8');
function extract(name, isAsync=false) {
  const marker = `${isAsync ? 'async ' : ''}function ${name}(`;
  const start = src.indexOf(marker); assert(start>=0, marker);
  const open=src.indexOf('{',start);let depth=0;
  for(let i=open;i<src.length;i++){
    if(src[i]==='{')depth++;
    if(src[i]==='}'&&!--depth)return src.slice(start,i+1);
  }
  throw Error('No closing brace: '+name);
}
assert.match(src,/votes\.dataset\.feedbackMessageId = String\(note\.feedback_message_id\)/);
assert.match(src,/displayedMessageRatings\.set\(id, data\.message_ratings/);
assert.match(src,/message_snapshot_id: messageId \|\| undefined/);
assert.match(src,/messageSnapshotId\) payload\.message_snapshot_id = messageSnapshotId/);
assert.match(src,/!coachingAvailableForPosition\(position\) && !position\?\.coach_explanation/);

async function run() {
  const clicked={dataset:{rating:'-1'},disabled:false};
  const other={dataset:{rating:'1'},disabled:false};
  const group={dataset:{feedbackCategory:'explanation',feedbackMessageId:'55'},title:'',
    querySelectorAll:()=>[clicked,other],closest:()=>group};
  let received=null;
  const context={
    currentPosition:()=>({id:11,coaching_version:'v33',coaching_ready:false,coach_explanation:'old text',feedback_message_id:55}),
    positionSolvedForRating:()=>true, coachingAvailableForPosition:()=>false,
    positionRatings:new Map(),positionCorrections:new Map(), continuationRatings:new Map(),
    continuationCorrections:new Map(), displayedMessageRatings:new Map([[11,{'55':1}]]),
    displayedMessageCorrections:new Map(), ratingRequestSerial:0,
    evaluationRunId:null,nextFeedbackRating:(previous,clicked)=>previous===clicked?0:clicked,
    location:{search:''},URLSearchParams, explanationPackageSnapshot:()=> 'old text',
    fetch:async (url,args)=>{received={url,body:JSON.parse(args.body)};return {ok:true,json:async()=>({ok:true,message_ratings:{55:-1},message_corrections:{55:{suggested_text:''}}})};},
    updatePositionRatingUI:()=>{},setRatingFeedbackStatus:()=>{},
    openCorrectionDialog:()=>{},closeCorrectionDialog:()=>{},
    currentPositionId:11, correctionTarget:null
  };
  const fn=vm.runInNewContext(extract('ratePositionFeedback',true)+';ratePositionFeedback',context);
  await fn({closest:()=>group,dataset:{rating:'-1'}});
  assert.equal(received.url,'/api/positions/11/feedback');
  assert.equal(received.body.message_snapshot_id,55);
  assert.equal(received.body.rating,-1);
  assert.equal(received.body.content_snapshot,'old text');
  assert.equal(context.displayedMessageRatings.get(11)['55'],-1);
  assert.equal(clicked.disabled,false);
  console.log('v112 saved stale-model feedback UI test passed');
}
run().catch(err=>{console.error(err);process.exitCode=1});
