# 개발 대신 가져올 후보 — 2026-11-01

## 바로 가져올 것 Top 10

| 순위 | #6460 미완료 항목 | 후보 | 라이선스 | 방법 |
|---:|---|---|---|---|
| 1 | 5-1 맥락 관리 | [Hermes 압축](https://github.com/NousResearch/hermes-agent/tree/main/agent) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 압축 부품 이식, 기존 B14 경유 |
| 2 | 5-1 큰 출력 보관 | [Hermes 터미널](https://github.com/NousResearch/hermes-agent/blob/main/tools/terminal_tool.py) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 파일 보관·참조 방식 이식, 구간 읽기 연결 |
| 3 | 5-1 긴 작업 백그라운드 | [Hermes 프로세스](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/tools.md) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 프로세스 관리 이식, COM2 작업 기록 연결 |
| 4 | 5-1 작업 이어가기 | [OpenCode 압축](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/compaction.ts) | [MIT](https://github.com/anomalyco/opencode/blob/dev/LICENSE) | 완료·진행·다음 단계 요약 형식 이식 |
| 5 | 5-1 큰 출력 | [OpenCode 출력 처리](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/v1/config/config.ts) | [MIT](https://github.com/anomalyco/opencode/blob/dev/LICENSE) | 파일 보관·미리보기 정책 이식; 2번과 비교 후 선택 |
| 6 | 5-1 맥락·이어가기 | [OpenClaw](https://github.com/openclaw/openclaw) | [MIT](https://github.com/openclaw/openclaw/blob/main/LICENSE) | 압축 후 원본 추적·생략 표시 부분 이식 |
| 7 | 5-1 왕복 줄이기 | [Hermes 묶음 실행](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/code-execution.md) | [MIT](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) | 묶음 인터페이스 이식; 내부 행동도 공통 하네스 통과 |
| 8 | 5·5-1 코드 탐색 | [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | [MIT](https://github.com/DeusData/codebase-memory-mcp/blob/main/LICENSE) | MCP 의존성 시험 |
| 9 | 5·5-1 코드 탐색 | [Serena SolidLSP](https://github.com/oraios/serena/tree/main/src/solidlsp) | [해당 부분 MIT](https://github.com/oraios/serena/blob/main/LICENSE) | MIT 디렉터리만 이식; Serena 앱은 GPL |
| 10 | 5 브라우저 사용 | [Browser Use](https://github.com/browser-use/browser-use) | [MIT](https://github.com/browser-use/browser-use/blob/main/LICENSE) | 기존 브라우저 권한에 라이브러리 연결 |

같은 제품의 다른 부품은 각각 순위에 넣었다. 사용 가능 라이선스라는 뜻이며 설치·연동·실사용 검증이 완료됐다는 뜻은 아니다. 5-1의 **PC 왕복·잘림·시간 초과 측정**은 바로 가져올 검증된 부품을 찾지 못했다.

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

- https://x.com/Kimi_Moonshot/status/2110687135183593646
- https://x.com/xiangxiang103/status/2110638131720700149
- https://x.com/mercury__agent/status/2110290765154799771
- https://x.com/mercury__agent/status/2110653153154568203
- https://x.com/NFT_Chen/status/2110635082860085486
- https://x.com/Lonely__MH/status/2110988196352073748
- https://x.com/suraj_sharma14/status/2110702226565906887
- https://x.com/PrunaAI/status/2110386051277550063
- https://x.com/taiyanghere/status/2110007655154483247
- https://x.com/itsjdraven/status/2110276791458038039
- https://x.com/anya_yfa7/status/2110608460270501985
- https://x.com/wesbos/status/2110509898958008515
- https://x.com/ishaan_jaff/status/2109752409597845962
- https://x.com/suraj_sharma14/status/2109690568590635440
- https://x.com/kawaidgaf/status/2110304679586631723
- https://x.com/TylerBai_loveai/status/2109569779984216346
- https://x.com/SahilPanhotra/status/2109004299674268099
- https://x.com/sergiorocaa/status/2108960970626248759
- https://x.com/TencentAI_News/status/2108133183019684187
- https://x.com/loki_yan_seo/status/2109262732763783400
- https://x.com/alxshp/status/2107879013641560218
- https://x.com/taiyanghere/status/2107864775262642320
- https://x.com/useincredible/status/2107457256090411223
- https://x.com/Rohit_Writes/status/2107161119064551924
- https://x.com/npm_i_shaders/status/2107467668009963819
- https://x.com/gmi_cloud/status/2107909066739814866
- https://x.com/EmperoAI/status/2107203283630628923
- https://x.com/michellechen/status/2106894709696422189
- https://x.com/cline/status/2107202446812733546
- https://x.com/BlockInsight214/status/2106664825346719889
- https://x.com/reflection_ai/status/2107186849370247235
- https://x.com/NFTCPS/status/2106682991972098122
- https://x.com/CopilotKit/status/2106489504236511533
- https://x.com/calbuldelis69/status/2107089393672704007
- https://x.com/melvindvivas/status/2106996300474683839
- https://x.com/xiangxiang103/status/2106803637167259707
- https://x.com/tomik99/status/2105777404174115117
- https://x.com/kawaidgaf/status/2105894157193748951
- https://x.com/calbuldelis69/status/2106077462207881561
- https://x.com/juampitech/status/2106395850830438509
- https://x.com/Yanir_/status/2105739528988238211
- https://x.com/OpenBot_/status/2105666545842012445
- https://x.com/ataiiam/status/2105710796198322659
- https://x.com/MonidHQ/status/2105089581330882973
- https://x.com/Tiny_Fish/status/2105009755442090123
- https://x.com/OpenAIDevs/status/2104997619152130278
- https://x.com/Offloop/status/2104900654137590212
- https://x.com/kseniam0s/status/2105370329434489265
- https://x.com/hanghuang_/status/2104949571789148416
- https://x.com/yiliush/status/2104997540454371658
- https://x.com/CopilotKit/status/2104899424585683381
- https://x.com/_inception_ai/status/2104974439314321660
- https://x.com/johnrush/status/2105067074720829819
- https://x.com/browser_use/status/2104814685518491911
- https://x.com/ai_fengshou/status/2104417258923773954
- https://x.com/nex_ify/status/2104491498444136512
- https://x.com/dingyi/status/2104604727900275072
- https://x.com/_0xKenny/status/2104639676598383095
- https://x.com/koffuxu/status/2104417854754034170
- https://x.com/itsjdraven/status/2104552519032869045
- https://x.com/TencentAI_News/status/2104500084880662942
- https://x.com/xiaomovps/status/2104198873774469409
- https://x.com/mylifcc/status/2104430399053045976
- https://x.com/MinLiBuilds/status/2104143124532781067
- https://x.com/akazwz_/status/2104125352293605774
- https://x.com/Lummox_eth/status/2104218875810185287
- https://x.com/garrytan/status/2104221282095218731
- https://x.com/lucas_flatwhite/status/2104114543463190699
- https://x.com/shao__meng/status/2104138489268670941
- https://x.com/usehazeai/status/2103151105236431283
- https://x.com/xiao92666/status/2102972794661486623
- https://x.com/hfcorriez/status/2102871334657397099
- https://x.com/Krongggggg/status/2102930610969088238
- https://x.com/VibeEverything/status/2102697640572113224
- https://x.com/nowlovepan/status/2103103135682306537
- https://x.com/polymarketjapan/status/2102982988170666291
- https://x.com/elonmusk/status/2102798963837665464
- https://x.com/trendtech33566/status/2102599463412076974
- https://x.com/Saccc_c/status/2101152089598791845
- https://x.com/moritzkremb/status/2100715237267660873
- https://x.com/TeddyinMedia/status/2099859887102558507
- https://x.com/AISuperDomain/status/2099648097357807991
- https://x.com/zefirium/status/2092659023002632532
- https://x.com/Jolyne_AI/status/2073285687793873367
- https://x.com/EngMoElgaraihy/status/2099511660205531263
- https://x.com/omarsar0/status/2105736578673033564
- https://x.com/taiyanghere/status/2110529688426909798
- https://x.com/xiangxiang103/status/2103705259554275560
- https://x.com/EngMoElgaraihy/status/2103918527845392787
- https://x.com/xiangxiang103/status/2103817359396118855
- https://x.com/huoshan007/status/2104013133786529812
- https://x.com/WalrusProtocol/status/2062646758564343908
- https://x.com/Shruti_0810/status/2103894457322262615
- https://x.com/MinLiBuilds/status/2103629659569336765
- https://x.com/SUOHA_AI/status/2103806382235378167
- https://x.com/pengsonal/status/2103714760441384976
- https://x.com/Sn0wbrave/status/2103078611783721444
- https://x.com/acidsound/status/2101295952422457786
- https://x.com/getjinxo/status/2111849640031322595
- https://x.com/ghumare64/status/2111332908657148356
- https://x.com/harrisonitsme/status/2099109471993872817
- https://x.com/reasonmachines/status/2111135100142518430
- https://x.com/suraj_sharma14/status/2109464068356546958
- https://x.com/lucian__03/status/2103097036254126238
- https://x.com/suraj_sharma14/status/2112038533510599020
- https://x.com/fankaishuoai/status/2111484271198343195
- https://x.com/elonmusk/status/2111161779657285919
- https://x.com/EngMoElgaraihy/status/2111297758934028330
- https://x.com/suraj_sharma14/status/2110015201177375032
- https://x.com/AniC_dev/status/2102785812635214139
- https://x.com/hridoyreh/status/2104100192719130843
- https://x.com/realchendahuang/status/2112167421390004459
- https://x.com/calbuldelis69/status/2112239888724808067
- https://x.com/ExaAILabs/status/2112218730952601719
- https://x.com/voidyaps/status/2112143153058988366
- https://x.com/rammcodes/status/2112175596071755830
- https://x.com/mylifcc/status/2111970589401321902
- https://x.com/gbauzap/status/2106492677344633185
- https://x.com/OpenBot_/status/2106330922861858826
- https://x.com/openclaw/status/2112260434116108528
- https://x.com/RodmanAi/status/2112210714949726604
- https://x.com/hqmank/status/2103834161090081097
- https://x.com/oldstackjournal/status/2103661382906638811
- https://x.com/yyyole/status/2103661669532774688
- https://x.com/calbuldelis69/status/2103771239672422517
- https://x.com/bkdgiffug/status/2106505321774526581
- https://x.com/itsjdraven/status/2103407813360066626
- https://x.com/FactoryAI/status/2103528493133000751
- https://www.youtube.com/watch?v=NLsiZtleLe4
- https://x.com/XRay96/status/2103354801400762528
- https://x.com/shneural/status/2103151003272962130
- https://x.com/AskPerplexity/status/2103484879937896710
- https://x.com/AISuperDomain/status/2103399761772683513
- https://x.com/aiehon_aya/status/2103403361022419005
- https://x.com/NousResearch/status/2102873234819698877
- https://x.com/Gozengogo_/status/2103349964290322846
- https://x.com/tonbistudio/status/2103374537182314751
- https://x.com/NousResearch/status/2103244070407802905
- https://x.com/perplexitydevs/status/2103241128216875283
- https://x.com/xiaohu/status/2102979455308439555
- https://x.com/steipete/status/2103147927313199260
- https://x.com/tkm_hmng8/status/2103304541588631671
- https://x.com/maarcoofdezz/status/2103084734892957889
- https://www.youtube.com/watch?v=knvviM-LAZU
- https://x.com/ChrisMTeryli/status/2099136522985324753
- https://x.com/pcmanabucom/status/2111357965965938928
- https://x.com/franpradasAI/status/2111129542647792070
- https://x.com/Farewe1ll/status/2111500162803867758
- https://x.com/OlatunjiAyokan2/status/2111317596574278138
- https://x.com/Manu_Sisti/status/2111441903476728094
- https://x.com/bot/status/2111184276662481202
- https://x.com/libukai/status/2111498950339658194
- https://x.com/gefei55/status/2104244165739766087
- https://x.com/DRbitcoin36/status/2104166358292595125
- https://x.com/Appkittie/status/2112193313235435547
- https://x.com/mercury__agent/status/2112804830456713644
- https://x.com/mattyp/status/2102759899314741736
- https://x.com/NaceAI/status/2112642726877405531
- https://x.com/Texas_Twins_Dad/status/2112622519983423515
- https://x.com/MiniMaxAgent/status/2112860752830931341
- https://x.com/memoh_ai/status/2112756499961557292
- https://x.com/WorkBuddy_AI/status/2112776352143425793
- https://x.com/PrajwalTomar_/status/2112521739976716525
- https://x.com/liambraus/status/2112176354909135306
- https://x.com/TencentAI_News/status/2112115861301649834
- https://x.com/yedabinbinah/status/2112515676027969970
- https://x.com/binghe/status/2112551923610227013
- https://x.com/benyuls/status/2112539062347174312
- https://x.com/bot/status/2112645531076096330
- https://x.com/OpenAIDevs/status/2112603916076781778
- https://x.com/Ga_Vasques/status/2112565952608952586
- https://x.com/WojakTheDev/status/2113200900412223530
- https://x.com/Suu766/status/2102604997049602527
- https://x.com/Suu766/status/2102604999515885757
- https://x.com/Suu766/status/2102605002133123270
- https://x.com/Suu766/status/2102605004775489662
- https://x.com/Suu766/status/2102605007325643257
- https://x.com/Suu766/status/2102605010270138846
- https://x.com/Suu766/status/2102605012979605630
- https://x.com/Suu766/status/2102605015567499546
- https://x.com/Suu766/status/2102605018209919034
- https://x.com/Suu766/status/2102605020940369932
- https://x.com/Suu766/status/2102605023641493506
- https://x.com/Suu766/status/2102605026913120357
- https://x.com/Suu766/status/2102605029530329127
- https://www.youtube.com/watch?v=ZoqgAy3h4OM
- https://www.youtube.com/watch?v=5MgBikgcWnY
- https://x.com/browser_use/status/2113299829489279126
- https://x.com/1Password/status/2113276767582498943
- https://x.com/grok/status/2103455600273449121
- https://x.com/inflowpayai/status/2112937220953035046
- https://x.com/i/article/2112936733251924057
- https://x.com/BearHuddleston/status/2114404737369911462
- https://x.com/BearHuddleston/status/2104109388780744775
- https://x.com/hiwise_aigc/status/2114287632683520385
- https://x.com/vmkbuilds/status/2114211061926965303
- https://x.com/BkashJosi/status/2114462089943413240
- https://x.com/GodsBoy7777/status/2114453912488948195
- https://x.com/BkashJosi/status/2114204582536688127
- https://x.com/Geeby_1/status/2111415265309425771
- https://x.com/hezycrypto/status/2111408739521581325
- https://x.com/alextalksai/status/2112556295370809688
- https://x.com/ikshitijsharma/status/2112817192089931941
- https://x.com/Jiler830219/status/2112574125474521197
- https://x.com/Hu59645Hugo/status/2112600855086034954
- https://x.com/MiniMax_AI/status/2112987176053215566
- https://x.com/GenAI_is_real/status/2112938798262919675
- https://x.com/MiniMax_AI/status/2110207378725740887
- https://x.com/Argona0x/status/2101400788731846664
- https://x.com/CryptoPainter/status/2101331932084883541
- https://x.com/suraj_sharma14/status/2114499750628327554
- https://x.com/pdp/status/2114341538364809575
- https://x.com/neeeel/status/2114425316135567634
- https://x.com/anya_yfa7/status/2114528505711263925
- https://x.com/alannnfx/status/2114600590366175385
- https://x.com/zeviodotsh/status/2114472975273759104
- https://x.com/Lovislexus/status/2114129813103628765
- https://x.com/donniy520/status/2114001247762022648
- https://x.com/liangzhu_AI/status/2114249096995451055
- https://x.com/byronzhang01/status/2114335975824576525
- https://x.com/seanbuildlog/status/2114280528694346005
- https://x.com/GitTrend0x/status/2114152481881989579
- https://x.com/Taheer_Defi/status/2114539271059345481
- https://x.com/fabioricotta/status/2114697690894188977:
- https://x.com/milindlabs/status/2114818252019036289
- https://x.com/making_cindy/status/2113993797671801149
- https://x.com/suraj_sharma14/status/2114612998593712228
- https://x.com/appinn/status/2114700442160566638
- https://x.com/WojakTheDev/status/2114613004264149361
- https://x.com/SungKimUp/status/2114886177111281788
- https://x.com/jojeangsaing/status/2114881094914805837
- https://x.com/taiyanghere/status/2114703397895250259
- https://x.com/alexmichael/status/2114894612406100333
- https://x.com/kseniam0s/status/2114802233971757248
- https://x.com/MetaforDevs/status/2114773643796631717
- https://x.com/BkashJosi/status/2114763790013341766
- https://x.com/Tiny_Fish/status/2114880848306770135
- https://x.com/Lovislexus/status/2114892336240963762
- https://x.com/lucaardito/status/2114814780162937208
- https://x.com/brettcalhounn/status/2114716427290640444
- https://x.com/BlackMelooo/status/2114750492320620673
- https://x.com/jojeangsaing/status/2114596792725872646
- https://x.com/morganxu45/status/2114677995097248070
- https://x.com/Lovislexus/status/2114869687783739824
- https://x.com/xiaomovps/status/2114977428682809759
- https://x.com/Lovislexus/status/2114885037577375972
- https://x.com/ataiiam/status/2115097056394240293
- https://x.com/alannnfx/status/2115082464196497817
- https://x.com/x_insider4/status/2114393316158537843
- https://x.com/bot/status/2115130760009273501

### #2996 (19개)

- https://x.com/adalagent/status/2102774996124721214
- https://x.com/kawaidgaf/status/2110755714209882455
- https://youtu.be/QOAJYkuX_-Y
- https://x.com/LawrenceW_Zen/status/2112052626494017951
- https://x.com/cu30rry_/status/2111738806139511125
- https://x.com/bot/status/2111184270819803351
- https://x.com/WalrusProtocol/status/2062646758564343908
- https://x.com/Shruti_0810/status/2103894457322262615
- https://x.com/Sn0wbrave/status/2103078611783721444
- https://x.com/acidsound/status/2101295952422457786
- https://x.com/getjinxo/status/2111849640031322595
- https://x.com/harrisonitsme/status/2099109471993872817
- https://x.com/suraj_sharma14/status/2110702226565906887
- https://x.com/reasonmachines/status/2111135100142518430
- https://x.com/cursor_ai/status/2111193957527146711
- https://x.com/suraj_sharma14/status/2109464068356546958
- https://x.com/Lummox_eth/status/2104218875810185287
- https://x.com/lucas_flatwhite/status/2104114543463190699
- https://x.com/yulmu_coffee/status/2102812297718886904

### #4956 (67개)

- https://www.youtube.com/watch?v=L09kacrneOc
- https://www.youtube.com/watch?v=Ngqxa0B6DqE
- https://www.youtube.com/watch?v=I-m4HSjptAM
- https://www.youtube.com/watch?v=GchXMRwuWxE
- https://youtu.be/Oo_GGWV9Hys
- https://youtu.be/IF-dwIm1YMo
- https://youtu.be/QfPJyzflkAI
- https://youtu.be/Fk5pQ0fQkJ0
- https://youtu.be/Or_yGUXwjMY
- https://youtu.be/oGzdBoKam0c
- https://youtu.be/vOZ5jdLJ3LE
- https://www.youtube.com/live/_M0admzUkuo
- https://youtu.be/9JDYeLgn7Q8
- https://youtu.be/NE306sbvopY
- https://youtu.be/YDjBNzhTUWo
- https://youtu.be/YiKAbr0KSPk
- https://youtu.be/IuxDOrKdMW8
- https://youtu.be/VAOdUAkVGpE
- https://youtu.be/Fd8XVsCZSjs
- https://youtu.be/IFE3KAz_Jbs
- https://www.youtube.com/watch?v=RDosoTCHFHA
- https://youtu.be/iHjWs6rXVvU
- https://youtu.be/gv0nZoxqIGo
- https://youtu.be/GvtjzW8UZCM
- https://youtu.be/-gfgQfw2g_E
- https://youtu.be/QPvScQBDrdw
- https://youtu.be/IMhsMzlzsTk
- https://youtu.be/KZiF2J83zaY
- https://youtu.be/Hn6bSMOpcoA
- https://youtu.be/NOOq7pagTSg
- https://youtu.be/-LWUtW87jlM
- https://youtu.be/tByhXkxDKDo
- https://www.youtube.com/watch?v=pFO41hA9doQ
- https://youtu.be/UMDSNYu7iNU
- https://youtu.be/ymj8Ha0oBtU
- https://youtu.be/OXg-0BXf_Yk
- https://youtu.be/z-cxE0yus4g
- https://www.youtube.com/live/9jgyfkG-9wA
- https://youtu.be/yUjTWl7tOYc
- https://www.youtube.com/watch?v=R3-anFK1YM8
- https://youtu.be/4AvQQHDTJFE
- https://youtu.be/qWJ5Nzf68Iw
- https://youtu.be/Cy1xjHaoqGI
- https://youtu.be/suK5R-j67Gg
- https://youtu.be/wJs7Ut2diB0
- https://youtu.be/gmhCepXTHaI
- https://youtu.be/qOqcz6J7K-o
- https://youtu.be/oT4zOjEc_BA
- https://youtu.be/R2SOaieHus8
- https://youtu.be/W_-ecvxMu3Y
- https://youtu.be/qh0FkdgieS8
- https://youtu.be/7ZOjMnbxJYE
- https://youtu.be/Kbf8yqauzF0
- https://youtu.be/jajEm8R9nD0
- https://youtu.be/JMeO5IOB22I
- https://youtu.be/tnOYNzGb_uA
- https://www.youtube.com/live/cBcPyHeu0Pw
- https://youtu.be/KvoMRRs3Jko
- https://youtu.be/gxeVxbT4Ctc
- https://youtu.be/iOsMx660JnA
- https://youtu.be/ZmugrBuT4Yc
- https://youtu.be/vjSZIyYd0NI
- https://youtu.be/QOAJYkuX_-Y
- https://www.youtube.com/live/pFO41hA9doQ
- https://youtu.be/ZtDMVgzUrHA
- https://www.youtube.com/watch?v=nwiL2LIYfUA
- https://www.youtube.com/watch?v=RatSJhbGOT0

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
