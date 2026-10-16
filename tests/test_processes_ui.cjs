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
 assert(list.innerHTML.includes('Stop'));
 assert(list.innerHTML.includes('previous attempt'));
 assert(!list.innerHTML.includes('database is locked'));
 assert(list.innerHTML.includes('Analyze again'));
 await controls.click({target:{closest(){return {disabled:false,dataset:{jobId:'11',processAction:'refresh',command:'start'}};}}});
 await flush();
 assert(posted.includes('/api/jobs/11/process/refresh'));
 assert(typeof interval==='function');
 console.log('Process UI states and action routing passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
