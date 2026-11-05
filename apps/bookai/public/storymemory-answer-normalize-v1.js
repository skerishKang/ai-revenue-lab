/* 261106 · 동행 답변 정규화(원시 JSON 노출 방지, 클라이언트측 최후 방어).
   워커 parseModelParagraphs 와 같은 계약을 화면에서 한 번 더 적용한다:
   - 코드펜스(```json) 제거 후 '{' 로 시작하는 문자열만 JSON 파싱을 시도한다.
   - {"paragraphs":[{text,citations}]} 형태가 파싱되면 문단 텍스트로 정규화한다.
     citations 는 '책이름 장:절' 라벨로 문단 뒤에 덧붙여 근거 칩 산출을 유지한다.
   - 파싱에 실패하면 null 을 돌려주고, 호출부는 JSON 대신
     '답을 정리하지 못했어요 · 다시 시도' 안내를 보여 준다. */
(function(){
'use strict';
function normalizeCompanionAnswer(raw){
  var text=String(raw==null?'':raw).trim();
  if(!text) return null;
  var fence=text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if(fence) text=fence[1].trim();
  if(!text.startsWith('{')) return null;
  var parsed;
  try{ parsed=JSON.parse(text); }catch(_){ return null; }
  if(!parsed||typeof parsed!=='object'||!Array.isArray(parsed.paragraphs)) return null;
  var out=[];
  for(var i=0;i<parsed.paragraphs.length;i++){
    var p=parsed.paragraphs[i];
    if(!p||typeof p!=='object') continue;
    var t=String(p.text==null?'':p.text).trim();
    if(!t) continue;
    var cites=Array.isArray(p.citations)?p.citations.map(function(c){return String(c).trim();}).filter(Boolean):[];
    if(cites.length&&t.indexOf(cites[0])<0) t=t+' ('+cites.join(', ')+')';
    out.push(t);
  }
  if(!out.length) return null;
  return out.join('\n\n');
}
/* 261106 · 배지 결정: 근거 칩이 없는 GROUNDED 답은 '근거 답변' 대신 '대화'로
   표시한다(일반 대화·칩 0개 공통). 나머지 상태는 기존 표기를 유지한다. */
function companionBadgeKey(state,hasChips){
  if(state==='GROUNDED'&&!hasChips) return 'CHAT';
  return state;
}
window.storyMemoryNormalizeCompanionAnswerV1=normalizeCompanionAnswer;
window.storyMemoryCompanionBadgeV1=companionBadgeKey;
})();
