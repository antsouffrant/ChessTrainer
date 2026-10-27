const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const html = fs.readFileSync('templates/coach_benchmark.html', 'utf8');
const benchmark = fs.readFileSync('static/benchmark_chart.js', 'utf8');
const feedback = fs.readFileSync('static/analytics.js', 'utf8');
const template = fs.readFileSync('templates/analytics.html', 'utf8');

test('per-model evaluation changes have distinct solved denominators', () => {
  assert.match(benchmark, /taxonomy_any_change_pct/);
  for (const field of ['context','move_type','motif']) {
    assert.match(benchmark, new RegExp(`taxonomy_${field}_change_pct`));
    assert.match(benchmark, new RegExp(`taxonomy_${field}_changed`));
  }
  assert.match(benchmark, /num\(r\.solved\)/);
  assert.match(html, /Later-model comparisons measure differences between frozen model outputs/);
});
test('pairwise model output change is distinct from feedback correction change', () => {
  assert.match(benchmark, /bar\('Explanation changed',c\.explanation_change_pct/);
  assert.match(benchmark, /bar\('Primary motif changed',c\.motif_change_pct/);
  assert.match(html, /per-model evaluation change rates above/);
});
test('general Coach change-rate chart includes authoritative evaluations', () => {
  assert.match(feedback, /data\.taxonomy_change_rates/);
  assert.match(template, /authoritative evaluation positions/);
  assert.match(feedback, /authoritative evaluation observations/);
});
