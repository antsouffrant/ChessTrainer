const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('templates/player.html', 'utf8');
const code = fs.readFileSync('static/player.js', 'utf8');
const app = fs.readFileSync('app.py', 'utf8');
assert.match(html, /id="player-reset-records"/);
assert.match(html, /id="player-attempt-export"/);
assert.match(html, /id="player-session-export"/);
assert.match(html, /id="player-reset-note"/);
assert.match(app, /@app\.post\('\/api\/player\/records\/reset'\)/);
assert.match(code, /fetch\('\/api\/player\/records\/reset'/);
assert.match(code, /Type RESET PLAYER/);
assert.match(code, /ignores motif\/opening\/mode\/position filters/);
const first = code.indexOf('  const resetRecords = ');
const last = code.indexOf('  form.addEventListener(', first);
assert.ok(first > 0 && last > first);
const handler = code.slice(first, last);

async function exercise({gameList='2', confirm=true, typed='RESET PLAYER', responseOk=true}={}) {
  const registrations = {}, elements = {};
  for(const key of ['player-reset-records', 'player-error', 'player-reset-note']) {
    elements[key] = {disabled:false, textContent:'', classList:{add(){},remove(){}},addEventListener(event,fn){registrations[event]=fn}};
  }
  const requests = [];
  let refreshed = 0;
  const scope = [];
  const context = {
    form:{elements:{job_id:{value:gameList},primary_motif_key:{value:'fork'}}},
    document:{getElementById:id=>elements[id]},
    window:{confirm:message=>{scope.push(message);return confirm;},prompt:()=>typed},
    fetch:async(url,options)=>{requests.push({url,options}); return {ok:responseOk,json:async()=>responseOk?{deleted:{sessions:2,attempts:3}}:{error:'Backend error'}};},
    refresh:async()=>{refreshed++;},
    fmt:n=>String(n), value:(id,txt)=>{elements[id].textContent=txt}
  };
  vm.createContext(context);
  vm.runInContext(handler,context);
  await registrations.click();
  return {requests, refreshed, elements, scope};
}
(async()=>{
  const cancelled=await exercise({confirm:false});
  assert.equal(cancelled.requests.length,0);
  const wrong=await exercise({typed:'no'});
  assert.equal(wrong.requests.length,0);
  const selected=await exercise({gameList:'4'});
  assert.equal(selected.requests.length,1);
  assert.equal(selected.requests[0].url,'/api/player/records/reset');
  assert.deepEqual(JSON.parse(selected.requests[0].options.body),{job_id:'4',confirmation:'RESET PLAYER'});
  assert.equal(selected.refreshed,1);
  assert.equal(selected.elements['player-reset-records'].disabled,false);
  assert.match(selected.elements['player-reset-note'].textContent,/2 sessions and 3 attempt events deleted/);
  assert.match(selected.scope[0],/ignores motif\/opening\/mode\/position filters/);
  const all=await exercise({gameList:''});
  assert.equal(JSON.parse(all.requests[0].options.body).job_id,null);
  const failed=await exercise({responseOk:false});
  assert.equal(failed.refreshed,0);
  assert.match(failed.elements['player-error'].textContent,/Backend error/);
  assert.equal(failed.elements['player-reset-records'].disabled,false);
  console.log('Player CSV controls and confirmed reset interaction passed');
})().catch(err=>{console.error(err);process.exitCode=1});
