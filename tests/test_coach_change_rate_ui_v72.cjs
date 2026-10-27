const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('templates/analytics.html','utf8');
const js = fs.readFileSync('static/analytics.js','utf8');
const trainer = fs.readFileSync('templates/trainer.html','utf8');
const tjs = fs.readFileSync('static/trainer.js','utf8');
test('taxonomy cards show solved-position change rates, not approval of responded dropdowns', () => {
  for (const field of ['context','move_type','motif']) {
    assert.match(html,new RegExp(`data-score="taxonomy_${field}"`));
    assert.match(js,/data\.taxonomy_change_rates/);
  }
  assert.match(js,/changes\.changed/);
  assert.match(js,/changes\.solved/);
  assert.match(js,/changes\.change_pct/);
  assert.doesNotMatch(js,/selections · .*match/);
  assert.match(html,/Untouched positions and selections changed back/);
  assert.match(html,/id="coach-taxonomy-export"/);
  assert.match(js,/api\/coach\/taxonomy\.csv/);
});
test('legacy motif thumbs are absent from UI but position/explanation thumbs remain', () => {
  assert.doesNotMatch(html,/Historical motif thumbs/);
  assert.doesNotMatch(html,/data-score="motif"/);
  // The new change-dimension selector legitimately offers motif; legacy *feedback area* does not.
  assert.doesNotMatch(html,/<option value="motif">Historical motif thumbs/);
  assert.match(html,/id="coach-changes-group"/);
  assert.doesNotMatch(trainer,/coaching-correction-motif/);
  assert.doesNotMatch(trainer,/data-feedback-category="motif"/);
  assert.doesNotMatch(tjs,/\['position', 'explanation', 'motif'\]\.includes\(category\)/);
  for (const type of ['position','explanation']) assert.match(trainer,new RegExp(`data-feedback-category="${type}"`));
});
