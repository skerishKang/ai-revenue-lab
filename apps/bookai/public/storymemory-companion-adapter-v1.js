/* B61 #1129 StoryMemory live Companion consumer adapter v1.
   Uses #1305 bounded packet only. Never calls Provider directly and never falls back to legacy Hybrid execution. */
(function(){
'use strict';
var AI_PATH='/api/storymemory-ai';
var MAX_QUESTION_CHARS=2000;
/* 261106 · 전송 UX(설계 G): 전송 잠금, 대기 말풍선, 45초 AbortController,
   오류 코드별 안내 문구, retryable 반영. */
var REQUEST_TIMEOUT_MS=45000;
var PACKET_TIMEOUT_MS=8000;
var inFlight=false;

function clip(v,n){var s=String(v==null?'':v).replace(/\s+/g,' ').trim();return s.length>n?s.slice(0,Math.max(0,n-1))+'…':s;}
function selectedOverride(){
  try{
    if(typeof selectedContextText==='undefined'||!String(selectedContextText||'').trim())return null;
    var meta=(typeof selectedContextMeta!=='undefined'&&selectedContextMeta)||null;
    return {text:String(selectedContextText||'').slice(0,2000),locator:meta&&meta.canonical_locator?String(meta.canonical_locator):null};
  }catch(_){return null;}
}
function buildPacket(question){
  if(typeof window.storyMemoryBuildBoundedCompanionPacketV1!=='function')throw new Error('bounded_companion_packet_unavailable');
  return window.storyMemoryBuildBoundedCompanionPacketV1({query:question,selectedOverride:selectedOverride()});
}
/* B61 #1804 · prior-page grounding warm-up: load+cache the in-ceiling corpus
   (units up to the knowledge ceiling) so the packet builder can project eligible
   already-read prior-page evidence into model-visible refs. Bounded, cached once
   per work, fail-open (best effort). */
async function buildPacketWithGrounding(question){
  try{
    var rc=window.storyMemoryGetReaderContextV1?window.storyMemoryGetReaderContextV1():null;
    var wk=rc?rc.current_work_key:null;
    if(wk && window.storyMemoryEnsureGroundingBlocksV1){
      try{ await window.storyMemoryEnsureGroundingBlocksV1(wk); }catch(_){}
    }
  }catch(_){}
  return buildPacket(question);
}
function localBlockedResult(packet){
  var d=packet&&packet.co_reader_decision||{};
  return {
    ok:true,
    local:true,
    blocked:true,
    title:'동행 독자',
    answer:String(d.copy||'현재 읽은 범위 안에서만 함께 이야기할 수 있어요.'),
    source:'읽기 경계',
    reason:String(d.reason||'HARD_NO_FUTURE'),
    context_permission:null
  };
}
/* 261106 · 오류 코드별 안내 문구(설계 G). */
function failureCopy(code){
  var c=String(code||'');
  if(c==='packet_timeout')return '질문 준비에 시간이 걸렸어요. 다시 시도해 주세요.';
  if(c==='response_timeout')return '응답이 길어져 중단했어요 · 다시 시도';
  if(c==='answer_incomplete')return '답이 끝까지 만들어지지 않았어요 · 다시 시도';
  if(c==='stream_failed'||c==='stream_incomplete'||c==='network_failed')return '응답이 중간에 끊겼어요 · 다시 시도';
  if(c==='credential_unavailable'||c==='com2_ai_credential_unavailable')return '서비스 설정 점검 중이에요. 잠시 후 다시 시도해 주세요.';
  if(c==='http_504'||c==='http_503'||c==='com2_ai_timeout'||c==='ingress_timeout')return '응답이 지연되고 있어요. 잠시 후 다시 시도해 주세요.';
  if(c==='http_403'||c==='service_authentication_failed'||c==='service_app_not_authorized')return '서비스 연결을 점검 중이에요. 잠시 후 다시 시도해 주세요.';
  return '지금은 AI 동행 독자 연결을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.';
}
function localFailure(code,retryable){
  return {
    ok:false,
    local:true,
    blocked:false,
    title:'동행 독자',
    answer:failureCopy(code),
    source:'StoryMemory',
    error:String(code||'companion_unavailable'),
    retryable:!!retryable
  };
}
/* 261106 · 조각 스트림: 첫 조각이 오면 대기 말풍선을 답 말풍선으로 바꿔 이어
   붙인다. 오류가 나면 이 함수는 결과만 돌려주고, 말풍선 정리는 submit 이 한다. */
async function readStreamResponse(response,bubble,packet,signal){
  var reader=response.body.getReader();
  var decoder=typeof TextDecoder==='function'?new TextDecoder():null;
  var buffer='',streamed='',doneFrame=null,errorFrame=null;
  function handle(frame){
    if(!frame||typeof frame!=='object')return;
    if(frame.ok===false||frame.type==='error'){
      var e=frame.error&&typeof frame.error==='object'?frame.error:{};
      errorFrame={code:String(e.code||'stream_failed'),retryable:e.retryable===true};
      return;
    }
    if(frame.type==='delta'){
      if(typeof frame.text==='string'&&frame.text){
        streamed+=frame.text;
        if(bubble){try{bubble.className='msg ai';bubble.textContent=streamed;}catch(_){}}
      }
      return;
    }
    if(frame.type==='done')doneFrame=frame;
  }
  function drain(text){
    buffer+=text;
    var index;
    while((index=buffer.indexOf('\n'))>=0){
      var line=buffer.slice(0,index).trim();buffer=buffer.slice(index+1);
      if(!line)continue;
      var frame;try{frame=JSON.parse(line);}catch(_){continue;}
      handle(frame);
    }
  }
  try{
    while(!errorFrame&&!doneFrame){
      var chunk=await reader.read();
      if(chunk.done)break;
      drain(decoder?decoder.decode(chunk.value,{stream:true}):String(chunk.value));
    }
    if(!errorFrame&&!doneFrame&&buffer.trim()){
      try{handle(JSON.parse(buffer.trim()));}catch(_){}
    }
  }catch(_){
    if(signal&&signal.aborted)errorFrame={code:'response_timeout',retryable:false};
    else if(!errorFrame)errorFrame={code:'network_failed',retryable:true};
  }finally{
    try{if(reader.releaseLock)reader.releaseLock();}catch(_){}
  }
  if(errorFrame)return localFailure(errorFrame.code,errorFrame.retryable);
  if(!doneFrame||doneFrame.ok===false)return localFailure('stream_incomplete',true);
  if(typeof doneFrame.answer!=='string'||!doneFrame.answer.trim())return localFailure('invalid_response');
  return {
    ok:true,local:false,blocked:false,title:'동행 독자',answer:doneFrame.answer,source:'StoryMemory · 현재 읽은 범위',
    context_permission:doneFrame.context_permission||null,runtime:doneFrame.runtime||'padiem-ai-engine',reference_trust:doneFrame.reference_trust||'UNTRUSTED_REFERENCE',evidencePacket:packet,
    spoilerFolds:Array.isArray(doneFrame.spoiler_folds)?doneFrame.spoiler_folds:null,
    outsideBooks:Array.isArray(doneFrame.outside_books)?doneFrame.outside_books:null,
    readingMode:doneFrame.reading_mode||null
  };
}
async function requestCompanion(question,opts){
  opts=opts||{};
  var q=clip(question,MAX_QUESTION_CHARS);
  if(!q)return localFailure('question_required');
  var packet;
  var packetStarted=(typeof performance!=='undefined' && typeof performance.now==='function')?performance.now():Date.now();
  var packetTimer;
  try{
    packet=await Promise.race([
      buildPacketWithGrounding(q),
      new Promise(function(_,reject){packetTimer=setTimeout(function(){reject(new Error('packet_timeout'));},PACKET_TIMEOUT_MS);})
    ]);
  }catch(e){
    var code=e&&e.message||'packet_build_failed';
    return localFailure(code,code==='packet_timeout');
  }finally{clearTimeout(packetTimer);}
  var packetFinished=(typeof performance!=='undefined' && typeof performance.now==='function')?performance.now():Date.now();
  var packetMs=Math.max(0,Math.round(packetFinished-packetStarted));
  var decision=packet&&packet.co_reader_decision||null;
  if(!decision||decision.decision!=='ALLOW')return localBlockedResult(packet);
  if(!(packet&&packet.diagnostics&&packet.diagnostics.boundary_available===true))return localBlockedResult(packet);
  var response;
  try{
    response=await fetch(AI_PATH,{method:'POST',headers:{'content-type':'application/json','accept':'application/x-ndjson'},credentials:'same-origin',body:JSON.stringify({question:q,packet:packet,packet_ms:packetMs}),signal:opts.signal});
  }catch(err){
    if(opts.signal&&opts.signal.aborted)return localFailure('response_timeout');
    return localFailure('network_failed',true);
  }
  var responseType='';
  try{responseType=response.headers&&typeof response.headers.get==='function'?String(response.headers.get('content-type')||''):'';}catch(_){}
  if(response.ok&&response.body&&typeof response.body.getReader==='function'&&responseType.split(';')[0].trim().toLowerCase()==='application/x-ndjson'){
    return readStreamResponse(response,opts.bubble,packet,opts.signal);
  }
  var payload=null;
  try{payload=await response.json();}catch(_){return localFailure('invalid_response');}
  if(!response.ok||!payload||payload.ok!==true||typeof payload.answer!=='string'){
    var code=payload&&payload.error||('http_'+response.status);
    return localFailure(code,!!(payload&&payload.error&&payload.error.retryable)||response.status>=500||response.status===429);
  }
  return {
    ok:true,local:false,blocked:false,title:'동행 독자',answer:payload.answer,source:'StoryMemory · 현재 읽은 범위',
    context_permission:payload.context_permission||null,runtime:payload.runtime||'padiem-ai-engine',reference_trust:payload.reference_trust||'UNTRUSTED_REFERENCE',evidencePacket:packet,
    spoilerFolds:Array.isArray(payload.spoiler_folds)?payload.spoiler_folds:null,
    outsideBooks:Array.isArray(payload.outside_books)?payload.outside_books:null,
    readingMode:payload.reading_mode||null
  };
}
function appendResult(result,q,selection,delay){
  var meta={question:q,packet:selection||null,answerEvidencePacket:result.evidencePacket||null,liveCompanion:true,blocked:!!result.blocked,error:result.error||null,retryable:!!result.retryable,context_permission:result.context_permission||null,runtime:result.runtime||null,spoilerFolds:result.spoilerFolds||null,outsideBooks:result.outsideBooks||null,readingMode:result.readingMode||null};
  setTimeout(function(){appendAIMessage(result.title,result.answer,result.source,meta);},Math.max(0,Number(delay)||0));
}
function setSendLocked(locked){
  try{
    var btn=document.getElementById('sendBtn');
    if(!btn)return;
    btn.disabled=!!locked;
    if(locked)btn.setAttribute('aria-busy','true');
    else btn.removeAttribute('aria-busy');
  }catch(_){}
}
function appendPendingBubble(){
  try{
    var thread=document.getElementById('chatThread');
    if(!thread)return null;
    var d=document.createElement('div');
    d.className='msg ai sm-pending';
    d.setAttribute('aria-live','polite');
    d.textContent='답을 준비하고 있어요';
    thread.append(d);
    thread.scrollTop=thread.scrollHeight;
    return d;
  }catch(_){return null;}
}
function removePendingBubble(el){ try{ if(el&&el.parentNode)el.parentNode.removeChild(el); }catch(_){} }
async function submit(question,{selection=null,delay=80}={}){
  var q=clip(question,MAX_QUESTION_CHARS);
  if(!q)return null;
  /* 261106 · 전송 잠금: 답을 기다리는 동안 같은 질문이 겹치지 않는다. */
  if(inFlight)return null;
  inFlight=true;
  setSendLocked(true);
  appendUserMessage(q,selection);
  var pendingEl=appendPendingBubble();
  /* 261106 · 45초 AbortController: 길어진 응답은 중단하고 다시 시도 안내. */
  var controller=typeof AbortController==='function'?new AbortController():null;
  var timer=controller?setTimeout(function(){controller.abort();},REQUEST_TIMEOUT_MS):null;
  var result;
  try{
    result=await requestCompanion(q,{signal:controller?controller.signal:null,bubble:pendingEl});
  }finally{
    if(timer)clearTimeout(timer);
    removePendingBubble(pendingEl);
    inFlight=false;
    setSendLocked(false);
  }
  appendResult(result,q,selection,delay);
  return result;
}
window.storyMemoryRequestCompanionV1=requestCompanion;
window.storyMemorySubmitCompanionQuestionV1=submit;
window.__smCompanionAdapterV1={version:'1',path:AI_PATH,legacyHybridFallback:false,directProvider:false,priorPageGrounding:true,sendLock:true,requestTimeoutMs:REQUEST_TIMEOUT_MS};

// Live UI ownership. Legacy Hybrid remains callable for isolated diagnostics only.
sendChat=async function(){
  var input=document.getElementById('askInput');var q=input&&input.value?input.value.trim():'';if(!q)return;
  var selection=null;
  try{selection=selectedContextText?{quote:selectedContextText,source:(selectedContextMeta&&selectedContextMeta.source)||__smCurrentReaderLabel}:null;}catch(_){}
  input.value='';
  await submit(q,{selection:selection,delay:120});
  try{selectedContextText='';selectedContextMeta=null;selectionChip.classList.remove('show');selectionChipMeta.textContent='';}catch(_){}
};
var send=document.getElementById('sendBtn');if(send)send.onclick=sendChat;
var quick=document.querySelector('.ai-panel .quick');
if(quick){
  quick.addEventListener('click',function(e){
    var b=e.target&&e.target.closest?e.target.closest('button'):null;if(!b||!quick.contains(b))return;
    e.preventDefault();e.stopImmediatePropagation();
    var q=b.dataset.query||b.textContent||'';submit(q,{delay:100});
  },true);
}
askPreset=function(key){
  var button=[...document.querySelectorAll('.quick button')].find(function(b){return b.dataset.q===key;})||document.querySelector('[data-q="'+CSS.escape(key)+'"]');
  var q=(button&&button.dataset.query)||(button&&button.textContent)||key;return submit(q,{delay:100});
};
})();
