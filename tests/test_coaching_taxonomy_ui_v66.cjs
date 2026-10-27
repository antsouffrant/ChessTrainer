// Cross-screen contract: lesson taxonomy filters must reach manifest playlists.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const src = read('static/lesson_detail.js');
const start = src.indexOf('const detailScopeQuery = () => {');
const end = src.indexOf('const detailDescriptor = ', start);
assert.ok(start >= 0 && end > start);
const fnSource = src.slice(start, end) + '\ndetailScopeQuery();';
function scope(isOpening, conceptKey, values) {
  return vm.runInNewContext(fnSource, {
    detailIsOpening: isOpening,
    detailConcept: conceptKey,
    document: {getElementById(id) {return {value:values[id] ?? null};}},
  });
}

test('lesson scoped to one primary motif by default', () => {
  const query=scope(false,'fork',{'position-concept-filter':'fork'});
  assert.equal(query.concept,'fork');
  assert.equal(query.context,undefined);
  assert.equal(query.move_type,undefined);
});

test('all motifs exposes meaningful attack/defense and tactical/strategic slices', () => {
  const query=scope(false,'fork',{
    'position-concept-filter':'all', 'position-context-filter':'defend',
    'position-move-type-filter':'tactical',
  });
  assert.equal(query.concept,undefined);
  assert.equal(query.context,'defend');
  assert.equal(query.move_type,'tactical');
});

test('opening filters still work with no variation selected', () => {
  const query=scope(true,'sicilian',{'position-concept-filter':''});
  assert.equal(query.opening,'sicilian');
  assert.equal(query.variation,undefined);
});

test('opening chosen variation remains intact', () => {
  const query=scope(true,'sicilian',{'position-concept-filter':'Najdorf'});
  assert.equal(query.variation,'Najdorf');
});

test('training forwards all taxonomy filters to manifest', () => {
  const trainer=read('static/trainer.js');
  assert.match(trainer,/params\.set\('context', trainerContextFilter\)/);
  assert.match(trainer,/params\.set\('move_type', trainerMoveTypeFilter\)/);
  assert.match(trainer,/renderConcepts\(p\.concepts \|\| \[\], p\.taxonomy\)/);
});

test('lesson labels remain primary motif, hierarchy is a badge not extra tiles', () => {
  const app=read('app.py');
  assert.match(app,/WHERE tp\.job_id = \? AND pc\.is_primary = 1/);
  assert.match(app,/JOIN position_motif_taxonomy scoped_tx/);
  assert.match(app,/base_where \+= ' AND scoped_tx\.move_type_key IS NULL'/);
  const detail=read('templates/lesson_detail.html');
  assert.match(detail,/id="position-context-filter"/);
  assert.match(detail,/id="position-move-type-filter"/);
  assert.match(detail,/All primary motifs/);
});
