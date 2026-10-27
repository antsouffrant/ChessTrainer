const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('templates/trainer.html', 'utf8');
const js = fs.readFileSync('static/trainer.js', 'utf8');
const api = fs.readFileSync('app.py', 'utf8');
const dash = fs.readFileSync('templates/analytics.html', 'utf8');
const dashJs = fs.readFileSync('static/analytics.js', 'utf8');
for (const f of ['context','move_type','motif']) {
  assert.match(js, /select.dataset.taxonomyField = field/);
  assert.match(dash, new RegExp(`value="taxonomy_${f}"`));
  assert.match(dashJs, new RegExp(`taxonomy_${f}`));
}
assert.doesNotMatch(html, /data-feedback-category="motif"/);
for (const f of ['explanation','position']) assert.match(html, new RegExp(`data-feedback-category="${f}"`));
assert.match(html, /Select a learning pill/);
assert.doesNotMatch(html, /taxonomy-feedback-fields/);
assert.match(js, /async function updateTaxonomyFeedbackChoice/);
assert.match(js, /selected_key:selectedKey/);
assert.match(js, /taxonomyFeedbackRecords\.set\(id, data\.taxonomy_feedback\)/);
assert.match(js, /updateTaxonomyFeedbackUI/);
assert.match(api, /set_position_taxonomy_feedback/);
assert.match(api, /'taxonomy_feedback': taxonomy_feedback_choices/);
assert.match(api, /'taxonomy_selections': taxonomy/);
console.log('v68 dropdown UI and export/filter wiring passed');
