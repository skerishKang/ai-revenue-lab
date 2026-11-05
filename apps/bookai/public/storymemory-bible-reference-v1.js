/* B61 #6474: Parse and validate a human-entered Bible reference without advancing reading progress. */
(function(root){
'use strict';
  function normalizeFullwidth(q){
    return String(q||'').replace(/[０-９]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0xFEE0)}).replace(/：/g,':').replace(/／/g,'/');
  }
  function lookupBook(name,aliases,chapterCounts){
    var norm=String(name||'').replace(/\s+/g,'').toLowerCase(), code=null, count=0;
    var al=aliases||{};
    for(var key in al){
      if(!Object.prototype.hasOwnProperty.call(al,key)||key.replace(/\s+/g,'').toLowerCase()!==norm)continue;
      var value=al[key];
      if(Array.isArray(value)){if(value.length!==1)return{error:'ambiguous_book'};code=value[0];}
      else code=value;
      count=Number(chapterCounts&&((chapterCounts[code])||chapterCounts[key]))||0;
      break;
    }
    if(!code)return{error:'unknown_book'};
    return{code:code,count:count};
  }
  function parseReference(input, bookAliases, chapterCounts){
    var q=normalizeFullwidth(String(input||'').trim().replace(/[\u3000\s]+/g,' '));
    var rangeEnd=null, rangeEndChapter=null, isRange=false;
    var rangeSplit=q.split('-');
    // Range split: only when trailing part has numbers
    if(rangeSplit.length===2){
      var leftM=rangeSplit[0].match(/^(.+?)\s*(\d{1,3})(?:\s*장(?:\s*(\d{1,3})\s*절?)?|:\s*(\d{1,3})\s*절?)?$/);
      var rightM=rangeSplit[1].trim().match(/^(\d{1,3})(?:\s*장(?:\s*(\d{1,3})\s*절?)?|:\s*(\d{1,3})\s*절?)?$/);
      if(leftM&&rightM&&rightM[1]){
        isRange=true;
        if(rightM[2]!=null){rangeEndChapter=Number(rightM[1]);rangeEnd=Number(rightM[2]);}
        else if(rightM[3]!=null){rangeEndChapter=Number(rightM[1]);rangeEnd=Number(rightM[3]);}
        else {rangeEnd=Number(rightM[1]);}
      }
    }
    var working=isRange?rangeSplit[0]:q;
    var m=working.match(/^(.+?)\s*(\d{1,3})\s*(?:편|장)?(?:(?:\s*장|\s*:)?(?:\s*(\d{1,3})\s*절?)?)$/);
    if(!m){
      var m2=working.match(/^(.+?)\s*(\d{1,3})\s+(\d{1,3})\s*절?$/);
      if(m2)m=m2;
    }
    if(!m){
      var spaced=working.match(/^(.+?)\s*(\d{1,3})\s+(.+)\s*$/);
      if(spaced){
        var bv=lookupBook(spaced[1],bookAliases,chapterCounts);
        if(bv.code&&bv.count===1){
          var v2=Number(spaced[3]);
          if(!isNaN(v2)&&v2>=1){
            var uk='book:'+bv.code+':chapter:001';
            return{ok:true,book:bv.code,chapter:1,verse:v2,kind:'passage',unitKey:uk,locator:'bible:web:'+bv.code+':1:'+v2};
          }
        }
      }
      // Single-chapter books: book + verse abbreviation alone (e.g. 옵 1, 몬 1:1, 유 1:1, 요이 1, 요삼 1)
      var sc=working.match(/^(.+?)\s*(\d{1,3})\s*절?$/)||working.match(/^(.+?)\s*(\d{1,3})\s*$/);
      if(sc){
        var lb=lookupBook(sc[1],bookAliases,chapterCounts);
        if(lb.error)return{ok:false,error:lb.error};
        if(lb.count===1){
          var v=Number(sc[2]);
          if(v<1)return{ok:false,error:'invalid_verse',book:lb.code,chapter:1,verse:v};
          var uk='book:'+lb.code+':chapter:001';
          return{ok:true,book:lb.code,chapter:1,verse:v,kind:'passage',unitKey:uk,locator:'bible:web:'+lb.code+':1:'+v};
        }
      }
      return{ok:false,error:'invalid_format'};
    }
    var name=m[1].replace(/\s+/g,'').toLowerCase();
    var found=lookupBook(name,bookAliases,chapterCounts);
    if(found.error)return{ok:false,error:found.error};
    var code=found.code, count=found.count;
    var chapter=Number(m[2]), verse=m[3]!=null?Number(m[3]):null;
    if(chapter<1||!count||chapter>count)return{ok:false,error:'invalid_chapter',book:code,chapter:chapter};
    if(verse!==null&&verse<1)return{ok:false,error:'invalid_verse',book:code,chapter:chapter,verse:verse};
    var unitKey='book:'+code+':chapter:'+String(chapter).padStart(3,'0');
    var out={ok:true,book:code,chapter:chapter,verse:verse,kind:verse===null?'chapter':'passage',unitKey:unitKey,locator:verse===null?unitKey:'bible:web:'+code+':'+chapter+':'+verse};
    if(isRange){
      out.isRange=true;
      out.rangeLabel=code+':'+chapter+':'+verse+'-'+(rangeEndChapter!=null&&rangeEndChapter!==chapter?(rangeEndChapter+':'+rangeEnd):(chapter+':'+rangeEnd));
      out.rangeStart=verse; out.rangeEnd=rangeEnd; out.rangeEndChapter=rangeEndChapter;
    }
    return out;
  }
  function matchPassage(parsed,unit){
    if(!parsed||!parsed.ok||parsed.verse===null||!unit||!Array.isArray(unit.passages))return null;
    var rawTarget={book:parsed.book,chapter:parsed.chapter,verse:parsed.verse};
    // KRV number priority: match raw_locator first so KRV-typed verses (2CO 13:13 etc.) reach the right WEB row
    var rawHit=null, canonHit=null;
    for(var i=0;i<unit.passages.length;i++){
      var p=unit.passages[i];
      if(!p)continue;
      if(p.canonical_locator===parsed.locator&&!canonHit)canonHit=p;
      var raw=p.raw_locator;
      if(Array.isArray(raw)){
        for(var j=0;j<raw.length;j++){
          var r=raw[j];
          if(r&&r.book===rawTarget.book&&Number(r.chapter)===rawTarget.chapter&&Number(r.verse)===rawTarget.verse){rawHit=p;break;}
        }
      }else if(raw&&raw.book===rawTarget.book&&Number(raw.chapter)===rawTarget.chapter&&Number(raw.verse)===rawTarget.verse){rawHit=p;}
      if(rawHit)break;
    }
    if(rawHit)return rawHit;
    return canonHit||null;
  }
  function krvLabelOf(passage,fallbackCode){
    if(!passage)return null;
    var raw=passage.raw_locator;
    var r=Array.isArray(raw)?raw[0]:(raw||null);
    if(r&&r.verse!=null)return{book:r.book,chapter:r.chapter,verse:r.verse};
    var loc=String(passage.canonical_locator||'').split(':');
    if(loc[0]==='bible'&&loc.length>=5)return{book:loc[2],chapter:Number(loc[3]),verse:Number(loc[4])};
    return fallbackCode?{book:fallbackCode,chapter:passage.locator?Number(passage.locator.chapter):null,verse:passage.locator?Number(passage.locator.verse):null}:null;
  }
  var api={parseReference:parseReference,matchPassage:matchPassage,krvLabelOf:krvLabelOf,normalizeFullwidth:normalizeFullwidth};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
if(root)root.storyMemoryBibleReferenceV1=api;
})(typeof window==='undefined'?null:window);
