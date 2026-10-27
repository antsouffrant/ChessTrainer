const fs = require('node:fs');
const assert = require('node:assert/strict');
const css = fs.readFileSync('static/styles.css', 'utf8');
const html = fs.readFileSync('templates/trainer.html', 'utf8');
const js = fs.readFileSync('static/trainer.js', 'utf8');

// Guard against the previous side-panel regression: the solved bubble wrapped
// because the message demanded 175px and the thumbs had fixed width.
const block = css.slice(css.indexOf('/* v115 — compact solved-status strip.'));
assert(block.startsWith('/* v115'));
assert.match(block, /\.trainer-main \.feedback\.good:not\(\.hidden\)\s*\{[^}]*flex-wrap:\s*nowrap;/);
assert.match(block, /\.trainer-main \.feedback\.good #feedback-message\s*\{[^}]*flex:\s*1 1 auto;/);
assert.match(block, /\.trainer-main \.feedback\.good \.position-votes:not\(\.hidden\)\s*\{[^}]*flex-wrap:\s*nowrap;/);
assert.match(block, /\.trainer-main \.feedback\.good \.position-votes \.rating-prompt\s*\{[^}]*clip-path:/);
assert.match(html, /aria-label="Was this training position helpful\?"/);
assert.match(html, /class="feedback-edit-correction hidden" aria-label="Edit suggested correction" title="Edit suggested correction">✎<\/button>/);
assert.match(js, /feedbackMessageEl\.textContent = result\.accepted_alternative \? '✓ Solved · strong move' : '✓ Solved';/);
assert.match(js, /feedbackMessageEl\.textContent = solved \? '✓ Solved' : '';/);
assert.match(js, /group\.querySelector\('\.feedback-edit-correction'\)\?\.classList\.toggle/);
assert.match(js, /group\.querySelectorAll\('\[data-rating\]'\)/);
console.log('PASS: compact one-line solved banner, exposed rating buttons, retained correction controls');
