const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/trainer.js', 'utf8');
const page = fs.readFileSync('templates/trainer.html', 'utf8');
const navigation = fs.readFileSync('templates/base.html', 'utf8');
const app = fs.readFileSync('app.py', 'utf8');
assert.match(page, /id="player-tracking-toggle"/);
assert.match(page, /id="player-tracking-label"/);
assert.match(js, /pct-player-tracking-enabled/);
assert.match(js, /track_learning:trackLearning/);
assert.match(js, /start_new_learning_session:startNewLearningSession/);
assert.match(app, /payload.get\('start_new_learning_session'\) is True/);
assert.match(js, /const activeSecondsDelta = trackLearning \? learningClockSnapshot\(\) : null/);
assert.match(app, /payload\.get\('track_learning', True\) is not False/);
assert.match(app, /@app\.post\('\/api\/positions\/<int:position_id>\/player\/clock-out'\)/);
const links = ["url_for('player_view')", "url_for('coach_view')", "url_for('processes')", "url_for('settings_page'" ];
const order = links.map(x => navigation.indexOf(x));
assert.ok(order.every((x, i) => x >= 0 && (!i || order[i-1] < x)), 'Nav order Player, Coach, Process, Settings');
const names = 'learningClockCanRun|learningClockPause|learningClockResume|learningClockStart|learningClockSnapshot|learningClockCommit|updatePlayerTrackingUI|setPlayerTrackingEnabled';
const defs = [...js.matchAll(new RegExp(`function (${names})\\([^\\n]*\\) \\{[\\s\\S]*?\\n\\}`, 'g'))].map(x=>x[0]);
assert.equal(defs.length,8);
const nodes = {};
for(const key of ['player-tracking-toggle','player-tracking-label']) {
  nodes[key]={checked:true, textContent:''};
}
let milliseconds = 0;
let abandonRequests=[];
const store=new Map();
const sandbox = {
  jobId:2,
  document:{visibilityState:'visible',hasFocus:()=>true},
  performance:{now:()=>milliseconds},
  localStorage:{setItem:(k,v)=>store.set(k,v)},
  fetch:(url,opts)=>{abandonRequests.push(url); return Promise.resolve({ok:true})},
};
vm.createContext(sandbox);
vm.runInContext(`let evaluationRunId=null, playerTrackingStorageKey='pct-player-tracking-enabled', learningTrackingEnabled=true,
 playerTrackingToggleEl=null, playerTrackingLabelEl=null, playerClockOutRequest=Promise.resolve(), restartTrackedSession=false,
 learningClockPositionId=null, learningClockElapsedMs=0, learningClockSince=null;
 ${defs.join('\n')}
 this.testApi={start:learningClockStart,snapshot:learningClockSnapshot,change:setPlayerTrackingEnabled,
 enabled:()=>learningTrackingEnabled,request:()=>playerClockOutRequest};`,sandbox);
sandbox.testApi.start(99);
milliseconds=12000;
assert.equal(sandbox.testApi.snapshot(),12);
sandbox.testApi.change(false);
assert.equal(store.get('pct-player-tracking-enabled'),'0');
// Clock-out is queued behind any previous request; verify after microtasks.
(async()=> {
await sandbox.testApi.request();
assert.equal(abandonRequests.length,1);
assert.equal(abandonRequests[0],'/api/positions/99/player/clock-out');
milliseconds=58000;
assert.equal(sandbox.testApi.snapshot(),0,'Untracked time never accumulates');
sandbox.testApi.change(true);
milliseconds=63000;
assert.equal(sandbox.testApi.snapshot(),5,'Timer starts fresh only after clocking in');
console.log('Player tracking opt-out, timer, and navigation order verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
