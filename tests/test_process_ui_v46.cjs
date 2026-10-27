const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../static/processes.js'),'utf8');
const html={innerHTML:'',addEventListener(_event,fn){this.click=fn;}};
const feedback={textContent:'',classList:{add(){},remove(){}}};
let list={id:4,username:'Alice',source_type:'self',date_range:'month',retrieval_status:'running',
  analysis_status:'waiting_for_games',refresh_status:'idle',games_retrieved:0,has_training_positions:0};
let poll, calls=[];
const ctx={document:{hidden:false,getElementById(id){return {'process-root':{dataset:{selectedJob:'4'}},
  'process-list':html,'process-feedback':feedback}[id];}},setInterval:fn=>poll=fn,
  fetch:async (url,opt)=>opt?.method==='POST' ? (calls.push(url),{ok:true,json:async()=>({ok:true})}) :
    {ok:true,json:async()=>({processes:[list]})}};
vm.runInNewContext(source,ctx);
const flush=()=>new Promise(resolve=>setTimeout(resolve,14));
(async()=>{
  await flush();
  const operation=(kind)=>html.innerHTML.match(new RegExp(`<button[^>]*class="secondary-button process-operation"[^>]*data-process-action="${kind}"[^>]*>`))[0];
  assert(operation('analyze').includes('disabled'));
  assert(operation('refresh').includes('disabled'));
  assert(html.innerHTML.includes('Restart analysis'));
  assert(html.innerHTML.includes('data-command="restart" data-job-id="4"') );
  assert(html.innerHTML.includes('data-command="restart" data-job-id="4"') && html.innerHTML.includes('disabled'));
  assert(!html.innerHTML.includes('Training →'));
  assert.equal((html.innerHTML.match(/class="process-control-bar"/g)||[]).length,1);
  await html.click({target:{closest(){return {disabled:false,dataset:{jobId:4,processAction:'retrieve',command:'pause'}}}}});
  assert(calls.includes('/api/jobs/4/process/retrieve/pause'));
  list={...list,retrieval_status:'complete',analysis_status:'running',games_retrieved:10,games_processed:4};
  poll();await flush();
  assert(operation('analyze').includes('disabled'));
  assert(operation('refresh').includes('disabled'));
  assert(html.innerHTML.includes('Restart analysis'));
  list={...list,analysis_status:'complete',has_training_positions:1,positions_found:3};
  poll();await flush();
  assert(!operation('analyze').includes('disabled'));
  assert(!operation('refresh').includes('disabled'));
  assert(html.innerHTML.includes('Training →'));
  assert(html.innerHTML.includes('Analyze again · next pass'));
  list={...list,analysis_status:'paused',refresh_status:'running'};
  poll();await flush();
  assert(operation('analyze').includes('disabled'));
  assert(operation('refresh').includes('disabled'));
  console.log('v46 per-list process locks, consolidated toolbar and resume actions: passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
