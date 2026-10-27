const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('templates/analytics.html','utf8');
const js = fs.readFileSync('static/analytics.js','utf8');
const css = fs.readFileSync('static/coach.css','utf8');
const app = fs.readFileSync('app.py','utf8');
test('headlines show thumbs approval and taxonomy change, without chat headline',()=>{
  for (const text of ['Training positions · Approval rate','Explanations · Approval rate']) assert.ok(html.includes(text),text);
  assert.doesNotMatch(html,/data-score="coaching"/);
  for (const text of ['Position context · change rate','Move type · change rate','Learning motif · change rate']) assert.ok(html.includes(text),text);
});
test('two charts with local category parameters instead of global three-way controls',()=>{
  for (const id of ['coach-changes-chart','coach-approval-chart','coach-changes-group','coach-approval-group']) assert.ok(html.includes(`id="${id}"`));
  for (const old of ['name="chart_group"','name="chart_approval"','name="chart_change"','id="analytics-comparison-chart"']) assert.ok(!html.includes(old),old);
  assert.match(js,/drawRateChart\(data, 'changes'\)/);
  assert.match(js,/drawRateChart\(data, 'approval'\)/);
  assert.match(app,/coaching_metric_chart\(/);
  const changesPanel=html.split('id="coach-changes-chart"')[0].split('aria-label="Taxonomy change rates by category"')[1];
  const approvalPanel=html.split('id="coach-approval-chart"')[0].split('aria-label="Feedback approval rates by category"')[1];
  assert.match(changesPanel,/id="coach-changes-group"/);
  assert.match(approvalPanel,/id="coach-approval-group"/);
});
test('each chart has one independent 0–100 percent scale',()=>{
  assert.equal((html.match(/class="coach-chart-axis"/g)||[]).length,2);
  assert.match(js,/comparison-segment comparison-\$\{isChange/);
  assert.match(js,/width:\$\{100 - value\}%/);
  assert.match(css,/\.coach-metric-row/);
});
