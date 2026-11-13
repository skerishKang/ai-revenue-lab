import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const dbSource=fs.readFileSync(new URL('../public/bookai-local-db.js',import.meta.url),'utf8');
const recordsSource=fs.readFileSync(new URL('../public/bookai-records.js',import.meta.url),'utf8');
// Small transaction fixture: writes become visible only on completion, and an
// aborted transaction rolls every touched store back. No server or browser.
function indexedDBFixture(){
  const stores=new Map();
  const connection={objectStoreNames:{contains:name=>stores.has(name)},close(){},
    createObjectStore:name=>stores.set(name,new Map()),
    transaction(names,mode){
      names=Array.isArray(names)?names:[names];let pending=0,finished=false,scheduled=false;
      const working=new Map(names.map(name=>[name,new Map(stores.get(name))]));
      const tx={error:null,abort(){if(finished)return;finished=true;tx.error=Error('transaction_aborted');queueMicrotask(()=>tx.onabort?.());},
        objectStore(name){
          const data=working.get(name);if(!data)throw Error('unknown_store');
          const read=value=>{const request={};pending++;queueMicrotask(()=>{
            if(!finished){request.result=value();request.onsuccess?.();}pending--;schedule();
          });return request;};
          return {get:key=>read(()=>data.get(key)),getAllKeys:()=>read(()=>[...data.keys()]),
            getAll:()=>read(()=>[...data.values()]),put:(value,key)=>data.set(key,structuredClone(value)),
            delete:key=>data.delete(key),clear:()=>data.clear()};
        }};
      function schedule(){if(scheduled)return;scheduled=true;setImmediate(()=>{
        scheduled=false;if(finished||pending)return;finished=true;
        if(mode==='readwrite')for(const [name,data] of working)stores.set(name,data);
        tx.oncomplete?.();
      });}
      schedule();return tx;
    }};
  return {stores,open(){const request={};queueMicrotask(()=>{
    request.result=connection;if(!stores.size)request.onupgradeneeded?.();request.onsuccess?.();
  });return request;}};
}
function storageFixture(){
  const rows=new Map([['storymemory.userMemories.v1',JSON.stringify([{id:'note',note:'synthetic note'}])],
    ['unrelated.preference','keep']]);
  return {get length(){return rows.size;},key:index=>[...rows.keys()][index]??null,
    getItem:key=>rows.get(key)??null,setItem:(key,value)=>rows.set(key,value),removeItem:key=>rows.delete(key)};
}
async function harness(indexedDB=indexedDBFixture(),native=storageFixture()){
  const root={localStorage:native,dispatchEvent(){}};
  const context=vm.createContext({window:root,indexedDB,crypto:webcrypto,TextEncoder,
    CustomEvent:class{constructor(name,options){this.type=name;this.detail=options.detail;}}});
  vm.runInContext(recordsSource,context);vm.runInContext(dbSource,context);
  await root.BookAILocalDB.init(native);
  return {root,indexedDB,native,db:root.BookAILocalDB};
}

test('first binding includes guest records and committed deletion clears linked data atomically',async()=>{
  const h=await harness();await h.db.bindAccount('sub_fixture');
  assert.equal((await h.db.pending('sub_fixture')).length,1);
  await h.db.setCursor('sub_fixture',17);
  assert.equal(await h.db.clearDeletedAccount('sub_fixture'),true);
  for(const name of ['entries','records','outbox'])assert.equal(h.indexedDB.stores.get(name).size,0);
  assert.equal(h.indexedDB.stores.get('meta').has('sync-owner'),false);
  assert.equal(h.indexedDB.stores.get('meta').has('since:sub_fixture'),false);
  assert.equal(h.indexedDB.stores.get('meta').get('deleted:sub_fixture'),true);
  assert.equal(h.native.getItem('storymemory.userMemories.v1'),null);
  assert.equal(h.native.getItem('unrelated.preference'),'keep');
  h.root.BookAIStorage.setItem('storymemory.userMemories.v1','[{"id":"resurrect"}]');
  await h.db.flush();assert.equal(h.indexedDB.stores.get('entries').size,0,'retired reader memory cannot write back');
});

test('guest or another bound account is preserved without a cleanup transaction',async()=>{
  const h=await harness();
  assert.equal(await h.db.clearDeletedAccount('sub_fixture'),false);
  await h.db.bindAccount('sub_other');
  assert.equal(await h.db.clearDeletedAccount('sub_fixture'),false);
  assert.equal((await h.db.pending('sub_other')).length,1);
  assert.notEqual(h.native.getItem('storymemory.userMemories.v1'),null);
});

test('stale tabs cannot recreate deleted records and a fresh account receives an empty store',async()=>{
  const first=await harness();await first.db.bindAccount('sub_fixture');
  const stale=await harness(first.indexedDB,first.native);
  await first.db.clearDeletedAccount('sub_fixture');
  stale.root.BookAIStorage.setItem('storymemory.userMemories.v1','[{"id":"note","note":"stale"}]');
  await assert.rejects(stale.db.flush(),/transaction_aborted/);
  assert.equal(first.indexedDB.stores.get('entries').size,0);
  await assert.rejects(stale.db.bindAccount('sub_fixture'),/account_deleted/);
  const fresh=await harness(first.indexedDB,first.native);await fresh.db.bindAccount('sub_new');
  assert.equal((await fresh.db.pending('sub_new')).length,0);
  assert.equal(fresh.root.BookAIStorage.getItem('storymemory.userMemories.v1'),null);
});

test('stale remote merge rolls back after the deletion marker',async()=>{
  const first=await harness();await first.db.bindAccount('sub_fixture');
  const stale=await harness(first.indexedDB,first.native);
  const records=await stale.db.pending('sub_fixture');records[0].updated_at+=10;
  await first.db.clearDeletedAccount('sub_fixture');
  await assert.rejects(stale.db.merge('sub_fixture',records),/transaction_aborted/);
  assert.equal(first.indexedDB.stores.get('entries').size,0);
});
