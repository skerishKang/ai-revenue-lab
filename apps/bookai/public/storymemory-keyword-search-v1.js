/* ===== B61 #1477 · Static Keyword Search v1 ===== */
(function(){
'use strict';

var MAX_TERMS=16;
var MAX_RESULTS_DEFAULT=8;
var SNIPPET_RADIUS=48;

/* B61 #1515 one-gap repair · deterministic Korean particle-stem expansion.
   Conversational wrappers (e.g. X에 대해 알려줘) must still reach the lexical
   stem (X) deterministically. Topic-free: strips only grammatical particles,
   keeps every original term, single strip, stem length>=2. No topic rules. */
var KO_PARTICLES=['에게서','에게','에서','께서','부터','까지','처럼','같이','보다','마다','밖에','이랑','하고','랑','와','과','으로','의','에','게','께','을','를','이','가','은','는','도','만','로','님'];
var KO_ARCHAIC={'예수님':'예수','멸망하지':'멸망치','하지':'치','하게':'케','하여':'케','주님':'주','성령님':'성령','그리스도님':'그리스도','하나님께':'하나님','할지어다':'할찌어다','있을지어다':'있을찌어다','말씀하셨다':'가라사대','이르시되':'가라사대','보셨다':'보시니라'};
var EN_STOPWORDS={'in':1,'the':1,'of':1,'and':1,'a':1,'to':1,'is':1,'was':1,'for':1};
/* Topic-free conversational function words: wrappers/question words that carry
   no lexical content (about/tell-me/please/what/how). Removed from the TERM
   list only; the original query string is untouched for exact-match scoring. */
var KO_STOPWORDS={'대해':1,'대하여':1,'대해서':1,'대한':1,'관해':1,'관하여':1,'관련':1,'알려줘':1,'알려주세요':1,'알려주':1,'알려':1,'주세요':1,'말해줘':1,'말해주세요':1,'말해':1,'설명해줘':1,'설명해주세요':1,'설명해':1,'설명':1,'궁금해':1,'궁금해요':1,'궁금합니다':1,'궁금':1,'뭐야':1,'뭐예요':1,'뭔가요':1,'무엇':1,'어떻게':1,'어떤':1,'무슨':1,'왜':1,'언제':1,'어디':1,'누구':1,'해줘':1,'줘':1};
function particleStem(term){
  if(!term || term.length<3) return null;
  for(var i=0;i<KO_PARTICLES.length;i++){
    var suf=KO_PARTICLES[i];
    if(term.length> suf.length+1 && term.slice(-suf.length)===suf){
      var stem=term.slice(0, term.length-suf.length);
      if(stem.length>=2) return stem;
    }
  }
  return null;
}
function tokenize(value){
  var raw=String(value||'').toLowerCase();
  var parts=raw.match(/[a-z0-9가-힣]+/g)||[];
  for(var _i=0,_a=['개','산','섬','왕','신','빛','물','피'];_i<_a.length;_i++){ var term=_a[_i]; var re=new RegExp('(^|[\\s(])'+term+'($|[\\s?!.),])'); if(re.test(raw)) parts.push(term); }
  var seen={}; var out=[];
  for(var i=0;i<parts.length;i++){ var p=parts[i]; if(KO_STOPWORDS[p]||EN_STOPWORDS[p]) continue; if(!seen[p]){ seen[p]=1; out.push(p); if(out.length>=MAX_TERMS) break; } }
  for(var s=0;s<parts.length && out.length<MAX_TERMS;s++){ if(KO_STOPWORDS[parts[s]]||EN_STOPWORDS[parts[s]]) continue; var st=particleStem(parts[s]); if(st && !KO_STOPWORDS[st] && !seen[st]){ seen[st]=1; out.push(st); } }
  // archaic expansion
  for(var ex=0;ex<parts.length && out.length<MAX_TERMS;ex++){
    var src=parts[ex];
    for(var ak in KO_ARCHAIC){ if(!Object.prototype.hasOwnProperty.call(KO_ARCHAIC,ak))continue; if(src.indexOf(ak)===0){ var expanded=KO_ARCHAIC[ak]; if(expanded&&!seen[expanded]){ seen[expanded]=1; out.push(expanded); } break; } }
  }
  return out;
}
/* Korean writes words and particles without a space between them, so a term that
   continues straight into a grammatical particle is still a whole word. Reading
   only the raw character made every agglutinative form a mid-word hit and scored
   it below the spaced form of the same word. */
function koParticleAt(low, end){
  for(var i=0;i<KO_PARTICLES.length;i++){
    var p=KO_PARTICLES[i];
    if(low.substr(end,p.length)===p) return true;
  }
  return false;
}
/* The boundary weight answers one question per passage: is the term used here as a
   whole word? Accumulating it per occurrence let a passage that repeats the word
   outrank an earlier passage in the canon, so the strongest single occurrence is
   what classifies the passage. */
function boundaryWeight(text,term){
  var low=String(text||'').toLowerCase(); var w=null; var pos=0;
  while(true){ var idx=low.indexOf(term,pos); if(idx===-1)break;
    var before=idx>0?low[idx-1]:' ';
    var afterIdx=idx+term.length;
    var after=afterIdx<low.length?low[afterIdx]:' ';
    var boundaryBefore=/[\s(?!.,;:]/.test(before)||before===' ';
    var boundaryAfter=/[\s?!.,;:)]/.test(after)||(/[가-힣]/.test(after)&&koParticleAt(low,afterIdx));
    var occ=0;
    if(boundaryAfter)occ+=8; else if(after!==' ')occ-=4;
    if(boundaryBefore)occ+=2;
    if(w===null||occ>w)w=occ;
    pos=idx+1;
  }
  return w===null?0:w;
}

function indexBlocksRange(blocks,postings,start,end){
  var from=Math.max(0,Number(start)||0);
  var to=Math.min(blocks.length,Number(end)||blocks.length);
  for(var i=from;i<to;i++){
    var b=blocks[i];
    var combined=(String(b.title||'')+' '+String(b.text||'')+' '+String(b.sourceText||'')).toLowerCase();
    var terms=combined.match(/[a-z0-9가-힣]+/g)||[];
    for(var _j=0,_b=['개','산','섬','왕','신','빛','물','피'];_j<_b.length;_j++){ var t=_b[_j]; var re2=new RegExp('(^|[\\s(])'+t+'($|[\\s?!.),])'); if(re2.test(combined)) terms.push(t); }
    var uniq={}; for(var k=0;k<terms.length;k++) uniq[terms[k]]=1;
    for(var term in uniq){ if(!postings.has(term)) postings.set(term,new Set()); postings.get(term).add(i); }
  }
  return postings;
}
function buildLexicalIndex(blocks){
  return indexBlocksRange(blocks,new Map(),0,blocks.length);
}
var _indexCache=(typeof WeakMap!=='undefined'?new WeakMap():null);
function cachedIndex(blocks){ if(_indexCache){ var hit=_indexCache.get(blocks); if(hit)return hit; var built=buildLexicalIndex(blocks); _indexCache.set(blocks,built); return built; } return buildLexicalIndex(blocks); }
function primeLexicalIndex(blocks,postings){ if(_indexCache&&blocks&&postings)_indexCache.set(blocks,postings); return postings; }
function hasCachedIndex(blocks){ return !!(_indexCache&&blocks&&_indexCache.get(blocks)); }

function loadCatalogSync(contentRoot){
  if(typeof require==='undefined') throw new Error('FS_UNAVAILABLE');
  var fs=require('fs');
  var p=(contentRoot||'dist/content')+'/catalog.json';
  return JSON.parse(fs.readFileSync(p,'utf8'));
}
function loadManifestSync(workKey, contentRoot){
  if(typeof require==='undefined') throw new Error('FS_UNAVAILABLE');
  var fs=require('fs');
  var cat=loadCatalogSync(contentRoot);
  var entry=null; for(var i=0;i<cat.works.length;i++) if(cat.works[i].work_key===workKey) entry=cat.works[i];
  if(!entry) throw new Error('WORK_NOT_FOUND:'+workKey);
  var mp=(contentRoot||'dist/content')+'/'+entry.manifest_path;
  var man=JSON.parse(fs.readFileSync(mp,'utf8'));
  return {catalog:cat, entry:entry, manifest:man};
}
function loadUnitsSync(workKey, contentRoot){
  if(typeof require==='undefined') throw new Error('FS_UNAVAILABLE');
  var fs=require('fs');
  var loaded=loadManifestSync(workKey, contentRoot);
  var man=loaded.manifest;
  var base=(contentRoot||'dist/content')+'/'+loaded.entry.manifest_path.replace(/\/[^\/]+$/,'');
  var blocks=[];
  for(var i=0;i<man.units.length;i++){
    var u=man.units[i];
    var path=base+'/'+u.path;
    var unit=JSON.parse(fs.readFileSync(path,'utf8'));
    var passages=unit.passages||[];
    for(var j=0;j<passages.length;j++){
      var row=passages[j];
      blocks.push({
        canonical_locator: String(row.canonical_locator||''),
        work_key: workKey,
        unit_key: unit.unit_key||u.unit_key,
        unit_ordinal: unit.unit_ordinal||u.unit_ordinal,
        sequence: row.sequence!=null?Number(row.sequence): (blocks.length+1),
        ordinal: row.sequence!=null?Number(row.sequence): (blocks.length+1),
        locator: row.canonical_locator,
        title: String(((row.section_title||'')+' '+(unit.unit_label||u.label||'')+' '+workKey).trim()),
        text: String(row.ko||row.en||''),
        sourceText: String(row.en||row.ko||''),
        ko: String(row.ko||''),
        en: String(row.en||''),
        raw_texts: Array.isArray(row.raw_texts)?row.raw_texts.slice():[],
        raw_locator: row.raw_locator?JSON.parse(JSON.stringify(row.raw_locator)):null,
        mapping_type: row.mapping_type||null,
        mapping_note: row.mapping_note||null,
        raw: row,
        unit: unit,
        manifestUnit: u
      });
    }
  }
  return blocks;
}

function makeSnippet(text, query, radius){
  var r=radius||SNIPPET_RADIUS;
  if(!text) return '';
  var low=text.toLowerCase();
  var q=String(query||'').trim().toLowerCase();
  var terms=tokenize(q);
  var pos=-1; var hit='';
  for(var i=0;i<terms.length;i++){ var t=terms[i]; var p=low.indexOf(t); if(p!==-1 && (pos===-1 || p<pos)){ pos=p; hit=t; } }
  if(pos===-1 && q){ var p2=low.indexOf(q); if(p2!==-1){ pos=p2; hit=q; } }
  if(pos===-1) return text.slice(0, r*2).trim();
  var start=Math.max(0, pos - r);
  var end=Math.min(text.length, pos + hit.length + r);
  var snippet=text.slice(start,end);
  if(start>0) snippet='…'+snippet;
  if(end<text.length) snippet=snippet+'…';
  return snippet;
}

function scoreBlock(block, terms, exact){
  var bodyHay=(String(block.text||'')+' '+String(block.sourceText||'')).toLowerCase();
  var titleHay=String(block.title||'').toLowerCase();
  var score=0;
  for(var i=0;i<terms.length;i++){ var term=terms[i]; if(bodyHay.indexOf(term)!==-1){ score+=10; } else if(titleHay.indexOf(term)!==-1) score+=3; }
  if(exact && bodyHay.indexOf(exact)!==-1) score+=25; else if(exact && titleHay.indexOf(exact)!==-1) score+=5;
  // word-boundary weighting on ko (and en when latin)
  var combinedText=String(block.ko||block.text||'');
  if(/[A-Za-z]/.test(String(block.ko||''))===false && terms.length && /[a-z]/i.test(terms[0])) combinedText=String(block.en||block.sourceText||'')+' '+String(block.ko||'');
  for(var w=0;w<terms.length;w++){ score+=boundaryWeight(combinedText,terms[w]); }
  return score;
}

function detectLanguage(block, terms){
  var lowKo=String(block.ko||'').toLowerCase();
  var lowEn=String(block.en||'').toLowerCase();
  var hasKo=false, hasEn=false;
  for(var i=0;i<terms.length;i++){
    var t=terms[i];
    if(lowKo.indexOf(t)!==-1) hasKo=true;
    if(lowEn.indexOf(t)!==-1) hasEn=true;
  }
  if(hasKo && !hasEn) return 'ko';
  if(!hasKo && hasEn) return 'en';
  if(hasKo && hasEn){
    // deterministic: for bible-web prefer ko, for six-work prefer en if title/work suggests english? Keep ko first for determinism
    return 'ko';
  }
  // fallback: check query language via Hangul presence in terms
  for(var j=0;j<terms.length;j++) if(/[가-힣]/.test(terms[j])) return 'ko';
  return 'en';
}

function staticKeywordSearch(query, opts){
  opts=opts||{};
  var workKey=opts.workKey||null;
  var limit=opts.limit!=null? Number(opts.limit): MAX_RESULTS_DEFAULT;
  limit=Math.max(1, Math.min(64, limit));
  var contentRoot=opts.contentRoot||'dist/content';
  var terms=tokenize(query);
  if(!terms.length) return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0};
  var exact=String(query||'').trim().toLowerCase();
  var allBlocks=[], cacheKey=null;
  if(opts.blocks && Array.isArray(opts.blocks)){
    cacheKey=opts.blocks;
    allBlocks=opts.blocks;
    if(workKey){
      var filtered=[];
      for(var i=0;i<allBlocks.length;i++) if(String(allBlocks[i].work_key)===String(workKey)) filtered.push(allBlocks[i]);
      if(filtered.length!==allBlocks.length){allBlocks=filtered;cacheKey=filtered;}
    }
  } else if(opts.dataAdapter && typeof opts.dataAdapter.getBlocks==='function'){
    var source=opts.dataAdapter.getBlocks();
    cacheKey=source; allBlocks=source;
    if(workKey){
      var filtered2=[];
      for(var k=0;k<allBlocks.length;k++) if(String(allBlocks[k].work_key)===String(workKey)) filtered2.push(allBlocks[k]);
      if(filtered2.length!==allBlocks.length){allBlocks=filtered2;cacheKey=filtered2;}
    }
  } else {
    if(typeof require==='undefined'){
      return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0, error:'NO_BLOCKS_AND_NO_FS'};
    }
    var cat=null;
    try{ cat=loadCatalogSync(contentRoot); }catch(e){ return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0, error:String(e)}; }
    var targetWorks=[];
    if(workKey) targetWorks=[workKey];
    else { for(var i=0;i<cat.works.length;i++) targetWorks.push(cat.works[i].work_key); }
    for(var wi=0;wi<targetWorks.length;wi++){
      var wk=targetWorks[wi];
      try{ var blocks=loadUnitsSync(wk, contentRoot); allBlocks=allBlocks.concat(blocks); }catch(e){ /* skip missing work */ }
    }
  }
  if(!allBlocks.length) return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0};
  var index=cachedIndex(cacheKey||allBlocks);
  var isLatinQuery=/^[A-Za-z0-9\s]+$/.test(String(query).trim())&&/[A-Za-z]/.test(String(query));
  var candidates=new Set();
  for(var ti=0;ti<terms.length;ti++){
    var term=terms[ti];
    var direct=index.get(term);
    if(direct) direct.forEach(function(idx){ candidates.add(idx); });
    index.forEach(function(rows, indexed){
      if(indexed===term) return;
      if(indexed.indexOf(term)!==-1 || term.indexOf(indexed)!==-1) rows.forEach(function(idx){ candidates.add(idx); });
    });
  }
  if(!candidates.size){
    // substring fallback for single-char / single-term queries
    var fallbackTerm=String(query||'').trim();
    if(fallbackTerm){
      for(var fi=0;fi<allBlocks.length;fi++){
        var fbBody=String(allBlocks[fi].text||'').toLowerCase();
        var fbEn=String(allBlocks[fi].en||'').toLowerCase();
        var fbKo=String(allBlocks[fi].ko||'').toLowerCase();
        if(fbBody.indexOf(fallbackTerm.toLowerCase())!==-1||fbEn.indexOf(fallbackTerm.toLowerCase())!==-1||fbKo.indexOf(fallbackTerm.toLowerCase())!==-1)candidates.add(fi);
      }
    }
    if(!candidates.size)return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0};
  }
  var rows=[];
  candidates.forEach(function(idx){
    var block=allBlocks[idx];
    var s=scoreBlock(block, terms, exact);
    if(s>0) rows.push({block:block, score:s});
  });
  if(!rows.length) return {status:'NO_RESULT', query:query, results:[], truncated:false, total:0};
  /* ordinal is the passage sequence within the work, so for the bible it is canon
     order: equal scores must read 창세기→계시록 rather than by locator text. */
  rows.sort(function(a,b){ var d=b.score-a.score; if(d!==0) return d; d=a.block.ordinal-b.block.ordinal; if(d!==0) return d; return String(a.block.canonical_locator).localeCompare(String(b.block.canonical_locator)); });
  var total=rows.length;
  var truncated=total>limit;
  var sliced=rows.slice(0,limit);
  var results=sliced.map(function(r){
    var b=r.block;
    var snippet=isLatinQuery?makeSnippet(b.en||b.sourceText||b.text||'', query):makeSnippet(b.text||b.ko||b.en||'', query);
    var lang=detectLanguage(b, terms);
    return {
      canonical_locator: b.canonical_locator,
      work_key: b.work_key,
      unit_key: b.unit_key,
      sequence: b.sequence,
      ordinal: b.ordinal,
      title: b.title,
      snippet: snippet,
      ko: b.ko,
      en: b.en,
      raw_texts: b.raw_texts,
      raw_locator: b.raw_locator,
      mapping_type: b.mapping_type,
      mapping_note: b.mapping_note,
      language: lang,
      score: r.score,
      locator: b.canonical_locator,
      stable_internal_key: b.canonical_locator,
      display_title: b.title||b.unit_key,
      navigation_target: b.unit_key||b.canonical_locator
    };
  });
  return {status:'FOUND', query:query, results:results, truncated:truncated, total:total, limit:limit};
}

  if(typeof window!=='undefined'){
    window.__smStaticKeywordSearchV1={tokenize:tokenize, buildLexicalIndex:buildLexicalIndex, cachedIndex:cachedIndex, indexBlocksRange:indexBlocksRange, primeLexicalIndex:primeLexicalIndex, hasCachedIndex:hasCachedIndex, boundaryWeight:boundaryWeight, makeSnippet:makeSnippet, staticKeywordSearch:staticKeywordSearch, loadCatalogSync: (typeof require!=='undefined'?loadCatalogSync:null)};
  }
  if(typeof module!=='undefined' && module.exports){
    module.exports={tokenize:tokenize, buildLexicalIndex:buildLexicalIndex, cachedIndex:cachedIndex, indexBlocksRange:indexBlocksRange, primeLexicalIndex:primeLexicalIndex, hasCachedIndex:hasCachedIndex, boundaryWeight:boundaryWeight, makeSnippet:makeSnippet, staticKeywordSearch:staticKeywordSearch, loadCatalogSync: (typeof require!=='undefined'?loadCatalogSync:null), loadManifestSync: (typeof require!=='undefined'?loadManifestSync:null), loadUnitsSync: (typeof require!=='undefined'?loadUnitsSync:null)};

  }
})();
