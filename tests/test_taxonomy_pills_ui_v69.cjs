const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const js = fs.readFileSync('static/trainer.js', 'utf8');
const html = fs.readFileSync('templates/trainer.html', 'utf8');
const css = fs.readFileSync('static/styles.css', 'utf8');

class Element {
  constructor(tag) { this.tag = tag; this.dataset = {}; this.children = []; this.handlers = {}; this.classList={toggle(){},remove(){},add(){}}; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  add(child) { this.children.push(child); }
  setAttribute(name,value) { this[name] = value; }
  addEventListener(name,cb) { this.handlers[name] = cb; }
}
const path = new Element('span');
const note = new Element('div');
const status = new Element('small');
const p = {id:81,learned:1,
  taxonomy:{context_key:'defend',context_name:'Defensive Resources',move_type_key:null,
    move_type_name:null,motif_key:'material_sacrifice',motif_name:'Sacrifice Material'},
  concepts:[{key:'material_sacrifice',name:'Sacrifice Material',is_primary:true}]};
const options = {
  context:[{key:'attack',name:'Attacking Plans'}, {key:'defend',name:'Defensive Resources'}],
  move_type:[{key:'none',name:'No tactical/strategic qualifier'}, {key:'tactical',name:'Tactical Calculation'},
    {key:'strategic',name:'Strategic Comprehension'}],
  motif:[{key:'material_sacrifice',name:'Sacrifice Material'}, {key:'fork',name:'Double Attack'}]
};
const feedback = {selected:{},predicted:{context:'defend',move_type:'none',motif:'material_sacrifice'},options};
const calls = [];
const document = {activeElement:null,
  getElementById(id) {return {'lesson-concepts':path}[id];},
  createElement(tag) {return new Element(tag);}};
const scope = {document,evaluationRunId:null,Option:class {constructor(text,value){this.text=text;this.value=value;}},
  currentPosition:()=>p, positionSolvedForRating:()=>true,
  taxonomyFeedbackEl:note, taxonomyFeedbackStatusEl:status,
  taxonomyFeedbackRecords:new Map([[81,feedback]]),
  suggestedMotifOptions:[], ratingRequestSerial:0,
  fetch:async (url,params) => {
    const body = JSON.parse(params.body);
    calls.push({url,body});
    if (body.selected_key) feedback.selected[body.field] = body.selected_key;
    else delete feedback.selected[body.field];
    return {ok:true,json:async()=>({taxonomy_feedback:{...feedback,selected:{...feedback.selected}}})};
  }};
const start = js.indexOf('const taxonomyFieldNames = ');
const end = js.indexOf('\nfunction updatePositionRatingUI() {',start);
assert.ok(start > 0 && end > start);
vm.runInNewContext(js.slice(start,end)+ '\nthis.api = {render:renderTaxonomyPills, save:updateTaxonomyFeedbackChoice};',scope);
const selects = () => path.children.filter(el=>el.tag==='span' && el.className?.includes('taxonomy-pill')).map(el=>({pill:el,select:el.children.at(-1),label:el.children[0].textContent}));
const get = field => selects().find(x=>x.select.dataset.taxonomyField===field);

test('two-node taxonomy appears as interactive pills, with optional move-type affordance', () => {
  scope.api.render();
  assert.equal(selects().length,3);
  assert.deepEqual(selects().map(x=>x.label),['Defensive Resources','Sacrifice Material','+ Move type']);
  assert.equal(get('motif').select.children.find(x=>x.value==='material_sacrifice').text,
    'Confirm coach: Sacrifice Material');
  assert.match(get('motif').select.children[0].text,/clear feedback/);
});

test('context correction is saved as feedback only and can be replaced or cleared', async () => {
  scope.api.render();
  const context = get('context');
  context.select.value = 'attack';
  await scope.api.save(context.select);
  assert.deepEqual(calls.at(-1).body,{field:'context',selected_key:'attack',evaluation_run_id:null});
  assert.equal(p.taxonomy.context_key,'defend'); // Never edit coach's prediction
  assert.equal(get('context').label,'Attacking Plans');
  assert.match(get('context').pill.className,/taxonomy-pill-edited/);
  get('context').select.value='defend';
  await scope.api.save(get('context').select);
  assert.match(get('context').pill.className,/taxonomy-pill-confirmed/);
  assert.equal(get('context').label,'Defensive Resources');
  get('context').select.value='';
  await scope.api.save(get('context').select);
  assert.equal(get('context').label,'Defensive Resources');
  assert.doesNotMatch(get('context').pill.className,/taxonomy-pill-confirmed/);
});

test('adding tactical move type inserts third path node without changing other feedback', async () => {
  get('move_type').select.value='tactical';
  await scope.api.save(get('move_type').select);
  assert.deepEqual(selects().map(x=>x.label),
    ['Defensive Resources','Tactical Calculation','Sacrifice Material']);
  assert.equal(p.taxonomy.move_type_key,null);
  get('motif').select.value='fork';
  await scope.api.save(get('motif').select);
  assert.equal(get('motif').label,'Double Attack');
  assert.equal(feedback.selected.move_type,'tactical');
  get('move_type').select.value='none';
  await scope.api.save(get('move_type').select);
  assert.deepEqual(selects().map(x=>x.label),['Defensive Resources','Double Attack','No qualifier']);
  assert.equal(feedback.selected.motif,'fork');
});

test('no separate dropdown panel, retaining thumbs for explanation and chat',()=>{
  assert.doesNotMatch(html,/taxonomy-feedback-fields/);
  assert.match(html,/Select a learning pill/);
  assert.match(css,/\.taxonomy-pill-native-select/);
  assert.match(html,/data-feedback-category="explanation"/);
  assert.match(html,/data-feedback-category="position"/);
  assert.doesNotMatch(html,/data-feedback-category="motif"/);
});
