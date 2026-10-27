const fs = require('fs'), vm = require('vm'), path = require('path'), assert=require('assert');
const runtime = src => fs.readFileSync(path.join(__dirname,'../static',src),'utf8');
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));

async function testHome() {
  const anchors=['/trainer/1','/lessons/1','/openings/1'].map(h=>({dataset:{readyHref:h},attributes:{},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},set href(v){this.attributes.href=v;},get href(){return this.attributes.href;}}));
  const actions={toggleValue:false,classList:{toggle(name,val){assert.equal(name,'game-list-ready');actions.toggleValue=val;}},};
  const label={textContent:''}, count={textContent:''};
  const card={dataset:{homeJob:'1'},querySelector(q){return ({'.game-list-index-links':actions,'[data-list-status]':label,'[data-list-count]':count})[q]},querySelectorAll(){return anchors}};
  let response={id:1,retrieval_status:'running',analysis_status:'waiting_for_games',has_training_positions:0,games_retrieved:0,positions_found:0};
  let tick;
  const document={querySelectorAll:()=>[card],hidden:false};
  const ctx={document,setInterval:f=>{tick=f;},fetch:async()=>({ok:true,json:async()=>({processes:[response]})})};
  vm.runInNewContext(runtime('home_readiness.js'),ctx);
  await sleep(10);
  assert.equal(label.textContent,'Retrieving games…');
  assert(anchors.every(a=>a.attributes['aria-disabled']==='true' && !a.href));
  assert(!actions.toggleValue);
  response={...response,retrieval_status:'complete',analysis_status:'running',games_retrieved:25};
  tick();await sleep(10);
  assert.equal(label.textContent,'Analyzing games…');
  assert(anchors.every(a=>!a.href));
  response={...response,has_training_positions:1,positions_found:3};
  tick();await sleep(10);
  assert.equal(label.textContent,'Ready · analyzing games');
  assert(actions.toggleValue);
  assert.deepEqual(anchors.map(a=>a.href),['/trainer/1','/lessons/1','/openings/1']);
  response={...response,has_training_positions:0,positions_found:0,analysis_status:'complete'};
  tick();await sleep(10);
  assert.equal(label.textContent,'Analysis complete · no training positions found');
  assert(anchors.every(a=>!a.href));
}

async function testProcess(){
  const callbacks={};const list={innerHTML:'',addEventListener:(t,cb)=>callbacks[t]=cb};
  const root={dataset:{selectedJob:'1'}}, feedback={textContent:'',classList:{add(){},remove(){}}};
  const document={getElementById(id){return {'process-root':root,'process-list':list,'process-feedback':feedback}[id]},hidden:false};
  let response={id:1,username:'Alice',date_range:'month',retrieval_status:'running',analysis_status:'waiting_for_games',bytes_downloaded:500,bytes_total:1000,has_training_positions:0,refresh_status:'idle'};
  let calls=[],interval;
  const ctx={document,window:{pctFormatCount:n=>String(n)},setInterval:f=>interval=f,fetch:async (url,opt)=>{
    if(opt?.method==='POST'){calls.push(url);return {ok:true,json:async()=>({ok:true})}}
    return {ok:true,json:async()=>({processes:[response]})};
  }};
  vm.runInNewContext(runtime('processes.js'),ctx); await sleep(10);
  assert(list.innerHTML.includes('Retrieval'));
  assert(list.innerHTML.includes('Retrieving') || list.innerHTML.includes('Running'));
  assert(!list.innerHTML.includes('Training →'));
  await callbacks.click({target:{closest(){return {disabled:false,dataset:{jobId:'1',processAction:'retrieve',command:'stop'}};}}});
  assert(calls.includes('/api/jobs/1/process/retrieve/stop'));
  response={...response,retrieval_status:'error',retrieval_error:'Lichess unavailable',analysis_status:'error'};
  interval();await sleep(10);
  assert(list.innerHTML.includes('Retry retrieval'));
  await callbacks.click({target:{closest(){return {disabled:false,dataset:{jobId:'1',processAction:'retrieve',command:'start'}};}}});
  assert(calls.includes('/api/jobs/1/process/retrieve'));
  response={...response,retrieval_status:'complete',analysis_status:'running',has_training_positions:1,games_retrieved:40,positions_found:2};
  interval();await sleep(10);
  assert(list.innerHTML.includes('Training →'));
}
(async()=>{await testHome();await testProcess();console.log('Retrieval Home + Process UI: passed');})().catch(e=>{console.error(e);process.exitCode=1;});
