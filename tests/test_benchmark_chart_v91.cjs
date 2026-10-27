const fs=require('fs');const assert=require('assert');
const chart=fs.readFileSync('static/benchmark_chart.js','utf8');
const html=fs.readFileSync('templates/coach_benchmark.html','utf8');
const process=fs.readFileSync('static/processes.js','utf8');
const trainer=fs.readFileSync('static/trainer.js','utf8');
assert(html.includes('id="model-benchmark-panel"'));
assert(!fs.readFileSync('templates/analytics.html','utf8').includes('id="model-benchmark-panel"'));
assert(process.includes('/coach/benchmark?job_id='));
for(const id of ['benchmark-job','benchmark-model-a','benchmark-model-b','benchmark-model-chart'])
  assert(html.includes(`id="${id}"`));
assert(chart.includes('model_a:baseline.value,model_b:against.value'));
assert(chart.includes("['all','All other models']"));
for(const field of ['explanation_change_pct','motif_change_pct','context_change_pct',
 'move_type_change_pct','paired_ratings','baseline_approval_pct','comparison_approval_pct'])
  assert(chart.includes(field),`Missing ${field}`);
assert(process.includes('data-command="new"'));
assert(process.includes('data-command="activate"'));
assert(process.includes('?benchmark=1&run_id=${j.evaluation_run.id}'));
assert(trainer.includes('evaluation_run_id:evaluationRunId'));
assert(trainer.includes("evaluationRunId ? 'Already solved in this evaluation run.'"));
console.log('PASS: Coach benchmark controls, matched metrics and independent evaluation progress');
