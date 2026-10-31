/* B61 #6474: Parse and validate a human-entered Bible reference without advancing reading progress. */
(function(root){
'use strict';
function parseReference(input, bookCodes, chapterCounts){
  var q=String(input||'').trim().replace(/\s+/g,' ');
  var m=q.match(/^(.+?)\s*(\d{1,3})\s*(?:장\s*(\d{1,3})\s*절?|:\s*(\d{1,3}))$/);
  if(!m)return {ok:false,error:'invalid_format'};
  var name=m[1].replace(/\s+/g,''), code=null, count=0;
  for(var key in bookCodes){
    if(Object.prototype.hasOwnProperty.call(bookCodes,key)&&key.replace(/\s+/g,'')===name){
      code=bookCodes[key];count=Number(chapterCounts[key])||0;break;
    }
  }
  if(!code)return {ok:false,error:'unknown_book'};
  var chapter=Number(m[2]), verse=Number(m[3]||m[4]);
  if(chapter<1||chapter>count||verse<1)return {ok:false,error:'invalid_reference'};
  return {ok:true,book:code,chapter:chapter,verse:verse,locator:'bible:web:'+code+':'+chapter+':'+verse};
}
function matchPassage(parsed,unit){
  if(!parsed||!parsed.ok||!unit||!Array.isArray(unit.passages))return null;
  return unit.passages.find(function(p){return p&&p.canonical_locator===parsed.locator;})||null;
}
var api={parseReference:parseReference,matchPassage:matchPassage};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(root)root.storyMemoryBibleReferenceV1=api;
})(typeof window==='undefined'?null:window);
