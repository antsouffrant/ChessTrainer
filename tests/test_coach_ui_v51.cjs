const assert = require('node:assert/strict');
const fs = require('node:fs');
const base = fs.readFileSync('templates/base.html','utf8');
const html = fs.readFileSync('templates/analytics.html','utf8');
const css = fs.readFileSync('static/coach.css','utf8');
const js = fs.readFileSync('static/analytics.js','utf8');
const app = fs.readFileSync('app.py','utf8');
assert.match(base,/url_for\('coach_view'\)/);
assert.match(base,/<span>Coach<\/span>/);
assert.match(app,/@app\.get\('\/coach'\)/);
assert.match(app,/@app\.get\('\/analytics'\)/);
assert.match(app,/redirect\(url_for\('coach_view'\)/);
for (const filter of ['coaching_version','position_category', 'feedback_type', 'rating','job_id','primary_motif_key']) {
  assert.ok(html.includes(`name="${filter}"`), `${filter} selector`);
}
for (const id of ['coach-changes-chart','coach-approval-chart','analytics-export','analytics-records','analytics-total']) {
  assert.ok(html.includes(`id="${id}"`), `${id} widget`);
}
assert.match(html,/content_snapshot/);
assert.match(html,/current_explanation/);
assert.match(css,/\.analytics-hub \{/);
assert.match(css,/\.analytics-export-guide/);
assert.match(html,/filename='coach.css'/);
assert.match(js,/fillFacet\('coaching_version'/);
assert.match(js,/fillFacet\('position_category'/);
assert.match(js,/drawRateChart/);
console.log('Coach v51 UI / filters / exports / navigation contract passed');
