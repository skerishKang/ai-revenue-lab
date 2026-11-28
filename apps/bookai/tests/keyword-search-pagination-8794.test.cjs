const test=require('node:test');
const assert=require('node:assert/strict');
const {staticKeywordSearch}=require('../public/storymemory-keyword-search-v1.js');

test('#8794 검색 결과를 20개씩 건너뛰어 정확히 읽는다',()=>{
  const blocks=Array.from({length:85},(_,i)=>({
    canonical_locator:'bible:web:GEN:1:'+(i+1),
    work_key:'bible-web',unit_key:'book:GEN:chapter:001',
    ordinal:i,sequence:i,title:'창세기 1장',
    text:'예수께서 말씀하셨다',ko:'예수께서 말씀하셨다',en:'Jesus spoke'
  }));
  const page=offset=>staticKeywordSearch('예수께서',{blocks,workKey:'bible-web',offset,limit:20});
  for(const [offset,count] of [[0,20],[20,20],[40,20],[60,20],[80,5]]){
    const result=page(offset);
    assert.equal(result.total,85,'전체 결과 수 유지');
    assert.equal(result.results.length,count,offset+'부터 돌려줄 결과 수');
    assert.equal(result.results[0].canonical_locator,'bible:web:GEN:1:'+(offset+1));
  }
});
