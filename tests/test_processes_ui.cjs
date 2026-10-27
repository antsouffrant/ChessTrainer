// No browser dependency: exercise process-list rendering and controls against a DOM fixture.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const controls = {};
const list = {innerHTML:'', addEventListener(type,fn){ controls[type]=fn; }};
const root = {dataset:{selectedJob:'11'}};
const feedback = {textContent:'',classList:{add(){},remove(){}}};
const jobs = [{id:11,username:'alice',date_range:'2026',source_type:'self',analysis_status:'complete',
  refresh_status:'error',refresh_error:'database is locked',games_retrieved:100,games_processed:100,
  current_pass:2,max_passes:2,total:20,processed:7,updated:7},
  {id:12,username:'bob',date_range:'2025',source_type:'self',analysis_status:'running',
   refresh_status:'idle',games_retrieved:90,games_processed:12,current_pass:1,max_passes:3}];
let posted = [];
const document = {getElementById(id){return ({'process-root':root,'process-list':list,'process-feedback':feedback})[id];},hidden:false};
let interval;
const context={document,window:{pctFormatCount:n=>String(n)},setInterval:fn=>{interval=fn;},fetch:async (path,opts)=>{
 if(opts?.method==='POST') {posted.push(path);return {ok:true,json:async()=>({ok:true})};}
 return {ok:true,json:async()=>({processes:jobs})};
}};
vm.runInNewContext(fs.readFileSync(require('path').join(__dirname,'../static/processes.js'),'utf8'),context);
const flush=()=>new Promise(done=>setTimeout(done,10));
(async()=>{
 await flush();
 assert(list.innerHTML.includes('Start refresh'));
 assert(list.innerHTML.includes('Pause'));
 assert(list.innerHTML.includes('Restart analysis'));
 assert(!list.innerHTML.includes('Stop analysis'));
 assert(list.innerHTML.includes('previous attempt'));
 assert(!list.innerHTML.includes('database is locked'));
 assert(list.innerHTML.includes('Analyze again'));
 await controls.click({target:{closest(){return {disabled:false,dataset:{jobId:'11',processAction:'refresh',command:'start'}};}}});
 await flush();
 assert(posted.includes('/api/jobs/11/process/refresh'));
 assert(typeof interval==='function');
 jobs[0].benchmark={size:36,available:36,source_count:100,versions:[
   {coaching_version:'v32',captured:36,expected:36,rated_messages:2,rated_positions:2,
    approval_pct:50,taxonomy_corrected_fields:1,taxonomy_rated_fields:4},
   {coaching_version:'v33',captured:36,expected:36,rated_messages:2,rated_positions:2,
    approval_pct:100,taxonomy_corrected_fields:0,taxonomy_rated_fields:4}],
   comparisons:[{from_version:'v32',to_version:'v33',paired_messages:2,
       before_approval_pct:50,after_approval_pct:100,motif_changes:2,
       paired_positions_with_snapshots:36}]};
 jobs[0].evaluation_run={id:14,solved:2,total:36,status:'active'};
 interval();await flush();
 assert(list.innerHTML.includes('Fixed coaching benchmark'));
 assert(list.innerHTML.includes('/trainer/11?benchmark=1&amp;run_id=14') || list.innerHTML.includes('/trainer/11?benchmark=1&run_id=14'));
 assert(list.innerHTML.includes('Replace current model evaluation'));
 assert(list.innerHTML.includes('2 identically rated messages'));
 // Completed evaluations are archived in Coach, never a Process training default.
 jobs[0].evaluation_run={id:14,solved:36,total:36,status:'completed'};
 interval();await flush();
 assert(list.innerHTML.includes('Evaluation complete · View in Coach'));
 assert(list.innerHTML.includes('/coach/benchmark?job_id=11'));
 assert(!list.innerHTML.includes('/trainer/11?benchmark=1&run_id=14'));
 console.log('Process UI states and benchmark rendering passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
