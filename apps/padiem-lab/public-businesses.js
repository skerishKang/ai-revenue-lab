(function (root, factory) {
  "use strict";
  var manifest = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = manifest;
  } else {
    root.PADIEM_LAB_BUSINESSES = manifest;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return Object.freeze([
    Object.freeze({
      number: 1,
      slug: "personal-edition",
      title: "Personal Edition",
      koreanTitle: "퍼스널 에디션",
      summary: "흩어진 기록을 한 호의 개인 에디션으로 묶고, 쓰기·읽기·피드백의 흐름을 합성 데이터로 탐색하는 정적 제품 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b01/",
      sourcePath: "apps/personal-edition/scripts/build_static_production.py"
    }),
    Object.freeze({
      number: 2,
      slug: "living-travel",
      title: "Living Travel",
      koreanTitle: "리빙 트래블",
      summary: "취향과 여행 속도에 따라 부산의 장소·동선·여행판이 달라지는 흐름을 합성 데이터로 탐색하는 정적 여행 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b02/",
      sourcePath: "apps/living-travel/pages-preview/site/"
    }),
    Object.freeze({
      number: 4,
      slug: "living-learning",
      title: "Living Learning",
      koreanTitle: "리빙 러닝",
      summary: "10분 AI·Python 수업과 이해도·학습 방식 피드백이 다음 수업에 어떻게 반영되는지 합성 데이터로 탐색하는 정적 학습 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b04/",
      sourcePath: "apps/living-learning/pages-preview/"
    }),
    Object.freeze({
      number: 6,
      slug: "world-feed",
      title: "World Feed",
      koreanTitle: "나의 세계 편집면",
      summary: "전 세계 소식 중 내 관심사와 가까운 이야기를 합성 로컬 콘텐츠와 세션 상태만으로 개인 브리프처럼 탐색하는 프론트엔드 경험입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b06/",
      sourcePath: "reference/business-06-world-feed-v1/"
    }),
    Object.freeze({
      number: 7,
      slug: "personal-meaning-map",
      title: "Personal Meaning Map",
      koreanTitle: "개인 의미 지도",
      summary: "기억 조각 사이의 반복되는 의미를 연결하고 직접 검토하는 개인 의미 필드입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b07/",
      sourcePath: "reference/business-07-personal-meaning-map-v1/"
    }),
    Object.freeze({
      number: 8,
      slug: "family-newspaper",
      title: "Family Newspaper",
      koreanTitle: "우리 가족 신문",
      summary: "사진·메모·일정을 한 호의 디지털 가족 신문으로 편집해 다시 읽는 경험입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b08/",
      sourcePath: "reference/business-08-family-newspaper-v1/"
    }),
    Object.freeze({
      number: 9,
      slug: "personalized-childrens-story",
      title: "Personalized Children's Story",
      koreanTitle: "우리 아이 이야기",
      summary: "아이의 선택에 따라 다음 장면과 질문이 달라지는 참여형 이야기 경험입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b09/",
      sourcePath: "reference/business-09-personalized-childrens-story-v1/"
    }),
    Object.freeze({
      number: 10,
      slug: "fan-magazine",
      title: "Fan Magazine",
      koreanTitle: "나만의 팬 매거진",
      summary: "다시 찾은 공개 장면과 그 이유를 한 호의 개인 팬 에디션으로 편집합니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b10/",
      sourcePath: "reference/business-10-fan-magazine-v1/"
    }),
    Object.freeze({
      number: 11,
      slug: "language-learning-magazine",
      title: "Language Learning Magazine",
      koreanTitle: "나의 언어학습 매거진",
      summary: "짧은 읽기에서 표현을 발견하고 한 문장을 다시 쓰며 학습 포인트를 남기는 개인 언어 저널입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b11/",
      sourcePath: "reference/business-11-language-learning-magazine-v1/"
    }),
    Object.freeze({
      number: 12,
      slug: "creator-mini-media",
      title: "Creator Mini-Media",
      koreanTitle: "크리에이터 미니미디어",
      summary: "하나의 아이디어를 기사·숏폼·오디오 제작 단위로 나누고 사람 검토 후 패키지로 묶는 창작 데스크입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b12/",
      sourcePath: "reference/business-12-creator-mini-media-v1/"
    }),
    Object.freeze({
      number: 13,
      slug: "personal-video-archive",
      title: "Personal Video Archive",
      koreanTitle: "나의 영상 아카이브",
      summary: "관심 주제별 공개 영상을 발견하고 시청 상태·메모·회고 흐름을 합성 데이터로 탐색하는 생성형 정적 UI 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b13/",
      sourcePath: "apps/personal-video-archive/scripts/build_static_preview.py"
    }),
    Object.freeze({
      number: 14,
      slug: "korean-ai-platform",
      title: "Korean AI Platform",
      koreanTitle: "한국형 AI 모델 플랫폼",
      summary: "여러 AI 모델과 공급자를 한국어 중심의 하나의 모델 접근 경험으로 연결합니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b14/",
      currentPublicUrl: "https://ai-revenue-korean-ai-platform.charliekant.workers.dev/workspace"
    }),
    Object.freeze({
      number: 15,
      slug: "global-ai-newsroom",
      title: "Global AI Newsroom",
      koreanTitle: "글로벌 AI 뉴스룸",
      summary: "주장·출처·불확실성을 한 화면에서 비교하고 사람 검토를 거쳐 브리핑으로 정리하는 검증 데스크입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b15/",
      sourcePath: "reference/business-15-global-ai-newsroom-v1/"
    }),
    Object.freeze({
      number: 16,
      slug: "personal-sports",
      title: "Personal Sports",
      koreanTitle: "나의 스포츠 채널",
      summary: "관심 경기의 시간순 흐름을 보고 내게 남은 장면만 세션 안에서 기록하는 매치데이 저널입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b16/",
      sourcePath: "reference/business-16-personal-sports-v1/"
    }),
    Object.freeze({
      number: 17,
      slug: "local-shop-magazine",
      title: "Local Shop Magazine",
      koreanTitle: "로컬 숍 매거진",
      summary: "가게의 작은 장면과 점주의 한 문장을 짧은 기사로 편집하고 가격·사람·과장 표현을 교정하는 로컬 매거진입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b17/",
      sourcePath: "reference/business-17-local-shop-magazine-v1/"
    }),
    Object.freeze({
      number: 18,
      slug: "personal-audio-channel",
      title: "Personal Audio Channel",
      koreanTitle: "나의 오디오 채널",
      summary: "합성 장면을 듣는 순서로 엮고 다시 찾을 순간을 세션 안에서 표시하는 개인 Listening Room입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b18/",
      sourcePath: "reference/business-18-personal-audio-channel-v1/"
    }),
    Object.freeze({
      number: 19,
      slug: "personal-memory-book",
      title: "Personal Memory Book",
      koreanTitle: "개인 기억책",
      summary: "합성 기억 조각을 장으로 묶고 근거와 해석의 경계를 확인하며 한 권의 기억책 흐름으로 편집합니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b19/",
      sourcePath: "reference/business-19-personal-memory-book-v1/"
    }),
    Object.freeze({
      number: 20,
      slug: "personal-memory-novel",
      title: "Personal Memory Novel",
      koreanTitle: "개인 기억소설",
      summary: "합성 기억을 시점과 장면 단위로 엮되 사실과 서사적 표현을 구분해 검토하는 Memory Manuscript Studio입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b20/",
      sourcePath: "reference/business-20-personal-memory-novel-v1/"
    }),
    Object.freeze({
      number: 21,
      slug: "founder-strategy-letter",
      title: "Founder Strategy Letter",
      koreanTitle: "창업자 전략 편지",
      summary: "주간 신호와 반론을 함께 비교하고 현재 결정을 고른 뒤 재검토 조건까지 남기는 전략 판단 편지입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b21/",
      sourcePath: "reference/business-21-founder-strategy-letter-v1/"
    }),
    Object.freeze({
      number: 22,
      slug: "personal-media-studio",
      title: "Personal Media Studio",
      koreanTitle: "개인 미디어 스튜디오",
      summary: "하나의 합성 원자료 묶음에서 Story Spine을 고정하고 기사·오디오·영상·카드 에디션의 Source Trace를 관리합니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b22/",
      sourcePath: "reference/business-22-personal-media-studio-v1/"
    }),
    Object.freeze({
      number: 23,
      slug: "lovebud",
      title: "LoveBud",
      koreanTitle: "러브버드",
      summary: "사람과 관계의 맥락을 이어가는 독립 제품 프로젝트입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b23/",
      currentPublicUrl: "https://lovebud.pages.dev/"
    }),
    Object.freeze({
      number: 24,
      slug: "lovetree-3",
      title: "LoveTree 3.0",
      koreanTitle: "러브트리 3.0",
      summary: "기억과 관계를 시각적으로 탐색하고 축적하는 LoveTree 제품 계열입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b24/",
      currentPublicUrl: "https://lovetree3.pages.dev/"
    }),
    Object.freeze({
      number: 30,
      slug: "civic-ai-navigator",
      title: "Civic AI Navigator",
      koreanTitle: "시민 AI 내비게이터",
      summary: "광주 북구청 민원 정보를 자연어로 찾고 필요한 절차와 담당 경로를 안내하는 독립 AI Finder 제품입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b30/",
      currentPublicUrl: "https://cgbukku.pages.dev/"
    }),
    Object.freeze({
      number: 32,
      slug: "ai-skill-studio",
      title: "AI Skill Studio",
      koreanTitle: "AI 업무 실습실",
      summary: "합성 업무를 근거 확인·역할 인계·사람 검토까지 실행해 재사용 가능한 조직 AI 스킬 카드로 남기는 브라우저 메모리 기반 정적 실습입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b32/",
      sourcePath: "reference/business-32-ai-skill-studio-ux/"
    }),
    Object.freeze({
      number: 35,
      slug: "ai-media-education-dx",
      title: "AI Media Education & DX",
      koreanTitle: "AI 미디어 교육·DX",
      summary: "조직의 미디어 업무 병목을 진단하고 새 업무 흐름·사람 검토 지점·6주 파일럿을 합성 데이터로 조립하는 파디엠의 정적 업무전환 스튜디오입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b35/",
      sourcePath: "reference/business-35-ai-media-education-dx-v3/"
    }),
    Object.freeze({
      number: 36,
      slug: "ai-women-safety",
      title: "AI Women Safety",
      koreanTitle: "AI 여성안전 서비스",
      summary: "합성 개인안전 시나리오에서 사용자 보고·관찰·불확실성을 분리하고, bounded options와 trusted-contact 계획을 사람 검토 안전대응 브리프로 정리하는 정적 시각 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b36/",
      sourcePath: "reference/business-36-ai-women-safety-v1/"
    }),
    Object.freeze({
      number: 37,
      slug: "ai-safe-route",
      title: "AI Safe Route",
      koreanTitle: "AI 안전경로",
      summary: "합성 이동 맥락에서 경로 대안의 환경 근거·불확실성·접근성·fallback을 병치하고 사람이 조건부로 검토하는 안전경로 시각 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b37/",
      sourcePath: "reference/business-37-ai-safe-route-v1/"
    }),
    Object.freeze({
      number: 39,
      slug: "112-real-time-interpretation",
      title: "112 Real-Time Interpretation",
      koreanTitle: "112 실시간 AI 통역",
      summary: "합성 긴급신고 발화·미확인 전사·통역 초안·중요 용어와 사람 교정 이력을 분리해 이중언어 기록으로 검토하는 정적 시각 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b39/",
      sourcePath: "reference/business-39-112-real-time-interpretation-v1/"
    }),
    Object.freeze({
      number: 48,
      slug: "ai-verification-engine",
      title: "AI Verification Engine",
      koreanTitle: "AI 검증·승인 엔진",
      summary: "작업자 주장·자체검사·독립검사·증거·검증자 판단·사람 승인을 분리해 정확한 버전에 한정된 검증 기록으로 검토하는 정적 시각 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b48/",
      sourcePath: "reference/business-48-ai-verification-engine-v1/"
    }),
    Object.freeze({
      number: 52,
      slug: "scheduled-agent-operations",
      title: "Scheduled Agent Operations",
      koreanTitle: "예약형 AI 운영",
      summary: "합성 예약 운영을 timezone·cadence·조건·실행 결과·예외·재시도·중복 방지·사람 승인 경계가 분명한 runbook으로 검토하는 정적 시각 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b52/",
      sourcePath: "reference/business-52-scheduled-agent-operations-v1/"
    }),
    Object.freeze({
      number: 53,
      slug: "embedded-ai-sdk",
      title: "Embedded AI SDK",
      koreanTitle: "임베드 AI SDK",
      summary: "합성 호스트 제품의 삽입 지점·입출력 계약·최소권한·호환성·fail-closed fallback·사람 release authority를 검토하는 정적 임베드 통합 명세 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b53/",
      sourcePath: "reference/business-53-embedded-ai-sdk-v1/"
    }),
    Object.freeze({
      number: 55,
      slug: "local-ai-fleet",
      title: "Local AI Fleet",
      koreanTitle: "로컬 AI 플릿",
      summary: "합성 로컬 AI 플릿의 모델 격리·워커 상태·작업 큐·용량·사고·재시도·사람 release authority를 명시적으로 검토하는 정적 운영 계획 프리뷰입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b55/",
      sourcePath: "reference/business-55-local-ai-fleet-v1/"
    }),
    Object.freeze({
      number: 59,
      slug: "living-archive",
      title: "Living Archive",
      koreanTitle: "나의 기록서재",
      summary: "합성 로컬 기록을 3D 서가에서 찾아 2D 정밀 리더로 이어 읽고, 검색·책갈피·세션 메모를 브라우저 메모리에서 탐색하는 정적 기록서재 MVP입니다.",
      publicStatus: "PREVIEW",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b59/",
      sourcePath: "reference/business-59-living-archive-v1/"
    }),
    Object.freeze({
      number: 60,
      slug: "ai-free-radar",
      title: "AI Free Radar",
      koreanTitle: "AI 무료 레이더",
      summary: "지금 무료로 사용할 수 있는 AI 모델·API·크레딧 기회를 빠르게 찾아 검증해 보여줍니다.",
      publicStatus: "LIVE",
      routeKind: "LOCAL_STATIC",
      targetPath: "/b60/",
      sourcePath: "reference/business-60-ai-api-v1/"
    }),
    Object.freeze({
      number: 62,
      slug: "padiem-chat",
      title: "Padiem Chat",
      koreanTitle: "파디엠 챗",
      summary: "누구나 설명 없이 바로 질문하고 검색하고 파일을 다룰 수 있도록 만드는 파디엠의 기본 AI입니다.",
      publicStatus: "LIVE",
      routeKind: "EXTERNAL_RUNTIME",
      targetPath: "/b62/",
      currentPublicUrl: "https://padiem-chat.charliekant.workers.dev/"
    })
  ]);
});
