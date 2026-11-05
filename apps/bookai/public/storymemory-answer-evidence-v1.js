/* B61 answer evidence display projection.
 * The plain Engine execution contract does not return grounded citation refs.
 * This product adapter therefore displays only verse locators explicitly
 * named by the answer and already present in the bounded B61 packet.
 */
(function(root){
'use strict';
var ENGLISH_BOOK_CODES={
  Genesis:'GEN',Exodus:'EXO',Leviticus:'LEV',Numbers:'NUM',Deuteronomy:'DEU',Joshua:'JOS',Judges:'JDG',Ruth:'RUT',
  '1 Samuel':'1SA','2 Samuel':'2SA','1 Kings':'1KI','2 Kings':'2KI','1 Chronicles':'1CH','2 Chronicles':'2CH',Ezra:'EZR',Nehemiah:'NEH',Esther:'EST',
  Job:'JOB',Psalms:'PSA',Psalm:'PSA',Proverbs:'PRO',Ecclesiastes:'ECC','Song of Songs':'SNG',Isaiah:'ISA',Jeremiah:'JER',Lamentations:'LAM',Ezekiel:'EZK',Daniel:'DAN',
  Hosea:'HOS',Joel:'JOL',Amos:'AMO',Obadiah:'OBA',Jonah:'JON',Micah:'MIC',Nahum:'NAM',Habakkuk:'HAB',Zephaniah:'ZEP',Haggai:'HAG',Zechariah:'ZEC',Malachi:'MAL',
  Matthew:'MAT',Mark:'MRK',Luke:'LUK',John:'JHN',Acts:'ACT',Romans:'ROM','1 Corinthians':'1CO','2 Corinthians':'2CO',Galatians:'GAL',Ephesians:'EPH',Philippians:'PHP',Colossians:'COL',
  '1 Thessalonians':'1TH','2 Thessalonians':'2TH','1 Timothy':'1TI','2 Timothy':'2TI',Titus:'TIT',Philemon:'PHM',Hebrews:'HEB',James:'JAS','1 Peter':'1PE','2 Peter':'2PE',
  '1 John':'1JN','2 John':'2JN','3 John':'3JN',Jude:'JUD',Revelation:'REV'
};
function escapeRegExp(value){return String(value).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
  function parseCitations(answer,bookCodes){
    var aliases=[];
    Object.keys(bookCodes||{}).forEach(function(name){aliases.push({name:name,code:bookCodes[name]});});
    Object.keys(ENGLISH_BOOK_CODES).forEach(function(name){aliases.push({name:name,code:ENGLISH_BOOK_CODES[name]});});
    Object.keys(bookCodes||{}).forEach(function(name){var code=bookCodes[name];if(code)aliases.push({name:code,code:code});});
    // Shared Korean 66-book abbreviations + short forms (synced with locator resolver table)
    var KO_ABBR={'창':'GEN','출':'EXO','레':'LEV','민':'NUM','신':'DEU','수':'JOS','삿':'JDG','룻':'RUT','삼상':'1SA','삼하':'2SA','왕상':'1KI','왕하':'2KI','대상':'1CH','대하':'2CH','스':'EZR','느':'NEH','에':'EST','욥':'JOB','시':'PSA','잠':'PRO','전':'ECC','아':'SNG','사':'ISA','렘':'JER','애':'LAM','겔':'EZK','단':'DAN','호':'HOS','욜':'JOL','암':'AMO','옵':'OBA','욘':'JON','미':'MIC','나':'NAM','합':'HAB','습':'ZEP','학':'HAG','슥':'ZEC','말':'MAL','마':'MAT','막':'MRK','눅':'LUK','요':'JHN','행':'ACT','롬':'ROM','고전':'1CO','고후':'2CO','갈':'GAL','엡':'EPH','빌':'PHP','골':'COL','살전':'1TH','살후':'2TH','딤전':'1TI','딤후':'2TI','딛':'TIT','몬':'PHM','히':'HEB','약':'JAS','벧전':'1PE','벧후':'2PE','요일':'1JN','요이':'2JN','요삼':'3JN','유':'JUD','계':'REV','시편':'PSA','마태':'MAT','마가':'MRK','누가':'LUK','요한':'JHN','사도':'ACT'};
    Object.keys(KO_ABBR).forEach(function(name){aliases.push({name:name,code:KO_ABBR[name]});});
    var unique={};
    aliases=aliases.filter(function(item){var key=String(item.name).toLowerCase();if(!item.code||unique[key])return false;unique[key]=true;return true;});
    aliases.sort(function(a,b){return b.name.length-a.name.length;});
    var text=String(answer||'').replace(/[０-９]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0xFEE0)}).replace(/：/g,':');
    // bible:web:CODE:ch:v explicit form
    var explicit=[], exRe=/bible:web:([A-Za-z0-9]+):(\d{1,3}):(\d{1,3})/g, exM;
    while((exM=exRe.exec(text))!==null){
      explicit.push({index:exM.index,code:exM[1].toUpperCase(),chapter:Number(exM[2]),start:Number(exM[3]),end:Number(exM[3])});
    }
    var found=explicit.slice();
    aliases.forEach(function(alias){
      var re=new RegExp('(^|[^A-Za-z0-9가-힣])('+escapeRegExp(alias.name)+')\\s*(\\d{1,3})(?:(?:\\s*장\\s*|\\s*:\\s*)(\\d{1,3})\\s*절?(?:\\s*(?:[-–—~〜]|부터)\\s*(\\d{1,3})\\s*절?)?)?','giu');
      var match;
      while((match=re.exec(text))!==null){
        var chapter=Number(match[3]),start=match[4]==null?null:Number(match[4]),end=match[5]==null?start:Number(match[5]);
        if(!Number.isInteger(chapter)||chapter<1||start==null||!Number.isInteger(start)||start<1||!Number.isInteger(end)||end<start)continue;
        found.push({index:match.index+match[1].length,code:alias.code,chapter:chapter,start:start,end:end,length:match[0].length});
        if(!match[0].length)re.lastIndex++;
      }
    });
    // Longest aliases win where one name is a prefix of another; overlapping matches keep only the longest span
    found.sort(function(a,b){
      if(a.index!==b.index)return a.index-b.index;
      var la=(a.length||a.nameLen||0), lb=(b.length||b.nameLen||0);
      return lb-la;
    });
    var filtered=[];
    for(var fi=0;fi<found.length;fi++){
      var cur=found[fi], skip=false;
      for(var fj=0;fj<filtered.length;fj++){
        var prev=filtered[fj];
        if(prev.index<=cur.index&&(cur.index<=prev.index+(prev.length||0))&&(prev.length||0)>=(cur.length||0)){skip=true;break;}
      }
      if(!skip)filtered.push(cur);
    }
    filtered.sort(function(a,b){return a.index-b.index;});
    var seen={},out=[];
    filtered.forEach(function(item){var key=[item.index,item.code,item.chapter,item.start,item.end].join(':');if(!seen[key]){seen[key]=true;out.push(item);}});
    return out;
  }
  // KRV-number display map. WEB verse numbers differ from KRV at the 2CO 13
  // merge and the ROM 14:24-26 / KRV 16:25-27 chapter shift.
  var KRV_EXCEPTIONS={
    '2CO:13:12':{chapter:13,verse:11},'2CO:13:13':{chapter:13,verse:12},'2CO:13:14':{chapter:13,verse:13},
    'ROM:14:24':{chapter:16,verse:25},'ROM:14:25':{chapter:16,verse:26},'ROM:14:26':{chapter:16,verse:27}
  };
  function krvLabelOf(locator){
    var m=String(locator||'').match(/^bible:[^:]+:([A-Za-z0-9]+):(\d+):(\d+)$/);
    if(!m)return null;
    var code=m[1].toUpperCase(),ch=Number(m[2]),vs=Number(m[3]);
    var ex=KRV_EXCEPTIONS[code+':'+ch+':'+vs];
    if(ex)return{code:code,chapter:ex.chapter,verse:ex.verse,label:code+' '+ex.chapter+':'+ex.verse};
    return{code:code,chapter:ch,verse:vs,label:code+' '+ch+':'+vs};
  }
  function projectAnswerEvidence(answer,packet,bookCodes,compareLocator){
  if(!packet||typeof packet!=='object'||!Array.isArray(packet.source_passages))return [];
  var reader=packet.reader_context||{},progress=packet.reading_progress||{},ceiling=progress.knowledge_ceiling_locator||null;
  if(reader.authoritative_reader!==true||reader.current_work_key!=='bible-web'||!ceiling||progress.furthest_read_locator!==ceiling)return [];
  var citations=parseCitations(answer,bookCodes);
  if(!citations.length)return [];
  var allowed=[];
  packet.source_passages.forEach(function(item){
    var locator=String(item&&(item.canonical_locator||item.canonicalLocator||item.locator)||'');
    var match=locator.match(/^bible:[^:]+:([A-Za-z0-9]+):(\d+):(\d+)$/);
    if(!match)return;
    if(ceiling){
      if(typeof compareLocator!=='function')return;
      try{if(compareLocator(locator,String(ceiling))>0)return;}catch(_){return;}
    }
    allowed.push({locator:locator,code:match[1].toUpperCase(),chapter:Number(match[2]),verse:Number(match[3])});
  });
  var result=[],seen={};
  citations.forEach(function(citation){
    allowed.forEach(function(item){
      if(item.code!==String(citation.code).toUpperCase())return;
      var krv=krvLabelOf(item.locator)||{chapter:item.chapter,verse:item.verse};
      var matchCanonical=item.chapter===citation.chapter&&item.verse>=citation.start&&item.verse<=citation.end;
      var matchKrv=krv.chapter===citation.chapter&&krv.verse>=citation.start&&krv.verse<=citation.end;
      if(!matchCanonical&&!matchKrv)return;
      if(!seen[item.locator]){seen[item.locator]=true;result.push(item.locator);}
    });
  });
  return result;
}
var api={parseCitations:parseCitations,projectAnswerEvidence:projectAnswerEvidence,krvLabelOf:krvLabelOf};
if(root)root.storyMemoryAnswerEvidenceV1=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window==='undefined'?null:window);
