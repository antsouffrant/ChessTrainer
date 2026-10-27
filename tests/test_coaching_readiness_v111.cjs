// Model readiness is per position, not per completed evaluation or job.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const src=fs.readFileSync('static/trainer.js','utf8');
const view=fs.readFileSync('templates/trainer.html','utf8');
function extract(name) {
  const start=src.indexOf(`function ${name}(`);
  assert(start>=0,name);
  const open=src.indexOf('{',start);
  let depth=0;
  for(let i=open;i<src.length;i++) {
    if(src[i]==='{')depth++;
    if(src[i]==='}'&&--depth===0)return src.slice(start,i+1);
  }
  throw Error(name);
}
const functions=['coachingAvailableForPosition','displayCoachRefreshWarning','showCoachRecapIssue'].map(extract).join('\n');
const fakeNode=()=>({classList:{hidden:false,toggle(_cls,hide){this.hidden=hide;},add(){this.hidden=true;},remove(){this.hidden=false;}},children:[],
    replaceChildren(){this.children=[];},append(...elements){this.children.push(...elements);}});
const banner=fakeNode(),recap=fakeNode();
const data={jobId:17,displayedPositionId:52,coachReadinessWarningEl:banner,coachRecapWarningEl:recap,
    currentPosition:()=>({id:52,coaching_ready:false}),document:{createElement:()=>({textContent:'',href:''})}};
vm.runInNewContext(functions+'\nthis.available=coachingAvailableForPosition;this.display=displayCoachRefreshWarning;this.issue=showCoachRecapIssue;',data);
assert.equal(data.available({coaching_ready:false}),false);
assert.equal(data.available({coaching_ready:true}),true);
assert.equal(data.available({id:1}),true,'legacy cards fall back to server guards');
data.display({id:52,coaching_ready:false,coaching_version:'v33',active_coaching_version:'v34'});
assert.equal(banner.classList.hidden,false);
assert.equal(banner.children.length,2);
assert.match(banner.children[0].textContent,/v33.*v34/);
assert.equal(banner.children[1].href,'/processes?job_id=17');
data.issue(52,'missing Stockfish continuation');
assert.equal(recap.classList.hidden,false,'recap failures must remain visible even with stale cached coaching');
data.display({id:53,coaching_ready:true});
assert.equal(banner.classList.hidden,true);
assert.match(view,/id="coach-readiness-warning"/);
assert.match(view,/id="coach-recap-warning"/);
assert.match(src,/if \(!response\.ok\) \{\s*const failure = await response\.json\(\)\.catch/);
assert.match(src,/message_snapshot_id: messageId \|\| undefined/);
console.log('v111 readiness and recap failure UI passed');
