/* B61 #6474: Parse and validate a human-entered Bible reference without advancing reading progress. */
(function(root){
'use strict';
function parseReference(input, bookAliases, chapterCounts){
  var q=String(input||'').trim().replace(/[\u3000\s]+/g,' ');
  var m=q.match(/^(.+?)\s*(\d{1,3})(?:\s*장(?:\s*(\d{1,3})\s*절?)?|:\s*(\d{1,3})\s*절?)?$/);
  if(!m)return {ok:false,error:'invalid_format'};
  var name=m[1].replace(/\s+/g,'').toLowerCase(), code=null, count=0;
  var aliases=bookAliases||{};
  for(var key in aliases){
    if(!Object.prototype.hasOwnProperty.call(aliases,key)||key.replace(/\s+/g,'').toLowerCase()!==name)continue;
    var value=aliases[key];
    if(Array.isArray(value)){if(value.length!==1)return {ok:false,error:'ambiguous_book'};code=value[0];}
    else code=value;
    count=Number(chapterCounts&&((chapterCounts[code])||chapterCounts[key]))||0;
    break;
  }
  if(!code)return {ok:false,error:'unknown_book'};
  var chapter=Number(m[2]), verse=m[3]!=null?Number(m[3]):(m[4]!=null?Number(m[4]):null);
  if(chapter<1||!count||chapter>count)return {ok:false,error:'invalid_chapter',book:code,chapter:chapter};
  if(verse!==null&&verse<1)return {ok:false,error:'invalid_verse',book:code,chapter:chapter,verse:verse};
  var unitKey='book:'+code+':chapter:'+String(chapter).padStart(3,'0');
  return {ok:true,book:code,chapter:chapter,verse:verse,kind:verse===null?'chapter':'passage',unitKey:unitKey,locator:verse===null?unitKey:'bible:web:'+code+':'+chapter+':'+verse};
}
function matchPassage(parsed,unit){
  if(!parsed||!parsed.ok||parsed.verse===null||!unit||!Array.isArray(unit.passages))return null;
  return unit.passages.find(function(p){return p&&p.canonical_locator===parsed.locator;})||null;
}
var api={parseReference:parseReference,matchPassage:matchPassage};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(root)root.storyMemoryBibleReferenceV1=api;
})(typeof window==='undefined'?null:window);
