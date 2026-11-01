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

const quotaStore=store({'storymemory.annotations.v2':JSON.stringify([{note:'a'.repeat(60)}])});
const initial=quotaStore.getItem('storymemory.annotations.v2');
const quotaSet=quotaStore.setItem;
quotaStore.setItem=(k,v)=>{
 const total=Array.from({length:quotaStore.length},(_,i)=>quotaStore.key(i)).filter(x=>x!==k).reduce((n,x)=>n+quotaStore.getItem(x).length,0);
 if(total+String(v).length>90)throw Error('quota'); quotaSet(k,v);
};
const tooMuch=JSON.stringify({format:'storymemory-backup',version:1,data:{'storymemory.annotations.v2':'[]','storymemory.userMemories.v1':JSON.stringify([{body:'b'.repeat(60)}]),'storymemory.pinnedEntities.v1':JSON.stringify(['c'.repeat(30)])}});
assert.throws(()=>backup.restore(quotaStore,tooMuch),/quota/);
assert.equal(quotaStore.getItem('storymemory.annotations.v2'),initial);
assert.equal(quotaStore.getItem('storymemory.userMemories.v1'),null);
const badRollback=store({'storymemory.annotations.v2':'[1]'});
const setBefore=badRollback.setItem;let writeCount=0;
badRollback.setItem=(k,v)=>{writeCount++;if(writeCount>=2)throw Error('blocked');setBefore(k,v)};
assert.throws(()=>backup.restore(badRollback,JSON.stringify({format:'storymemory-backup',version:1,data:{'storymemory.annotations.v2':'[]','storymemory.userMemories.v1':'[]'}})),/backup_rollback_failed/);
console.log('PASS: quota rollback releases new entries and reports rollback failure');
