const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/trainer.js','utf8');
const app = fs.readFileSync('app.py','utf8');
const catalog = fs.readFileSync('learning.py','utf8');
const check = fs.readFileSync('coaching/board_context/check_response.py','utf8');

test('live taxonomy menu sorts by alphabetic label, with evaluation outcomes last',()=>{
  // Validate the comparator actually used by renderTaxonomyPill, not an unused helper.
  const source=js.match(/for \(const \[key,name\] of \[\.\.\.choices\]\.sort\(\(a,b\) =>([\s\S]*?)\)\) \{/)?.[1];
  assert.ok(source, 'Active select-option ordering found');
  const comparator = vm.runInNewContext('(a,b) => '+source, {});
  const pairs=[['evaluation_win_to_loss','Winning to Losing Position'],
    ['skewer','Skewer'], ['fork','Double Attack'],
    ['evaluation_change','Evaluation Swing'], ['blocking','Blocking']];
  const actual=[...pairs].sort(comparator).map(p=>p[0]);
  assert.deepEqual(actual, ['blocking','fork','skewer','evaluation_change','evaluation_win_to_loss']);
});

test('solved navigation restores explanation before waiting for solution fetch',()=>{
  const start=js.indexOf('async function showPosition(index)');
  const end=js.indexOf('async function loadPositions(',start);
  const block=js.slice(start,end);
  assert.ok(start!==-1 && end>start);
  assert.match(block,/if \(solved\) \{[\s\S]*?renderSolvedDetails\(p\);\s*loadSolvedDetails\(p\);/);
  assert.match(app,/tp\.estimated_rating, tp\.coach_prompt, tp\.coach_explanation,/);
  assert.match(app,/tp\.eval_before_cp, tp\.eval_after_cp, tp\.mate_before, tp\.mate_after,/);
  assert.match(js,/explainedPositionId = Number\(currentPosition\(\)\?\.id\)/);
});

test('focused Stockfish checkbox cannot intercept review arrow keys',()=>{
  const helpers=js.match(/function isEditableKeyboardTarget\([\s\S]*?\n}\n\nfunction isCoachInteraction\([\s\S]*?\n}\n\nfunction chessKeyboardContextActive\([\s\S]*?\n}/)?.[0];
  assert.ok(helpers);
  const context={document:{activeElement:null}};
  vm.runInNewContext(`let trainerKeyboardArmed=true; const correctionDialog={open:false}; ${helpers}\nthis.allow=chessKeyboardContextActive; this.edit=isEditableKeyboardTarget;`,context);
  const check={isContentEditable:false,tagName:'INPUT',type:'checkbox',closest:selector=>selector.includes('input')?check:null};
  const text={isContentEditable:false,tagName:'INPUT',type:'text',closest:selector=>selector.includes('input')?text:null};
  const board={isContentEditable:false,closest:()=>null};
  context.document.activeElement=check;
  assert.equal(context.edit(check),false);
  assert.equal(context.allow({target:board,isComposing:false}),true);
  context.document.activeElement=text;
  assert.equal(context.allow({target:board,isComposing:false}),false);
  assert.match(js,/trainerKeyboardArmed = true; \/\/ User-enabled Stockfish/);
});

test('new blocking and material distinctions appear in canonical learning catalog',()=>{
  assert.match(catalog,/'key': 'blocking', 'name': 'Blocking'/);
  assert.match(catalog,/'key': 'lost_material', 'name': 'Material Loss'/);
  assert.match(check,/def blocking_response/);
  assert.match(catalog,/discovered_verified/);
});
