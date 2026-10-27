const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root,'templates/trainer.html'),'utf8');
const js = fs.readFileSync(path.join(root,'static/trainer.js'),'utf8');
const css = fs.readFileSync(path.join(root,'static/styles.css'),'utf8');
const report = fs.readFileSync(path.join(root,'templates/analytics.html'),'utf8');
test('each attempted continuation is its own chat message, not a section inside the solving bubble',()=>{
  const region = html.split('id="coach-chat"')[1].split('id="coach-form"')[0];
  assert.ok(region.indexOf('id="coach-position-review"') < region.indexOf('id="coach-attempt-comments"'));
  const solution = region.split('id="coach-position-review"')[1];
  assert.ok(solution.includes('id="coach-attempt-comments"')); // following sibling, not nested in bubble
  assert.match(js,/section\.className = 'coach-message assistant coach-continuation-message'/);
  assert.match(js,/votes\.dataset\.continuationKey = note\.origin === 'game'/);
  assert.match(js,/const attempts = new Map\(\)/);
});
test('individual solution and attempt votes stay isolated, including corrections',()=>{
  assert.match(js,/continuationRatings\.get\(id\)/);
  assert.match(js,/continuationCorrections\.get\(id\)/);
  assert.match(js,/payload\.continuation_key = continuationKey/);
  assert.match(js,/category === 'continuation' \? key : undefined/);
  assert.match(js,/return coachTextEl\?\.textContent\?\.trim\(\) \|\| ''/);
  assert.match(js,/handleExplanationFeedbackClick/);
});
test('fixed width and distinct light-blue attempt bubble',()=>{
  assert.match(css,/\.coach-chat > \.coach-message \{ width: 88%; max-width: 88%/);
  assert.match(css,/\.coach-chat > \.coach-attempt-comments \{[\s\S]*width: 88%; max-width: 88%/);
  assert.match(css,/\.coach-message\.assistant\.coach-continuation-message \.coach-message-body \{[\s\S]*rgba\(69, 133, 186/);
});
test('approval reporting distinguishes solving and attempted continuations',()=>{
  assert.match(report,/name="continuation_scope"/);
  assert.match(report,/value="continuation_kind"/);
});
