const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const full=fs.readFileSync('static/trainer.js','utf8');
const snippet=full.slice(full.indexOf('function escapeCoachHtml(value) {'),full.indexOf('function updateCoachMode() {'));
const output = [], calls=[];
const ctx = {
  coachChatEl: {}, coachThreadReadyPositionId:7, displayedPositionId:7,
  historicCoachRequests:new Set(), solved:true,openingKey:'philidor-defense',
  fetch:async(url,opts)=>{calls.push({url,opts});return {ok:true,json:async()=>({shown:true, content:'A real historic game', message_id:19,reference:{title:'The Opera Game',source_url:'https://example.org/game',match_type:'related_opening'}})}},
  appendCoachMessage:(...args)=>output.push(args),JSON,Set,Boolean,String,Number
};
vm.createContext(ctx);
vm.runInContext(snippet,ctx);
const rendered=vm.runInContext(`coachMessageHtml({id:19,role:'assistant',content:'Historic link',structured_json:JSON.stringify({kind:'historical_reference',historical_reference:{title:'Opera',source_url:'https://example.org/game'}})})`,ctx);
assert.match(rendered,/class="historic-coach-link"/);
assert.match(rendered,/https:\/\/example.org\/game/);
assert.doesNotMatch(rendered,/coach-response-feedback/);
const evil=vm.runInContext(`coachMessageHtml({role:'assistant',content:'<script>alert(1)</script>',structured_json:JSON.stringify({kind:'historical_reference',historical_reference:{title:'Oops',source_url:'javascript:alert(1)'}})})`,ctx);
assert.doesNotMatch(evil,/href=/);
assert.match(evil,/&lt;script&gt;/);
(async()=>{
 await ctx.maybeOfferHistoricalCoach({id:7,learned:1});
 await ctx.maybeOfferHistoricalCoach({id:7,learned:1});
 assert.equal(calls.length,1);
 assert.equal(output.length,1);
 assert.equal(JSON.parse(calls[0].opts.body).opening_playlist,true);
 console.log('Historic coach rendering/one-shot messaging: passed');
})().catch(e=>{console.error(e);process.exit(1)});
