const assert = require('node:assert/strict');
const fs = require('node:fs');
const trainer = fs.readFileSync('templates/trainer.html','utf8');
const base = fs.readFileSync('templates/base.html','utf8');
const js = fs.readFileSync('static/trainer.js','utf8');
const dashboard = fs.readFileSync('templates/analytics.html','utf8');
const dashboardJS = fs.readFileSync('static/analytics.js','utf8');
for (const category of ['position','explanation']) {
  assert.match(trainer,new RegExp(`data-feedback-category="${category}"`));
  assert.match(js,/\/api\/positions\/\$\{id\}\/feedback/);
}
assert.match(trainer,/id="feedback-message"/);
for (const field of ['context','move_type','motif']) {
  assert.match(js,new RegExp(`data-taxonomy-field.*|select.dataset.taxonomyField = field`));
}
assert.doesNotMatch(trainer,/data-feedback-category="motif"/);
assert.match(trainer,/id="coach-text"/);
assert.match(trainer,/id="lesson-concepts"/);
assert.match(js,/new URLSearchParams\(location\.search\)\.get\('concept'\)/);
assert.match(js,/updatePositionRatingUI\(\)/);
assert.match(js,/loadPositionRatings\(p\.id\)/);
assert.match(base,/url_for\('coach_view'\)/);
assert.match(dashboard,/name="primary_motif_key"/);
assert.match(dashboard,/name="job_id"/);
assert.match(dashboard,/name="lesson_key"/);
assert.match(dashboard,/name="opening_key"/);
assert.match(dashboard,/id="analytics-export"/);
assert.match(dashboardJS,/new URLSearchParams\(new FormData\(form\)\)/);
assert.match(dashboardJS,/api\/analytics\/feedback\.csv/);
console.log('v48 analytics/feedback interface contract passed');
