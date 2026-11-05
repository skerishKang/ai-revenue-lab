const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');

const publicDir=path.join(__dirname,'../public');
const SHARDS=[{path:'shard-01.json'},{path:'shard-02.json'},{path:'shard-03.json'}];

function makeEl(id){
  return {
    id,hidden:false,open:false,disabled:false,textContent:'',children:[],parentElement:null,isConnected:true,
    addEventListener(){},append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},
    remove(){this.isConnected=false},insertBefore(){},setAttribute(){},getAttribute(){return null},
    querySelector(){return null},querySelectorAll(){return []}
  };
}

function createHarness(opts={}){
  const state={
    passageVisible:!!opts.passageVisible,idleCalls:[],timers:[],warns:[],manifestFetches:0,shardFetches:0,
    activeShardFetches:0,maxActiveShardFetches:0,rangeCalls:[],primedBlocks:null,observers:[]
  };
  const els={};
  ['bibleSearchPanel','bibleSearchForm','bibleSearchInput','bibleSearchSubmit','bibleSearchCancel','bibleSearchRetry','bibleSearchStatus','bibleSearchResults','bibleSearchReturn']
    .forEach(id=>{els[id]=makeEl(id);});
  els.bibleSearchResults.parentElement=makeEl('ol-parent');
  const document={
    hidden:!!opts.documentHidden,
    getElementById(id){return els[id]||null;},
    createElement(tag){return makeEl(tag);},
    querySelector(selector){return selector==='#readerPageBody .sm-source-passage'&&state.passageVisible?makeEl('p'):null;},
    querySelectorAll(){return [];}
  };
  function MutationObserverStub(callback){this.callback=callback;this.observed=false;this.disconnected=false;state.observers.push(this);}
  MutationObserverStub.prototype.observe=function(){this.observed=true;};
  MutationObserverStub.prototype.disconnect=function(){this.disconnected=true;};
  const ctx={
    console:{warn(...args){state.warns.push(args.map(String).join(' '));},error(){},log(){}},
    navigator:{connection:{saveData:!!opts.saveData,effectiveType:opts.effectiveType||'4g'}},
    document,
    MutationObserver:MutationObserverStub,
    requestIdleCallback(fn,options){
      if(opts.idleThrows)throw new TypeError("Failed to execute 'requestIdleCallback': The provided value is not of type 'IdleRequestOptions'.");
      state.idleCalls.push({fn,options});
      return state.idleCalls.length;
    },
    setTimeout(fn,delay){state.timers.push({fn,delay:Number(delay)||0});return state.timers.length;},
    clearTimeout(){},
    AbortController,DOMException,Promise,Map,Set,WeakMap,
    async fetch(url){
      if(String(url).includes('search-index/manifest.json')){
        state.manifestFetches++;
        return {ok:true,async json(){return {schema_version:'storymemory-bible-search-index-1',shards:SHARDS};}};
      }
      if(String(url).includes('search-index/shard-')){
        state.shardFetches++;state.activeShardFetches++;
        state.maxActiveShardFetches=Math.max(state.maxActiveShardFetches,state.activeShardFetches);
        await new Promise(resolve=>setImmediate(resolve));
        state.activeShardFetches--;
        return {ok:true,async json(){return {schema_version:1,units:[['GEN',1,1,'GEN 1',1,[[1,'','태초에 하나님이 천지를 창조하시니라','In the beginning God created',null]]]]};}};
      }
      throw new Error('UNEXPECTED_FETCH:'+url);
    }
  };
  ctx.window=ctx;
  ctx.storyMemoryBibleReferenceV1={};
  ctx.__smLocatorResolverV1={bookAliases:{},chapterCounts:{}};
  if(opts.noPrefetch)ctx.__smBibleSearchNoPrefetch=true;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(publicDir,'storymemory-keyword-search-v1.js'),'utf8'),ctx);
  vm.runInContext(fs.readFileSync(path.join(publicDir,'storymemory-bible-search-v1.js'),'utf8'),ctx);
  const keywordApi=ctx.__smStaticKeywordSearchV1;
  const originalRange=keywordApi.indexBlocksRange;
  keywordApi.indexBlocksRange=function(blocks,postings,start,end){
    state.rangeCalls.push({start,end,count:end-start});
    return originalRange(blocks,postings,start,end);
  };
  const originalPrime=keywordApi.primeLexicalIndex;
  keywordApi.primeLexicalIndex=function(blocks,postings){
    state.primedBlocks=blocks;
    return originalPrime(blocks,postings);
  };
  return {state,ctx,els,keywordApi};
}

async function flush(rounds=40){
  for(let i=0;i<rounds;i++)await new Promise(resolve=>setImmediate(resolve));
}

async function pumpIdle(harness,limit=20){
  let index=0;
  while(index<harness.state.idleCalls.length&&index<limit){
    const call=harness.state.idleCalls[index++];
    call.fn();
    await flush(10);
  }
}

test('prefetch waits for the first reader passage, then schedules idle with an options object',async()=>{
  const harness=createHarness({passageVisible:false});
  const {state}=harness;
  assert.equal(state.idleCalls.length,0,'no idle work before the reader renders');
  assert.equal(state.timers.length,0,'no delayed prefetch before the reader renders');
  assert.equal(state.observers.length,1,'a render observer is armed');

  state.passageVisible=true;
  state.observers[0].callback();
  assert.equal(state.timers.length,1,'one delayed prefetch after the first render');
  assert.equal(state.timers[0].delay,3000,'the delay is three seconds');
  assert.equal(harness.ctx.storyMemoryBibleSearchV1.prefetchState().scheduled,true);

  state.timers[0].fn();
  assert.equal(state.idleCalls.length,1,'prefetch uses idle time after the delay');
  assert.equal(typeof state.idleCalls[0].options,'object','requestIdleCallback must receive options');
  assert.equal(typeof state.idleCalls[0].options.timeout,'number');
  assert.ok(state.idleCalls[0].options.timeout>0);

  state.idleCalls[0].fn();
  await flush();
  assert.equal(state.manifestFetches,1,'the index manifest is fetched once');
  assert.equal(state.shardFetches,SHARDS.length,'every shard is prefetched');
  assert.equal(state.maxActiveShardFetches,1,'prefetch keeps one shard request in flight');

  await pumpIdle(harness);
  assert.ok(state.primedBlocks&&state.primedBlocks.length===SHARDS.length,'the prefetched blocks are indexed');
  assert.equal(harness.keywordApi.hasCachedIndex(state.primedBlocks),true,'the prefetched index is primed');
  assert.ok(state.rangeCalls.length>=1,'index work is chunked');
  for(const call of state.rangeCalls)assert.ok(call.count<=800,'index chunks stay small: '+JSON.stringify(call));

  const rangeBefore=state.rangeCalls.length;
  const result=harness.keywordApi.staticKeywordSearch('태초에',{workKey:'bible-web',blocks:state.primedBlocks,limit:10});
  assert.equal(result.results.length,SHARDS.length,'the primed index serves search results');
  assert.equal(state.rangeCalls.length,rangeBefore,'the first search reuses the primed index');
});

test('a scheduling failure is reported and falls back to a timer',async()=>{
  const harness=createHarness({passageVisible:true,idleThrows:true});
  const {state}=harness;
  assert.equal(state.timers.length,1,'the three second delay is scheduled');
  state.timers[0].fn();
  assert.ok(state.warns.some(message=>message.includes('requestIdleCallback')),'the failure is logged: '+JSON.stringify(state.warns));
  assert.equal(state.timers.length,2,'scheduling falls back to a timer');
  assert.equal(state.timers[1].delay,3000);
  state.timers[1].fn();
  await flush();
  assert.equal(state.manifestFetches,1,'the fallback still starts the prefetch');
});

test('prefetch is skipped for the opt-out hook, save data and 2g',async()=>{
  for(const opts of [{noPrefetch:true},{saveData:true},{effectiveType:'2g'},{documentHidden:true}]){
    const harness=createHarness({passageVisible:true,...opts});
    assert.equal(harness.state.timers.length,0,'no prefetch timer for '+JSON.stringify(opts));
    assert.equal(harness.state.idleCalls.length,0,'no idle work for '+JSON.stringify(opts));
  }
});
