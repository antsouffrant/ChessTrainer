// v102: completion must never make an evaluation the default Training playlist.
const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const script=fs.readFileSync('static/trainer.js','utf8');
const startup=script.slice(0,script.indexOf('let currentIndex = 0;'));
assert(startup.includes('function rememberTraining(positionId)'));

function browser(query='',state=null,plain=null) {
  const entries=new Map();
  if(state)entries.set('pct-training-17-state',JSON.stringify(state));
  if(plain)entries.set('pct-training-17',plain);
  const storage={
    getItem(key){return entries.get(key)??null;},
    setItem(key,value){entries.set(key,String(value));},
    removeItem(key){entries.delete(key);}
  };
  const replaced=[];
  const location={origin:'http://localhost',pathname:'/trainer/17',search:query,
    replace(url){replaced.push(url);}};
  const context={URL,URLSearchParams,location,localStorage:storage,
    window:{TRAINER_JOB_ID:17, TRAINER_EVALUATION_RUN_ID:query.includes('benchmark=1')?24:null},
    document:{documentElement:{classList:{add(){}}}}
  };
  vm.runInNewContext(startup,context,{filename:'trainer-startup.js'});
  return {entries,replaced,context};
}
const legacy='/trainer/17?benchmark=1&run_id=24';
// A browser returning to normal Training after a completed eval must start
// an ordinary session, never redirect back into its old evaluation.
const old=browser('',{url:legacy,positionId:5},legacy);
assert.deepEqual(old.replaced,[]);
assert(!old.entries.has('pct-training-17-state'));
assert(!old.entries.has('pct-training-17'));
vm.runInNewContext('rememberTraining(55)',old.context);
assert.equal(JSON.parse(old.entries.get('pct-training-17-state')).url,'/trainer/17');

// Evaluating must neither overwrite nor delete a previously saved ordinary
// session; it is explicitly launched via the benchmark route only.
const saved='/trainer/17?concept=pin';
const evalBrowser=browser('?benchmark=1&run_id=24',{url:saved,positionId:55},saved);
vm.runInNewContext('rememberTraining(27);keepPlaylistSnapshot()',evalBrowser.context);
assert.equal(JSON.parse(evalBrowser.entries.get('pct-training-17-state')).url,saved);
assert.equal(evalBrowser.entries.get('pct-training-17'),saved);
assert.equal(evalBrowser.entries.has('pct-training-17-playlist'),false);
assert.deepEqual(evalBrowser.replaced,[]);

// Ordinary Training can still resume an ordinary lesson.
const resume=browser('',{url:saved,positionId:55},saved);
assert.deepEqual(resume.replaced,[saved]);

// Menu destinations must remain independent of the evaluation.
const base=fs.readFileSync('templates/base.html','utf8');
const process=fs.readFileSync('static/processes.js','utf8');
const lessons=fs.readFileSync('templates/lessons.html','utf8');
const openings=fs.readFileSync('templates/openings.html','utf8');
const coach=fs.readFileSync('static/benchmark_chart.js','utf8');
assert(base.includes("url_for('lessons', job_id=nav_training_job_id)"));
assert(base.includes("url_for('openings', job_id=nav_training_job_id)"));
assert(base.includes("!saved.searchParams.has('benchmark')"));
assert(lessons.includes('{% if evaluation_feature %}'));
assert(openings.includes('{% if evaluation_feature %}'));
assert(process.includes('Evaluation complete · View in Coach'));
assert(coach.includes('Review evaluation'));
const app=fs.readFileSync('app.py','utf8');
assert(app.includes("Select an evaluation explicitly from Coach or Process."));
assert(app.includes('if not requested_run:'));
console.log('PASS: completed evaluations never hijack normal training and remain available in Coach');
