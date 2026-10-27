const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const html = fs.readFileSync(path.join(root,'templates/trainer.html'),'utf8');
const js = fs.readFileSync(path.join(root,'static/trainer.js'),'utf8');
const css = fs.readFileSync(path.join(root,'static/styles.css'),'utf8');
test('coach chat messages precede text input',()=>{
  const panel = html.split('<aside class="coach-panel">')[1].split('</aside>')[0];
  assert.ok(panel.indexOf('id="coach-chat"') < panel.indexOf('id="coach-form"'));
  assert.ok(css.includes('grid-template-rows: auto auto auto minmax(200px, 1fr) auto;'));
});
test('attempt comments each have thumbs separate from solving explanation',()=>{
  const panel = html.split('<aside class="coach-panel">')[1].split('</aside>')[0];
  assert.ok(panel.includes('id="coach-attempt-comments"'));
  assert.ok(panel.includes('id="coach-text"'));
  assert.equal((panel.match(/data-feedback-category="explanation"/g)||[]).length,1);
  assert.ok(js.includes('for (const note of notes.filter(entry => entry.origin !== \'solving\' && entry.origin !== \'game\' && !entry.correct))'));
  assert.ok(js.includes('coachAttemptCommentsEl.append(section)'));
  assert.ok(js.includes("votes.dataset.feedbackCategory = 'continuation'"));
  assert.ok(js.includes("votes.dataset.continuationKey = note.origin === 'game'"));
  assert.ok(js.includes('explanationPackageSnapshot()'));
});
test('recaps retain one stored session recap and render independent continuation message cards',()=>{
  assert.ok(js.includes('if (solvedRecap) return'));
  assert.ok(js.includes('attemptNotesFromRecap(structured)'));
  assert.ok(js.includes('renderCoachAttemptComments(lastRecap, position.id)'));
  assert.ok(js.includes('renderCoachAttemptComments(message, positionId)'));
  assert.ok(js.includes('clearCoachAttemptComments()'));
  assert.ok(!js.includes('await publishPostSolveCoach(position)'));
});
