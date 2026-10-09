const assert=require('node:assert/strict');
const drafts=require('../static/draft.js');
const map=new Map(),storage={getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)};
const value={batch:'synthetic vless://private',source:'default',rows:[{country:'US',name:'Synthetic',link:'vless://private'}],policies:[],overrides:{node:{country:'US',name:'Synthetic'}}};
drafts.store(storage,value,100);
assert(drafts.restore(storage,100+drafts.TTL-1));
assert.equal(drafts.restore(storage,100+drafts.TTL),null);
assert.equal(map.size,0);
drafts.store(storage,value,100,'keep');
assert.equal(drafts.restore(storage,100+drafts.TTL*10).batch,value.batch);
// Preference is not authority to retroactively extend the record's old TTL.
drafts.store(storage,value,100);drafts.setPolicy(storage,'keep');
assert.equal(drafts.policy(storage),'keep');assert.equal(drafts.restore(storage,100+drafts.TTL),null);
assert.equal(storage.getItem(drafts.KEY),null);
for(const invalid of ['broken',JSON.stringify({version:1,saved_at:100,retention_policy:'forever',...value}),JSON.stringify({version:1,saved_at:500,...value})]){
 storage.setItem(drafts.KEY,invalid);assert.equal(drafts.restore(storage,200),null);assert.equal(storage.getItem(drafts.KEY),null);
}
drafts.store(storage,{...value,password:'PRIVATE_PASSWORD',csrf_token:'PRIVATE_CSRF',session:'PRIVATE_COOKIE',yaml_file:'FILE_BYTES',rows:[{...value.rows[0],csrf_token:'PRIVATE_CSRF'}],overrides:{node:{...value.overrides.node,password:'PRIVATE_PASSWORD'}}},100,'keep');
const saved=storage.getItem(drafts.KEY);
for(const marker of ['PRIVATE_PASSWORD','PRIVATE_CSRF','PRIVATE_COOKIE','FILE_BYTES'])assert(!saved.includes(marker));
drafts.clear(storage);assert.equal(drafts.restore(storage,200),null);
assert.equal(drafts.policy(storage),'keep'); // Clear data preserves user preference.
assert.throws(()=>drafts.setPolicy(storage,'forever'));
assert.throws(()=>drafts.store({setItem(){throw Error('quota');}},value));
assert.throws(()=>drafts.restore({getItem(){throw Error('denied');}}));
console.log('PASS retention draft unit: default TTL, keep, no resurrection, data whitelist, clear, storage failure');
