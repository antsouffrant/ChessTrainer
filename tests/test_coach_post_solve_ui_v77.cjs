const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const js = fs.readFileSync(path.join(root,'static/trainer.js'),'utf8');
const html = fs.readFileSync(path.join(root,'templates/trainer.html'),'utf8');
const py = fs.readFileSync(path.join(root,'app.py'),'utf8');

test('solved coaching explanation and thumbs live in coach thread, not Your Task',()=>{
  const coachRegion = html.split('<aside class="coach-panel">')[1];
  assert.ok(coachRegion.includes('id="coach-position-review"'));
  assert.ok(coachRegion.includes('id="explanation-feedback-area"'));
  assert.ok(coachRegion.includes('id="coach-text"'));
  const task = html.split('<aside class="side-panel">')[1].split('{% endif %}')[0];
  assert.ok(html.includes('{% if not coach_enabled %}')); // graceful fallback only
  assert.match(js,/coachPositionReviewEl\?\.classList\.add\('hidden'\)/);
  assert.match(js,/coachPositionReviewEl\?\.classList\.remove\('hidden'\)/);
  assert.ok(html.includes('id="solved-opening"'));
});

test('move remains responsive: publish recap only after correct attempt and never await it',()=>{
  assert.match(js,/coach_session_key:coachChatEl \? coachSolveSessionKey\(position.id\) : null/);
  const start=js.indexOf('async function attemptMove(');
  const end=js.indexOf('async function refreshCurrentPosition', start);
  const handler=js.slice(start,end);
  assert.ok(handler.indexOf('if (!result.correct)') < handler.indexOf('void publishPostSolveCoach(position)'));
  assert.ok(!handler.includes('await publishPostSolveCoach'));
  assert.ok(py.includes("@app.post('/api/positions/<int:position_id>/coach/solve-recap')"));
  assert.match(js,/displayedPositionId !== positionId/);
});

test('recap persists once and avoids duplicate chat thumbs',()=>{
  assert.ok(js.includes("structured.kind === 'solved_attempt_recap'"));
  assert.ok(js.includes('&& !solvedRecap'));
  assert.ok(js.includes('preserveCoachReviewInThread()'));
  assert.ok(js.includes('renderCoachAttemptComments(message, positionId)'));
  assert.ok(js.includes('if (solvedRecap) return'));
  assert.ok(js.includes('explanationPackageSnapshot()'));
});
