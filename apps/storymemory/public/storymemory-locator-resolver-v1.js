/* ===== B61 #1426 · Deterministic Locator + Unit Lookup v1 ===== */
(function(){
'use strict';

var LOC_RE=/^[a-z0-9][a-z0-9-]*(:[A-Za-z0-9][A-Za-z0-9.\-]*)+$/;
function unitOf(loc){var p=String(loc).split(':');return p[0]==='bible'?p.slice(0,4).join(':'):p.slice(0,3).join(':');}

var BIBLE_USFM=[
  'GEN','EXO','LEV','NUM','DEU','JOS','JDG','RUT','1SA','2SA','1KI','2KI','1CH','2CH','EZR','NEH','EST','JOB','PSA','PRO','ECC','SNG','ISA','JER','LAM','EZK','DAN','HOS','JOL','AMO','OBA','JON','MIC','NAM','HAB','ZEP','HAG','ZEC','MAL',
  'MAT','MRK','LUK','JHN','ACT','ROM','1CO','2CO','GAL','EPH','PHP','COL','1TH','2TH','1TI','2TI','TIT','PHM','HEB','JAS','1PE','2PE','1JN','2JN','3JN','JUD','REV'
];

var KO_TO_USFM={
  '창세기':'GEN','출애굽기':'EXO','레위기':'LEV','민수기':'NUM','신명기':'DEU','여호수아':'JOS','사사기':'JDG','룻기':'RUT',
  '사무엘상':'1SA','사무엘하':'2SA','열왕기상':'1KI','열왕기하':'2KI','역대상':'1CH','역대하':'2CH','에스라':'EZR','느헤미야':'NEH','에스더':'EST',
  '욥기':'JOB','시편':'PSA','잠언':'PRO','전도서':'ECC','아가':'SNG','이사야':'ISA','예레미야':'JER','예레미야애가':'LAM','에스겔':'EZK','다니엘':'DAN',
  '호세아':'HOS','요엘':'JOL','아모스':'AMO','오바댜':'OBA','요나':'JON','미가':'MIC','나훔':'NAM','하박국':'HAB','스바냐':'ZEP','학개':'HAG','스가랴':'ZEC','말라기':'MAL',
  '마태복음':'MAT','마가복음':'MRK','누가복음':'LUK','요한복음':'JHN','사도행전':'ACT','로마서':'ROM','고린도전서':'1CO','고린도후서':'2CO',
  '갈라디아서':'GAL','에베소서':'EPH','빌립보서':'PHP','골로새서':'COL','데살로니가전서':'1TH','데살로니가후서':'2TH','디모데전서':'1TI','디모데후서':'2TI',
  '디도서':'TIT','빌레몬서':'PHM','히브리서':'HEB','야고보서':'JAS','베드로전서':'1PE','베드로후서':'2PE','요한일서':'1JN','요한이서':'2JN','요한삼서':'3JN','유다서':'JUD','요한계시록':'REV'
};
var USFM_TO_KO={}; for(var k in KO_TO_USFM) USFM_TO_KO[KO_TO_USFM[k]]=k;

var VOLUME_CHAPTERS={
  '창세기':50,'출애굽기':40,'레위기':27,'민수기':36,'신명기':34,'여호수아':24,'사사기':21,'룻기':4,
  '사무엘상':31,'사무엘하':24,'열왕기상':22,'열왕기하':25,'역대상':29,'역대하':36,'에스라':10,'느헤미야':13,'에스더':10,
  '욥기':42,'시편':150,'잠언':31,'전도서':12,'아가':8,'이사야':66,'예레미야':52,'예레미야애가':5,'에스겔':48,'다니엘':12,
  '호세아':14,'요엘':3,'아모스':9,'오바댜':1,'요나':4,'미가':7,'나훔':3,'하박국':3,'스바냐':3,'학개':2,'스가랴':14,'말라기':4,
  '마태복음':28,'마가복음':16,'누가복음':24,'요한복음':21,'사도행전':28,'로마서':16,
  '고린도전서':16,'고린도후서':13,'갈라디아서':6,'에베소서':6,'빌립보서':4,'골로새서':4,
  '데살로니가전서':5,'데살로니가후서':3,'디모데전서':6,'디모데후서':4,'디도서':3,'빌레몬서':1,
  '히브리서':13,'야고보서':5,'베드로전서':5,'베드로후서':3,'요한일서':5,'요한이서':1,'요한삼서':1,'유다서':1,'요한계시록':22
};
var USFM_CHAPTERS={}; for(var ko in VOLUME_CHAPTERS){ var us=KO_TO_USFM[ko]; if(us) USFM_CHAPTERS[us]=VOLUME_CHAPTERS[ko]; }

var USFM_TO_EN={
  'GEN':'Genesis','EXO':'Exodus','LEV':'Leviticus','NUM':'Numbers','DEU':'Deuteronomy','JOS':'Joshua','JDG':'Judges','RUT':'Ruth',
  '1SA':'1 Samuel','2SA':'2 Samuel','1KI':'1 Kings','2KI':'2 Kings','1CH':'1 Chronicles','2CH':'2 Chronicles','EZR':'Ezra','NEH':'Nehemiah','EST':'Esther',
  'JOB':'Job','PSA':'Psalms','PRO':'Proverbs','ECC':'Ecclesiastes','SNG':'Song of Songs','ISA':'Isaiah','JER':'Jeremiah','LAM':'Lamentations','EZK':'Ezekiel','DAN':'Daniel',
  'HOS':'Hosea','JOL':'Joel','AMO':'Amos','OBA':'Obadiah','JON':'Jonah','MIC':'Micah','NAM':'Nahum','HAB':'Habakkuk','ZEP':'Zephaniah','HAG':'Haggai','ZEC':'Zechariah','MAL':'Malachi',
  'MAT':'Matthew','MRK':'Mark','LUK':'Luke','JHN':'John','ACT':'Acts','ROM':'Romans','1CO':'1 Corinthians','2CO':'2 Corinthians',
  'GAL':'Galatians','EPH':'Ephesians','PHP':'Philippians','COL':'Colossians','1TH':'1 Thessalonians','2TH':'2 Thessalonians','1TI':'1 Timothy','2TI':'2 Timothy',
  'TIT':'Titus','PHM':'Philemon','HEB':'Hebrews','JAS':'James','1PE':'1 Peter','2PE':'2 Peter','1JN':'1 John','2JN':'2 John','3JN':'3 John','JUD':'Jude','REV':'Revelation'
};

var ALIAS_MAP={};
// USFM codes
BIBLE_USFM.forEach(function(u){ ALIAS_MAP[u.toLowerCase()]=[u]; });
// English full/short
var EN_ALIASES={
  'genesis':['GEN'],'gen':['GEN'],
  'exodus':['EXO'],'exod':['EXO'],'ex':['EXO'],
  'leviticus':['LEV'],'lev':['LEV'],
  'numbers':['NUM'],'num':['NUM'],
  'deuteronomy':['DEU'],'deut':['DEU'],
  'joshua':['JOS'],'josh':['JOS'],
  'judges':['JDG'],'jdg':['JDG'],
  'ruth':['RUT'],
  '1 samuel':['1SA'],'1samuel':['1SA'],'1sa':['1SA'],
  '2 samuel':['2SA'],'2samuel':['2SA'],'2sa':['2SA'],
  '1 kings':['1KI'],'1kings':['1KI'],'1ki':['1KI'],
  '2 kings':['2KI'],'2kings':['2KI'],'2ki':['2KI'],
  '1 chronicles':['1CH'],'1chronicles':['1CH'],'1ch':['1CH'],
  '2 chronicles':['2CH'],'2chronicles':['2CH'],'2ch':['2CH'],
  'ezra':['EZR'],
  'nehemiah':['NEH'],'neh':['NEH'],
  'esther':['EST'],'est':['EST'],
  'job':['JOB'],
  'psalms':['PSA'],'psalm':['PSA'],'psa':['PSA'],'ps':['PSA'],
  'proverbs':['PRO'],'prov':['PRO'],'pro':['PRO'],
  'ecclesiastes':['ECC'],'ecc':['ECC'],
  'song of songs':['SNG'],'song':['SNG'],'sng':['SNG'],'canticles':['SNG'],
  'isaiah':['ISA'],'isa':['ISA'],
  'jeremiah':['JER'],'jer':['JER'],
  'lamentations':['LAM'],'lam':['LAM'],
  'ezekiel':['EZK'],'ezek':['EZK'],
  'daniel':['DAN'],'dan':['DAN'],
  'hosea':['HOS'],'hos':['HOS'],
  'joel':['JOL'],'jol':['JOL'],
  'amos':['AMO'],'amo':['AMO'],
  'obadiah':['OBA'],'oba':['OBA'],
  'jonah':['JON'],'jon':['JON'],
  'micah':['MIC'],'mic':['MIC'],
  'nahum':['NAM'],'nah':['NAM'],
  'habakkuk':['HAB'],'hab':['HAB'],
  'zephaniah':['ZEP'],'zeph':['ZEP'],'zep':['ZEP'],
  'haggai':['HAG'],'hag':['HAG'],
  'zechariah':['ZEC'],'zech':['ZEC'],'zec':['ZEC'],
  'malachi':['MAL'],'mal':['MAL'],
  'matthew':['MAT'],'matt':['MAT'],'mat':['MAT'],
  'mark':['MRK'],'mrk':['MRK'],'mk':['MRK'],
  'luke':['LUK'],'luk':['LUK'],'lk':['LUK'],
  'john':['JHN'],'jhn':['JHN'],'jn':['JHN'],
  'acts':['ACT'],'act':['ACT'],
  'romans':['ROM'],'rom':['ROM'],'ro':['ROM'],
  '1 corinthians':['1CO'],'1corinthians':['1CO'],'1co':['1CO'],
  '2 corinthians':['2CO'],'2corinthians':['2CO'],'2co':['2CO'],
  'galatians':['GAL'],'gal':['GAL'],
  'ephesians':['EPH'],'eph':['EPH'],
  'philippians':['PHP'],'philippians':['PHP'],'php':['PHP'],'phil':['PHP'],
  'colossians':['COL'],'col':['COL'],
  '1 thessalonians':['1TH'],'1thessalonians':['1TH'],'1th':['1TH'],
  '2 thessalonians':['2TH'],'2thessalonians':['2TH'],'2th':['2TH'],
  '1 timothy':['1TI'],'1timothy':['1TI'],'1ti':['1TI'],
  '2 timothy':['2TI'],'2timothy':['2TI'],'2ti':['2TI'],
  'titus':['TIT'],'tit':['TIT'],
  'philemon':['PHM'],'phm':['PHM'],
  'hebrews':['HEB'],'heb':['HEB'],
  'james':['JAS'],'jas':['JAS'],'jm':['JAS'],
  '1 peter':['1PE'],'1peter':['1PE'],'1pe':['1PE'],
  '2 peter':['2PE'],'2peter':['2PE'],'2pe':['2PE'],
  '1 john':['1JN'],'1john':['1JN'],'1jn':['1JN'],
  '2 john':['2JN'],'2john':['2JN'],'2jn':['2JN'],
  '3 john':['3JN'],'3john':['3JN'],'3jn':['3JN'],
  'jude':['JUD'],'jud':['JUD'],
  'revelation':['REV'],'rev':['REV']
};
for(var a in EN_ALIASES) ALIAS_MAP[a]=EN_ALIASES[a];
// Korean full
for(var ko in KO_TO_USFM){ ALIAS_MAP[ko.toLowerCase()] = [KO_TO_USFM[ko]]; }
// Korean short ambiguous — 요 covers JHN/1JN/2JN/3JN/REV
ALIAS_MAP['요']=['JHN'];
ALIAS_MAP['요한']=['JHN'];
// Ensure no duplicate alias for known Korean short: allow direct

// Mapping exceptions — KRV-only raw with no WEB row
var ORPHANS={'ACT:8:37':1,'ACT:15:34':1,'ACT:24:7':1,'LUK:17:36':1};

// Six-work catalog (minimal for deterministic lookup)
var SIX_WORKS=[
  {work_key:'bible-web', title:'The Holy Bible', aliases:['bible','성경','bible-web']},
  {work_key:'iliad', title:'The Iliad', aliases:['iliad','일리아드']},
  {work_key:'odyssey', title:'The Odyssey', aliases:['odyssey','오디세이']},
  {work_key:'aeneid', title:'The Aeneid', aliases:['aeneid','아이네이스']},
  {work_key:'metamorphoses', title:'Metamorphoses', aliases:['metamorphoses','변신이야기']},
  {work_key:'paradise-lost', title:'Paradise Lost', aliases:['paradise lost','paradise-lost','실낙원']},
  {work_key:'divine-comedy', title:'The Divine Comedy', aliases:['divine comedy','divine-comedy','신곡']}
];

function normalizeInput(s){
  if(typeof s!=='string') return '';
  var t=s.trim();
  t=t.replace(/\u3000/g,' ');
  t=t.replace(/장/g,' ');
  t=t.replace(/절/g,'');
  t=t.replace(/[:.]/g,' ');
  t=t.replace(/,/g,' ');
  t=t.replace(/\s+/g,' ');
  return t.trim();
}

function parseBibleTokens(input){
  var norm=normalizeInput(input);
  if(!norm) return null;
  var parts=norm.split(' ');
  // Find numeric tokens from end
  var nums=[];
  var i=parts.length-1;
  while(i>=0 && /^\d+$/.test(parts[i])){ nums.unshift(parseInt(parts[i],10)); i--; }
  var bookTokens=parts.slice(0,i+1);
  var bookRaw=bookTokens.join(' ').trim();
  if(!bookRaw) return null;
  var bookKey=bookRaw.toLowerCase();
  var candidates=ALIAS_MAP[bookKey] || null;
  if(!candidates){
    // Try without spaces (e.g., "1 john" vs "1john" already handled, but try join)
    var nospace=bookKey.replace(/\s+/g,'');
    candidates=ALIAS_MAP[nospace] || null;
  }
  if(!candidates){
    // Try original case for Korean (already lowercased)
    return {bookRaw:bookRaw, candidates:null, chapter:nums[0], verse:nums[1]};
  }
  return {bookRaw:bookRaw, candidates:candidates, chapter:nums[0], verse:nums[1]};
}

// Simple existence check via manifest: we embed chapter counts, and verse existence will be checked via file read if available
var MANIFEST_CACHE=null;
function getManifest(work_key){
  if(MANIFEST_CACHE) return MANIFEST_CACHE;
  try{ MANIFEST_CACHE=JSON.parse(require('fs').readFileSync('dist/content/catalog.json','utf8')); }catch(e){ try{MANIFEST_CACHE=JSON.parse(require('fs').readFileSync(require('path').join(__dirname,'content','catalog.json'),'utf8'));}catch(e2){} }
  return MANIFEST_CACHE;
}

// Helper to check passage existence synchronously
function passageExists(usfm, chapter, verse){
  var key='bible:web:'+usfm+':'+chapter+':'+verse;
  // Orphan hard lock
  if(ORPHANS[usfm+':'+chapter+':'+verse]) return 'orphan';
  // Check via file read
  try{
    var fs=require('fs');
    var path='dist/content/bible-web/book-'+usfm+'-chapter-'+String(chapter).padStart(3,'0')+'.json';
    try{ fs.accessSync(path); }catch(_){ path=require('path').join(__dirname,'content','bible-web','book-'+usfm+'-chapter-'+String(chapter).padStart(3,'0')+'.json'); }
    var data=JSON.parse(fs.readFileSync(path,'utf8'));
    for(var i=0;i<data.passages.length;i++){ if(data.passages[i].canonical_locator===key) return data.passages[i]; }
    return null;
  }catch(e){ return null; }
}

function chapterExists(usfm, chapter){
  var max=USFM_CHAPTERS[usfm]||0;
  if(chapter<1 || chapter>max) return false;
  try{
    var fs=require('fs');
    var path='dist/content/bible-web/book-'+usfm+'-chapter-'+String(chapter).padStart(3,'0')+'.json';
    try{ fs.accessSync(path); }catch(_){ path=require('path').join(__dirname,'content','bible-web','book-'+usfm+'-chapter-'+String(chapter).padStart(3,'0')+'.json'); }
    fs.accessSync(path);
    return true;
  }catch(e){ return false; }
}

function buildDisplayRefs(usfm, chapter, verse){
  var ko=USFM_TO_KO[usfm]||usfm;
  var en=USFM_TO_EN[usfm]||usfm;
  if(verse){
    return {ko: ko+' '+chapter+':'+verse, en: en+' '+chapter+':'+verse};
  } else if(chapter){
    return {ko: ko+' '+chapter+'장', en: en+' '+chapter};
  } else {
    return {ko: ko, en: en};
  }
}

function resolveBible(input){
  var parsed=parseBibleTokens(input);
  if(!parsed) return {status:'INVALID_REFERENCE', input:input, reason:'parse_failed'};
  var candidates=parsed.candidates;
  var ch=parsed.chapter;
  var vs=parsed.verse;
  // No candidates -> NOT_FOUND or INVALID
  if(!candidates){
    // Check if bookRaw looks like a bible book but unknown
    return {status:'NOT_FOUND', input:input, reason:'unknown_book', bookRaw:parsed.bookRaw};
  }
  // Ambiguity handling for '요' etc
  if(candidates.length>1){
    if(ch===undefined && vs===undefined){
      return {status:'AMBIGUOUS', input:input, reason:'ambiguous_alias', candidates:candidates};
    }
    // Filter candidates where chapter/verse exists or is orphan (for MAPPING_EXCEPTION)
    var viable=[];
    for(var i=0;i<candidates.length;i++){
      var u=candidates[i];
      if(vs!==undefined){
        var ex=passageExists(u, ch, vs);
        if(ex==='orphan') viable.push({usfm:u, type:'orphan'});
        else if(ex) viable.push({usfm:u, type:'found', passage:ex});
      } else if(ch!==undefined){
        if(chapterExists(u, ch)) viable.push({usfm:u, type:'chapter'});
      } else {
        viable.push({usfm:u, type:'book'});
      }
    }
    if(viable.length===0){
      // No viable -> check if orphan in any candidate
      for(var j=0;j<candidates.length;j++){
        var uj=candidates[j];
        if(vs!==undefined && ORPHANS[uj+':'+ch+':'+vs]){
          return {status:'MAPPING_EXCEPTION', input:input, reason:'orphan', book_id:uj, chapter:ch, verse:vs, canonical_locator:'bible:web:'+uj+':'+ch+':'+vs, work_key:'bible-web'};
        }
      }
      return {status:'NOT_FOUND', input:input, reason:'no_viable_candidate', candidates:candidates};
    }
    if(viable.length>1){
      // Still ambiguous if multiple viable
      // For '요 3:16', only JHN 3:16 viable
      if(viable.length===1) { /* fall through */ } else {
        return {status:'AMBIGUOUS', input:input, reason:'multiple_viable', viable:viable.map(function(v){return v.usfm;})};
      }
    }
    // Single viable
    var pick=viable[0];
    if(pick.type==='orphan'){
      return {status:'MAPPING_EXCEPTION', input:input, book_id:pick.usfm, chapter:ch, verse:vs, canonical_locator:'bible:web:'+pick.usfm+':'+ch+':'+vs, work_key:'bible-web', reason:'orphan'};
    }
    if(pick.type==='found'){
      var p=pick.passage;
      var disp=buildDisplayRefs(pick.usfm,ch,vs);
      return {status:'FOUND', kind:'passage', work_key:'bible-web', book_id:pick.usfm, chapter:ch, verse:vs, canonical_locator:p.canonical_locator, unit_key:'book:'+pick.usfm+':chapter:'+String(ch).padStart(3,'0'), display_reference_ko:disp.ko, display_reference_en:disp.en, krv:p.raw_texts?p.raw_texts[0]:null, web:p.ko||p.en, raw:p, locator_start:p.canonical_locator, locator_end:p.canonical_locator, stable_internal_key:p.canonical_locator, display_title:disp.ko, navigation_target:p.canonical_locator, passages:[p]};
    }
    if(pick.type==='chapter'){
      var disp2=buildDisplayRefs(pick.usfm,ch,null);
      var unitKey='book:'+pick.usfm+':chapter:'+String(ch).padStart(3,'0');
      var canStart='bible:web:'+pick.usfm+':'+ch+':1';
      return {status:'FOUND', kind:'unit', work_key:'bible-web', book_id:pick.usfm, chapter:ch, canonical_locator:unitKey, unit_key:unitKey, display_reference_ko:disp2.ko, display_reference_en:disp2.en, stable_internal_key:unitKey, display_title:disp2.ko, navigation_target:unitKey, locator_start:canStart};
    }
    return {status:'FOUND', kind:'book', work_key:'bible-web', book_id:pick.usfm, stable_internal_key:'book:'+pick.usfm, display_title:USFM_TO_KO[pick.usfm]||pick.usfm, navigation_target:'book:'+pick.usfm};
  }

  // Single candidate
  var usfm=candidates[0];
  // Check orphan
  if(vs!==undefined && ORPHANS[usfm+':'+ch+':'+vs]){
    return {status:'MAPPING_EXCEPTION', input:input, book_id:usfm, chapter:ch, verse:vs, canonical_locator:'bible:web:'+usfm+':'+ch+':'+vs, work_key:'bible-web', reason:'orphan'};
  }
  if(vs!==undefined){
    var ex=passageExists(usfm, ch, vs);
    if(ex && ex!=='orphan'){
      var disp=buildDisplayRefs(usfm,ch,vs);
      return {status:'FOUND', kind:'passage', work_key:'bible-web', book_id:usfm, chapter:ch, verse:vs, canonical_locator:ex.canonical_locator, unit_key:'book:'+usfm+':chapter:'+String(ch).padStart(3,'0'), display_reference_ko:disp.ko, display_reference_en:disp.en, krv:ex.raw_texts?ex.raw_texts[0]:null, web:ex.ko||ex.en, raw:ex, locator_start:ex.canonical_locator, locator_end:ex.canonical_locator, stable_internal_key:ex.canonical_locator, display_title:disp.ko, navigation_target:ex.canonical_locator, passages:[ex]};
    } else {
      // Not found — check if chapter exists but verse not
      if(!chapterExists(usfm,ch)) return {status:'NOT_FOUND', input:input, reason:'chapter_not_found', book_id:usfm, chapter:ch, verse:vs};
      return {status:'NOT_FOUND', input:input, reason:'verse_not_found', book_id:usfm, chapter:ch, verse:vs};
    }
  } else if(ch!==undefined){
    if(!chapterExists(usfm,ch)) return {status:'NOT_FOUND', input:input, reason:'chapter_not_found', book_id:usfm, chapter:ch};
    var disp2=buildDisplayRefs(usfm,ch,null);
    var unitKey='book:'+usfm+':chapter:'+String(ch).padStart(3,'0');
    var canStart2='bible:web:'+usfm+':'+ch+':1';
    return {status:'FOUND', kind:'unit', work_key:'bible-web', book_id:usfm, chapter:ch, canonical_locator:unitKey, unit_key:unitKey, display_reference_ko:disp2.ko, display_reference_en:disp2.en, stable_internal_key:unitKey, display_title:disp2.ko, navigation_target:unitKey, locator_start:canStart2};
  } else {
    // Book only
    return {status:'FOUND', kind:'book', work_key:'bible-web', book_id:usfm, canonical_locator:'bible:web:'+usfm, stable_internal_key:'book:'+usfm, display_title:USFM_TO_KO[usfm]||usfm, navigation_target:'book:'+usfm};
  }
}

function resolveSixWork(input){
  var norm=input.trim().toLowerCase();
  // Normalize aliases
  for(var i=0;i<SIX_WORKS.length;i++){
    var w=SIX_WORKS[i];
    for(var j=0;j<w.aliases.length;j++){
      var al=w.aliases[j].toLowerCase();
      if(norm.indexOf(al)===0){
        var rest=norm.slice(al.length).trim();
        // Parse book/canto
        var m=rest.match(/^(book|canto)?\s*(\d+)?/);
        var num=m&&m[2]?parseInt(m[2],10):null;
        var work_key=w.work_key;
        // Load manifest to validate
        try{
          var fs=require('fs');
          var manPath='dist/content/'+work_key+'/manifest.json';
          try{ fs.accessSync(manPath);}catch(_){ manPath=require('path').join(__dirname,'content',work_key,'manifest.json'); }
          var man=JSON.parse(fs.readFileSync(manPath,'utf8'));
          if(num!==null){
            var unit=null;
            for(var k=0;k<man.units.length;k++){ if(man.units[k].unit_ordinal===num) {unit=man.units[k]; break;} }
            if(!unit) return {status:'NOT_FOUND', input:input, reason:'unit_not_found', work_key:work_key};
            return {status:'FOUND', kind:'unit', work_key:work_key, unit_ordinal:num, unit_key:unit.unit_key, stable_internal_key:unit.unit_key||work_key+':'+num, canonical_locator:unit.first_locator, canonical_locator_or_unit_key:unit.unit_key, locator_start:unit.first_locator, locator_end:unit.last_locator, display_title:unit.label, navigation_target:unit.unit_key, manifest_unit:unit};
          } else {
            // Work only
            return {status:'FOUND', kind:'work', work_key:work_key, stable_internal_key:work_key, display_title:w.title, navigation_target:work_key};
          }
        }catch(e){
          return {status:'FOUND', kind:'work', work_key:work_key, stable_internal_key:work_key, display_title:w.title, navigation_target:work_key};
        }
      }
    }
  }
  return null;
}

function resolve(input){
  if(typeof input!=='string' || !input.trim()) return {status:'INVALID_REFERENCE', input:input, reason:'empty'};
  var trimmed=input.trim();
  // Try six-work first if input contains iliad etc.
  var six=resolveSixWork(trimmed);
  if(six) return six;
  // Try bible
  var bible=resolveBible(trimmed);
  if(bible) return bible;
  return {status:'NOT_FOUND', input:input, reason:'unrecognized'};
}

// Expose
if(typeof window!=='undefined'){
  window.__smLocatorResolverV1={resolve:resolve, resolveBible:resolveBible, resolveSixWork:resolveSixWork, parseBibleTokens:parseBibleTokens, passageExists:passageExists, chapterExists:chapterExists, ORPHANS:ORPHANS, BIBLE_USFM:BIBLE_USFM};
} 
if(typeof module!=='undefined' && module.exports){
  module.exports={resolve:resolve, resolveBible:resolveBible, resolveSixWork:resolveSixWork, passageExists:passageExists, chapterExists:chapterExists, ORPHANS:ORPHANS};
}

})();