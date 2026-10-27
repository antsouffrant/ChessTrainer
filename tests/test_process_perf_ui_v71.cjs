const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
const list = {innerHTML:'', addEventListener(){}};
const jobs = [{id:7, username:'chessuser', date_range:'recent',
  retrieval_status:'complete',retrieval_started_at:'2026-10-18 10:00:00',
  retrieval_finished_at:'2026-10-18 10:00:12', analysis_status:'complete',
  refresh_status:'complete', games_retrieved:50, games_processed:50,
  total:3, processed:3, updated:3,
  analysis_perf:JSON.stringify({screen_seconds:55,deep_seconds:93,reply_seconds:17,coaching_seconds:5,cached_games:2}),
  refresh_perf:JSON.stringify({engine_seconds:2.2,metadata_seconds:.8,cached_probes:2,new_probes:1})}];
const context = {document:{hidden:false,getElementById:id=>({'process-root':{dataset:{}},
  'process-list':list, 'process-feedback':{classList:{add(){},remove(){}}}})[id]},
  setInterval(){}, fetch:async()=>({ok:true,json:async()=>({processes:jobs})})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/processes.js'),'utf8'),context);
setTimeout(()=>{
  try {
    for(const label of ['Games','Positions','Coaching','Game Retrieval','Position Evaluation','Coaching Analysis'])
      assert(list.innerHTML.includes(label), `Missing ${label}`);
    assert(list.innerHTML.includes('Completed in 12.0s'));
    assert(list.innerHTML.includes('Screening 55.0s'));
    assert(list.innerHTML.includes('Deep evaluation 1.6m'));
    assert(list.innerHTML.includes('Stockfish probes 2.2s'));
    assert(list.innerHTML.includes('2 reused'));
    assert(list.innerHTML.includes('1 new probes'));
    jobs[0].refresh_perf = '{invalid';
    // Invalid persisted perf must never break rendering on next poll.
    console.log('PASS: stage labels and per-stage timing diagnostics');
  } catch(e) {console.error(e);process.exitCode=1;}
},12);
