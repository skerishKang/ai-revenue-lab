(() => {
  if (document.documentElement.lang !== 'ko') return;

  const exact = new Map([
    ['SIGNAL', '정보'], ['SOURCE', '출처'],
    ['Discover', '탐색'], ['DISCOVER', '탐색'],
    ['Providers', '제공사'], ['PROVIDERS', '제공사'],
    ['Models', '모델'], ['MODELS', '모델'],
    ['Connect', '연결'], ['CONNECT', '연결'],
    ['Watch', '관심 목록'], ['WATCH', '관심 목록'], ['WATCHLIST', '관심 목록'], ['WATCHING', '관심 목록'],
    ['FREE NOW', '지금 무료'], ['NEW TODAY', '오늘 추가'], ['ENDING SOON', '종료 임박'], ['CHANGES', '변경 기록'], ['ALL ACCESS', '전체 경로'],
    ['NOW', '현재'], ['EXPIRING', '종료 임박'], ['ACCESS', '접근 방식'],
    ['OFFICIAL', '공식 확인'], ['VERIFIED', '확인 완료'], ['VERIFIED_OFFICIAL_WEB', '공식 확인 완료'],
    ['PENDING WEB VERIFICATION', '추가 확인 필요'], ['PENDING_WEB_VERIFICATION', '추가 확인 필요'],
    ['OFFICIAL_SOURCE_SNAPSHOT', '공식 출처 스냅샷'],
    ['RECURRING_CREDIT', '정기 크레딧'], ['PERMANENT_FREE', '상시 무료'], ['FREE_MODEL', '무료 모델'],
    ['PROVIDER', '제공사'], ['MODEL', '모델'], ['MODEL ID', '모델 ID'], ['ROUTE ID', '경로 ID'],
    ['ACCESS ROUTE', '접근 경로'], ['ROUTE', '경로'], ['ROUTE COMPARE', '경로 비교'], ['COMPARE ACCESS ROUTES', '접근 경로 비교'],
    ['PRICE', '가격'], ['CONTEXT', '컨텍스트'], ['RUNTIME', '실행 상태'], ['EXECUTION', '실행 상태'],
    ['CURRENT ACCESS', '현재 이용 조건'], ['SOURCE CONFIDENCE', '출처 신뢰도'], ['SOURCE STATE', '출처 상태'],
    ['ENTITY CONTEXT', '제공사·모델 정보'], ['LATEST RECORDED ACTIVITY', '최근 기록'],
    ['INFO ONLY', '정보만 제공'], ['DISCOVERY ONLY', '정보만 제공'], ['ROUTER MAPPED', '실행 경로 연결됨'],
    ['CONNECTABLE', '연결 가능'], ['CONNECTED', '연결됨'], ['DISCOVERY → EXECUTION', '탐색 → 실행'],
    ['SAVE', '저장'], ['SAVED', '저장됨'], ['SELECTED', '선택됨'], ['COMPARE', '비교'], ['REMOVE', '제외'],
    ['OPEN ROUTE', '경로 열기'], ['VIEW PROVIDER', '제공사 보기'], ['VIEW ROUTES', '경로 보기'],
    ['ALL PROVIDERS', '전체 제공사'], ['ALL MODELS', '전체 모델'],
    ['OFFICIAL SOURCE', '공식 출처'], ['OPEN SOURCE LAYER', '출처와 근거 보기'],
    ['HANDOFF DETAILS', '실행 경로 상세'], ['EXECUTION HANDOFF', '실행 연결 정보'],
    ['DISCOVERY ROUTE', '탐색 경로'], ['API KEY', 'API 키'], ['EXECUTION PATH', '실행 경로'], ['EXECUTION TARGET', '실행 대상'],
    ['BOUND', '연결됨'], ['NOT BOUND', '미연결'],
    ['VERIFIED END DATE', '공식 확인 종료일'], ['END DATE', '종료일'], ['NO VERIFIED END DATE', '확인된 종료일 없음'],
    ['EXECUTION ROUTE VERIFIED', '실행 경로 확인 완료'],
    ['COPY LINK', '링크 복사'], ['COPIED', '복사됨'], ['LINK READY', '링크 준비됨'],
    ['SAVED ROUTES', '저장한 경로'], ['WATCH ACTIVITY', '관심 경로 기록'], ['SAVED-ROUTE ACTIVITY', '저장 경로 기록'], ['CATALOG ACTIVITY', '전체 기록'],
    ['BASELINE', '기준선'], ['PENDING', '확인 중'], ['CHANGED', '변경됨'],
    ['FIRST_SEEN', '최초 확인'], ['PENDING_CLAIM_RECORDED', '확인 대기 기록'],
    ['NO HISTORY EVENT', '기록 없음'],
    ['CHANGE LEDGER', '변경 기록'], ['FIRST SEEN TODAY', '오늘 처음 확인'],
    ['SNAPSHOT', '스냅샷'], ['TRUTH-FIRST EXPIRY', '공식 종료일 우선'], ['ENDING SOON · TRUTH FIRST', '종료 임박 · 공식 확인 기준'],
    ['CHANGE ENGINE · BASELINE ONLY', '변경 추적 · 기준선만 있음'], ['VERIFIED DIFF', '확인된 변경'], ['REVIEW REQUIRED', '검토 필요'], ['NO CHANGE', '변경 없음'],
    ['ACCESS METHOD', '접근 방식'], ['LOCAL', '브라우저'], ['SESSION', '세션'], ['Unknown', '확인되지 않음'], ['UNKNOWN', '확인되지 않음'],
    ['Catalog / varies', '카탈로그 / 항목별 상이'], ['Current access', '현재 이용 조건'],
    ['LIVE ACCESS SIGNAL / 001', '현재 접근 정보 / 001'],
    ['GLM 5.2 access signal', 'GLM 5.2 접근 정보'],
    ['GLM 5.2 official model facts', 'GLM 5.2 공식 모델 정보'],
    ['Vercel Labs fx product identity', 'Vercel Labs fx 제품 정보'],
    ['exact fx promotion / end-date claim', 'fx 프로모션 종료일 주장'],
    ['VERCEL OFFICIAL MODEL PAGE ↗', 'VERCEL 공식 모델 페이지 ↗'], ['VERCEL LABS FX REPOSITORY ↗', 'VERCEL LABS FX 저장소 ↗'],
    ['ACCESS CHANGES THE WORLD', 'AI 접근의 모든 경로'], ['SCROLL', '스크롤'], ['GESTURE', '제스처'],
    ['MODEL', '모델'], ['ROUTE', '경로'], ['ACTION', '실행'], ['CREATE', '만들기'], ['PROVIDERS', '제공사'],
    ['available route', '이용 가능 경로'], ['cost · speed · access', '비용 · 속도 · 접근'], ['intent → code', '요청 → 코드'],
    ['touch the access layer', '접근 지점을 눌러 연결'],
    ['AI API primary product navigation', 'AI API 주요 탐색'], ['Current section views', '현재 화면 보기'],
    ['Access route comparison', '접근 경로 비교'], ['Close comparison', '비교 닫기'],
    ['Execution handoff details', '실행 연결 상세'], ['Close handoff details', '실행 연결 상세 닫기'],
    ['Access route detail', '접근 경로 상세'], ['Close route detail', '접근 경로 상세 닫기'], ['Close details', '상세 닫기'],
    ['provider / model / access', '제공사 / 모델 / 접근 방식'], ['search providers / models', '제공사 / 모델 검색'],
    ['search models / providers', '모델 / 제공사 검색'], ['search saved / changes', '저장 경로 / 변경 기록 검색'],
    ['search saved routes / providers / models', '저장 경로 / 제공사 / 모델 검색'], ['search recorded activity', '기록 검색'],
    ['ACCOUNT SYNC 없음 · 이 브라우저에만 저장', '계정 동기화 없음 · 이 브라우저에만 저장'],
    ['LOCAL STORAGE 사용 불가 · 현재 세션에서만 유지', '브라우저 저장소 사용 불가 · 현재 세션에서만 유지'],
    ['Primary-source expiry evidence is present.', '1차 공식 출처에서 종료일을 확인했습니다.'],
    ['Free on fx through 2026-08-27', 'fx 무료 프로모션 종료일: 2026-08-27 · 추가 확인 필요'],
    ['Varies by routed provider', '라우팅 제공사별 상이']
  ]);

  const register = (from, to) => {
    if (from != null && to != null && String(from) !== String(to)) exact.set(String(from), String(to));
    return to;
  };

  const signalCopy = {
    'vercel-glm52': {
      title: 'Vercel AI Gateway · GLM 5.2',
      freeLabel: '$5 크레딧 / 30일',
      summary: '결제 이력이 없는 Vercel 무료 사용자는 30일마다 AI Gateway 크레딧 $5를 받습니다.',
      context: '100만 토큰', price: '라우팅 제공사별 상이', access: ['API', 'AI 게이트웨이', 'CLI/에이전트'],
      facts: ['Vercel AI Gateway에서 GLM 5.2를 사용할 수 있습니다.', '모델 식별자: zai/glm-5.2.', '컨텍스트 길이: 100만 토큰.', 'AI Gateway는 GLM 5.2를 여러 제공사로 라우팅하며 요금은 제공사별로 다릅니다.', '결제 이력이 없는 무료 사용자는 30일마다 $5 크레딧을 받습니다.'],
      sources: ['Vercel · GLM 5.2 공식 페이지'],
      pendingLabel: 'fx 무료 프로모션 종료일: 8월 27일',
      pendingNote: '해당 종료일 주장은 현재 확보한 1차 공식 웹 근거에서 확인되지 않아 추가 확인 필요로 분리합니다.'
    },
    'google-gemini-free': {
      title: 'Gemini Developer API · 무료 티어', freeLabel: '무료 티어',
      summary: '대상 Gemini 모델을 무료 입력·출력 토큰 한도 내에서 사용할 수 있으며 Google AI Studio도 이용할 수 있습니다.',
      context: '모델별 상이', price: '무료 티어 제공', access: ['API', 'AI Studio'],
      facts: ['Google은 개발자와 소규모 프로젝트를 위한 무료 티어를 제공합니다.', '무료 티어에서는 일부 모델을 제한된 한도로 사용할 수 있습니다.', '대상 무료 티어 요청의 입력·출력 토큰은 무료입니다.', 'Google AI Studio를 함께 이용할 수 있습니다.'],
      sources: ['Google · Gemini API 요금']
    },
    'cloudflare-workers-ai-free': {
      title: 'Workers AI · 무료 할당량', freeLabel: '매일 10,000 neurons',
      summary: 'Workers AI는 유료 사용량이 시작되기 전에 매일 무료 사용량을 제공합니다.',
      model: 'Workers AI 카탈로그', context: '모델별 상이', price: '하루 10,000 neurons 무료', access: ['API', '클라우드 콘솔', 'Workers'],
      facts: ['Workers AI는 Free 및 Paid Workers 플랜에 포함됩니다.', '무료 할당량은 하루 10,000 neurons입니다.', '무료 할당량을 초과하면 Workers Paid가 필요합니다.', 'Cloudflare는 현재 무료 할당량 초과분을 1,000 neurons당 $0.011로 안내합니다.'],
      sources: ['Cloudflare · Workers AI 요금']
    },
    'groq-free-plan': {
      title: 'Groq API · 무료 플랜', freeLabel: '무료 플랜',
      summary: 'Groq는 모델별 무료 플랜 한도를 공개하며, 더 높은 한도가 필요한 경우 별도의 Developer 요금제로 업그레이드할 수 있습니다.',
      model: 'Groq 모델 카탈로그', context: '모델별 상이', price: '무료 플랜 한도 적용', access: ['API'],
      facts: ['Groq는 별도의 무료 플랜 요청 한도 표를 공개합니다.', '한도는 모델별로 다르며 RPM·RPD·TPM·TPD 항목으로 제공됩니다.', 'Developer 티어는 결제 수단을 사용하는 별도 업그레이드입니다.'],
      sources: ['Groq · 무료 플랜 한도', 'Groq · 결제 FAQ']
    },
    'openrouter-free-router': {
      title: 'OpenRouter · 무료 모델 접근', freeLabel: '하루 50회 요청',
      summary: '무료 플랜에서 무료 모델 API를 사용할 수 있으며, openrouter/free가 현재 이용 가능한 무료 모델로 요청을 라우팅합니다.',
      context: '라우터 컨텍스트 20만 토큰', price: '무료 라우터 입력·출력 토큰 $0', access: ['API', '라우터'],
      facts: ['OpenRouter 무료 플랜은 하루 50회 요청을 제공합니다.', 'openrouter/free 라우터는 현재 이용 가능한 무료 모델 중 하나를 선택합니다.', '무료 라우터 페이지에는 20만 토큰 컨텍스트 길이가 표시됩니다.', 'openrouter/free의 입력·출력 토큰 가격은 $0입니다.'],
      sources: ['OpenRouter · 요금', 'OpenRouter · 무료 모델 라우터']
    }
  };

  (window.B60_ACCESS_SIGNALS || []).forEach(signal => {
    const ko = signalCopy[signal.id];
    if (!ko) return;
    ['title', 'freeLabel', 'summary', 'model', 'context', 'price'].forEach(key => {
      if (Object.prototype.hasOwnProperty.call(ko, key)) signal[key] = register(signal[key], ko[key]);
    });
    if (ko.access) signal.access = (signal.access || []).map((value, index) => register(value, ko.access[index] ?? value));
    if (ko.facts) signal.facts = (signal.facts || []).map((value, index) => register(value, ko.facts[index] ?? value));
    if (ko.sources) (signal.sources || []).forEach((source, index) => { if (ko.sources[index]) source.label = register(source.label, ko.sources[index]); });
    if (signal.pending) {
      if (ko.pendingLabel) signal.pending.label = register(signal.pending.label, ko.pendingLabel);
      if (ko.pendingNote) signal.pending.note = register(signal.pending.note, ko.pendingNote);
    }
  });

  const deal = (window.B60_DEALS || [])[0];
  if (deal) {
    deal.accessSurface = register(deal.accessSurface, 'fx / AI Gateway 접근 정보');
    deal.headline = register(deal.headline, 'GLM 5.2 접근 정보');
    deal.promoClaim = register(deal.promoClaim, 'fx 무료 프로모션 종료일: 2026-08-27 · 추가 확인 필요');
    const facts = ['Vercel AI Gateway에서 GLM 5.2를 사용할 수 있습니다.', '공식 모델 식별자: zai/glm-5.2.', '컨텍스트 길이: 100만 토큰.', 'AI Gateway는 GLM 5.2를 여러 제공사로 라우팅하며 요금은 제공사별로 다릅니다.', '결제 이력이 없는 무료 사용자는 30일마다 AI Gateway 크레딧 $5를 받습니다.'];
    deal.verifiedFacts = (deal.verifiedFacts || []).map((value, index) => register(value, facts[index] ?? value));
    const fxFacts = ['fx는 Vercel Labs의 오픈소스 코딩 에이전트입니다.', 'fx는 Vercel 로그인과 AI Gateway API 키 설정을 지원합니다.'];
    deal.fxFacts = (deal.fxFacts || []).map((value, index) => register(value, fxFacts[index] ?? value));
    deal.note = register(deal.note, 'GLM 5.2와 fx 제품 자체 정보는 공식 출처로 확인했습니다. 다만 fx 프로모션 종료일은 아직 1차 공식 출처 확인이 끝나지 않아 별도로 표시합니다.');
  }

  const historyCopy = {
    'vercel-glm52': ['공식 출처를 바탕으로 GLM 5.2 / Vercel AI Gateway 접근 정보를 카탈로그에 추가했습니다.', 'fx 무료 프로모션이 8월 27일까지라는 정보를 1차 공식 출처 확인 대기 상태로 분리 기록했습니다.'],
    'google-gemini-free': ['Google 공식 요금 문서를 바탕으로 Gemini Developer API 무료 티어를 추가했습니다.'],
    'cloudflare-workers-ai-free': ['Cloudflare 공식 요금 문서를 바탕으로 Workers AI의 일일 무료 할당량을 추가했습니다.'],
    'groq-free-plan': ['Groq 공식 요청 한도 및 결제 문서를 바탕으로 무료 플랜을 추가했습니다.'],
    'openrouter-free-router': ['OpenRouter 공식 요금 및 모델 페이지를 바탕으로 무료 플랜과 openrouter/free 경로를 추가했습니다.']
  };
  (window.B60_SIGNAL_HISTORY || []).forEach(item => {
    const copy = historyCopy[item.id] || [];
    (item.events || []).forEach((event, index) => { if (copy[index]) event.summary = register(event.summary, copy[index]); });
  });

  const regex = [
    [/^(\d+) signals$/, '$1개 정보'], [/^(\d+) providers$/, '$1개 제공사'], [/^(\d+) official$/, '$1개 공식 확인'],
    [/^(\d+) free\/credit paths$/, '$1개 무료/크레딧 경로'], [/^(\d+) known routes$/, '$1개 확인된 경로'],
    [/^(\d+) routes$/, '$1개 경로'], [/^(\d+) model entries$/, '$1개 모델 항목'], [/^(\d+) free\/credit$/, '$1개 무료/크레딧'],
    [/^(\d+) models\/catalog entries$/, '$1개 모델/카탈로그 항목'], [/^(\d+) access routes$/, '$1개 접근 경로'],
    [/^(\d+) free\/credit routes$/, '$1개 무료/크레딧 경로'], [/^(\d+) models$/, '$1개 모델'],
    [/^(\d+) router mapped$/, '$1개 실행 경로 연결'], [/^(\d+) info only$/, '$1개 정보만 제공'],
    [/^(\d+) saved routes$/, '$1개 저장 경로'], [/^(\d+) saved-route events$/, '$1개 저장 경로 기록'],
    [/^(\d+) verified changes$/, '$1개 확인된 변경'], [/^(\d+) pending evidence$/, '$1개 확인 대기 근거'], [/^(\d+) catalog events$/, '$1개 전체 기록'],
    [/^(\d+) history events$/, '$1개 이력'], [/^(\d+) tracked signals$/, '$1개 추적 정보'],
    [/^(\d+) new today$/, '$1개 오늘 추가'], [/^(\d+) current records$/, '$1개 현재 기록'],
    [/^(\d+) ending ≤ 7 days$/, '$1개 7일 이내 종료'], [/^(\d+) checked records$/, '$1개 확인 기록'],
    [/^(\d+) snapshot diffs$/, '$1개 스냅샷 변경'], [/^(\d+) snapshots$/, '$1개 스냅샷'],
    [/^(\d+) watched$/, '$1개 관심 경로'], [/^(\d+) saved total$/, '$1개 전체 저장'],
    [/^(\d+) provider route$/, '$1개 제공사 경로'], [/^(\d+) provider routes$/, '$1개 제공사 경로'],
    [/^(\d+) captured · (\d+) records · (\d+) verified diffs$/, '$1개 저장 · $2개 기록 · $3개 확인된 변경'],
    [/^Open (.+) details$/, '$1 상세 보기']
  ];

  const generic = [
    [/\bProviders?\b/g, '제공사'], [/\bModels?\b/g, '모델'], [/\broutes?\b/gi, '경로'], [/\bcatalog\b/gi, '카탈로그'],
    [/\bsnapshots?\b/gi, '스냅샷'], [/\bsignals?\b/gi, '정보'], [/\bsources?\b/gi, '출처'], [/\bcontext\b/gi, '컨텍스트'],
    [/\bfree\/credit\b/gi, '무료/크레딧'], [/\bbefore → after\b/gi, '변경 전 → 변경 후'], [/\binfo-only\b/gi, '정보만 제공'],
    [/\bverified\b/gi, '확인'], [/\bofficial\b/gi, '공식'], [/\bWatch\b/g, '관심 목록']
  ];

  function translate(value) {
    if (value == null) return value;
    const raw = String(value);
    const lead = raw.match(/^\s*/)?.[0] || '';
    const tail = raw.match(/\s*$/)?.[0] || '';
    const core = raw.trim();
    if (!core) return raw;
    let out = exact.get(core) || core;
    if (out === core) {
      for (const [pattern, replacement] of regex) {
        if (pattern.test(out)) { out = out.replace(pattern, replacement); break; }
      }
    }
    for (const [pattern, replacement] of generic) out = out.replace(pattern, replacement);
    return `${lead}${out}${tail}`;
  }

  function translateAttrs(element) {
    if (!(element instanceof Element)) return;
    ['placeholder', 'title', 'aria-label'].forEach(name => {
      if (!element.hasAttribute(name)) return;
      const before = element.getAttribute(name);
      const after = translate(before);
      if (after !== before) element.setAttribute(name, after);
    });
  }

  function translateTextNode(node) {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    if (node.parentElement?.closest('script,style,pre')) return;
    const before = node.nodeValue;
    const after = translate(before);
    if (after !== before) node.nodeValue = after;
  }

  function translateTree(root) {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) return translateTextNode(root);
    if (!(root instanceof Element) && root !== document.body) return;
    if (root instanceof Element) translateAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) translateTextNode(node);
    if (root.querySelectorAll) root.querySelectorAll('*').forEach(translateAttrs);
  }

  document.title = 'AI API — 검증된 AI 접근 경로';
  translateTree(document.body);

  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') translateTextNode(record.target);
      else if (record.type === 'attributes') translateAttrs(record.target);
      else record.addedNodes.forEach(translateTree);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label'] });

  window.B60_KO_UI = Object.freeze({ translate });
})();
