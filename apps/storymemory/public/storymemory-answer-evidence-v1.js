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
  var unique={};
  aliases=aliases.filter(function(item){var key=String(item.name).toLowerCase();if(!item.code||unique[key])return false;unique[key]=true;return true;});
  aliases.sort(function(a,b){return b.name.length-a.name.length;});
  var text=String(answer||''),found=[];
  aliases.forEach(function(alias){
    var re=new RegExp('(^|[^A-Za-z0-9가-힣])('+escapeRegExp(alias.name)+')\\s*(\\d{1,3})(?:(?:\\s*장\\s*|\\s*:\\s*)(\\d{1,3})\\s*절?(?:\\s*(?:[-–—~〜]|부터)\\s*(\\d{1,3})\\s*절?)?)?','giu');
    var match;
    while((match=re.exec(text))!==null){
      var chapter=Number(match[3]),start=match[4]==null?null:Number(match[4]),end=match[5]==null?start:Number(match[5]);
      if(!Number.isInteger(chapter)||chapter<1||start==null||!Number.isInteger(start)||start<1||!Number.isInteger(end)||end<start)continue;
      found.push({index:match.index+match[1].length,code:alias.code,chapter:chapter,start:start,end:end});
      if(!match[0].length)re.lastIndex++;
    }
  });
  // Longest aliases win where one name is a prefix of another; then retain the
  // answer's written order and discard duplicate parses of the same citation.
  found.sort(function(a,b){return a.index-b.index;});
  var seen={},out=[];
  found.forEach(function(item){var key=[item.index,item.code,item.chapter,item.start,item.end].join(':');if(!seen[key]){seen[key]=true;out.push(item);}});
  return out;
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
      if(item.code!==String(citation.code).toUpperCase()||item.chapter!==citation.chapter)return;
      if(citation.start!=null&&(item.verse<citation.start||item.verse>citation.end))return;
      if(!seen[item.locator]){seen[item.locator]=true;result.push(item.locator);}
    });
  });
  return result;
}
var api={parseCitations:parseCitations,projectAnswerEvidence:projectAnswerEvidence};
if(root)root.storyMemoryAnswerEvidenceV1=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window==='undefined'?null:window);
