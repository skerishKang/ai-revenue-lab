#!/usr/bin/env node
'use strict';

const crypto=require('node:crypto');
const fs=require('node:fs');
const path=require('node:path');
const zlib=require('node:zlib');

const appRoot=path.resolve(__dirname,'..');
const contentRoot=path.join(appRoot,'public','content','bible-web');
const DEFAULT_OUTPUT=path.join(contentRoot,'search-index');
const SHARD_COUNT=12;

function compressSizes(text){
  const input=Buffer.from(text,'utf8');
  return {bytes:input.length,gzip_bytes:zlib.gzipSync(input,{level:9}).length,brotli_bytes:zlib.brotliCompressSync(input,{params:{[zlib.constants.BROTLI_PARAM_QUALITY]:11}}).length};
}
function balancedGroups(units,count){
  const total=units.reduce((sum,unit)=>sum+(Number(unit.passage_count)||0),0);
  const target=total/count;const groups=[];let current=[];let currentCount=0;
  for(let i=0;i<units.length;i++){
    const unit=units[i];current.push(unit);currentCount+=Number(unit.passage_count)||0;
    const left=units.length-i-1;const shardsLeft=count-groups.length-1;
    if(groups.length<count-1&&currentCount>=target&&left>=shardsLeft){groups.push(current);current=[];currentCount=0;}
  }
  if(current.length)groups.push(current);
  return groups;
}
function buildIndex({sourceDir=contentRoot,outputDir=DEFAULT_OUTPUT,shardCount=SHARD_COUNT}={}){
  const sourceManifestPath=path.join(sourceDir,'manifest.json');
  const sourceText=fs.readFileSync(sourceManifestPath,'utf8');
  const sourceManifest=JSON.parse(sourceText);
  if(sourceManifest.work_key!=='bible-web'||!Array.isArray(sourceManifest.units))throw new Error('BIBLE_SOURCE_MANIFEST_INVALID');
  const groups=balancedGroups(sourceManifest.units,Math.max(1,Number(shardCount)||SHARD_COUNT));
  const outputManifest={
    schema_version:'storymemory-bible-search-index-1',
    work_key:'bible-web',
    source_manifest_sha256:crypto.createHash('sha256').update(sourceText).digest('hex'),
    source_unit_count:sourceManifest.units.length,
    passage_count:Number(sourceManifest.passage_count)||0,
    shards:[]
  };
  fs.mkdirSync(outputDir,{recursive:true});
  let fallbackOrdinal=0;
  let uncompressedTotal=0,gzipTotal=0,brotliTotal=0;
  groups.forEach((entries,index)=>{
    const packedUnits=[];let passageCount=0;
    for(const entry of entries){
      const unit=JSON.parse(fs.readFileSync(path.join(sourceDir,entry.path),'utf8'));
      const unitParts=String(unit.unit_key||entry.unit_key||'').split(':');
      const code=String(unit.book_code||unitParts[1]||'');
      const chapter=Number(unit.chapter_number||unitParts[3])||0;
      const unitOrdinal=Number(unit.unit_ordinal||entry.unit_ordinal)||0;
      const rows=[];
      for(const passage of unit.passages||[]){
        fallbackOrdinal++;
        const sequence=passage.sequence!=null?Number(passage.sequence):fallbackOrdinal;
        if(sequence!==fallbackOrdinal)throw new Error('BIBLE_SEQUENCE_NOT_CONTIGUOUS:'+passage.canonical_locator);
        const locator=String(passage.canonical_locator||'');
        if(!locator)continue;
        const verse=Number(locator.split(':').pop());
        const ko=String(passage.ko||'');const rawTexts=Array.isArray(passage.raw_texts)?passage.raw_texts:[];
        const rawLocator=passage.raw_locator||null;const defaultRawLocator=[{book:code,chapter:chapter,verse:verse}];
        const mappingType=passage.mapping_type||null;const mappingNote=passage.mapping_note||null;
        const hasExtra=JSON.stringify(rawTexts)!==JSON.stringify([ko])||JSON.stringify(rawLocator)!==JSON.stringify(defaultRawLocator)||mappingType!=='normal'||mappingNote!==null;
        rows.push([verse,String(passage.section_title||''),ko,String(passage.en||''),hasExtra?[rawTexts,rawLocator,mappingType,mappingNote]:null]);
      }
      if(rows.length){packedUnits.push([code,chapter,unitOrdinal,String(unit.unit_label||entry.label||''),fallbackOrdinal-rows.length+1,rows]);passageCount+=rows.length;}
    }
    const filename='shard-'+String(index+1).padStart(2,'0')+'.json';
    const text=JSON.stringify({schema_version:1,units:packedUnits});
    fs.writeFileSync(path.join(outputDir,filename),text,'utf8');
    const sizes=compressSizes(text);
    uncompressedTotal+=sizes.bytes;gzipTotal+=sizes.gzip_bytes;brotliTotal+=sizes.brotli_bytes;
    const firstUnit=packedUnits[0],lastUnit=packedUnits.at(-1);
    const firstRow=firstUnit?.[5]?.[0],lastRow=lastUnit?.[5]?.at(-1);
    const locator=(unit,row)=>unit&&row?'bible:web:'+unit[0]+':'+unit[1]+':'+row[0]:null;
    outputManifest.shards.push({path:filename,unit_count:packedUnits.length,passage_count:passageCount,first_locator:locator(firstUnit,firstRow),last_locator:locator(lastUnit,lastRow),...sizes});
  });
  const manifestText=JSON.stringify(outputManifest,null,2)+'\n';
  fs.writeFileSync(path.join(outputDir,'manifest.json'),manifestText,'utf8');
  const manifestSizes=compressSizes(manifestText);
  const total={
    raw_bytes:uncompressedTotal+manifestSizes.bytes,
    gzip_bytes:gzipTotal+manifestSizes.gzip_bytes,
    brotli_bytes:brotliTotal+manifestSizes.brotli_bytes,
    data_raw_bytes:uncompressedTotal,
    data_gzip_bytes:gzipTotal,
    data_brotli_bytes:brotliTotal,
    manifest:manifestSizes
  };
  return {outputDir,sourceManifestSha256:outputManifest.source_manifest_sha256,sourceUnitCount:outputManifest.source_unit_count,passageCount:outputManifest.passage_count,shardCount:groups.length,total,shards:outputManifest.shards};
}

if(require.main===module){
  try{process.stdout.write(JSON.stringify(buildIndex(),null,2)+'\n')}
  catch(error){console.error(error);process.exitCode=1}
}

module.exports={buildIndex,balancedGroups,compressSizes};
