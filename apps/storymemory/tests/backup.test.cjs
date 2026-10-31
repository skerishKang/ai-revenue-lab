const assert = require('node:assert/strict');
const backup = require('../public/storymemory-backup-v1.js');
function store(seed={}) {
  const m=new Map(Object.entries(seed));
  return {get length(){return m.size},key(i){return [...m.keys()][i]??null},getItem(k){return m.has(k)?m.get(k):null},setItem(k,v){m.set(k,String(v))},removeItem(k){m.delete(k)}};
}
const src=store({'storymemory.annotations.v2':'[{"note":"test"}]','storymemory.readerProgress.test':'{"page":3}','storymemory.authBridgeState.v1':'DO_NOT_EXPORT','unrelated':'x'});
const snap=backup.snapshot(src);
assert.equal(Object.keys(snap.data).length,2);
assert.equal(JSON.stringify(snap).includes('DO_NOT_EXPORT'),false);
const dst=store({'storymemory.annotations.v2':'[]','unrelated':'preserved'});
backup.restore(dst,JSON.stringify(snap));
assert.equal(dst.getItem('storymemory.annotations.v2'),'[{"note":"test"}]');
assert.equal(dst.getItem('storymemory.readerProgress.test'),'{"page":3}');
assert.equal(dst.getItem('unrelated'),'preserved');
assert.throws(()=>backup.restore(dst,JSON.stringify({format:'storymemory-backup',version:1,data:{'storymemory.authBridgeState.v1':'{}'}})));
assert.throws(()=>backup.restore(dst,JSON.stringify({format:'storymemory-backup',version:1,data:{'storymemory.annotations.v2':'not json'}})));
assert.equal(dst.getItem('storymemory.annotations.v2'),'[{"note":"test"}]');
let calls=0; const original=dst.setItem; dst.setItem=(k,v)=>{if(++calls===2)throw Error('quota');original(k,v)};
assert.throws(()=>backup.restore(dst,JSON.stringify({format:'storymemory-backup',version:1,data:{'storymemory.annotations.v2':'[]','storymemory.userMemories.v1':'[]'}})));
assert.equal(dst.getItem('storymemory.annotations.v2'),'[{"note":"test"}]');
console.log('PASS: backup round trip, credential exclusion, invalid input and rollback');
