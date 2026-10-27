const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync('static/process_launch.js', 'utf8');
async function checkScenario(status, expectedPost, responseStatus=202) {
  let handler, url = null, count = 0;
  const button = {disabled:false,dataset:{jobId:'42',processStart:'refresh'}};
  const document = {addEventListener(type, fn){if (type==='click') handler=fn;}};
  const fetch = async (path, opts) => {
    if (path === '/api/processes') return {ok:true,json:async()=>({processes: [{id:42,analysis_status:status,refresh_status:'idle'}]})};
    count++;
    return {status:responseStatus,ok:responseStatus===202,json:async()=>({ok:true})};
  };
  vm.runInNewContext(code,{document,fetch,window:{location:{assign(path){url=path;}}},alert:()=>{throw Error('unexpected alert')},Set});
  await handler({target:{closest:()=>button}});
  assert.equal(count,expectedPost,`POST count for ${status}`);
  assert.equal(url,'/processes?job_id=42');
  assert.equal(button.disabled,false);
}
(async()=>{
  await checkScenario('running',0);
  await checkScenario('queued',0);
  await checkScenario('retrieving',0);
  await checkScenario('restarting',0);
  await checkScenario('complete',1);
  await checkScenario('paused',1);
  await checkScenario('complete',1,409);
  console.log('Home process routing: 7 cases passed');
})().catch(err=>{console.error(err);process.exit(1)});
