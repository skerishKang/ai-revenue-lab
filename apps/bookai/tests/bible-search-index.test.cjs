const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const zlib=require('node:zlib');
const keyword=require('../public/storymemory-keyword-search-v1.js');
const {compressSizes}=require('../scripts/build-bible-search-index.cjs');

const appRoot=path.resolve(__dirname,'..');
const contentRoot=path.join(appRoot,'public','content');
const bibleRoot=path.join(contentRoot,'bible-web');
const indexRoot=path.join(bibleRoot,'search-index');
const sourceManifest=JSON.parse(fs.readFileSync(path.join(bibleRoot,'manifest.json'),'utf8'));
const indexManifest=JSON.parse(fs.readFileSync(path.join(indexRoot,'manifest.json'),'utf8'));
const fullBlocks=keyword.loadUnitsSync('bible-web',contentRoot);
const indexBlocks=[];

assert.equal(indexManifest.schema_version,'storymemory-bible-search-index-1');
assert.equal(indexManifest.source_unit_count,sourceManifest.unit_count);
assert.equal(indexManifest.passage_count,sourceManifest.passage_count);
for(const shardEntry of indexManifest.shards){
  const shard=JSON.parse(fs.readFileSync(path.join(indexRoot,shardEntry.path),'utf8'));
  assert.equal(shard.schema_version,1);
  for(const [code,chapter,unitOrdinal,unitLabel,firstSequence,rows] of shard.units){
    const unitKey='book:'+code+':chapter:'+String(chapter).padStart(3,'0');
    rows.forEach(([verse,sectionTitle,ko,en,extra],i)=>{
      const sequence=firstSequence+i;
      const locator='bible:web:'+code+':'+chapter+':'+verse;
      indexBlocks.push({
        canonical_locator:locator,work_key:'bible-web',unit_key:unitKey,unit_ordinal:unitOrdinal,
        sequence:sequence,ordinal:sequence,locator:locator,
        title:String(((sectionTitle||'')+' '+unitLabel+' bible-web').trim()),
        text:ko||en,sourceText:en||ko,ko:ko,en:en,
        raw_texts:extra?extra[0]:[ko],
        raw_locator:extra?extra[1]:[{book:code,chapter:chapter,verse:verse}],
        mapping_type:extra?extra[2]:'normal',mapping_note:extra?extra[3]:null
      });
    });
  }
}
assert.equal(indexBlocks.length,fullBlocks.length);
const fields=['canonical_locator','work_key','unit_key','unit_ordinal','sequence','ordinal','locator','title','text','sourceText','ko','en','raw_texts','raw_locator','mapping_type','mapping_note'];
for(let i=0;i<fullBlocks.length;i++){
  const expected=Object.fromEntries(fields.map(key=>[key,fullBlocks[i][key]]));
  const actual=Object.fromEntries(fields.map(key=>[key,indexBlocks[i][key]]));
  assert.deepEqual(actual,expected,'packed index row differs from source at '+fullBlocks[i].canonical_locator);
}

const queries=['태초에','여호와','사랑','예수','믿음','바울','이스라엘','홍해','In the beginning','Jesus Christ'];
for(const query of queries){
  const baseline=keyword.staticKeywordSearch(query,{workKey:'bible-web',blocks:fullBlocks,limit:8});
  const indexed=keyword.staticKeywordSearch(query,{workKey:'bible-web',blocks:indexBlocks,limit:8});
  assert.deepEqual(indexed,baseline,'index search must match full-corpus search for '+query);
}

function gzipSize(text){return zlib.gzipSync(Buffer.from(text),{level:9}).length;}
function assetSizes(root,relativePaths){
  const total={raw_bytes:0,gzip_bytes:0};
  for(const relativePath of relativePaths){
    const text=fs.readFileSync(path.join(root,relativePath),'utf8');
    total.raw_bytes+=Buffer.byteLength(text);total.gzip_bytes+=gzipSize(text);
  }
  return total;
}
const oldAssets=['manifest.json',...sourceManifest.units.map(unit=>unit.path)];
const newAssets=['manifest.json',...indexManifest.shards.map(shard=>shard.path)];
const before=assetSizes(bibleRoot,oldAssets);
const after=assetSizes(indexRoot,newAssets);
assert.ok(after.gzip_bytes<=3_000_000,'gzip index transfer exceeds 3 MB: '+after.gzip_bytes);
for(const [index,shard] of indexManifest.shards.entries()){
  const text=fs.readFileSync(path.join(indexRoot,shard.path),'utf8');
  assert.equal(gzipSize(text),shard.gzip_bytes,'gzip size metadata differs for '+shard.path);
  // The large Brotli recompression runs once as a sample; gzip is the transfer gate.
  if(index===0){
    const actual=compressSizes(text);
    assert.equal(actual.brotli_bytes,shard.brotli_bytes,'Brotli size metadata differs for '+shard.path);
  }
}
console.log('PASS packed records match all '+fullBlocks.length.toLocaleString()+' source passages');
console.log('PASS full-corpus search results match for '+queries.length+' sample queries: '+queries.join(', '));
console.log('TRANSFER '+JSON.stringify({before,after}));
