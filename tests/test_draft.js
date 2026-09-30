const assert = require('node:assert/strict');
const drafts = require('../static/draft.js');
const data = new Map();
const storage = {getItem: k => data.get(k), setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k)};
const draft = {batch:'US|Name|vless://secret', rows:[{country:'TW',name:'台北',link:'vmess://private'}], policies:['test'], source:'custom', overrides:{a:{country:'JP'}}};
drafts.store(storage, draft, 100);
assert.deepEqual(drafts.restore(storage, 101), {version:1,saved_at:100,...draft,node_update_mode:'replace'});
for (const mode of ['replace','merge']) {
  drafts.store(storage, {...draft,node_update_mode:mode},100);
  assert.equal(drafts.restore(storage,101).node_update_mode,mode);
}
for (const mode of [undefined,null,true,'MERGE','invalid']) {
  drafts.store(storage, {...draft,node_update_mode:mode},100);
  assert.equal(drafts.restore(storage,101).node_update_mode,'replace');
}
assert.equal(drafts.restore(storage, 100 + drafts.TTL), null);
assert.equal(data.size, 0);
storage.setItem(drafts.KEY, '{broken'); assert.equal(drafts.restore(storage), null);
drafts.store(storage, draft); drafts.clear(storage); assert.equal(drafts.restore(storage), null);
assert.throws(() => drafts.store({setItem(){throw Error('quota');}}, draft));
console.log('Draft storage: restore, expiry, corruption, clear, quota and Merge/legacy mode checks passed');

const {matchesCountry} = require('../static/nodes.js');
assert(matchesCountry('TW',{english:'Taiwan',chinese:'台湾',aliases:[]},'tai'));
assert(matchesCountry('TH',{english:'Thailand',chinese:'泰国',aliases:[],search_aliases:['tai']},'tai'));
assert(matchesCountry('US',{english:'United States',chinese:'美国',aliases:[]},'美'));
assert(matchesCountry('JP',{english:'Japan',chinese:'日本',aliases:[]},'JP'));

const {preventImplicitGeneration, isExplicitGenerate} = require('../static/nodes.js');
function keyEvent(tagName, type, key = 'Enter') {
  return {key, target: {tagName, type, value:'JP'}, defaultPrevented:false,
    preventDefault() {this.defaultPrevented = true;}};
}
// Country search inside process-form: cancellation suppresses the browser's
// default implicit submission even if it would nominate the Generate button.
for (const control of ['aux-country-search', 'preview-country-search', 'aux-name', 'aux-link', 'preview-name']) {
  const event = keyEvent('INPUT', control.includes('search') ? 'search' : 'text');
  preventImplicitGeneration(event);
  let generated = 0;
  if (!event.defaultPrevented) generated++; // browser's otherwise-implicit action
  assert.equal(generated, 0, control);
  assert.equal(event.target.value, 'JP', 'search text must remain');
}
for (const key of ['ArrowDown', 'ArrowUp', 'Tab', 'j']) {
  const event = keyEvent('INPUT', 'search', key);
  preventImplicitGeneration(event); assert.equal(event.defaultPrevented, false);
}
for (const [tag, type] of [['TEXTAREA','textarea'], ['BUTTON','submit'], ['INPUT','submit']]) {
  const event = keyEvent(tag, type);
  preventImplicitGeneration(event); assert.equal(event.defaultPrevented, false);
}
const generate = {id:'generate-yaml'};
for (const submitter of [null, undefined, {id:'parse-nodes'}, {id:'add-node-row'}, {id:'generate-yaml'}]) {
  const event = {submitter, preventDefault() {this.defaultPrevented = true;}};
  assert.equal(isExplicitGenerate(event, generate), false);
  assert.equal(event.defaultPrevented, true);
}
for (let i = 0; i < 3; i++) {
  const event = {submitter:generate, preventDefault() {throw Error('explicit Generate blocked');}};
  assert.equal(isExplicitGenerate(event, generate), true); // repeated clicks/requestSubmit work
}
console.log('Generate-only guard: country search, preview, auxiliary, textarea, keyboard and submitters passed');
