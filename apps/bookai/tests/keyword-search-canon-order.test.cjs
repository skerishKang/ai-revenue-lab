const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');

const keyword=require('../public/storymemory-keyword-search-v1.js');
const contentRoot=path.join(__dirname,'..','public','content');
const blocks=keyword.loadUnitsSync('bible-web',contentRoot);

/* Oracle for canon order, taken from the corpus manifest's own unit sequence rather
   than a second hardcoded book list, so it cannot drift with the module under test. */
const manifest=JSON.parse(fs.readFileSync(path.join(contentRoot,'bible-web','manifest.json'),'utf8'));
const unitRank=new Map();
manifest.units.forEach((unit,i)=>unitRank.set(unit.unit_key,i));
function canonRank(block){
  const m=/^bible:[^:]+:([0-9]?[A-Z]{2,3}):(\d+):(\d+)$/.exec(block.canonical_locator);
  assert.ok(m,'unparsable bible locator: '+block.canonical_locator);
  const unitKey='book:'+m[1]+':chapter:'+String(Number(m[2])).padStart(3,'0');
  assert.ok(unitRank.has(unitKey),'manifest has no unit for '+unitKey);
  return unitRank.get(unitKey)*100000+Number(m[3]);
}

function search(query){return keyword.staticKeywordSearch(query,{workKey:'bible-web',blocks,limit:8}).results}

test('the first hit for a repeated word is the earliest canonical passage, not the densest',()=>{
  assert.equal(search('빛')[0].canonical_locator,'bible:web:GEN:1:3');
  assert.equal(search('예수께서')[0].canonical_locator.split(':')[2],'MAT');
  assert.equal(search('장막')[0].canonical_locator.split(':')[2],'GEN');
});

for(const query of ['빛','예수께서','장막','여호와','태초에','믿음']){
  test('equal scores read in canon order for '+query,()=>{
    const results=search(query);
    assert.ok(results.length>1,query+' must return enough rows to order');
    for(let i=1;i<results.length;i++){
      if(results[i-1].score!==results[i].score) continue;
      assert.ok(canonRank(results[i-1])<=canonRank(results[i]),
        query+' breaks canon order: '+results[i-1].canonical_locator+' before '+results[i].canonical_locator);
    }
  });
}

test('a word carried by a Korean particle is the same whole word as the spaced form',()=>{
  assert.equal(keyword.boundaryWeight('빛이 있으라','빛'),keyword.boundaryWeight('빛 이 있으라','빛'));
  assert.ok(keyword.boundaryWeight('빛이 있으라','빛')>0,'particle form must not be scored as mid-word');
});
