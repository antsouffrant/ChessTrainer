const assert = require('node:assert/strict');
const fs = require('node:fs');
const coach = fs.readFileSync('static/coach.css', 'utf8');
const shared = fs.readFileSync('static/styles.css', 'utf8');
const page = fs.readFileSync('templates/analytics.html', 'utf8');
const base = fs.readFileSync('templates/base.html', 'utf8');

assert.match(base, /\{% block extra_head %\}/, 'base supports page-specific stylesheets');
assert.match(page, /filename='coach\.css'/, 'Coach loads dedicated stylesheet');
assert.doesNotMatch(shared, /\.analytics-(overview|score|breakdowns|hub)\s*\{/, 'no conflicting Coach card layout rules in global CSS');
assert.match(coach, /grid-template-columns:\s*repeat\(auto-fit,\s*minmax\(min\(100%,\s*230px\),\s*1fr\)\)/, 'overview wraps instead of forcing five narrow columns');
assert.match(coach, /\.analytics-breakdowns\s*\{[^}]*grid-template-columns:\s*repeat\(2,minmax\(0,1fr\)\)/s, 'breakdown cards have two well-spaced columns');
assert.match(coach, /@media\s*\(max-width:1050px\)/, 'breakdown cards stack on smaller viewports');
assert.match(coach, /\.analytics-score\s*\{[^}]*overflow-wrap:\s*anywhere/s, 'long score labels wrap');
assert.match(coach, /\.analytics-table-scroll\s*\{[^}]*overflow-x:\s*auto/s, 'tables scroll instead of clipping text');
assert.match(coach, /#analytics-results:not\(\.hidden\)\s*\{[^}]*gap:/, 'result sections have explicit spacing');
assert.match(coach, /\.analytics-score\s*\{[^}]*min-height:\s*208px/s, 'scorecards have legible vertical room');
console.log('Coach v55 responsive layout and stylesheet isolation contracts passed');
