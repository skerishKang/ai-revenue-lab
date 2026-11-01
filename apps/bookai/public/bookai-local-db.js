/* IndexedDB is the reader's durable store. A hydrated synchronous adapter keeps
   the existing reader's startup and editing functions ordered; writes and their
   COM2 outbox records commit in the same IndexedDB transaction. */
(function (root) {
  'use strict';
  const NAME='bookai-local-v1', STORE='entries', META='meta', RECORDS='records', OUTBOX='outbox';
  const MARKER='legacy-localstorage-migrated-v1';
  const allowed=key=>key.startsWith('storymemory.') &&
    !/^storymemory\.(authBridgeState|installationId|syncState|syncTombstones)\./.test(key);
  let persisted=new Map(), writes=[], applyingRemote=false;
  let connection, cache, recordMap=new Map(), owner='', tail=Promise.resolve(), failure=null, native;
  function open() {
    return new Promise((resolve,reject)=>{
      const request=indexedDB.open(NAME,2);
      request.onupgradeneeded=()=>{
        for(const name of [STORE,META,RECORDS,OUTBOX])
          if(!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
      };
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>reject(request.error);
      request.onblocked=()=>reject(new Error('indexeddb_blocked'));
    });
  }
  function complete(tx) {
    return new Promise((resolve,reject)=>{
      tx.oncomplete=resolve;
      tx.onabort=tx.onerror=()=>reject(tx.error||new Error('indexeddb_failed'));
    });
  }
  function status(error) {
    root.dispatchEvent(new CustomEvent('bookai-storage-status',{detail:{error:error?String(error.message||error):null,pending:writes.length>0}}));
  }
  function enqueue(task, durable=false) {
    const result=tail.then(task);
    tail=result.catch(error=>{if(durable){failure=error;status(error);}});
    return result;
  }
  async function flush() { await tail; if(failure)throw failure; }
  async function migrate(storage) {
    const db=await open();
    try {
      const entries=[];
      for(let i=0;i<storage.length;i++){
        const key=storage.key(i);
        if(key&&allowed(key))entries.push([key,storage.getItem(key)]);
      }
      const tx=db.transaction([STORE,META],'readwrite'),done=complete(tx);
      const marker=tx.objectStore(META).get(MARKER);
      let conflict=false,migrated=false;
      marker.onsuccess=()=>{
        if(marker.result)return;
        migrated=true;
        const store=tx.objectStore(STORE);
        for(const [key,value] of entries) {
          if(value===null)continue;
          const check=store.get(key);
          check.onsuccess=()=>{
            if(check.result===undefined)store.put(value,key);
            else if(check.result!==value){conflict=true;tx.abort();}
          };
        }
        tx.objectStore(META).put({count:entries.length},MARKER);
      };
      try{await done;}catch(error){if(conflict)throw new Error('migration_conflict');throw error;}
      return {preserved:entries.length,migrated};
    }finally{db.close();}
  }
  async function get(key) {
    const db=await open();
    try {
      const tx=db.transaction(STORE,'readonly'),done=complete(tx),req=tx.objectStore(STORE).get(key);
      await done;return req.result===undefined?null:req.result;
    }finally{db.close();}
  }
  async function set(key,value) {
    if(!allowed(key)||typeof value!=='string')throw new Error('invalid_entry');
    if(cache){storage.setItem(key,value);return flush();}
    const db=await open();
    try{const tx=db.transaction(STORE,'readwrite'),done=complete(tx);tx.objectStore(STORE).put(value,key);await done;}
    finally{db.close();}
  }
  async function readMap(store) {
    const tx=connection.transaction(store,'readonly'),done=complete(tx);
    const keys=tx.objectStore(store).getAllKeys(),values=tx.objectStore(store).getAll();
    await done;return new Map(keys.result.map((key,i)=>[key,values.result[i]]));
  }
  async function localWrite(write) {
    const {key,before,after}=write;
    const previous=new Map((await root.BookAIRecords.records(key,before)).map(r=>[r.record_id,r]));
    const next=new Map((await root.BookAIRecords.records(key,after)).map(r=>[r.record_id,r]));
    const changes=[];
    for(const [id,record] of next) {
      const prior=previous.get(id),stored=recordMap.get(id);
      if(prior&&JSON.stringify(prior.payload)===JSON.stringify(record.payload)&&stored&&!stored.deleted)continue;
      record.updated_at=Math.max(Date.now(),record.updated_at,(stored?.updated_at||0)+1);
      changes.push(record);
    }
    for(const [id,record] of previous)if(!next.has(id)) {
      const stored=recordMap.get(id);
      changes.push({...record,deleted:true,updated_at:Math.max(Date.now(),(stored?.updated_at||0)+1)});
    }
    const tx=connection.transaction([STORE,RECORDS,OUTBOX],'readwrite'),done=complete(tx);
    const nextEntries=new Map(persisted);
    root.BookAIRecords.patch(nextEntries,key,before,after);
    for(const [k,value] of nextEntries)if(persisted.get(k)!==value)tx.objectStore(STORE).put(value,k);
    for(const k of persisted.keys())if(!nextEntries.has(k))tx.objectStore(STORE).delete(k);
    for(const record of changes){
      tx.objectStore(RECORDS).put(record,record.record_id);
      tx.objectStore(OUTBOX).put(record,record.record_id);
    }
    await done;
    persisted=nextEntries;writes=writes.filter(w=>w!==write);rebuildCache();
    for(const record of changes)recordMap.set(record.record_id,record);
    status(null);
    if(changes.length)root.dispatchEvent(new CustomEvent('bookai-storage-change'));
  }
  function rebuildCache(){
    cache=new Map(persisted);
    for(const write of writes)root.BookAIRecords.patch(cache,write.key,write.before,write.after);
  }
  const storage={
    get length(){return cache.size+Array.from({length:native.length},(_,i)=>native.key(i)).filter(k=>!allowed(k)).length;},
    key(index){return [...cache.keys(),...Array.from({length:native.length},(_,i)=>native.key(i)).filter(k=>!allowed(k))][index]??null;},
    getItem(key){key=String(key);return allowed(key)?(cache.get(key)??null):native.getItem(key);},
    setItem(key,value){
      key=String(key);value=String(value);
      if(applyingRemote)return;
      if(!allowed(key)){native.setItem(key,value);return;}
      if(failure)throw failure;
      const before=cache.get(key)??null;
      if(before===value)return;
      cache.set(key,value);
      const write={key,before,after:value};writes.push(write);
      enqueue(()=>localWrite(write),true).catch(()=>{});
    },
    removeItem(key){
      key=String(key);
      if(!allowed(key)){native.removeItem(key);return;}
      if(failure)throw failure;
      const before=cache.get(key)??null;
      if(before===null)return;
      cache.delete(key);
      const write={key,before,after:null};writes.push(write);
      enqueue(()=>localWrite(write),true).catch(()=>{});
    },
    clear(){for(const key of [...cache.keys()])this.removeItem(key);}
  };
  async function init(storageSource=root.localStorage) {
    native=storageSource;
    const migration=await migrate(native);
    connection=await open();
    connection.onversionchange=()=>connection.close();
    cache=await readMap(STORE);persisted=new Map(cache);recordMap=await readMap(RECORDS);
    const meta=await readMap(META);owner=meta.get('sync-owner')||'';
    // Seed migrated records once without editing their original stored bytes.
    const seed=[];
    for(const [key,value] of cache)for(const record of await root.BookAIRecords.records(key,value)){
      if(!recordMap.has(record.record_id)){
        record.updated_at=record.updated_at||Date.now();seed.push(record);
      }
    }
    const tx=connection.transaction([RECORDS,OUTBOX],'readwrite'),done=complete(tx);
    for(const record of seed){tx.objectStore(RECORDS).put(record,record.record_id);tx.objectStore(OUTBOX).put(record,record.record_id);}
    await done;for(const record of seed)recordMap.set(record.record_id,record);
    root.BookAIStorage=Object.freeze(storage);
    return migration;
  }
  function checkAccount(account){if(!account||owner!==account)throw new Error('account_mismatch');}
  async function bindAccount(account) {
    return enqueue(async()=>{
      if(typeof account!=='string'||!account)throw new Error('invalid_account');
      if(owner&&owner!==account)throw new Error('account_mismatch');
      if(!owner){const tx=connection.transaction(META,'readwrite'),done=complete(tx);tx.objectStore(META).put(account,'sync-owner');await done;owner=account;}
    });
  }
  async function pending(account){await flush();checkAccount(account);return [...(await readMap(OUTBOX)).values()];}
  async function acknowledge(account,records) {
    return enqueue(async()=>{
      checkAccount(account);
      const tx=connection.transaction(OUTBOX,'readwrite'),done=complete(tx),store=tx.objectStore(OUTBOX);
      for(const record of records){
        const req=store.get(record.record_id);
        req.onsuccess=()=>{if(req.result?.updated_at===record.updated_at)store.delete(record.record_id);};
      }
      await done;
    });
  }
  async function merge(account,records) {
    return enqueue(async()=>{
      checkAccount(account);
      const changed=[];
      for(const record of records){
        if(!root.BookAIRecords.valid(record))throw new Error('invalid_bookai_record');
        const old=recordMap.get(record.record_id);
        if(!old||record.updated_at>old.updated_at)changed.push(record);
      }
      if(!changed.length)return;
      const next=new Map(persisted);
      for(const record of changed)root.BookAIRecords.apply(record,next);
      const tx=connection.transaction([STORE,RECORDS,OUTBOX],'readwrite'),done=complete(tx);
      for(const [key,value] of next)if(persisted.get(key)!==value)tx.objectStore(STORE).put(value,key);
      for(const key of persisted.keys())if(!next.has(key))tx.objectStore(STORE).delete(key);
      for(const record of changed){tx.objectStore(RECORDS).put(record,record.record_id);tx.objectStore(OUTBOX).delete(record.record_id);}
      await done;persisted=next;rebuildCache();
      for(const record of changed)recordMap.set(record.record_id,record);
      applyingRemote=true;
      try{root.dispatchEvent(new CustomEvent('bookai-storage-remote',{detail:{keys:[...new Set(changed.map(r=>r.payload._bookai.key))]}}));}finally{applyingRemote=false;}
    });
  }
  async function cursor(account){await flush();checkAccount(account);return (await readMap(META)).get('since:'+account)||0;}
  async function setCursor(account,value){
    return enqueue(async()=>{
      checkAccount(account);
      if(!Number.isSafeInteger(value)||value<0)throw new Error('invalid_cursor');
      const tx=connection.transaction(META,'readwrite'),done=complete(tx);
      tx.objectStore(META).put(value,'since:'+account);await done;
    });
  }
  root.BookAILocalDB=Object.freeze({migrate,get,set,init,flush,bindAccount,pending,acknowledge,merge,cursor,setCursor});
})(window);
