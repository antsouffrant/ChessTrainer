const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/trainer.js', 'utf8');
const template = fs.readFileSync('templates/trainer.html', 'utf8');
const stylesheet = fs.readFileSync('static/styles.css', 'utf8');

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `Missing ${name}`);
  const opening = source.indexOf('{', start);
  let depth = 0;
  for (let i = opening; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`Unterminated ${name}`);
}
const functions = [functionSource('currentPosition'), functionSource('resetHint'), functionSource('toggleHint')].join('\n');

function element() {
  const classes = new Set(['hidden']);
  const attrs = {};
  return {
    textContent: '',
    classList: {
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      contains: name => classes.has(name)
    },
    setAttribute: (name, value) => {attrs[name] = String(value)},
    getAttribute: name => attrs[name] || null
  };
}
function fixture({evaluation = false, solved = false, prompt = 'Watch the bishop on f7.'} = {}) {
  const button = element();
  const hint = element();
  const coachText = element();
  coachText.textContent = 'The verified solution is Rxe6.';
  const ctx = {
    hintToggleEl: button,
    hintTextEl: hint,
    coachTextEl: coachText,
    evaluationRunId: evaluation ? 52 : null,
    solved, currentIndex: 0,
    positions: [{id: 12, coach_prompt: prompt}]
  };
  vm.runInNewContext(`${functions}\nthis.toggleHint=toggleHint;this.resetHint=resetHint;`, ctx);
  return {ctx, button, hint, coachText};
}

test('hint has its own visible element regardless of Adaptive Coach enabled', () => {
  const buttonAt = template.indexOf('id="hint-toggle"');
  const hintAt = template.indexOf('id="trainer-hint-text"');
  const coachConditionalAt = template.indexOf('{% if not coach_enabled %}', buttonAt);
  assert(buttonAt >= 0 && hintAt > buttonAt && hintAt < coachConditionalAt);
  assert.match(template, /id="hint-toggle"[^>]*aria-controls="trainer-hint-text"[^>]*aria-expanded="false"/);
  assert.match(stylesheet, /\.task-intro-block \.trainer-hint-text/);
  assert.doesNotMatch(functionSource('toggleHint'), /coachTextEl/);
});

test('Show and Hide hint work in coached ordinary Training and evaluation', () => {
  for (const evaluation of [false, true]) {
    const {ctx, button, hint, coachText} = fixture({evaluation});
    ctx.toggleHint();
    assert.equal(hint.classList.contains('hidden'), false);
    assert.equal(hint.textContent, 'Watch the bishop on f7.');
    assert.equal(button.textContent, 'Hide hint');
    assert.equal(button.getAttribute('aria-expanded'), 'true');
    assert.equal(coachText.textContent, 'The verified solution is Rxe6.');
    ctx.toggleHint();
    assert.equal(hint.classList.contains('hidden'), true);
    assert.equal(hint.textContent, '');
    assert.equal(button.textContent, 'Show hint');
    assert.equal(button.getAttribute('aria-expanded'), 'false');
  }
});

test('hint falls back if metadata has no coaching prompt', () => {
  const {ctx, hint} = fixture({prompt: '  '});
  ctx.toggleHint();
  assert.match(hint.textContent, /identify the opponent’s threat/);
});

test('solved position cannot display hints; navigation and solving reset hints', () => {
  const {ctx, hint} = fixture({solved: true});
  ctx.toggleHint();
  assert.equal(hint.classList.contains('hidden'), true);
  assert.match(source, /async function showPosition\(index\)\s*\{[\s\S]*?resetHint\(\);/);
  assert.match(source, /function renderSolvedDetails\(result\)\s*\{[\s\S]*?resetHint\(\);/);
  const reset = ctx.resetHint;
  ctx.solved = false;
  ctx.toggleHint();
  assert.equal(hint.classList.contains('hidden'), false);
  reset();
  assert.equal(hint.classList.contains('hidden'), true);
});
