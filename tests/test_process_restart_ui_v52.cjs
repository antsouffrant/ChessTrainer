// The Process toolbar exposes Restart for an analyzed saved PGN, never Stop.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('static/processes.js','utf8');
const container = {innerHTML:'',addEventListener(name,handler){this.click = handler;}};
const warning={textContent:'',classList:{add(){},remove(){}}};
let job={id:9,username:'alice',date_range:'month',analysis_status:'running',retrieval_status:'complete',
  refresh_status:'idle',games_retrieved:100,games_processed:32,positions_found:4};
let refresh, confirmed=true, confirmCount=0;
const requests=[];
const document={hidden:false,getElementById(id){return {
  'process-root':{dataset:{selectedJob:'9'}},'process-list':container,'process-feedback':warning
}[id];}};
const window={confirm(){confirmCount++;return confirmed;}};
const fetch=async (url, opts) => {
  if(opts?.method==='POST') {requests.push(url);return {ok:true,json:async()=>({ok:true})};}
  return {ok:true,json:async()=>({processes:[job]})};
};
vm.runInNewContext(source,{document,window,fetch,setInterval(fn){refresh=fn;}});
const flush=()=>new Promise(r=>setTimeout(r,12));
const restartButton=()=>container.innerHTML.match(/<button[^>]+data-command="restart"[^>]*>/)?.[0]||'';
const press=()=>container.click({target:{closest(){return {disabled:false,dataset:{jobId:'9',processAction:'analyze',command:'restart'}};}}});
(async()=>{
  await flush();
  assert.match(restartButton(),/Restart analysis/);
  assert.doesNotMatch(restartButton(),/disabled/);
  assert.doesNotMatch(container.innerHTML,/Stop analysis/);
  confirmed=false;
  await press();
  assert.equal(requests.length,0,'cancelled confirmation must not POST');
  confirmed=true;
  await press();
  assert.equal(requests[0],'/api/jobs/9/process/analyze/restart');
  assert.equal(confirmCount,2);
  for(const analysis_status of ['paused','complete']) {
    job={...job,analysis_status}; refresh(); await flush();
    assert.doesNotMatch(restartButton(),/disabled/);
  }
  job={...job,analysis_status:'restarting'};
  refresh();await flush();
  assert.match(restartButton(),/disabled/);
  assert.match(container.innerHTML,/Restarting analysis/);
  job={...job,analysis_status:'running',refresh_status:'running'};
  refresh();await flush();
  assert.match(restartButton(),/disabled/);
  job={...job,refresh_status:'idle',retrieval_status:'running'};
  refresh();await flush();
  assert.match(restartButton(),/disabled/);
  console.log('PASS: restart confirmation, enabling and process locks');
})().catch(e=>{console.error(e);process.exitCode=1;});
