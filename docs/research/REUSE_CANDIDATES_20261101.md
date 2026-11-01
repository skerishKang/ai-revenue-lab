# 개발 대신 가져올 후보 — 2026-11-01

## 바로 가져올 것 Top 10

| 순위 | #6460 미완료 항목 | 후보 | 라이선스 | 방법 |
|---:|---|---|---|---|
| 1 | 5-1 맥락 관리 | [Hermes 압축](https://github.com/NousResearch/hermes-agent/tree/main/agent) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 압축 부품 이식, 기존 B14 경유 |
| 2 | 5-1 큰 출력 보관 | [Hermes 터미널](https://github.com/NousResearch/hermes-agent/blob/main/tools/terminal_tool.py) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 파일 보관·참조 방식 이식, 구간 읽기 연결 |
| 3 | 5-1 긴 작업 백그라운드 | [Hermes 프로세스](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/tools.md) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 프로세스 관리 이식, COM2 작업 기록 연결 |
| 4 | 5-1 작업 이어가기 | [OpenCode 압축](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/compaction.ts) | [MIT](https://github.com/anomalyco/opencode/blob/dev/LICENSE) | 완료·진행·다음 단계 요약 형식 이식 |
| 5 | 5-1 도구 호출·토큰 측정 | [Hermes Insights](https://github.com/NousResearch/hermes-agent/blob/main/agent/insights.py) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 호출·토큰 집계 코드 이식; PC 왕복·잘림·시간 초과는 추가 계측 |
| 6 | 5 Android Chat·작업 이어가기 | [OpenMuse 모바일](https://github.com/CopilotKit/OpenMuse) | [MIT](https://github.com/CopilotKit/openmuse/blob/main/LICENSE) | 모바일 채팅·작업 진행 화면 일부 이식; 기기 파일 커넥터는 별도 |
| 7 | 5-1 왕복 줄이기 | [Hermes 묶음 실행](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/code-execution.md) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 묶음 인터페이스 이식; 내부 행동도 공통 하네스 통과 |
| 8 | 5·5-1 코드 탐색 | [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | [MIT](https://github.com/DeusData/codebase-memory-mcp/blob/main/LICENSE) | MCP 의존성 시험 |
| 9 | 5·5-1 코드 탐색 | [Serena SolidLSP](https://github.com/oraios/serena/tree/main/src/solidlsp) | [해당 부분 MIT](https://github.com/oraios/serena/blob/main/LICENSE) | MIT 디렉터리만 이식; Serena 앱은 GPL |
| 10 | 5 브라우저 사용 | [Browser Use](https://github.com/browser-use/browser-use) | [MIT](https://github.com/browser-use/browser-use/blob/main/LICENSE) | 기존 브라우저 권한에 라이브러리 연결 |

같은 제품의 다른 부품은 각각 순위에 넣었다. 사용 가능 라이선스라는 뜻이며 설치·연동·실사용 검증이 완료됐다는 뜻은 아니다. 5-1의 도구 호출·토큰 집계 후보를 추가했다. PC 왕복·잘림 바이트·시간 초과는 추가 계측이 필요하다.

## 기준

[#6460](https://github.com/skerishKang/ai-revenue-lab/issues/6460) 3·4·5·5-1의 미완료 항목에 연결되는 후보만 아래 표에 넣었다. [#4935](https://github.com/skerishKang/ai-revenue-lab/issues/4935) 본문·댓글 92개, [#2996](https://github.com/skerishKang/ai-revenue-lab/issues/2996) 본문·댓글 76개, [#4956](https://github.com/skerishKang/ai-revenue-lab/issues/4956) 본문·댓글 43개를 순서대로 가져왔다.

표의 라이선스는 GitHub의 실제 LICENSE 파일을 조회한 결과다. 별과 기본 브랜치 최신 커밋 날짜는 2026-11-01 조회값이며 변한다. MIT·Apache는 고지 조건을 지켜 이식·의존성으로, AGPL·GPL·없음은 방식만 참고한다. 선택 버전의 서드파티 구성요소 라이선스와 비용은 도입 전 별도 확인한다. 사용료는 공개 소스와 모델·호스팅 비용을 구분한다.

## 이슈별 후보 전체 표


### #4935

| 해결 항목·후보 | LICENSE | 방법 | 최신 커밋 / 별 |
|---|---|---|---|
| 5-1 맥락 압축, 큰 출력, 백그라운드, 묶음 실행 — [Hermes Agent](https://github.com/NousResearch/hermes-agent) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | Python 관련 부품 이식; B14·기존 하네스에 연결 | 11-01 / 25.9만 |
| 5-1 대화 압축, 이어가기 — [OpenClaw](https://github.com/openclaw/openclaw) | [MIT](https://github.com/openclaw/openclaw/blob/main/LICENSE) | 원본 추적·생략 표시 부품 이식 | 11-01 / 39.4만 |
| 5 브라우저 사용 — [Browser Use](https://github.com/browser-use/browser-use) | [MIT](https://github.com/browser-use/browser-use/blob/main/LICENSE) | Python 라이브러리 의존성; 클라우드·모델 별도 요금 | 10-30 / 12.0만 |
| 5 브라우저 사용 — [Drex Browser Harness](https://github.com/nace-ai/drex-browser-harness-pub) | [MIT](https://github.com/nace-ai/drex-browser-harness-pub/blob/main/LICENSE) | CDP/MCP 부품 이식 검토 | 10-30 / 6 |
| 5-1 코드 탐색 묶음 — [Repomix](https://github.com/yamadashy/repomix) | [MIT](https://github.com/yamadashy/repomix/blob/main/LICENSE) | 지정 범위 묶기 CLI 의존성 | 11-01 / 2.9만 |
| 5-1 코드 탐색 묶음 — [Gitingest](https://github.com/coderamp-labs/gitingest) | [MIT](https://github.com/coderamp-labs/gitingest/blob/main/LICENSE) | 저장소 이전됨; 묶기 의존성, Repomix 대안 | 2025-08-16 / 1.6만 |
| 5·5-1 코드 탐색 — [Tree-sitter](https://github.com/tree-sitter/tree-sitter) | [MIT](https://github.com/tree-sitter/tree-sitter/blob/master/LICENSE) | 증분 구문분석 의존성; 언어 grammar 별도 확인 | 10-31 / 2.7만 |
| 4 큰 문서 탐색·5-1 검색 — [PageIndex](https://github.com/VectifyAI/PageIndex) | [MIT](https://github.com/VectifyAI/PageIndex/blob/main/LICENSE) | 문서 구조 색인 의존성 시험; 범용 파일 분할 읽기는 별도 | 10-29 / 4.0만 |
| 5-1 맥락 관리 — [OpenViking](https://github.com/volcengine/OpenViking) | [AGPL-3.0](https://github.com/volcengine/OpenViking/blob/main/LICENSE) | 방식만 참고, 직접 개발 | 10-31 / 4.1만 |
| 5·5-1 코드 탐색 — [Serena SolidLSP](https://github.com/oraios/serena) | [혼합: SolidLSP MIT / 앱 GPL-3+](https://github.com/oraios/serena/blob/main/LICENSE) | src/solidlsp 등 MIT 부분만 이식; GPL 앱은 방식만 참고 | 10-28 / 3.1만 |

### #2996

| 해결 항목·후보 | LICENSE | 방법 | 최신 커밋 / 별 |
|---|---|---|---|
| 5-1 맥락 압축, 큰 출력, 백그라운드, 묶음 실행 — [Hermes Agent](https://github.com/NousResearch/hermes-agent) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | Python 관련 부품 이식; B14·기존 하네스에 연결 | 11-01 / 25.9만 |
| 5-1 맥락 압축, 이어가기, 큰 출력 보관 — [OpenCode](https://github.com/anomalyco/opencode) | [MIT](https://github.com/anomalyco/opencode/blob/dev/LICENSE) | TS 압축·상태 요약·파일 참조 일부 이식 | 11-01 / 22.4만 |
| 5-1 대화 압축, 이어가기 — [OpenClaw](https://github.com/openclaw/openclaw) | [MIT](https://github.com/openclaw/openclaw/blob/main/LICENSE) | 원본 추적·생략 표시 부품 이식 | 11-01 / 39.4만 |
| 5·5-1 코드 저장소 검색·탐색 — [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | [MIT](https://github.com/DeusData/codebase-memory-mcp/blob/main/LICENSE) | MCP 의존성 시험; 일반 PC 전체 파일 검색 대체 아님 | 11-01 / 4.8만 |
| 5 브라우저 사용 — [Browser Use](https://github.com/browser-use/browser-use) | [MIT](https://github.com/browser-use/browser-use/blob/main/LICENSE) | Python 라이브러리 의존성; 클라우드·모델 별도 요금 | 10-30 / 12.0만 |
| 5-1 이어가기·측정 — [OpenAI Codex](https://github.com/openai/codex) | [Apache-2.0](https://github.com/openai/codex/blob/main/LICENSE) | 압축 이벤트·체크포인트 Rust 부품 이식 검토 | 10-31 / 13.3만 |
| 5-1 이어가기 표시 — [Kimi Code CLI](https://github.com/MoonshotAI/kimi-code) | [MIT](https://github.com/MoonshotAI/kimi-code/blob/main/LICENSE) | CLI 상태 표시 부품 이식; 상용 Kimi Work와 구분 | 10-30 / 0.8만 |
| 5-1 작업 이어가기 — [Orca](https://github.com/stablyai/orca) | [MIT](https://github.com/stablyai/orca/blob/main/LICENSE) | 작업 세션·진행 표시 관련 코드 이식 검토 | 11-01 / 11.2만 |
| 5-1 맥락 관리 — [OpenViking](https://github.com/volcengine/OpenViking) | [AGPL-3.0](https://github.com/volcengine/OpenViking/blob/main/LICENSE) | 방식만 참고, 직접 개발 | 10-31 / 4.1만 |

### #4956

| 해결 항목·후보 | LICENSE | 방법 | 최신 커밋 / 별 |
|---|---|---|---|
| 5-1 맥락 압축, 큰 출력, 백그라운드, 묶음 실행 — [Hermes Agent](https://github.com/NousResearch/hermes-agent) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | Python 관련 부품 이식; B14·기존 하네스에 연결 | 11-01 / 25.9만 |
| 5·5-1 코드 저장소 검색·탐색 — [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | [MIT](https://github.com/DeusData/codebase-memory-mcp/blob/main/LICENSE) | MCP 의존성 시험; 일반 PC 전체 파일 검색 대체 아님 | 11-01 / 4.8만 |
| 5 브라우저 검색 — [wigolo](https://github.com/KnockOutEZ/wigolo) | [AGPL-3.0](https://github.com/KnockOutEZ/wigolo/blob/main/LICENSE) | 방식만 참고, 직접 개발 | 10-31 / 0.6만 |
| 5 PC 본문 검색 — [WinSearcher](https://github.com/infohelpful/WinSearcher-Release) | [없음 확인 불가](https://github.com/infohelpful/WinSearcher-Release) | 배포 저장소에 소스 없음·LICENSE API 404; 방식만 참고 | 08-24 / 0 |

## 한계와 후속 확인

- 기존 조사에서 확인된 기능과 공식 저장소 자료를 기준으로 매핑했다. 이 목록은 관련 후보의 선별 결과이며 모든 외부 링크의 기술·라이선스 검증을 마친 전체 목록은 아니다.
- Hermes의 묶음 실행을 적용할 때 각 위험 행동이 기존 PADIEM 공통 하네스와 권한 검사를 통과하도록 연결해야 한다. 큰 출력은 소유자별로 보관하고 필요한 구간을 다시 읽을 수 있게 해야 한다.
- 5-1 일곱 기능의 Windows/COM2 실제 작동·토큰·왕복 횟수·시간은 측정하지 않았다. 코드베이스 메모리의 영상 내 절감 수치도 PADIEM 실측이 아니다.
- WinSearcher 영상은 이슈에 기록된 설명과 목차 기준이며 영상 전체·HWP 본문 정확성은 확인되지 않았다.
- 다음 목록은 이슈에 등장한 X·YouTube 원문 중 이번에 원문 전체를 직접 확인하지 않은 링크다. 기존 이슈의 요약은 보존하되 원문 검증 완료로 취급하지 않는다.

## 미확인 원문 링크

### #4935 (250개)

- https://x.com/Kimi_Moonshot/status/2110687135183593646 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiangxiang103/status/2110638131720700149 — 접근 불가: 웹 조회 DisabledError
- https://x.com/mercury__agent/status/2110290765154799771 — 접근 불가: 웹 조회 DisabledError
- https://x.com/mercury__agent/status/2110653153154568203 — 접근 불가: 웹 조회 DisabledError
- https://x.com/NFT_Chen/status/2110635082860085486 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lonely__MH/status/2110988196352073748 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2110702226565906887 — 접근 불가: 웹 조회 DisabledError
- https://x.com/PrunaAI/status/2110386051277550063 — 접근 불가: 웹 조회 DisabledError
- https://x.com/taiyanghere/status/2110007655154483247 — 접근 불가: 웹 조회 DisabledError
- https://x.com/itsjdraven/status/2110276791458038039 — 접근 불가: 웹 조회 DisabledError
- https://x.com/anya_yfa7/status/2110608460270501985 — 접근 불가: 웹 조회 DisabledError
- https://x.com/wesbos/status/2110509898958008515 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ishaan_jaff/status/2109752409597845962 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2109690568590635440 — 접근 불가: 웹 조회 DisabledError
- https://x.com/kawaidgaf/status/2110304679586631723 — 접근 불가: 웹 조회 DisabledError
- https://x.com/TylerBai_loveai/status/2109569779984216346 — 접근 불가: 웹 조회 DisabledError
- https://x.com/SahilPanhotra/status/2109004299674268099 — 접근 불가: 웹 조회 DisabledError
- https://x.com/sergiorocaa/status/2108960970626248759 — 접근 불가: 웹 조회 DisabledError
- https://x.com/TencentAI_News/status/2108133183019684187 — 접근 불가: 웹 조회 DisabledError
- https://x.com/loki_yan_seo/status/2109262732763783400 — 접근 불가: 웹 조회 DisabledError
- https://x.com/alxshp/status/2107879013641560218 — 접근 불가: 웹 조회 DisabledError
- https://x.com/taiyanghere/status/2107864775262642320 — 접근 불가: 웹 조회 DisabledError
- https://x.com/useincredible/status/2107457256090411223 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Rohit_Writes/status/2107161119064551924 — 접근 불가: 웹 조회 DisabledError
- https://x.com/npm_i_shaders/status/2107467668009963819 — 접근 불가: 웹 조회 DisabledError
- https://x.com/gmi_cloud/status/2107909066739814866 — 접근 불가: 웹 조회 DisabledError
- https://x.com/EmperoAI/status/2107203283630628923 — 접근 불가: 웹 조회 DisabledError
- https://x.com/michellechen/status/2106894709696422189 — 접근 불가: 웹 조회 DisabledError
- https://x.com/cline/status/2107202446812733546 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BlockInsight214/status/2106664825346719889 — 접근 불가: 웹 조회 DisabledError
- https://x.com/reflection_ai/status/2107186849370247235 — 접근 불가: HTTP 403
- https://x.com/NFTCPS/status/2106682991972098122 — 접근 불가: 웹 조회 DisabledError
- https://x.com/CopilotKit/status/2106489504236511533 — 접근 불가: HTTP 403
- https://x.com/calbuldelis69/status/2107089393672704007 — 접근 불가: 웹 조회 DisabledError
- https://x.com/melvindvivas/status/2106996300474683839 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiangxiang103/status/2106803637167259707 — 접근 불가: 웹 조회 DisabledError
- https://x.com/tomik99/status/2105777404174115117 — 접근 불가: 웹 조회 DisabledError
- https://x.com/kawaidgaf/status/2105894157193748951 — 접근 불가: 웹 조회 DisabledError
- https://x.com/calbuldelis69/status/2106077462207881561 — 접근 불가: 웹 조회 DisabledError
- https://x.com/juampitech/status/2106395850830438509 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Yanir_/status/2105739528988238211 — 접근 불가: 웹 조회 DisabledError
- https://x.com/OpenBot_/status/2105666545842012445 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ataiiam/status/2105710796198322659 — 접근 불가: HTTP 403
- https://x.com/MonidHQ/status/2105089581330882973 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Tiny_Fish/status/2105009755442090123 — 접근 불가: 웹 조회 DisabledError
- https://x.com/OpenAIDevs/status/2104997619152130278 — 접근 불가: HTTP 403
- https://x.com/Offloop/status/2104900654137590212 — 접근 불가: 웹 조회 DisabledError
- https://x.com/kseniam0s/status/2105370329434489265 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hanghuang_/status/2104949571789148416 — 접근 불가: 웹 조회 DisabledError
- https://x.com/yiliush/status/2104997540454371658 — 접근 불가: 웹 조회 DisabledError
- https://x.com/CopilotKit/status/2104899424585683381 — 접근 불가: 웹 조회 DisabledError
- https://x.com/_inception_ai/status/2104974439314321660 — 접근 불가: 웹 조회 DisabledError
- https://x.com/johnrush/status/2105067074720829819 — 접근 불가: HTTP 403
- https://x.com/browser_use/status/2104814685518491911 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ai_fengshou/status/2104417258923773954 — 접근 불가: 웹 조회 DisabledError
- https://x.com/nex_ify/status/2104491498444136512 — 접근 불가: 웹 조회 DisabledError
- https://x.com/dingyi/status/2104604727900275072 — 접근 불가: 웹 조회 DisabledError
- https://x.com/_0xKenny/status/2104639676598383095 — 접근 불가: HTTP 403
- https://x.com/koffuxu/status/2104417854754034170 — 접근 불가: 웹 조회 DisabledError
- https://x.com/itsjdraven/status/2104552519032869045 — 접근 불가: 웹 조회 DisabledError
- https://x.com/TencentAI_News/status/2104500084880662942 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiaomovps/status/2104198873774469409 — 접근 불가: 웹 조회 DisabledError
- https://x.com/mylifcc/status/2104430399053045976 — 접근 불가: 웹 조회 DisabledError
- https://x.com/MinLiBuilds/status/2104143124532781067 — 접근 불가: 웹 조회 DisabledError
- https://x.com/akazwz_/status/2104125352293605774 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lummox_eth/status/2104218875810185287 — 접근 불가: HTTP 403
- https://x.com/garrytan/status/2104221282095218731 — 접근 불가: 웹 조회 DisabledError
- https://x.com/lucas_flatwhite/status/2104114543463190699 — 접근 불가: 웹 조회 DisabledError
- https://x.com/shao__meng/status/2104138489268670941 — 접근 불가: 웹 조회 DisabledError
- https://x.com/usehazeai/status/2103151105236431283 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiao92666/status/2102972794661486623 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hfcorriez/status/2102871334657397099 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Krongggggg/status/2102930610969088238 — 접근 불가: 웹 조회 DisabledError
- https://x.com/VibeEverything/status/2102697640572113224 — 접근 불가: 웹 조회 DisabledError
- https://x.com/nowlovepan/status/2103103135682306537 — 접근 불가: 웹 조회 DisabledError
- https://x.com/polymarketjapan/status/2102982988170666291 — 접근 불가: 웹 조회 DisabledError
- https://x.com/elonmusk/status/2102798963837665464 — 접근 불가: 웹 조회 DisabledError
- https://x.com/trendtech33566/status/2102599463412076974 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Saccc_c/status/2101152089598791845 — 접근 불가: 웹 조회 DisabledError
- https://x.com/moritzkremb/status/2100715237267660873 — 접근 불가: 웹 조회 DisabledError
- https://x.com/TeddyinMedia/status/2099859887102558507 — 접근 불가: 웹 조회 DisabledError
- https://x.com/AISuperDomain/status/2099648097357807991 — 접근 불가: 웹 조회 DisabledError
- https://x.com/zefirium/status/2092659023002632532 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Jolyne_AI/status/2073285687793873367 — 접근 불가: 웹 조회 DisabledError
- https://x.com/EngMoElgaraihy/status/2099511660205531263 — 접근 불가: 웹 조회 DisabledError
- https://x.com/omarsar0/status/2105736578673033564 — 접근 불가: 웹 조회 DisabledError
- https://x.com/taiyanghere/status/2110529688426909798 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiangxiang103/status/2103705259554275560 — 접근 불가: 웹 조회 DisabledError
- https://x.com/EngMoElgaraihy/status/2103918527845392787 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiangxiang103/status/2103817359396118855 — 접근 불가: 웹 조회 DisabledError
- https://x.com/huoshan007/status/2104013133786529812 — 접근 불가: 웹 조회 DisabledError
- https://x.com/WalrusProtocol/status/2062646758564343908 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Shruti_0810/status/2103894457322262615 — 접근 불가: 웹 조회 DisabledError
- https://x.com/MinLiBuilds/status/2103629659569336765 — 접근 불가: 웹 조회 DisabledError
- https://x.com/SUOHA_AI/status/2103806382235378167 — 접근 불가: 웹 조회 DisabledError
- https://x.com/pengsonal/status/2103714760441384976 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Sn0wbrave/status/2103078611783721444 — 접근 불가: 웹 조회 DisabledError
- https://x.com/acidsound/status/2101295952422457786 — 접근 불가: 웹 조회 DisabledError
- https://x.com/getjinxo/status/2111849640031322595 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ghumare64/status/2111332908657148356 — 접근 불가: 웹 조회 DisabledError
- https://x.com/harrisonitsme/status/2099109471993872817 — 접근 불가: 웹 조회 DisabledError
- https://x.com/reasonmachines/status/2111135100142518430 — 접근 불가: HTTP 403
- https://x.com/suraj_sharma14/status/2109464068356546958 — 접근 불가: 웹 조회 DisabledError
- https://x.com/lucian__03/status/2103097036254126238 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2112038533510599020 — 접근 불가: 웹 조회 DisabledError
- https://x.com/fankaishuoai/status/2111484271198343195 — 접근 불가: 웹 조회 DisabledError
- https://x.com/elonmusk/status/2111161779657285919 — 접근 불가: 웹 조회 DisabledError
- https://x.com/EngMoElgaraihy/status/2111297758934028330 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2110015201177375032 — 접근 불가: 웹 조회 DisabledError
- https://x.com/AniC_dev/status/2102785812635214139 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hridoyreh/status/2104100192719130843 — 접근 불가: 웹 조회 DisabledError
- https://x.com/realchendahuang/status/2112167421390004459 — 접근 불가: HTTP 403
- https://x.com/calbuldelis69/status/2112239888724808067 — 접근 불가: HTTP 403
- https://x.com/ExaAILabs/status/2112218730952601719 — 접근 불가: HTTP 403
- https://x.com/voidyaps/status/2112143153058988366 — 접근 불가: 웹 조회 DisabledError
- https://x.com/rammcodes/status/2112175596071755830 — 접근 불가: 웹 조회 DisabledError
- https://x.com/mylifcc/status/2111970589401321902 — 접근 불가: 웹 조회 DisabledError
- https://x.com/gbauzap/status/2106492677344633185 — 접근 불가: 웹 조회 DisabledError
- https://x.com/OpenBot_/status/2106330922861858826 — 접근 불가: 웹 조회 DisabledError
- https://x.com/openclaw/status/2112260434116108528 — 접근 불가: 웹 조회 DisabledError
- https://x.com/RodmanAi/status/2112210714949726604 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hqmank/status/2103834161090081097 — 접근 불가: 웹 조회 DisabledError
- https://x.com/oldstackjournal/status/2103661382906638811 — 접근 불가: 웹 조회 DisabledError
- https://x.com/yyyole/status/2103661669532774688 — 접근 불가: 웹 조회 DisabledError
- https://x.com/calbuldelis69/status/2103771239672422517 — 접근 불가: 웹 조회 DisabledError
- https://x.com/bkdgiffug/status/2106505321774526581 — 접근 불가: 웹 조회 DisabledError
- https://x.com/itsjdraven/status/2103407813360066626 — 접근 불가: 웹 조회 DisabledError
- https://x.com/FactoryAI/status/2103528493133000751 — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=NLsiZtleLe4 — 접근 불가: 조회 제한
- https://x.com/XRay96/status/2103354801400762528 — 접근 불가: 웹 조회 DisabledError
- https://x.com/shneural/status/2103151003272962130 — 접근 불가: HTTP 403
- https://x.com/AskPerplexity/status/2103484879937896710 — 접근 불가: 웹 조회 DisabledError
- https://x.com/AISuperDomain/status/2103399761772683513 — 접근 불가: 웹 조회 DisabledError
- https://x.com/aiehon_aya/status/2103403361022419005 — 접근 불가: HTTP 403
- https://x.com/NousResearch/status/2102873234819698877 — 접근 불가: HTTP 403
- https://x.com/Gozengogo_/status/2103349964290322846 — 접근 불가: 웹 조회 DisabledError
- https://x.com/tonbistudio/status/2103374537182314751 — 접근 불가: 웹 조회 DisabledError
- https://x.com/NousResearch/status/2103244070407802905 — 접근 불가: 웹 조회 DisabledError
- https://x.com/perplexitydevs/status/2103241128216875283 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiaohu/status/2102979455308439555 — 접근 불가: 웹 조회 DisabledError
- https://x.com/steipete/status/2103147927313199260 — 접근 불가: HTTP 403
- https://x.com/tkm_hmng8/status/2103304541588631671 — 접근 불가: HTTP 403
- https://x.com/maarcoofdezz/status/2103084734892957889 — 접근 불가: HTTP 403
- https://www.youtube.com/watch?v=knvviM-LAZU — 접근 불가: 조회 제한
- https://x.com/ChrisMTeryli/status/2099136522985324753 — 접근 불가: 웹 조회 DisabledError
- https://x.com/pcmanabucom/status/2111357965965938928 — 접근 불가: 웹 조회 DisabledError
- https://x.com/franpradasAI/status/2111129542647792070 — 접근 불가: HTTP 403
- https://x.com/Farewe1ll/status/2111500162803867758 — 접근 불가: 웹 조회 DisabledError
- https://x.com/OlatunjiAyokan2/status/2111317596574278138 — 접근 불가: HTTP 403
- https://x.com/Manu_Sisti/status/2111441903476728094 — 접근 불가: 웹 조회 DisabledError
- https://x.com/bot/status/2111184276662481202 — 접근 불가: HTTP 403
- https://x.com/libukai/status/2111498950339658194 — 접근 불가: 웹 조회 DisabledError
- https://x.com/gefei55/status/2104244165739766087 — 접근 불가: 웹 조회 DisabledError
- https://x.com/DRbitcoin36/status/2104166358292595125 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Appkittie/status/2112193313235435547 — 접근 불가: HTTP 403
- https://x.com/mercury__agent/status/2112804830456713644 — 접근 불가: 웹 조회 DisabledError
- https://x.com/mattyp/status/2102759899314741736 — 접근 불가: 웹 조회 DisabledError
- https://x.com/NaceAI/status/2112642726877405531 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Texas_Twins_Dad/status/2112622519983423515 — 접근 불가: 웹 조회 DisabledError
- https://x.com/MiniMaxAgent/status/2112860752830931341 — 접근 불가: 웹 조회 DisabledError
- https://x.com/memoh_ai/status/2112756499961557292 — 접근 불가: 웹 조회 DisabledError
- https://x.com/WorkBuddy_AI/status/2112776352143425793 — 접근 불가: 웹 조회 DisabledError
- https://x.com/PrajwalTomar_/status/2112521739976716525 — 접근 불가: 웹 조회 DisabledError
- https://x.com/liambraus/status/2112176354909135306 — 접근 불가: 웹 조회 DisabledError
- https://x.com/TencentAI_News/status/2112115861301649834 — 접근 불가: 웹 조회 DisabledError
- https://x.com/yedabinbinah/status/2112515676027969970 — 접근 불가: 웹 조회 DisabledError
- https://x.com/binghe/status/2112551923610227013 — 접근 불가: 웹 조회 DisabledError
- https://x.com/benyuls/status/2112539062347174312 — 접근 불가: 웹 조회 DisabledError
- https://x.com/bot/status/2112645531076096330 — 접근 불가: HTTP 403
- https://x.com/OpenAIDevs/status/2112603916076781778 — 접근 불가: HTTP 403
- https://x.com/Ga_Vasques/status/2112565952608952586 — 접근 불가: 웹 조회 DisabledError
- https://x.com/WojakTheDev/status/2113200900412223530 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102604997049602527 — 접근 불가: HTTP 403
- https://x.com/Suu766/status/2102604999515885757 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605002133123270 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605004775489662 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605007325643257 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605010270138846 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605012979605630 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605015567499546 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605018209919034 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605020940369932 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605023641493506 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605026913120357 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Suu766/status/2102605029530329127 — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=ZoqgAy3h4OM — 제목만 열림, 본문·영상/자막 접근 불가
- https://www.youtube.com/watch?v=5MgBikgcWnY — 제목만 열림, 본문·영상/자막 접근 불가
- https://x.com/browser_use/status/2113299829489279126 — 접근 불가: 웹 조회 DisabledError
- https://x.com/1Password/status/2113276767582498943 — 접근 불가: HTTP 403
- https://x.com/grok/status/2103455600273449121 — 접근 불가: 웹 조회 DisabledError
- https://x.com/inflowpayai/status/2112937220953035046 — 접근 불가: 웹 조회 DisabledError
- https://x.com/i/article/2112936733251924057 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BearHuddleston/status/2114404737369911462 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BearHuddleston/status/2104109388780744775 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hiwise_aigc/status/2114287632683520385 — 접근 불가: HTTP 403
- https://x.com/vmkbuilds/status/2114211061926965303 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BkashJosi/status/2114462089943413240 — 접근 불가: 웹 조회 DisabledError
- https://x.com/GodsBoy7777/status/2114453912488948195 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BkashJosi/status/2114204582536688127 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Geeby_1/status/2111415265309425771 — 접근 불가: 웹 조회 DisabledError
- https://x.com/hezycrypto/status/2111408739521581325 — 접근 불가: 웹 조회 DisabledError
- https://x.com/alextalksai/status/2112556295370809688 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ikshitijsharma/status/2112817192089931941 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Jiler830219/status/2112574125474521197 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Hu59645Hugo/status/2112600855086034954 — 접근 불가: 웹 조회 DisabledError
- https://x.com/MiniMax_AI/status/2112987176053215566 — 접근 불가: HTTP 403
- https://x.com/GenAI_is_real/status/2112938798262919675 — 접근 불가: 웹 조회 DisabledError
- https://x.com/MiniMax_AI/status/2110207378725740887 — 접근 불가: HTTP 403
- https://x.com/Argona0x/status/2101400788731846664 — 접근 불가: 웹 조회 DisabledError
- https://x.com/CryptoPainter/status/2101331932084883541 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2114499750628327554 — 접근 불가: 웹 조회 DisabledError
- https://x.com/pdp/status/2114341538364809575 — 접근 불가: 웹 조회 DisabledError
- https://x.com/neeeel/status/2114425316135567634 — 접근 불가: 웹 조회 DisabledError
- https://x.com/anya_yfa7/status/2114528505711263925 — 접근 불가: 웹 조회 DisabledError
- https://x.com/alannnfx/status/2114600590366175385 — 접근 불가: 웹 조회 DisabledError
- https://x.com/zeviodotsh/status/2114472975273759104 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lovislexus/status/2114129813103628765 — 접근 불가: 웹 조회 DisabledError
- https://x.com/donniy520/status/2114001247762022648 — 접근 불가: HTTP 403
- https://x.com/liangzhu_AI/status/2114249096995451055 — 접근 불가: HTTP 403
- https://x.com/byronzhang01/status/2114335975824576525 — 접근 불가: 웹 조회 DisabledError
- https://x.com/seanbuildlog/status/2114280528694346005 — 접근 불가: 웹 조회 DisabledError
- https://x.com/GitTrend0x/status/2114152481881989579 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Taheer_Defi/status/2114539271059345481 — 접근 불가: 웹 조회 DisabledError
- https://x.com/fabioricotta/status/2114697690894188977: — 접근 불가: 웹 조회 DisabledError
- https://x.com/milindlabs/status/2114818252019036289 — 접근 불가: 웹 조회 DisabledError
- https://x.com/making_cindy/status/2113993797671801149 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2114612998593712228 — 접근 불가: HTTP 403
- https://x.com/appinn/status/2114700442160566638 — 접근 불가: 웹 조회 DisabledError
- https://x.com/WojakTheDev/status/2114613004264149361 — 접근 불가: 웹 조회 DisabledError
- https://x.com/SungKimUp/status/2114886177111281788 — 접근 불가: 웹 조회 DisabledError
- https://x.com/jojeangsaing/status/2114881094914805837 — 접근 불가: 웹 조회 DisabledError
- https://x.com/taiyanghere/status/2114703397895250259 — 접근 불가: 웹 조회 DisabledError
- https://x.com/alexmichael/status/2114894612406100333 — 접근 불가: 웹 조회 DisabledError
- https://x.com/kseniam0s/status/2114802233971757248 — 접근 불가: HTTP 403
- https://x.com/MetaforDevs/status/2114773643796631717 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BkashJosi/status/2114763790013341766 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Tiny_Fish/status/2114880848306770135 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lovislexus/status/2114892336240963762 — 접근 불가: 웹 조회 DisabledError
- https://x.com/lucaardito/status/2114814780162937208 — 접근 불가: 웹 조회 DisabledError
- https://x.com/brettcalhounn/status/2114716427290640444 — 접근 불가: 웹 조회 DisabledError
- https://x.com/BlackMelooo/status/2114750492320620673 — 접근 불가: 웹 조회 DisabledError
- https://x.com/jojeangsaing/status/2114596792725872646 — 접근 불가: 웹 조회 DisabledError
- https://x.com/morganxu45/status/2114677995097248070 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lovislexus/status/2114869687783739824 — 접근 불가: 웹 조회 DisabledError
- https://x.com/xiaomovps/status/2114977428682809759 — 접근 불가: HTTP 403
- https://x.com/Lovislexus/status/2114885037577375972 — 접근 불가: 웹 조회 DisabledError
- https://x.com/ataiiam/status/2115097056394240293 — 접근 불가: HTTP 403
- https://x.com/alannnfx/status/2115082464196497817 — 접근 불가: 웹 조회 DisabledError
- https://x.com/x_insider4/status/2114393316158537843 — 접근 불가: HTTP 403
- https://x.com/bot/status/2115130760009273501 — 접근 불가: HTTP 403

### #2996 (19개)

- https://x.com/adalagent/status/2102774996124721214 — 접근 불가: 웹 조회 DisabledError
- https://x.com/kawaidgaf/status/2110755714209882455 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/QOAJYkuX_-Y — 접근 불가: 웹 조회 DisabledError
- https://x.com/LawrenceW_Zen/status/2112052626494017951 — 접근 불가: 웹 조회 DisabledError
- https://x.com/cu30rry_/status/2111738806139511125 — 접근 불가: 웹 조회 DisabledError
- https://x.com/bot/status/2111184270819803351 — 접근 불가: HTTP 403
- https://x.com/WalrusProtocol/status/2062646758564343908 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Shruti_0810/status/2103894457322262615 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Sn0wbrave/status/2103078611783721444 — 접근 불가: 웹 조회 DisabledError
- https://x.com/acidsound/status/2101295952422457786 — 접근 불가: 웹 조회 DisabledError
- https://x.com/getjinxo/status/2111849640031322595 — 접근 불가: 웹 조회 DisabledError
- https://x.com/harrisonitsme/status/2099109471993872817 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2110702226565906887 — 접근 불가: 웹 조회 DisabledError
- https://x.com/reasonmachines/status/2111135100142518430 — 접근 불가: HTTP 403
- https://x.com/cursor_ai/status/2111193957527146711 — 접근 불가: 웹 조회 DisabledError
- https://x.com/suraj_sharma14/status/2109464068356546958 — 접근 불가: 웹 조회 DisabledError
- https://x.com/Lummox_eth/status/2104218875810185287 — 접근 불가: HTTP 403
- https://x.com/lucas_flatwhite/status/2104114543463190699 — 접근 불가: 웹 조회 DisabledError
- https://x.com/yulmu_coffee/status/2102812297718886904 — 접근 불가: 웹 조회 DisabledError

### #4956 (67개)

- https://www.youtube.com/watch?v=L09kacrneOc — 접근 불가: 조회 제한
- https://www.youtube.com/watch?v=Ngqxa0B6DqE — 접근 불가: 조회 제한
- https://www.youtube.com/watch?v=I-m4HSjptAM — 접근 불가: 조회 제한
- https://www.youtube.com/watch?v=GchXMRwuWxE — 제목만 열림, 본문·영상/자막 접근 불가
- https://youtu.be/Oo_GGWV9Hys — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/IF-dwIm1YMo — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/QfPJyzflkAI — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Fk5pQ0fQkJ0 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Or_yGUXwjMY — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/oGzdBoKam0c — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/vOZ5jdLJ3LE — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/live/_M0admzUkuo — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/9JDYeLgn7Q8 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/NE306sbvopY — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/YDjBNzhTUWo — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/YiKAbr0KSPk — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/IuxDOrKdMW8 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/VAOdUAkVGpE — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Fd8XVsCZSjs — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/IFE3KAz_Jbs — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=RDosoTCHFHA — 접근 불가: 조회 제한
- https://youtu.be/iHjWs6rXVvU — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/gv0nZoxqIGo — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/GvtjzW8UZCM — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/-gfgQfw2g_E — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/QPvScQBDrdw — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/IMhsMzlzsTk — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/KZiF2J83zaY — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Hn6bSMOpcoA — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/NOOq7pagTSg — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/-LWUtW87jlM — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/tByhXkxDKDo — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=pFO41hA9doQ — 접근 불가: 조회 제한
- https://youtu.be/UMDSNYu7iNU — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/ymj8Ha0oBtU — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/OXg-0BXf_Yk — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/z-cxE0yus4g — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/live/9jgyfkG-9wA — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/yUjTWl7tOYc — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=R3-anFK1YM8 — 접근 불가: 조회 제한
- https://youtu.be/4AvQQHDTJFE — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/qWJ5Nzf68Iw — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Cy1xjHaoqGI — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/suK5R-j67Gg — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/wJs7Ut2diB0 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/gmhCepXTHaI — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/qOqcz6J7K-o — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/oT4zOjEc_BA — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/R2SOaieHus8 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/W_-ecvxMu3Y — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/qh0FkdgieS8 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/7ZOjMnbxJYE — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/Kbf8yqauzF0 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/jajEm8R9nD0 — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/JMeO5IOB22I — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/tnOYNzGb_uA — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/live/cBcPyHeu0Pw — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/KvoMRRs3Jko — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/gxeVxbT4Ctc — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/iOsMx660JnA — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/ZmugrBuT4Yc — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/vjSZIyYd0NI — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/QOAJYkuX_-Y — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/live/pFO41hA9doQ — 접근 불가: 웹 조회 DisabledError
- https://youtu.be/ZtDMVgzUrHA — 접근 불가: 웹 조회 DisabledError
- https://www.youtube.com/watch?v=nwiL2LIYfUA — 접근 불가: 조회 제한
- https://www.youtube.com/watch?v=RatSJhbGOT0 — 접근 불가: 웹 조회 DisabledError

## 미확인 저장소 링크

아래는 자료 이슈에서 발견했으나 위 표의 관련 후보로 검증하지 못한 외부 GitHub 링크다. 미완료 항목 관련성·실제 대상·라이선스는 미확인이며 채택 목록에 포함하지 않는다.

### #4935 (61개)

- https://github.com/NousResearch/hermes-official-plugins/blob/main/rea/README.md
- https://github.com/CopilotKit/OpenMuse
- https://github.com/debpalash/VoiceStudio
- https://github.com/akazwz/hostc
- https://github.com/mem0ai/mem0
- https://github.com/vectorize-io/hindsight
- https://github.com/epoko77-ai/im-not-ai
- https://github.com/Sac-Y/Jev-cu
- https://github.com/Panniantong/Agent-Reach
- https://github.com/rlaope/oh-my-hermes
- https://github.com/AhmadIbrahiim/Website-downloader
- https://github.com/MystenLabs/MemWal
- https://github.com/genspark-ai/genoffice
- https://github.com/THU-MAIC/OpenMAIC
- https://github.com/Tencent/WeKnora
- https://github.com/getzep/graphiti
- https://github.com/topoteretes/cognee
- https://github.com/open-webui/open-webui
- https://github.com/QwenAudio/qwen-audio-agent
- https://github.com/jamiepine/voicebox
- https://github.com/reason-machines/reason-network
- https://github.com/NevaMind-AI/memU
- https://github.com/letta-ai/letta
- https://github.com/letta-ai/letta-code
- https://github.com/mem0ai/openmemory
- https://github.com/vectorize-io/agent-memory-benchmark
- https://github.com/Nanako0129/sepia
- https://github.com/blader/humanizer
- https://github.com/textlint-ja/textlint-rule-preset-ai-writing
- https://github.com/op7418/Humanizer-zh
- https://github.com/cloudflare/agentic-inbox
- https://github.com/YuJunZhiXue/dsh-purge
- https://github.com/Subhan-code/Amicro--Micro-transitions-
- https://github.com/continuedev/continue
- https://github.com/Aider-AI/aider
- https://github.com/sourcegraph/sourcegraph
- https://github.com/github/codeql
- https://github.com/semgrep/semgrep
- https://github.com/oracle/opengrok
- https://github.com/CopilotKit/OpenDots
- https://github.com/kajisho5/ffmpeg-skill
- https://github.com/hkqr/my-free-code
- https://github.com/Rescenix/Yosuri
- https://github.com/win4r/MuseAI-Skills
- https://github.com/carnot-tech/jinba-consulting-pptx-skill
- https://github.com/JohnHeibel/PDoomVideo
- https://github.com/oceanbase/powercontext
- https://github.com/rmyndharis/OpenWA
- https://github.com/TencentCloud/Octop
- https://github.com/nano-muse/nanoMuse
- https://github.com/Ebony-Vinyl/dsh-our-free-model
- https://github.com/kw2828/OpenJev
- https://github.com/OpenMili/aimili-vpngate
- https://github.com/pbakaus/impeccable
- https://github.com/Nutlope/hallmark
- https://github.com/makecindy/cindy
- https://github.com/luongnv89/claude-howto
- https://github.com/pollen-robotics/microduck
- https://github.com/Ikaleio/lm-detector
- https://github.com/milind-soni/OpenMausBot
- https://github.com/CopilotKit/OpenDuet

### #2996 (35개)

- https://github.com/CopilotKit/OpenMuse
- https://github.com/rlaope/oh-my-hermes
- https://github.com/techjanitor/botmaker
- https://github.com/msitarzewski/agency-agents
- https://github.com/Panniantong/Agent-Reach
- https://github.com/calesthio/OpenMontage
- https://github.com/SylphAI-Inc/adal-cli
- https://github.com/rociiu/talorys
- https://github.com/simstudioai/sim
- https://github.com/amontlabs/lcu
- https://github.com/MystenLabs/MemWal
- https://github.com/genspark-ai/genoffice
- https://github.com/THU-MAIC/OpenMAIC
- https://github.com/Tencent/WeKnora
- https://github.com/getzep/graphiti
- https://github.com/topoteretes/cognee
- https://github.com/open-webui/open-webui
- https://github.com/QwenAudio/qwen-audio-agent
- https://github.com/jamiepine/voicebox
- https://github.com/reason-machines/reason-network
- https://github.com/mem0ai/mem0
- https://github.com/vectorize-io/hindsight
- https://github.com/NevaMind-AI/memU
- https://github.com/letta-ai/letta
- https://github.com/letta-ai/letta-code
- https://github.com/mem0ai/openmemory
- https://github.com/vectorize-io/agent-memory-benchmark
- https://github.com/epoko77-ai/im-not-ai
- https://github.com/Nanako0129/sepia
- https://github.com/blader/humanizer
- https://github.com/textlint-ja/textlint-rule-preset-ai-writing
- https://github.com/op7418/Humanizer-zh
- https://github.com/TencentCloud/Octop
- https://github.com/nano-muse/nanoMuse
- https://github.com/CopilotKit/OpenIntelligentUI

### #4956 (5개)

- https://github.com/jkf87/murmur-translate
- https://github.com/jkf87/murmur
- https://github.com/jkf87/webmcp-practice
- https://github.com/morluto/rea
- https://github.com/block/buzz
## 2차 조사 — 2026-11-01

### Top 10 변경 이유

- **5번 교체:** OpenCode 출력 보관은 Hermes 출력 보관(2번)과 중복이다. Hermes Insights의 도구 호출 수·입출력 토큰 집계를 넣어 측정 공백을 일부 줄였다. [구현](https://github.com/NousResearch/hermes-agent/blob/main/agent/insights.py)·[훅](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/hooks.md)·[LICENSE](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE). 원본이 PADIEM PC 왕복·잘림 바이트·시간 초과를 자동 집계한다는 근거는 없으며 기존 B14 기록에 별도 연결해야 한다.
- **6번 교체:** OpenClaw의 압축은 OpenCode(4번)와 겹친다. OpenMuse의 MIT React Native Android 채팅·작업 진행 화면을 넣어 Android 항목을 채웠다. OpenMuse는 자체 브라우저와 Linux 작업공간을 쓰며 Android 단말 파일 커넥터를 제공한다고 확인된 것은 아니다.

### 관련 후보 상세

저장소 74곳을 조회해 LICENSE 원문과 기본 브랜치 최신 커밋·별을 확인했다. 다음은 #6460의 3·4·5·5-1과 연관된 후보만 추린 것이다. 별은 2026-11-01 조회 당시 수치다. 기능은 공개 저장소 설명 기준이고 PADIEM 실측은 아니다. 상용 호스팅·모델 비용은 미확인이다.

| 후보·해결 항목 | LICENSE 원문 | 가져오는 방법 | 최신 커밋 / 별 |
|---|---|---|---|
| [CopilotKit/OpenDuet](https://github.com/CopilotKit/OpenDuet) — 5-1 이어가기 | [MIT](https://github.com/CopilotKit/OpenDuet/blob/main/LICENSE) | MIT 지속 작업·진행 표시 부품 검토 | 2026-10-31 / 1739 |
| [CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse) — 5 Android Chat·5-1 이어가기 | [MIT](https://github.com/CopilotKit/openmuse/blob/main/LICENSE) | 모바일 채팅·진행 UI 코드 이식. 자체 브라우저는 Linux 작업공간이며 Android 파일 커넥터가 아님 | 2026-10-26 / 6029 |
| [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) — 5 브라우저·웹 접근 | [MIT](https://github.com/Panniantong/Agent-Reach/blob/main/LICENSE) | MIT CLI 중 웹 조회 부품 의존성 검토; 각 사이트의 로그인·이용 조건 별도 | 2026-11-01 / 107280 |
| [TencentCloud/Octop](https://github.com/TencentCloud/Octop) — 5-1 백그라운드·이어가기 | [MIT](https://github.com/TencentCloud/Octop/blob/main/LICENSE) | MIT의 작업 상태·복구 부품 검토; PADIEM 권한과 통합 필요 | 2026-10-25 / 11398 |
| [amontlabs/lcu](https://github.com/amontlabs/lcu) — 5 컴퓨터·브라우저 사용 | [MIT](https://github.com/amontlabs/lcu/blob/main/LICENSE) | MIT 코드 일부 검토; Windows 11 x64는 후보 단계라 Windows 실측 전 교체 금지 | 2026-10-31 / 2336 |
| [cloudflare/agentic-inbox](https://github.com/cloudflare/agentic-inbox) — 3 메일 채널 | [Apache-2.0](https://github.com/cloudflare/agentic-inbox/blob/main/LICENSE) | Apache-2.0 메일 화면·어댑터 검토; 비밀번호 재설정 메일 발송 구현과는 별도 | 2026-04-17 / 8567 |
| [genspark-ai/genoffice](https://github.com/genspark-ai/genoffice) — 3 문서·유틸 실행 | [Apache-2.0](https://github.com/genspark-ai/genoffice/blob/main/LICENSE) | Apache-2.0 오피스 CLI 일부 검토; 견적 양식 재현은 별도 실측 | 2026-10-30 / 11454 |
| [jkf87/webmcp-practice](https://github.com/jkf87/webmcp-practice) — 5 MCP 게이트웨이 | LICENSE 미확인 ([저장소](https://github.com/jkf87/webmcp-practice); LICENSE API 404) | 저장소 LICENSE API 404; 방식만 참고 | 2026-10-11 / 0 |
| [letta-ai/letta](https://github.com/letta-ai/letta) — 5-1 맥락·이어가기 | [Apache-2.0](https://github.com/letta-ai/letta/blob/main/LICENSE) | Apache-2.0 상태 저장 부품 비교; 별도 서버 전면 도입 아님 | 2026-10-18 / 25310 |
| [letta-ai/letta-code](https://github.com/letta-ai/letta-code) — 5-1 맥락·이어가기 | [Apache-2.0](https://github.com/letta-ai/letta-code/blob/main/LICENSE) | Apache-2.0 세션 기억 관련 코드 이식 검토; 계정 격리 별도 | 2026-11-01 / 3749 |
| [mem0ai/openmemory](https://github.com/mem0ai/openmemory) — 5-1 작업 이어가기 | [MIT](https://github.com/mem0ai/openmemory/blob/main/LICENSE) | MIT 세션 이관 부품 검토; Claude·Codex·OpenCode 대상이라 PADIEM 어댑터 필요 | 2026-07-29 / 101 |
| [morluto/rea](https://github.com/morluto/rea) — 5 컴퓨터·브라우저 사용 | [MIT](https://github.com/morluto/rea/blob/main/LICENSE) | MIT 진단 도구 일부 검토; 직접 PC 작업 경로 재사용 여부 추가 검증 | 2026-10-31 / 415980 |
| [nano-muse/nanoMuse](https://github.com/nano-muse/nanoMuse) — 5 Android 커넥터 | [GPL-3.0+](https://github.com/nano-muse/nanoMuse/blob/main/LICENSE) | GPL-3+; Android 접근·연결 방식만 참고, 직접 개발 | 2026-10-31 / 2955 |
| [oceanbase/powercontext](https://github.com/oceanbase/powercontext) — 5-1 작업 이어가기·맥락 | [Apache-2.0](https://github.com/oceanbase/powercontext/blob/master/LICENSE) | Apache-2.0 인계 부품 이식 검토; 제품의 실제 사용자 대화와 코드 에이전트 범위 차이 확인 | 2026-11-01 / 1472 |
| [open-webui/open-webui](https://github.com/open-webui/open-webui) — 5 Android Chat 대안 비교 | [Open WebUI License (비표준)](https://github.com/open-webui/open-webui/blob/main/LICENSE) | 별도 Open WebUI License: 표준 MIT 아님; 라이선스 판정 미완료, 참고만 | 2026-10-29 / 157421 |
| [simstudioai/sim](https://github.com/simstudioai/sim) — 5-1 측정·작업 이어가기 | [Apache-2.0](https://github.com/simstudioai/sim/blob/main/LICENSE) | Apache-2.0 작업 모니터링 UI·실행 상태 코드 검토; PC 왕복·잘림 필드 제공은 미검증 | 2026-10-31 / 29952 |
| [vectorize-io/agent-memory-benchmark](https://github.com/vectorize-io/agent-memory-benchmark) — 5-1 맥락 측정 | LICENSE 미확인 ([저장소](https://github.com/vectorize-io/agent-memory-benchmark); LICENSE API 404) | LICENSE API 404, 방식만 참고; PC 왕복·잘림·시간 초과 측정 도구는 아님 | 2026-10-31 / 159 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) — 5-1 맥락·이어가기 | [MIT](https://github.com/vectorize-io/hindsight/blob/main/LICENSE) | MIT 기억 관리 부품 검토; 대화 압축·작업 재개는 별도 검증 | 2026-10-30 / 57016 |

### 74개 저장소 확인 상태

아래는 기존 미확인 링크에서 중복·하위 경로를 저장소 단위로 합친 목록이다. LICENSE API의 404는 **라이선스가 없다고 단정하지 않고** 저장소 또는 파일 미확인으로 남겼다. 비표준·혼합 라이선스는 세부 범위를 검토하기 전 이식하지 않는다. 관련 후보가 아닌 항목은 #6460 범위 밖이다.

| 저장소 | LICENSE 직접 조회 | 최신 커밋 / 별 | 2차 판정 |
|---|---|---|---|
| [AhmadIbrahiim/Website-downloader](https://github.com/AhmadIbrahiim/Website-downloader) | [MIT](https://github.com/AhmadIbrahiim/Website-downloader/blob/master/LICENSE.md) | 2026-08-12 / 6057 | #6460 직접 연관 미확인 |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | [Apache-2.0](https://github.com/Aider-AI/aider/blob/main/LICENSE.txt) | 2026-05-22 / 49858 | #6460 직접 연관 미확인 |
| [CopilotKit/OpenDots](https://github.com/CopilotKit/OpenDots) | [MIT](https://github.com/CopilotKit/OpenDots/blob/main/LICENSE) | 2026-10-22 / 6269 | #6460 직접 연관 미확인 |
| [CopilotKit/OpenDuet](https://github.com/CopilotKit/OpenDuet) | [MIT](https://github.com/CopilotKit/OpenDuet/blob/main/LICENSE) | 2026-10-31 / 1739 | 위 상세 표 |
| [CopilotKit/OpenIntelligentUI](https://github.com/CopilotKit/OpenIntelligentUI) | [MIT](https://github.com/CopilotKit/OpenIntelligentUI/blob/main/LICENSE) | 2026-10-13 / 4088 | #6460 직접 연관 미확인 |
| [CopilotKit/OpenMuse](https://github.com/CopilotKit/OpenMuse) | [MIT](https://github.com/CopilotKit/openmuse/blob/main/LICENSE) | 2026-10-26 / 6029 | 위 상세 표 |
| [Ebony-Vinyl/dsh-our-free-model](https://github.com/Ebony-Vinyl/dsh-our-free-model) | [MIT](https://github.com/Ebony-Vinyl/dsh-our-free-model/blob/main/LICENSE) | 2026-11-01 / 54627 | #6460 직접 연관 미확인 |
| [Ikaleio/lm-detector](https://github.com/Ikaleio/lm-detector) | [MIT](https://github.com/Ikaleio/lm-detector/blob/main/LICENSE) | 2026-10-30 / 1306 | #6460 직접 연관 미확인 |
| [JohnHeibel/PDoomVideo](https://github.com/JohnHeibel/PDoomVideo) | 미확인 (API 404) | 2026-09-25 / 2753 | #6460 직접 연관 미확인 |
| [MystenLabs/MemWal](https://github.com/MystenLabs/MemWal) | [Apache-2.0](https://github.com/MystenLabs/walrus-memory/blob/dev/LICENSE) | 2026-10-30 / 131 | #6460 직접 연관 미확인 |
| [Nanako0129/sepia](https://github.com/Nanako0129/sepia) | [MIT](https://github.com/Nanako0129/sepia/blob/main/LICENSE) | 2026-10-31 / 3566 | #6460 직접 연관 미확인 |
| [NevaMind-AI/memU](https://github.com/NevaMind-AI/memU) | [혼합·비표준 원문](https://github.com/NevaMind-AI/memU/blob/main/LICENSE.txt) | 2026-10-30 / 14584 | #6460 직접 연관 미확인 |
| [NousResearch/hermes-official-plugins](https://github.com/NousResearch/hermes-official-plugins) | [MIT](https://github.com/NousResearch/hermes-official-plugins/blob/main/LICENSE) | 2026-11-01 / 558 | #6460 직접 연관 미확인 |
| [Nutlope/hallmark](https://github.com/Nutlope/hallmark) | [MIT](https://github.com/Nutlope/hallmark/blob/main/LICENSE) | 2026-10-29 / 44048 | #6460 직접 연관 미확인 |
| [OpenMili/aimili-vpngate](https://github.com/OpenMili/aimili-vpngate) | [혼합·비표준 원문](https://github.com/OpenMili/aimili-vpngate/blob/main/LICENSE) | 2026-10-14 / 2310 | #6460 직접 연관 미확인 |
| [Panniantong/Agent-Reach](https://github.com/Panniantong/Agent-Reach) | [MIT](https://github.com/Panniantong/Agent-Reach/blob/main/LICENSE) | 2026-11-01 / 107280 | 위 상세 표 |
| [QwenAudio/qwen-audio-agent](https://github.com/QwenAudio/qwen-audio-agent) | [Apache-2.0](https://github.com/QwenAudio/qwen-audio-agent/blob/main/LICENSE) | 2026-10-29 / 3095 | #6460 직접 연관 미확인 |
| [Rescenix/Yosuri](https://github.com/Rescenix/Yosuri) | [AGPL-3.0](https://github.com/Rescenix/Yosuri/blob/main/LICENSE) | 2026-09-24 / 88 | #6460 직접 연관 미확인 |
| [Sac-Y/Jev-cu](https://github.com/Sac-Y/Jev-cu) | [MIT](https://github.com/Sac-Y/Jev-cu/blob/main/LICENSE) | 2026-09-22 / 630 | #6460 직접 연관 미확인 |
| [Subhan-code/Amicro--Micro-transitions-](https://github.com/Subhan-code/Amicro--Micro-transitions-) | [MIT](https://github.com/Subhan-code/Amicro--Micro-transitions-/blob/main/LICENSE) | 2026-10-26 / 2738 | #6460 직접 연관 미확인 |
| [SylphAI-Inc/adal-cli](https://github.com/SylphAI-Inc/adal-cli) | 미확인 (API 404) | 2026-09-22 / 111 | #6460 직접 연관 미확인 |
| [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) | [MIT](https://github.com/THU-MAIC/OpenMAIC/blob/main/LICENSE) | 2026-10-30 / 42250 | #6460 직접 연관 미확인 |
| [Tencent/WeKnora](https://github.com/Tencent/WeKnora) | [혼합·비표준 원문](https://github.com/Tencent/WeKnora/blob/main/LICENSE) | 2026-10-30 / 36135 | #6460 직접 연관 미확인 |
| [TencentCloud/Octop](https://github.com/TencentCloud/Octop) | [MIT](https://github.com/TencentCloud/Octop/blob/main/LICENSE) | 2026-10-25 / 11398 | 위 상세 표 |
| [YuJunZhiXue/dsh-purge](https://github.com/YuJunZhiXue/dsh-purge) | [Apache-2.0](https://github.com/YuJunZhiXue/dsh-purge/blob/master/LICENSE) | 2026-10-31 / 14703 | #6460 직접 연관 미확인 |
| [akazwz/hostc](https://github.com/akazwz/hostc) | [Apache-2.0](https://github.com/akazwz/hostc/blob/main/LICENSE) | 2026-11-01 / 608 | #6460 직접 연관 미확인 |
| [amontlabs/lcu](https://github.com/amontlabs/lcu) | [MIT](https://github.com/amontlabs/lcu/blob/main/LICENSE) | 2026-10-31 / 2336 | 위 상세 표 |
| [blader/humanizer](https://github.com/blader/humanizer) | [MIT](https://github.com/blader/humanizer/blob/main/LICENSE) | 2026-10-28 / 63014 | #6460 직접 연관 미확인 |
| [block/buzz](https://github.com/block/buzz) | [Apache-2.0](https://github.com/block/buzz/blob/main/LICENSE) | 2026-10-31 / 36643 | #6460 직접 연관 미확인 |
| [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) | [AGPL-3.0](https://github.com/calesthio/OpenMontage/blob/main/LICENSE) | 2026-10-28 / 74044 | #6460 직접 연관 미확인 |
| [carnot-tech/jinba-consulting-pptx-skill](https://github.com/carnot-tech/jinba-consulting-pptx-skill) | [MIT](https://github.com/carnot-tech/jinba-consulting-pptx-skill/blob/main/LICENSE) | 2026-10-25 / 1455 | #6460 직접 연관 미확인 |
| [cloudflare/agentic-inbox](https://github.com/cloudflare/agentic-inbox) | [Apache-2.0](https://github.com/cloudflare/agentic-inbox/blob/main/LICENSE) | 2026-04-17 / 8567 | 위 상세 표 |
| [continuedev/continue](https://github.com/continuedev/continue) | [Apache-2.0](https://github.com/continuedev/continue/blob/main/LICENSE) | 2026-07-21 / 36386 | #6460 직접 연관 미확인 |
| [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio) | [AGPL-3.0](https://github.com/debpalash/VoiceStudio/blob/main/LICENSE) | 2026-11-01 / 97009 | #6460 직접 연관 미확인 |
| [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) | [MIT](https://github.com/epoko77-ai/im-not-ai/blob/main/LICENSE) | 2026-10-12 / 6347 | #6460 직접 연관 미확인 |
| [genspark-ai/genoffice](https://github.com/genspark-ai/genoffice) | [Apache-2.0](https://github.com/genspark-ai/genoffice/blob/main/LICENSE) | 2026-10-30 / 11454 | 위 상세 표 |
| [getzep/graphiti](https://github.com/getzep/graphiti) | [Apache-2.0](https://github.com/getzep/graphiti/blob/main/LICENSE) | 2026-11-01 / 32403 | #6460 직접 연관 미확인 |
| [github/codeql](https://github.com/github/codeql) | [MIT](https://github.com/github/codeql/blob/main/LICENSE) | 2026-10-30 / 10283 | #6460 직접 연관 미확인 |
| [hkqr/my-free-code](https://github.com/hkqr/my-free-code) | 미확인 (API 404) | 미확인 / 미확인 | 접근 불가 (저장소 API 404) |
| [jamiepine/voicebox](https://github.com/jamiepine/voicebox) | [MIT](https://github.com/jamiepine/voicebox/blob/main/LICENSE) | 2026-10-07 / 59164 | #6460 직접 연관 미확인 |
| [jkf87/murmur](https://github.com/jkf87/murmur) | 미확인 (API 404) | 2026-08-24 / 22 | #6460 직접 연관 미확인 |
| [jkf87/murmur-translate](https://github.com/jkf87/murmur-translate) | [MIT](https://github.com/jkf87/murmur-translate/blob/main/LICENSE) | 2026-10-13 / 0 | #6460 직접 연관 미확인 |
| [jkf87/webmcp-practice](https://github.com/jkf87/webmcp-practice) | 미확인 (API 404) | 2026-10-11 / 0 | 위 상세 표 |
| [kajisho5/ffmpeg-skill](https://github.com/kajisho5/ffmpeg-skill) | [MIT](https://github.com/kajisho5/ffmpeg-skill/blob/main/LICENSE) | 2026-10-31 / 4201 | #6460 직접 연관 미확인 |
| [kw2828/OpenJev](https://github.com/kw2828/OpenJev) | [MIT](https://github.com/kw2828/OpenJev/blob/main/LICENSE) | 2026-09-25 / 2 | #6460 직접 연관 미확인 |
| [letta-ai/letta](https://github.com/letta-ai/letta) | [Apache-2.0](https://github.com/letta-ai/letta/blob/main/LICENSE) | 2026-10-18 / 25310 | 위 상세 표 |
| [letta-ai/letta-code](https://github.com/letta-ai/letta-code) | [Apache-2.0](https://github.com/letta-ai/letta-code/blob/main/LICENSE) | 2026-11-01 / 3749 | 위 상세 표 |
| [luongnv89/claude-howto](https://github.com/luongnv89/claude-howto) | [MIT](https://github.com/luongnv89/claude-howto/blob/main/LICENSE) | 2026-10-29 / 46291 | #6460 직접 연관 미확인 |
| [makecindy/cindy](https://github.com/makecindy/cindy) | [Apache-2.0](https://github.com/makecindy/cindy/blob/main/LICENSE) | 2026-11-01 / 8844 | #6460 직접 연관 미확인 |
| [mem0ai/mem0](https://github.com/mem0ai/mem0) | [Apache-2.0](https://github.com/mem0ai/mem0/blob/main/LICENSE) | 2026-10-30 / 68181 | #6460 직접 연관 미확인 |
| [mem0ai/openmemory](https://github.com/mem0ai/openmemory) | [MIT](https://github.com/mem0ai/openmemory/blob/main/LICENSE) | 2026-07-29 / 101 | 위 상세 표 |
| [milind-soni/OpenMausBot](https://github.com/milind-soni/OpenMausBot) | [Apache-2.0](https://github.com/milind-soni/OpenMausBot/blob/main/LICENSE) | 2026-10-31 / 9788 | #6460 직접 연관 미확인 |
| [morluto/rea](https://github.com/morluto/rea) | [MIT](https://github.com/morluto/rea/blob/main/LICENSE) | 2026-10-31 / 415980 | 위 상세 표 |
| [msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) | [MIT](https://github.com/msitarzewski/agency-agents/blob/main/LICENSE) | 2026-10-25 / 165724 | #6460 직접 연관 미확인 |
| [nano-muse/nanoMuse](https://github.com/nano-muse/nanoMuse) | [GPL-3.0](https://github.com/nano-muse/nanoMuse/blob/main/LICENSE) | 2026-10-31 / 2955 | 위 상세 표 |
| [oceanbase/powercontext](https://github.com/oceanbase/powercontext) | [Apache-2.0](https://github.com/oceanbase/powercontext/blob/master/LICENSE) | 2026-11-01 / 1472 | 위 상세 표 |
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | [MIT](https://github.com/op7418/Humanizer-zh/blob/main/LICENSE) | 2026-09-23 / 21626 | #6460 직접 연관 미확인 |
| [open-webui/open-webui](https://github.com/open-webui/open-webui) | [혼합·비표준 원문](https://github.com/open-webui/open-webui/blob/main/LICENSE) | 2026-10-29 / 157421 | 위 상세 표 |
| [oracle/opengrok](https://github.com/oracle/opengrok) | [혼합·비표준 원문](https://github.com/oracle/opengrok/blob/master/LICENSE.txt) | 2026-10-20 / 5025 | #6460 직접 연관 미확인 |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | [Apache-2.0](https://github.com/pbakaus/impeccable/blob/main/LICENSE) | 2026-10-31 / 98451 | #6460 직접 연관 미확인 |
| [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) | [Apache-2.0](https://github.com/pollen-robotics/microduck/blob/main/LICENSE) | 2026-10-30 / 13241 | #6460 직접 연관 미확인 |
| [reason-machines/reason-network](https://github.com/reason-machines/reason-network) | [Apache-2.0](https://github.com/reason-machines/reason-network/blob/main/LICENSE-APACHE) | 2026-10-30 / 1413 | #6460 직접 연관 미확인 |
| [rlaope/oh-my-hermes](https://github.com/rlaope/oh-my-hermes) | [MIT](https://github.com/rlaope/oh-my-hermes/blob/main/LICENSE) | 2026-10-31 / 4981 | #6460 직접 연관 미확인 |
| [rmyndharis/OpenWA](https://github.com/rmyndharis/OpenWA) | [MIT](https://github.com/rmyndharis/OpenWA/blob/main/LICENSE) | 2026-10-31 / 16431 | #6460 직접 연관 미확인 |
| [rociiu/talorys](https://github.com/rociiu/talorys) | [MIT](https://github.com/rociiu/talorys/blob/main/LICENSE) | 2026-10-31 / 1430 | #6460 직접 연관 미확인 |
| [semgrep/semgrep](https://github.com/semgrep/semgrep) | [LGPL-2.1](https://github.com/semgrep/semgrep/blob/develop/LICENSE) | 2026-10-28 / 17387 | #6460 직접 연관 미확인 |
| [simstudioai/sim](https://github.com/simstudioai/sim) | [Apache-2.0](https://github.com/simstudioai/sim/blob/main/LICENSE) | 2026-10-31 / 29952 | 위 상세 표 |
| [sourcegraph/sourcegraph](https://github.com/sourcegraph/sourcegraph) | 미확인 (API 404) | 미확인 / 미확인 | 접근 불가 (저장소 API 404) |
| [techjanitor/botmaker](https://github.com/techjanitor/botmaker) | [MIT](https://github.com/techjanitor/botmaker/blob/main/LICENSE) | 2026-09-01 / 289 | #6460 직접 연관 미확인 |
| [textlint-ja/textlint-rule-preset-ai-writing](https://github.com/textlint-ja/textlint-rule-preset-ai-writing) | [MIT](https://github.com/textlint-ja/textlint-rule-preset-ai-writing/blob/main/LICENSE) | 2026-05-13 / 1159 | #6460 직접 연관 미확인 |
| [topoteretes/cognee](https://github.com/topoteretes/cognee) | [Apache-2.0](https://github.com/topoteretes/cognee/blob/main/LICENSE) | 2026-10-29 / 32969 | #6460 직접 연관 미확인 |
| [vectorize-io/agent-memory-benchmark](https://github.com/vectorize-io/agent-memory-benchmark) | 미확인 (API 404) | 2026-10-31 / 159 | 위 상세 표 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | [MIT](https://github.com/vectorize-io/hindsight/blob/main/LICENSE) | 2026-10-30 / 57016 | 위 상세 표 |
| [win4r/MuseAI-Skills](https://github.com/win4r/MuseAI-Skills) | 미확인 (API 404) | 2026-09-28 / 406 | #6460 직접 연관 미확인 |

### X·YouTube 원문 접근 결과

기존 목록의 고유 링크 324개를 개별 요청했다. 275개는 DisabledError, 37개는 HTTP 403, 9개는 조회 제한, 3개는 제목만 반환되어 본문·영상·자막을 확인하지 못했다. 원본 목록의 각 링크 뒤에 실제 반환 사유를 표시했다. 이 결과는 콘텐츠 자체의 삭제 여부를 뜻하지 않는다. 이전 이슈의 요약과 저장소 원문은 별도로 확인한 근거다.

### 확인 범위와 남은 일

- 측정: Hermes는 도구 호출 수와 토큰 집계 재사용 후 PC 호출과 결과의 잘림 바이트·타임아웃을 PADIEM 측에서 기록해야 한다. 실제 소스 변경·실측은 이번 조사 범위 밖이다.
- Android: OpenMuse는 Android 화면 재사용 후보이며 기기 파일 접근용 커넥터라고 단정하지 않는다. nanoMuse Android 앱은 GPL-3.0+이므로 방식을 참고한다.
- 1차 원문 링크 목록은 보존했다. 미확인 저장소의 하위 파일 각각과 X·영상 본문은 접근 가능한 원문이 없어 확인되지 않았다. 공개 저장소 검증 결과는 위 표를 따른다.
