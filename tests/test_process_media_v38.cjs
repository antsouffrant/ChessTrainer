const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const dom = {};
let handler;
const list = {innerHTML:'',addEventListener(_k, fn){handler=fn;}};
const feedback = {textContent:'',classList:{add(){},remove(){}}};
const jobs = [{id:1,username:'Alice',date_range:'2026',analysis_status:'paused',refresh_status:'stopped',current_pass:2,max_passes:3,games_processed:12,games_retrieved:24}];
const posts=[];
const context={
  document:{hidden:false,getElementById:id=>({'process-root':{dataset:{selectedJob:'1'}},'process-list':list,'process-feedback':feedback})[id]},
  window:{pctFormatCount:n=>String(n)},
  setInterval:()=>{},
  fetch:async (url, opts)=>{
    if(opts?.method==='POST'){ posts.push(url); return {ok:true,json:async()=>({ok:true})}; }
    return {ok:true,json:async()=>({processes:jobs})};
  }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/processes.js'),'utf8'),context);
const flush=()=>new Promise(r=>setTimeout(r,12));
(async()=>{
  await flush();
  assert(list.innerHTML.includes('fa-play'));
  assert(list.innerHTML.includes('fa-pause'));
  assert(list.innerHTML.includes('fa-rotate-right'));
  assert(list.innerHTML.includes('Restart analysis'));
  assert(!list.innerHTML.includes('Stop analysis')); 
  assert(list.innerHTML.includes('aria-label="Resume analysis"'));
  assert(list.innerHTML.includes('>Resume analysis</span></button>'));
  // Only one transport row per game list, not one in every stage.
  assert.equal((list.innerHTML.match(/class="process-control-bar"/g) || []).length, 1);
  await handler({target:{closest(){return {disabled:false,dataset:{jobId:'1',processAction:'analyze',command:'resume'}}}}});
  assert(posts.includes('/api/jobs/1/resume'));
  jobs[0].analysis_status='stopped';
  await flush();
  await handler({target:{closest(){return {disabled:false,dataset:{jobId:'1',processAction:'analyze',command:'start'}}}}});
  assert(posts.includes('/api/jobs/1/process/analyze'));
  await handler({target:{closest(){return {disabled:false,dataset:{jobId:'1',processAction:'analyze',command:'restart'}}}}});
  assert(posts.includes('/api/jobs/1/process/analyze/restart'));
  console.log('PASS: media icons, resume vs restart routes');
})().catch(e=>{console.error(e); process.exitCode=1;});
