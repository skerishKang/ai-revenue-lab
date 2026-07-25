window.ARL_PROJECTS = [
  {
    id: "portfolio-console",
    name: "Portfolio Console",
    koreanName: "포트폴리오 콘솔",
    businessNumber: null,
    purpose: "AI Revenue Lab의 모든 프로젝트와 Business를 한 화면에서 확인하는 개인용 관리 콘솔입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/portfolio-console/",
    pageUrl: "https://ai-revenue-portfolio-console.pages.dev",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "pc-project-directory",
        name: "Project Directory",
        done: true,
        evidence: "PR #134 merged — Project Directory 기본 구현"
      },
      {
        id: "pc-open-service-links",
        name: "Open service links",
        done: true,
        evidence: "PR #141 merged — 카드에서 서비스 URL 직접 오픈"
      },
      {
        id: "pc-issue-140",
        name: "검증된 마일스톤 진행률",
        done: true,
        evidence: "PR #140 작업 현재 브랜치"
      }
    ],
    currentMilestone: ["#140"],
    progressNote: "Cloudflare Pages에 배포 완료. Cloudflare Access 인증 후 접근 가능.",
    currentWork: "Project Directory 기능 추가 (Issue #132)",
    nextAction: "Project Directory 검증 후 병합",
    blockers: [],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "lovebud",
    name: "LoveBud",
    koreanName: "러브버드",
    businessNumber: null,
    purpose: "커플·가족의 일상 기록과 공유를 위한 개인용 웹 서비스입니다.",
    repositoryLabel: "skerishKang/LoveBud",
    repositoryUrl: "https://github.com/skerishKang/LoveBud",
    workspace: "/",
    pageUrl: "https://lovebud.pages.dev/",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "lb-auth-audit",
        name: "Architecture audit",
        done: false,
        evidence: "#3425 OPEN — architecture audit 진행 중"
      },
      {
        id: "lb-migration-ledger",
        name: "Migration ledger",
        done: false,
        evidence: "#3458 OPEN — migration ledger 및 provenance gate 미완료"
      },
      {
        id: "lb-provenance-gate",
        name: "Provenance gate",
        done: false,
        evidence: "#3458 OPEN — provenance gate 미완료"
      },
      {
        id: "lb-auth-css-cache",
        name: "Auth CSS cache busting",
        done: true,
        evidence: "#3451 CLOSED/COMPLETED"
      },
      {
        id: "lb-tree-owner-binding",
        name: "Tree owner binding",
        done: true,
        evidence: "#3481 CLOSED/COMPLETED"
      },
      {
        id: "lb-scout-target-tree",
        name: "Scout target tree selection",
        done: true,
        evidence: "PR #3531 merge commit e0ff1b2a4089c31fe4adb3e9c082ef9a4499a1cf"
      }
    ],
    currentMilestone: ["#3425", "#3458"],
    progressNote: "Cloudflare Pages에 배포 완료. OPEN parent Issue를 완료 evidence로 사용하지 않음.",
    currentWork: "현재 작업 없음",
    nextAction: "기능 확장 계획 수립",
    blockers: ["#3425 OPEN", "#3458 OPEN"],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "personal-edition",
    name: "Personal Edition",
    koreanName: "퍼스널 에디션",
    businessNumber: 1,
    purpose: "개인 맞춤형 AI 어시스턴트 서비스의 프로토타입입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/personal-edition/",
    pageUrl: "https://feat-personal-edition-final.ai-revenue-personal-edition.pages.dev",
    stage: "review",
    developmentMode: "needs-improvement",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "pe-implementation",
        name: "Implementation",
        done: true,
        evidence: "PR #111 head 3f44ac725c1b946776ae41d3b25bc8c2d56df626"
      },
      {
        id: "pe-ctoreview",
        name: "CTO review",
        done: false,
        evidence: "CTO review pending"
      },
      {
        id: "pe-merge",
        name: "Merge",
        done: false,
        evidence: ""
      },
      {
        id: "pe-production",
        name: "Production deployment",
        done: false,
        evidence: ""
      }
    ],
    currentMilestone: ["PR #111"],
    progressNote: "Draft PR #111 검토 중. CTO 변경 요청 대기.",
    currentWork: "시각 및 클릭 흐름 차단 요소 수정",
    nextAction: "PR #111 재검토",
    blockers: ["PR #111 OPEN Draft, mergeable: false"],
    futureRoadmap: ["CTO review", "Merge", "Production deployment"],
    lastVerified: "2026-07-25"
  },
  {
    id: "living-travel",
    name: "Living Travel",
    koreanName: "리빙 트래블",
    businessNumber: 2,
    purpose: "여행자·운영자용 AI 여행 계획 및 실행 서비스입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/living-travel/",
    pageUrl: "https://ops-living-travel-external-s.ai-revenue-living-travel.pages.dev",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "lt-local-provider-spike",
        name: "Local provider spike",
        done: true,
        evidence: "Issue #107 comment 5071926646 — local provider spike succeeded"
      },
      {
        id: "lt-remote-workflow",
        name: "Remote commit/PR",
        done: false,
        evidence: "원격 PR·commit 없음"
      },
      {
        id: "lt-full-workflow",
        name: "Full workflow complete",
        done: false,
        evidence: ""
      }
    ],
    currentMilestone: ["#107"],
    progressNote: "Cloudflare Pages + Modal + Neon 스택으로 배포 완료.",
    currentWork: "현재 작업 없음",
    nextAction: "60–90초 데모 시퀀스 준비",
    blockers: ["원격 PR·commit 없음"],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "living-fiction",
    name: "Living Fiction",
    koreanName: "리빙 픽션",
    businessNumber: 3,
    purpose: "AI 기반 인터랙티브 소설·스토리 생성 서비스입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/living-fiction/",
    pageUrl: null,
    stage: "live",
    developmentMode: "needs-improvement",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "lf-deployment-reverification",
        name: "배포 재검증",
        done: false,
        evidence: "기존 Modal 주소 404 — 배포 재검증 필요"
      }
    ],
    currentMilestone: [],
    progressNote: "기존 Modal 배포 주소가 응답하지 않아(404) 배포 재검증이 필요함.",
    currentWork: "현재 작업 없음",
    nextAction: "합성 초대 자격 증명 및 데모 데이터 초기화 절차 문서화",
    blockers: ["배포 주소 404"],
    futureRoadmap: ["배포 재검증"],
    lastVerified: "2026-07-25"
  },
  {
    id: "living-learning",
    name: "Living Learning",
    koreanName: "리빙 러닝",
    businessNumber: 4,
    purpose: "AI 적응형 학습·레슨 생성 서비스입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/living-learning/",
    pageUrl: "https://ai-revenue-living-learning.pages.dev/",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "ll-static-demo",
        name: "정적 데모 배포",
        done: true,
        evidence: "Cloudflare Pages 정적 데모 배포 완료"
      },
      {
        id: "ll-adaptive-lesson",
        name: "적응형 레슨 데모",
        done: false,
        evidence: "첫 레슨에서 적응형 레슨 데모 내레이션 표준화 필요"
      }
    ],
    currentMilestone: [],
    progressNote: "Cloudflare Pages 정적 데모로 배포 완료.",
    currentWork: "현재 작업 없음",
    nextAction: "첫 레슨 → 적응형 레슨 데모 내레이션 표준화",
    blockers: [],
    futureRoadmap: ["적응형 레슨"],
    lastVerified: "2026-07-25"
  },
  {
    id: "personal-video-archive",
    name: "Personal Video Archive",
    koreanName: "나의 영상 아카이브",
    businessNumber: 13,
    purpose: "개인 영상 컬렉션의 아카이빙 및 검색 서비스입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/personal-video-archive/",
    pageUrl: "https://feat-personal-video-archive.ai-revenue-personal-video-archive.pages.dev",
    stage: "demo",
    developmentMode: "needs-improvement",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "pva-branch-preview",
        name: "Branch preview",
        done: true,
        evidence: "병합된 브랜치 프리뷰 배포 완료"
      },
      {
        id: "pva-production",
        name: "고정 Production",
        done: false,
        evidence: "고정 Production 미확보"
      }
    ],
    currentMilestone: [],
    progressNote: "병합된 브랜치 프리뷰로 배포 완료. 고정 Production 미확보 상태.",
    currentWork: "현재 작업 없음",
    nextAction: "병합된 프리뷰 검증 및 다음 프로덕션 인프라 범위 결정",
    blockers: ["고정 Production 미확보"],
    futureRoadmap: ["고정 Production"],
    lastVerified: "2026-07-25"
  },
  {
    id: "lovetree-3",
    name: "LoveTree 3.0",
    koreanName: "러브트리 3.0",
    businessNumber: null,
    purpose: "가계도·가족 관계 시각화 및 관리 서비스의 3세대 버전입니다.",
    repositoryLabel: "skerishKang/lovetree3.0",
    repositoryUrl: "https://github.com/skerishKang/lovetree3.0",
    workspace: "/",
    pageUrl: "https://lovetree3.pages.dev/",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "undefined",
    milestoneTasks: [],
    currentMilestone: [],
    progressNote: "Cloudflare Pages에 배포 완료. 검증된 새 마일스톤 없음.",
    currentWork: "현재 작업 없음",
    nextAction: "기능 확장 계획 수립",
    blockers: [],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "korean-ai-platform",
    name: "Korean AI Platform",
    koreanName: "한국형 AI 실행 플랫폼",
    businessNumber: 14,
    purpose: "한국어 특화 AI 실행 환경 및 BYOK(Bring Your Own Key) 게이트웨이입니다.",
    repositoryLabel: "skerishKang/ai-revenue-lab",
    repositoryUrl: "https://github.com/skerishKang/ai-revenue-lab",
    workspace: "apps/korean-ai-platform/",
    pageUrl: null,
    stage: "review",
    developmentMode: "needs-improvement",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "kap-dedicated-worker",
        name: "Dedicated Worker 배포",
        done: true,
        evidence: "PR #142 merged — d8714ad4dddf605dde09a78937d52b2166258e7c, #138 CLOSED/COMPLETED"
      },
      {
        id: "kap-provider-registry",
        name: "Provider registry",
        done: false,
        evidence: "Provider registry 미설정, 실제 chat 비활성"
      }
    ],
    currentMilestone: ["#142", "#138"],
    progressNote: "PR #142 병합 완료. dedicated Worker 배포 완료. Provider registry 미설정, 실제 chat 비활성 상태.",
    currentWork: "Provider registry 구성 및 BYOK chat 활성화",
    nextAction: "Provider registry 구성 및 실제 BYOK chat 활성화",
    blockers: ["Provider registry 미설정", "실제 chat 비활성"],
    futureRoadmap: ["Provider registry", "BYOK chat 활성화"],
    lastVerified: "2026-07-25"
  },
  {
    id: "ai-finder-bukgu",
    name: "AI Finder / 광주 북구청",
    koreanName: "AI 파인더 / 광주 북구청",
    businessNumber: null,
    purpose: "광주 북구청 대상 AI 기반 정보 검색·안내 서비스입니다.",
    repositoryLabel: "skerishKang/400-ai-finder",
    repositoryUrl: "https://github.com/skerishKang/400-ai-finder",
    workspace: "/",
    pageUrl: "https://cgbukku.pages.dev/",
    stage: "live",
    developmentMode: "active-development",
    progressBasis: "task",
    milestoneStatus: "defined",
    milestoneTasks: [
      {
        id: "af-official-source-freshness",
        name: "Official source freshness",
        done: false,
        evidence: "#1150 OPEN"
      },
      {
        id: "af-page-agent-parity",
        name: "Page agent parity integration",
        done: false,
        evidence: "#1080 OPEN"
      }
    ],
    currentMilestone: ["#1150", "#1080"],
    progressNote: "Cloudflare Pages에 배포 완료.",
    currentWork: "현재 작업 없음",
    nextAction: "기능 확장 계획 수립",
    blockers: [],
    futureRoadmap: ["#1181 planning-only/deferred — crawl filter hardening"],
    lastVerified: "2026-07-25"
  },
  {
    id: "love-matchmaking",
    name: "Love Matchmaking",
    koreanName: "러브 매치메이킹",
    businessNumber: null,
    purpose: "AI 기반 매칭·소개 서비스 컨셉입니다.",
    repositoryLabel: "skerishKang/401-love-match-making",
    repositoryUrl: "https://github.com/skerishKang/401-love-match-making",
    workspace: "/",
    pageUrl: null,
    stage: "planned",
    developmentMode: "planning",
    progressBasis: "task",
    milestoneStatus: "undefined",
    milestoneTasks: [],
    currentMilestone: [],
    progressNote: "저장소 존재. 구현·배포 근거 없음. 진척도 미정 · 목표 정의 필요.",
    currentWork: "현재 작업 없음",
    nextAction: "구현 범위 정의",
    blockers: [],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "ai-finder-namgu",
    name: "광주 남구청 AI Finder",
    koreanName: "광주 남구청 AI 파인더",
    businessNumber: null,
    purpose: "광주 남구청 대상 AI 기반 정보 검색·안내 서비스입니다.",
    repositoryLabel: "확인 필요",
    repositoryUrl: null,
    workspace: "확인 필요",
    pageUrl: null,
    stage: "planned",
    developmentMode: "planning",
    progressBasis: "task",
    milestoneStatus: "undefined",
    milestoneTasks: [],
    currentMilestone: [],
    progressNote: "구현·배포 근거 없음. 진척도 미정 · 목표 정의 필요.",
    currentWork: "현재 작업 없음",
    nextAction: "저장소 및 구현 범위 정의",
    blockers: [],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  },
  {
    id: "ai-finder-seogu",
    name: "광주 서구청 AI Finder",
    koreanName: "광주 서구청 AI 파인더",
    businessNumber: null,
    purpose: "광주 서구청 대상 AI 기반 정보 검색·안내 서비스입니다.",
    repositoryLabel: "확인 필요",
    repositoryUrl: null,
    workspace: "확인 필요",
    pageUrl: null,
    stage: "planned",
    developmentMode: "planning",
    progressBasis: "task",
    milestoneStatus: "undefined",
    milestoneTasks: [],
    currentMilestone: [],
    progressNote: "구현·배포 근거 없음. 진척도 미정 · 목표 정의 필요.",
    currentWork: "현재 작업 없음",
    nextAction: "저장소 및 구현 범위 정의",
    blockers: [],
    futureRoadmap: [],
    lastVerified: "2026-07-25"
  }
];
