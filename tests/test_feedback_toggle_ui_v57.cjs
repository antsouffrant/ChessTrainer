const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/trainer.js', 'utf8');
const trainer = fs.readFileSync('templates/trainer.html', 'utf8');
const app = fs.readFileSync('app.py', 'utf8');
const feedback = fs.readFileSync('feedback_analytics.py', 'utf8');

// Exercise the real isolated decision helper so clicking the active vote
// clears it instead of reopening the thumbs-down prompt.
const toggle = js.match(/function nextFeedbackRating\([\s\S]*?\n}/)?.[0];
assert.ok(toggle);
const context = vm.createContext({});
vm.runInContext(`${toggle}\nthis.vote=nextFeedbackRating;`, context);
assert.equal(context.vote(-1, -1), 0);
assert.equal(context.vote(1, 1), 0);
assert.equal(context.vote(-1, 1), 1);
assert.equal(context.vote(0, -1), -1);
assert.equal(context.vote(0, 1), 1);

// The retired alphabeticalMotifs helper was never called by the application.
// The active taxonomy pill sorts its options inline, alphabetically with outcomes last.
assert.match(js, /\[\.\.\.choices\]\.sort\(\(a,b\) =>/);
assert.match(js, /Number\(a\[0\]\.startsWith\('evaluation_'\)\)/);
assert.match(js, /a\[1\]\.localeCompare\(b\[1\]/);
assert.match(feedback, /ORDER BY lc\.name COLLATE NOCASE/);
assert.match(app, /ORDER BY lc\.name COLLATE NOCASE ASC/);

const protection = js.match(/function isEditableKeyboardTarget\([\s\S]*?\n}\n\nfunction isCoachInteraction\([\s\S]*?\n}\n\nfunction chessKeyboardContextActive\([\s\S]*?\n}/)?.[0];
assert.ok(protection);
vm.runInContext(`let trainerKeyboardArmed = true; const correctionDialog = {open:false}; ${protection}\nthis.keyboard = chessKeyboardContextActive; this.modal = correctionDialog;`, context);
const textArea = {isContentEditable:false,closest: selector => selector.includes('textarea') ? {} : null};
const chessboard = {isContentEditable:false,closest: () => null};
vm.runInContext('this.document = {activeElement: null};', context);
assert.equal(context.keyboard({target:textArea, isComposing:false}), false);
assert.equal(context.keyboard({target:chessboard, isComposing:false}), true);
context.modal.open = true;
assert.equal(context.keyboard({target:chessboard, isComposing:false}), false);
context.modal.open = false;
context.document.activeElement = textArea;
assert.equal(context.keyboard({target:chessboard, isComposing:false}), false);

assert.match(js, /nextFeedbackRating\(priorRating, chosenRating\)/);
assert.match(js, /\.feedback-edit-correction/);
assert.match(js, /if \(rating === -1\) openCorrectionDialog\('coaching'/);
// The explanation control has a coach-enabled and coach-disabled template
// branch (only one is rendered); position feedback has one shared control.
assert.equal((trainer.match(/class="feedback-edit-correction hidden"/g) || []).length, 3);
assert.match(js, /select.dataset.taxonomyField = field/);
assert.match(js, /rating === 0 \? 'Rating removed\.'/);
console.log('v57 thumbs toggle, live motif ordering and feedback keyboard tests passed');
