/* ===== B61 #1305 · Knowledge Ceiling policy — consumes #1337 R1 locator/progress module ===== */
(function(){
'use strict';
var R1=window.__smLocatorProgressR1V1;
if(!R1) throw new Error('StoryMemory locator/progress R1 module missing');
var locatorWorkFamily=R1.locatorWorkFamily;
var isLocatorCompatibleWithWork=R1.isLocatorCompatibleWithWork;
var compareLocators=R1.compareLocators;
var getCeiling=R1.getCeiling;
function isFuture(locator, workKey){
  if(!locator || !workKey) return false;
  if(!isLocatorCompatibleWithWork(locator, workKey)) return true;
  var ceil=getCeiling(workKey);
  if(!ceil) return false;
  if(!isLocatorCompatibleWithWork(ceil, workKey)) return true;
  if(locatorWorkFamily(locator)!==locatorWorkFamily(ceil)) return true;
  return compareLocators(locator, ceil)>0;
}
function filterFuturePassages(passages, workKey){
  if(!Array.isArray(passages)) return [];
  var ceil=getCeiling(workKey);
  if(!ceil) return [];
  return passages.filter(function(p){ var loc=p.canonical_locator||p.canonicalLocator||p.locator||''; if(!loc) return false; if(!isLocatorCompatibleWithWork(loc, workKey)) return false; if(locatorWorkFamily(loc)!==locatorWorkFamily(ceil)) return false; return compareLocators(loc, ceil)<=0; });
}
function filterFutureAnnotations(annotations, workKey){
  if(!Array.isArray(annotations)) return [];
  var ceil=getCeiling(workKey);
  if(!ceil) return [];
  return annotations.filter(function(a){ var loc=a.locator||a.canonical_locator||''; if(!loc) return false; if(!isLocatorCompatibleWithWork(loc, workKey)) return false; if(locatorWorkFamily(loc)!==locatorWorkFamily(ceil)) return false; return compareLocators(loc, ceil)<=0; });
}
var REFUSAL_COPY_FUTURE="아직 읽지 않은 부분은 안내해 드릴 수 없어요. 현재까지 읽은 범위 안에서 함께 이야기 나눠요.";
var REFUSAL_COPY_CONSENT="스포일러 허용을 말씀해 주셔도, 동행 독자 모드에서는 미리 알려드리지 않아요. 지금 읽은 곳까지만 나눠요.";
var REFUSAL_COPY_YESNO="해당 내용은 앞으로의 전개를 직접 확인하셔야 해서, 미리 결론을 전해 드리지 않아요.";
var REFUSAL_COPY_NOBOUNDARY="아직 읽은 범위가 설정되지 않아, 안전하게 답변드리기 어렵습니다. 먼저 읽은 챕터를 이동해 주세요.";
var REFUSAL_COPY_NOEVIDENCE="아직 읽지 않은 범위와 관련된 내용이라 지금은 안내해 드릴 수 없어요. 현재까지 읽은 부분 안에서 함께 이야기할 수 있어요.";
var REFUSAL_COPY_NORELEVANT="지금 읽은 부분과 관련 없는 내용이라 안내해 드릴 수 없어요. 현재까지 읽은 범위 안에서 함께 이야기 나눠요.";
/* B61 #1656 · deterministic work-related classification (Layer A).
   No LLM, no entity DB, no RAG. Uses the shipped book-name tables and a
   compact Bible-entity keyword set to distinguish work-content questions
   from unrelated general chat (인사/독서 방법/기분 전환). */
var WORK_ENTITY_RE=/(?:예수님|예수|그리스도|바울|모세|아브라함|노아|홍수|다윗|솔로몬|요셉|야곱|이삭|아담|하와|가인|아벨|에녹|므두셀라|라멕|롯|이스라엘|애굽|이집트|홍해|십계명|성전|제사장|선지자|예언자|사도|제자|바리새인|천사|사탄|마귀|부활|구원자|천국|성령|베들레헴|나사렛|갈릴리|예루살렘|겟세마네|골고다|십자가|세례|창조|구약|신약|복음|계명|심판|사명|언약|가나안)/;
var WORK_REFERENCE_RE=/(?:성경|성서|말씀|bible|scripture)/i;
/* Compact Korean book-name list mirroring BIBLE_BOOK_ORDER (66 books).
   Kept in the product layer so the trusted R1 locator module stays untouched. */
var BIBLE_BOOK_KO=['창세기','출애굽기','레위기','민수기','신명기','여호수아','사사기','룻기','사무엘상','사무엘하','열왕기상','열왕기하','역대상','역대하','에스라','느헤미야','에스더','욥기','시편','잠언','전도서','아가','이사야','예레미야','예레미야애가','에스겔','다니엘','호세아','요엘','아모스','오바댜','요나','미가','나훔','하박국','스바냐','학개','스가랴','말라기','마태복음','마가복음','누가복음','요한복음','사도행전','로마서','고린도전서','고린도후서','갈라디아서','에베소서','빌립보서','골로새서','데살로니가전서','데살로니가후서','디모데전서','디모데후서','디도서','빌레몬서','히브리서','야고보서','베드로전서','베드로후서','요한일서','요한이서','요한삼서','유다서','요한계시록'];
var WORK_BOOK_RE=new RegExp(BIBLE_BOOK_KO.sort(function(a,b){return b.length-a.length;}).join('|'));
function isWorkRelatedQuery(query, workKey){
  var q=String(query||'');
  if(!q) return false;
  if(/bible-web/i.test(String(workKey||''))) return WORK_BOOK_RE.test(q)||WORK_ENTITY_RE.test(q)||WORK_REFERENCE_RE.test(q);
  var wk=String(workKey||'').toLowerCase();
  return new RegExp(wk.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).test(q);
}
/* B61 #1656 · extended future-probe preflight (Layer C): catches story-advance
   phrasings (전개/이어서/어떻게 돼/그 후/끝나) that previously reached the model.
   261106 · '다시 만나나요' 계열 재등장 물음도 전개 질문으로 잡는다 (대표 결정
   2026-11-05: 전개 질문은 거절 대신 접힘 응답으로 바뀐다). */
var FUTURE_PROBE_RE=/(?:다음|그\s*다음|다음\s*장|다음\s*권|앞으로|미래|결말|스포|결국|어떻게\s*돼|어떻게\s*전개|이야기\s*전개|이어서|그\s*후|이후|나중에|끝나|죽어|죽지|죽는지|사망|살아\s*남|무슨\s*일\s*생기|어떤\s*일\s*생기|무슨\s*내용|전개를\s*알려|전개가\s*어떻|다시\s*만나|만나나요|만날까|다시\s*돌아|돌아오나요|다시\s*오나요|what\s*happens?|the\s*end|ending)/i;
/* 261106 · 배경 질문(누구/어디/무슨 뜻/언제/왜 불리는지)은 어느 읽기 방식에서도
   전체 참고다. 결정론 판정(LLM 없음). */
var BACKGROUND_RE=/(?:누구|누가|어디|무슨\s*뜻|무슨\s*말|무슨\s*의미|무엇|어떤\s*사람|어떤\s*곳|어떤\s*책|언제|왜|어떻게\s*불리|불리는|유래|의미|뜻|배경|정의)/;
/* 261106 · 일반 대화는 질문 자체(인사·기분·독서법)로 판정한다. 작품 고유어
   (인물·책이름)가 있으면 일반 대화로 보지 않는다. */
var GENERAL_CHAT_RE=/(?:안녕|하이|hello|좋은\s*아침|좋은\s*저녁|좋은\s*밤|반갑|기분|우울|힘들|스트레스|짜증|외로|불안|행복|설레|심심|지쳤|피곤|어떻게\s*읽|읽는\s*방법|읽기\s*설정|읽기\s*방법|몇\s*장부터|글꼴|글자\s*크기|줄\s*간격|테마|감사|고마워|수고)/i;
/* 261106 · 이야기책(서사) 목록 — 코드 상수. 창세기~에스더, 복음서 4권, 사도행전.
   이 목록 밖(시가서·예언서·서신, 비-성경 작품)은 처음 읽어요 모드에서도
   전개 질문이 전체 참고다. */
var NARRATIVE_BIBLE_BOOKS=['GEN','EXO','LEV','NUM','DEU','JOS','JDG','RUT','1SA','2SA','1KI','2KI','1CH','2CH','EZR','NEH','EST','MAT','MRK','LUK','JHN','ACT'];
/* B61 #1724 · deterministic relevance gate. The pre-#1724 contract gated ONLY
   on evidence COUNT (current-page passages always exist), so work-related
   queries with no permitted grounding still reached ALLOW → model invoked →
   pretrained leakage. This gate scores the query against the actual in-ceiling
   evidence text (stem overlap) and requires at least one overlapping stem
   before ALLOW. No LLM; no topic rules; fail-closed when text is unusable. */
function getTokenizer(){
  if(typeof window!=='undefined' && window.__smStaticKeywordSearchV1 && typeof window.__smStaticKeywordSearchV1.tokenize==='function') return window.__smStaticKeywordSearchV1.tokenize;
  return null;
}
function evidenceText(ev){
  if(typeof ev==='string') return ev;
  if(!ev || typeof ev!=='object') return '';
  return String(ev.text||ev.snippet||ev.ko||ev.en||ev.note||'').slice(0,2000);
}
function evidenceHasRelevantStem(query, evidence){
  var tokenizer=getTokenizer();
  if(typeof tokenizer!=='function') return false;
  var qTerms=tokenizer(String(query||''));
  if(!Array.isArray(qTerms) || !qTerms.length) return false;
  if(!Array.isArray(evidence)) return false;
  for(var i=0;i<evidence.length;i++){
    var txt=evidenceText(evidence[i]);
    if(!txt) continue;
    var eTerms=tokenizer(txt);
    if(!Array.isArray(eTerms) || !eTerms.length) continue;
    for(var j=0;j<qTerms.length;j++){
      if(eTerms.indexOf(qTerms[j])!==-1) return true;
    }
  }
  return false;
}
/* B61 #1804 · query-vs-in-ceiling-corpus term overlap. Requires the grounding
   term index built by the retrieval adapter from cached in-ceiling blocks;
   returns false (no signal) when the index is unavailable so callers/tests
   without the corpus keep the exact pre-#1804 behavior. */
function queryContentRelated(query, workKey){
  try{
    if(typeof window==='undefined' || typeof window.storyMemoryInCeilingTermIndexV1!=='function') return false;
    var tokenizer=getTokenizer();
    if(typeof tokenizer!=='function') return false;
    var idx=window.storyMemoryInCeilingTermIndexV1(workKey);
    if(!idx || typeof idx.has!=='function') return false;
    var terms=tokenizer(String(query||''));
    if(!Array.isArray(terms) || !terms.length) return false;
    for(var i=0;i<terms.length;i++){ if(idx.has(terms[i])) return true; }
    return false;
  }catch(_){ return false; }
}
/* 261106 · 결정론 질문 분류 (LLM 없음). 일반 대화(인사·기분·독서법) → 배경
   질문 → 전개 질문 → 작품 내용 순. 작품 고유어(인물·책이름)가 있으면 일반
   대화 패턴보다 작품 질문이 이긴다. */
function classifyCompanionQuestion(query, context){
  context=context||{};
  var q=String(query||'').toLowerCase();
  var workKey=context.workKey||null;
  var entityHit=isWorkRelatedQuery(q, workKey);
  /* B61 #1804 · content-overlap: 천장 어휘와 겹치면 작품 내용 신호로 본다
     (일상어 오버랩은 더 이상 거절로 이어지지 않고 분류 힌트로만 쓴다). */
  var contentHit=false;
  try{ contentHit=queryContentRelated(q, workKey); }catch(_){ contentHit=false; }
  var general=GENERAL_CHAT_RE.test(q) && !WORK_ENTITY_RE.test(q) && !WORK_BOOK_RE.test(q);
  var plot=FUTURE_PROBE_RE.test(q);
  var background=!plot && BACKGROUND_RE.test(q);
  var cls = general?'general' : plot?'plot' : background?'background' : (entityHit||contentHit)?'work' : 'work';
  return {
    question_class:cls,
    general:cls==='general',
    plot:cls==='plot',
    background:cls==='background',
    work_related:entityHit||contentHit,
    reading_mode:context.readingMode||null
  };
}
function isNarrativeBibleBook(bookId){
  return NARRATIVE_BIBLE_BOOKS.indexOf(String(bookId||'').toUpperCase())>=0;
}
function coReaderDecision(query, targetLocator, workKey, evidence, context){
  var q=String(query||'').toLowerCase();
  context=context||{};
  var ceil=getCeiling(workKey);
  if(!ceil){
    return {decision:'BLOCK', reason:'BOUNDARY_UNAVAILABLE', copy:REFUSAL_COPY_NOBOUNDARY, ceiling:null, requested: targetLocator||null, query:q};
  }
  if(targetLocator && !isLocatorCompatibleWithWork(targetLocator, workKey)) {
    return {decision:'BLOCK', reason:'HARD_NO_FUTURE', copy:REFUSAL_COPY_FUTURE, ceiling:ceil, requested: targetLocator||null, query:q};
  }
  var mode=(context.readingMode!==undefined && context.readingMode!==null)?context.readingMode:(R1.getReadingMode?R1.getReadingMode(workKey):null);
  var classification=context.classification||classifyCompanionQuestion(query, {workKey:workKey, readingMode:mode, currentBookId:context.currentBookId});
  /* 구형 경로(reading_mode 미지정): 기존 거절 정책을 그대로 유지한다. */
  if(mode===null || mode===undefined){
    var isConsent = /스포.*괜찮|괜찮.*스포|스포일러.*허용|미리.*알려/.test(q);
    var isYesNo = /yes\/no|예.*아니오|아니오.*예|맞나|아니냐|일까/.test(q) && /미래|앞으로|다음/.test(q);
    var isFutureLoc = targetLocator ? isFuture(targetLocator, workKey) : false;
    var needsFuture = isFutureLoc || FUTURE_PROBE_RE.test(q);
    if(needsFuture){
      var copy=isConsent? REFUSAL_COPY_CONSENT : (isYesNo? REFUSAL_COPY_YESNO : REFUSAL_COPY_FUTURE);
      return {decision:'BLOCK', reason:'HARD_NO_FUTURE', copy:copy, ceiling:ceil, requested: targetLocator||null, query:q};
    }
    var workRelatedLegacy=isWorkRelatedQuery(q, workKey) || queryContentRelated(q, workKey);
    var hasEvidenceContentLegacy=Array.isArray(evidence);
    var evidenceCountLegacy=hasEvidenceContentLegacy ? evidence.length : (Number.isFinite(Number(evidence)) ? Number(evidence) : null);
    if(workRelatedLegacy && evidenceCountLegacy!==null && evidenceCountLegacy<=0){
      return {decision:'BLOCK', reason:'NO_WITHIN_CEILING_EVIDENCE', copy:REFUSAL_COPY_NOEVIDENCE, ceiling:ceil, requested: targetLocator||null, query:q};
    }
    if(workRelatedLegacy && hasEvidenceContentLegacy){
      var relevantLegacy=evidenceHasRelevantStem(q, evidence);
      if(!relevantLegacy){
        return {decision:'BLOCK', reason:'NO_RELEVANT_WITHIN_CEILING_EVIDENCE', copy:REFUSAL_COPY_NORELEVANT, ceiling:ceil, requested: targetLocator||null, query:q};
      }
    }
    return {decision:'ALLOW', reason:'WITHIN_CEILING', ceiling:ceil, requested: targetLocator||null, query:q};
  }
  /* 261106 · 새 결정 경로: 일반 대화·배경 질문은 어느 모드에서도 전체 참고,
     전개 질문만 읽기 방식을 따른다. 일상어 오버랩으로 질문을 거절하지 않는다
     (evidenceHasRelevantStem 게이트는 새 경로에서 제거). */
  if(classification.general){
    return {decision:'ALLOW', reason:'GENERAL_CHAT', question_class:'general', ceiling:ceil, requested: targetLocator||null, query:q};
  }
  if(classification.plot){
    if(mode==='browse'){
      return {decision:'ALLOW', reason:'WITHIN_CEILING', question_class:'plot', ceiling:ceil, requested: targetLocator||null, query:q};
    }
    if(workKey==='bible-web'){
      var bookId=String(context.currentBookId||'');
      if(!isNarrativeBibleBook(bookId)){
        /* 비이야기책(시가서·예언서·서신)은 처음 읽어요 모드에서도 전체 참고. */
        return {decision:'ALLOW', reason:'WITHIN_CEILING', question_class:'plot', ceiling:ceil, requested: targetLocator||null, query:q};
      }
      /* 이야기책 + 처음 읽어요: 거절 대신 접힘 응답. */
      return {decision:'ALLOW', reason:'WITHIN_CEILING', question_class:'plot', spoiler_fold:true, ceiling:ceil, requested: targetLocator||null, query:q};
    }
    return {decision:'BLOCK', reason:'HARD_NO_FUTURE', copy:REFUSAL_COPY_FUTURE, ceiling:ceil, requested: targetLocator||null, query:q};
  }
  if(classification.background){
    return {decision:'ALLOW', reason:'BACKGROUND_QUESTION', question_class:'background', ceiling:ceil, requested: targetLocator||null, query:q};
  }
  var hasEvidenceContent=Array.isArray(evidence);
  var evidenceCount=hasEvidenceContent ? evidence.length : (Number.isFinite(Number(evidence)) ? Number(evidence) : null);
  if(classification.work_related && evidenceCount!==null && evidenceCount<=0){
    return {decision:'BLOCK', reason:'NO_WITHIN_CEILING_EVIDENCE', copy:REFUSAL_COPY_NOEVIDENCE, ceiling:ceil, requested: targetLocator||null, query:q};
  }
  return {decision:'ALLOW', reason:'WITHIN_CEILING', question_class:classification.question_class, ceiling:ceil, requested: targetLocator||null, query:q};
}
window.storyMemoryIsFutureLocatorV1=isFuture;
window.storyMemoryFilterFuturePassagesV1=filterFuturePassages;
window.storyMemoryFilterFutureAnnotationsV1=filterFutureAnnotations;
window.storyMemoryCoReaderDecisionV1=coReaderDecision;
window.storyMemoryClassifyCompanionQuestionV1=classifyCompanionQuestion;
window.storyMemoryIsWorkRelatedQueryV1=isWorkRelatedQuery;
window.storyMemoryEvidenceHasRelevantStemV1=evidenceHasRelevantStem;
window.storyMemoryQueryContentRelatedV1=queryContentRelated;
window.__smKnowledgeCeilingV1={
  STORAGE_KEY:R1.STORAGE_KEY, VERSION:R1.VERSION, BIBLE_BOOK_ORDER:R1.BIBLE_BOOK_ORDER,
  NARRATIVE_BIBLE_BOOKS:NARRATIVE_BIBLE_BOOKS, FUTURE_PROBE_RE:FUTURE_PROBE_RE, BACKGROUND_RE:BACKGROUND_RE, GENERAL_CHAT_RE:GENERAL_CHAT_RE,
  REFUSAL_COPY_FUTURE:REFUSAL_COPY_FUTURE, REFUSAL_COPY_CONSENT:REFUSAL_COPY_CONSENT, REFUSAL_COPY_YESNO:REFUSAL_COPY_YESNO, REFUSAL_COPY_NOBOUNDARY:REFUSAL_COPY_NOBOUNDARY, REFUSAL_COPY_NOEVIDENCE:REFUSAL_COPY_NOEVIDENCE, REFUSAL_COPY_NORELEVANT:REFUSAL_COPY_NORELEVANT
};
if(typeof module!=='undefined' && module.exports){
  module.exports={coReaderDecision:coReaderDecision, classifyCompanionQuestion:classifyCompanionQuestion, isNarrativeBibleBook:isNarrativeBibleBook, NARRATIVE_BIBLE_BOOKS:NARRATIVE_BIBLE_BOOKS, isWorkRelatedQuery:isWorkRelatedQuery, isFuture:isFuture, filterFuturePassages:filterFuturePassages, filterFutureAnnotations:filterFutureAnnotations, evidenceHasRelevantStem:evidenceHasRelevantStem, queryContentRelated:queryContentRelated, REFUSAL_COPY_FUTURE:REFUSAL_COPY_FUTURE, REFUSAL_COPY_CONSENT:REFUSAL_COPY_CONSENT, REFUSAL_COPY_YESNO:REFUSAL_COPY_YESNO, REFUSAL_COPY_NOBOUNDARY:REFUSAL_COPY_NOBOUNDARY, REFUSAL_COPY_NOEVIDENCE:REFUSAL_COPY_NOEVIDENCE, REFUSAL_COPY_NORELEVANT:REFUSAL_COPY_NORELEVANT};
}
})();
