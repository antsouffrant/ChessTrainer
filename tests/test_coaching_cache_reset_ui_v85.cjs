const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const handlers = {};
const list = {innerHTML:'', addEventListener(kind, fn){handlers[kind] = fn;}};
const feedback = {textContent:'',classList:{add(){},remove(){}}};
const jobs = [{id:7, username:'student',date_range:'2026',source_type:'self',
  games_retrieved:22, positions_found:8, has_training_positions:1,
  analysis_status:'complete',refresh_status:'complete'},
  {id:8, username:'active',date_range:'2026',source_type:'self',
  games_retrieved:5, positions_found:2, has_training_positions:1,
  analysis_status:'running',refresh_status:'idle'}];
const posted=[];const confirmations=[];
const document={getElementById(id){return ({'process-root':{dataset:{selectedJob:'7'}},
  'process-list':list,'process-feedback':feedback})[id];},hidden:false};
const context={document,window:{confirm(txt){confirmations.push(txt);return true;}},setInterval(){},
  fetch:async (url,opts)=>{
    if(opts?.method==='POST'){
      posted.push({url,body:JSON.parse(opts.body)});
      jobs[0].refresh_status='needs_refresh';
      return {ok:true,json:async()=>({ok:true})};
    }
    return {ok:true,json:async()=>({processes:jobs})};
  }};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/processes.js'),'utf8'), context);
(async()=>{
  const tick=()=>new Promise(done=>setTimeout(done,10));
  await tick();
  assert(list.innerHTML.includes('Clear coaching cache'));
  assert(/data-job-id="8"[^>]*disabled/.test(list.innerHTML));
  await handlers.click({target:{closest(){return {disabled:false,dataset:{jobId:'7',processAction:'coaching-cache',command:'clear'}};}}});
  await tick();
  assert.equal(posted[0].url,'/api/jobs/7/process/coaching-cache/clear');
  assert.equal(posted[0].body.confirmation,'CLEAR COACHING CACHE');
  assert(confirmations[0].includes('All rated feedback'));
  assert(confirmations[0].includes('coach conversation')); 
  assert(list.innerHTML.includes('Needs refresh'));
  assert(list.innerHTML.includes('Start coaching refresh'));
  console.log('Coaching cache process action passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
