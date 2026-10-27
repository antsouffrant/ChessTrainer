// Exercise the actual lazy-hydration code without an installed browser/runtime.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(__dirname + '/../static/trainer.js', 'utf8');
function extract(name) {
  const asyncStart = source.indexOf(`async function ${name}(`);
  const start = asyncStart >= 0 ? asyncStart : source.indexOf(`function ${name}(`);
  assert(start >= 0, `function ${name} missing`);
  const brace = source.indexOf('{', start);
  let level = 0;
  for (let i = brace; i < source.length; i++) {
    if (source[i] === '{') level++;
    else if (source[i] === '}' && --level === 0) return source.slice(start, i + 1);
  }
  throw new Error(`function ${name} unterminated`);
}
let requests = 0;
const sandbox = {
  positions: Array.from({length: 105}, (_, i) => ({id:i+1, learned:i%5===0?1:0})),
  positionChunkRequests: new Map(),
  POSITION_CHUNK_SIZE: 20,
  jobId: 8, openingKey:'sicilian',
  fetch: async (url,opts) => {
    assert(url.includes('/positions/playlist'));
    const ids = JSON.parse(opts.body).position_ids;
    assert(ids.length <= 20);
    requests++;
    await new Promise(resolve=>setTimeout(resolve, 10));
    return {ok:true,json:async()=>ids.map(id=>({id, fen:`fen-${id}`, learned:id%5===1?1:0, user_color:'white'}))};
  },
  window: {}, setTimeout,
  Map, Number, Math, JSON,
};
vm.createContext(sandbox);
vm.runInContext(extract('hydratePositionChunk'),sandbox);
(async()=>{
  await Promise.all([sandbox.hydratePositionChunk(0), sandbox.hydratePositionChunk(9)]);
  assert.equal(requests,1, 'same chunk must share a request');
  assert.equal(sandbox.positions[0].fen,'fen-1');
  assert(!sandbox.positions[20].fen, 'other positions must remain unloaded');
  await sandbox.hydratePositionChunk(40);
  assert.equal(requests,2);
  await sandbox.hydratePositionChunk(0);
  assert.equal(requests,2, 'loaded history must remain cached');
  assert.equal(sandbox.positions.length,105, 'playlist should never truncate history');
  assert(source.includes("renderBoard(p, restoredSolvedFen || p.fen, solved);"), 'solved board must be drawn');
  assert(source.includes("showBoardMark('correct');"), 'solved green check must be restored');
  assert(source.includes('sessionSolvedMoves[String(position.id)]'), 'accepted moves must be saved per-position');
  assert(source.includes('loadPositions(false).finally'), 'Analysis loading must be deferred');
  console.log('PASS: lazy batches, concurrency, history preservation, solved restoration hooks');
})().catch(e=>{console.error(e);process.exit(1)});
