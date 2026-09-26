const assert = require('node:assert/strict');
const drafts = require('../static/draft.js');
const data = new Map();
const storage = {getItem: k => data.get(k), setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k)};
const draft = {batch:'US|Name|vless://secret', rows:[{country:'TW',name:'台北',link:'vmess://private'}], policies:['test'], source:'custom', overrides:{a:{country:'JP'}}};
drafts.store(storage, draft, 100);
assert.deepEqual(drafts.restore(storage, 101), {version:1,saved_at:100,...draft});
assert.equal(drafts.restore(storage, 100 + drafts.TTL), null);
assert.equal(data.size, 0);
storage.setItem(drafts.KEY, '{broken'); assert.equal(drafts.restore(storage), null);
drafts.store(storage, draft); drafts.clear(storage); assert.equal(drafts.restore(storage), null);
assert.throws(() => drafts.store({setItem(){throw Error('quota');}}, draft));
console.log('Draft storage: restore, expiry, corruption, clear and quota checks passed');

const {matchesCountry} = require('../static/nodes.js');
assert(matchesCountry('TW',{english:'Taiwan',chinese:'台湾',aliases:[]},'tai'));
assert(matchesCountry('TH',{english:'Thailand',chinese:'泰国',aliases:[],search_aliases:['tai']},'tai'));
assert(matchesCountry('US',{english:'United States',chinese:'美国',aliases:[]},'美'));
assert(matchesCountry('JP',{english:'Japan',chinese:'日本',aliases:[]},'JP'));
