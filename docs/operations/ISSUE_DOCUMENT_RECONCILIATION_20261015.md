# CENTRAL — GitHub OPEN 이슈·PR 및 기준 문서 통합 인덱스 (2026-10-15)

**성격:** GitHub 공개 기술 운영·정리 스냅샷. 비공개 회사 사업방침/고객별 위임/인증 자료를 포함하지 않습니다. **이 인덱스는 개별 이슈의 현재 상태와 CI·운영 배포·사용자 수용을 대체하지 않습니다.** 새 세션에서는 먼저 [AGENTS.md](../../AGENTS.md), 이 [운영 인덱스](README.md), 관련 실제 이슈·PR·Run을 새로 확인합니다.

- 조사 기준 `main=983a4333c76db5adbf2c7d9c4d12d35b458138f8` (PR #4789 merge 직후). 본 인덱스의 OPEN 목록은 GitHub REST API 별도 재조회 시점의 스냅샷이며 작성 후 변경될 수 있습니다.
- OPEN 실제 Issue **87개**, OPEN PR **59개** (Draft **54개**, non-Draft **5개**). 서로 다른 객체로 계수했습니다. 최신값은 [이슈 검색](https://github.com/skerishKang/ai-revenue-lab/issues?q=is%3Aissue+is%3Aopen) / [PR 검색](https://github.com/skerishKang/ai-revenue-lab/pulls?q=is%3Apr+is%3Aopen)이 기준입니다.
- 일괄 CLOSE·일괄 병합·모델 정책 변경·Production 배포를 하지 않습니다. **MERGED source != deployed Worker != live owner E2E != audible device acceptance.**

## 1. 당장 개발 대상으로 이미 분리된 #4771 잔여분

| 담당 범위 | 이슈 | 기록된 실패 | 상태 |
|---|---|---:|---|
| SSE/5xx/stream/core, unknown slash-alias 응답 | [#4797](https://github.com/skerishKang/ai-revenue-lab/issues/4797) | 9 | OPEN; 실제 결함과 stale fixture 분류 필요 |
| 서버 검증 Free/Plus/Pro/Max 및 로컬 텍스트 등급 오판 | [#4799](https://github.com/skerishKang/ai-revenue-lab/issues/4799) | 8 | OPEN; 모델 정책 무단 변경 금지 |
| Chat/Claw UI·프로젝트 파일 대화상자·정적 계약 | [#4800](https://github.com/skerishKang/ai-revenue-lab/issues/4800) | 8 | OPEN; 최신 프레임과 Library 구현 우선 재사용 |

숫자는 **PR #4795 head `de51a6ff6`** 의 [B62 Full Regression Run 38688081751](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38688081751) 결과 **5,867 pass / 25 fail / 42 skip** 에서 기인합니다. 현재 `main`의 확정 실패 수가 아닙니다. 변경 부분만 재현하세요. 오래된 초기 50건 조사 [#4771](https://github.com/skerishKang/ai-revenue-lab/issues/4771)는 3개 이슈로 이관하고 CLOSED, 해결 코드/테스트 PR #4782/#4784/#4785/#4786/#4795는 병합 상태로 보존합니다.

## 2. 완료 범위 정리와 남은 수용 구분

- [#4774](https://github.com/skerishKang/ai-revenue-lab/issues/4774): Browser QA 구 선택자 수리 PR #4779 merge `d935644c`; CLOSED. 과거 일부 Browser QA 실패를 미해결로 재진입하지 않습니다.
- [#4775](https://github.com/skerishKang/ai-revenue-lab/issues/4775): 답변 TTS 첫 클릭·지연된 한국어 `voiceschanged`·취소 PR #4780 merge `2bc86840`; B62 Production [Run 38684193015](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38684193015) SUCCESS. **실제 사용자 스피커 출력을 검증하지 않았고**, 수용 항목을 기존 [#4649](https://github.com/skerishKang/ai-revenue-lab/issues/4649)로 명시 이관 후 #4775 CLOSED.
- [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139): Windows Resident EXE/installer PR #4789 merge `983a4333`; #4750 TXT 경로 Draft, #4751 PC 연결 웹 UI OPEN. 실제 연결·TXT 소유 범위·Claw 파일 readback을 별도로 검증해야 하므로 상위 OPEN 유지. [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099)가 Windows 장치/설치 수용.
- [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317): Drive read #4788 `19de54c1`, evidence link #4790 `a3f34813`, 대화창 유지 #4792 `dd486f35` 병합; 전체 Chat 사용자 E2E는 OPEN 유지.
- [#4469](https://github.com/skerishKang/ai-revenue-lab/issues/4469): 공통 public web search 실제 Chat/Claw/B66 근거 응답을 추적하는 단일 통합 Issue OPEN. 브라우저 private Drive read는 별개 권한·데이터 경계.
- [#4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488) 공통 디자인과 [#4489](https://github.com/skerishKang/ai-revenue-lab/issues/4489) Library end-to-end는 상위 수용 범위 유지; 상세 회귀 8건은 #4800 소유. 같은 UI 수정 PR을 두 벌 만들지 않습니다.
- 음성 입력 STT는 [#4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643), 실제 음성 출력 및 후속 연속 음성대화는 [#4649](https://github.com/skerishKang/ai-revenue-lab/issues/4649). 기능 구현/수용/유료 TTS 확장을 혼동하지 않습니다.

## 3. 통합 대상이 아닌 기존 정식 문서 — 단일 권위 유지

- 회사 비공개 사업·운영방침: COM1 `G:\\Ddrive\\BatangD\\task\\workdiary\\ai-revenue-lab-governance\\README.md`에서 **실열람**. 이 공개 문서로 복사·요약·이관하지 않습니다.
- 공개 실행 기준: [운영 README](README.md), [AI 개발 기준](AI_DEVELOPMENT_OPERATING_POLICY.md), [최소 충분 검증](TEST_SCOPE_AND_DELIVERY_POLICY.md), [현행 상태모델](WORKFLOW_STATUS_MODEL.md), [배포/롤백](DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md), [보고 분리](GITHUB_REPORT_HANDOFF_POLICY.md).
- 모델 단일 출처: [models/README.md](../models/README.md), 관련 Owner 결정·실제 registry/served proof를 구분합니다. 이 인덱스에서 모델을 새로 선택하지 않습니다.
- Connector installer 절차: [PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md](PADIEM_CONNECTOR_INSTALLER_DISTRIBUTION_20261015.md), 실제 Windows 수용은 #3099.
- 장기 보류·사업 기획/개별 제품별 장문 문서와 과거 이슈 댓글은 **기록**으로 보존합니다. 파일을 일괄 삭제하거나 백업을 현재 정책에 덮어쓰지 않습니다. 충돌하면 위 정식 정책/최신 대표 결정 우선이며 과거 이슈를 실행 명령으로 재활성화하지 않습니다.

## 4. 전체 OPEN Issue 스냅샷 — 담당 영역으로 묶어 보기

**그룹은 관리용 탐색 분류이며 owner 승인/실제 우선순위/수용 완료 판정이 아닙니다.** `FIX_NOW` 외 OPEN 이슈에는 별도 개발 권한이 자동 발생하지 않습니다.

### 현재 분리된 잔여 개발 (3)

| 이슈 | 제목 | 최종 갱신 (UTC) |
|---|---|---|
| [#4800](https://github.com/skerishKang/ai-revenue-lab/issues/4800) | [B62][#4771 후속] Chat·Claw UI·프로젝트 파일 회귀 8건 수정 | 2026-10-15 |
| [#4799](https://github.com/skerishKang/ai-revenue-lab/issues/4799) | [B62][#4771 후속] 서버 검증 회원등급·모델 신원 회귀 8건 수정 | 2026-10-15 |
| [#4797](https://github.com/skerishKang/ai-revenue-lab/issues/4797) | [B62][P1][#4771 후속] SSE·5xx·런타임 잔여 회귀 9건 수정 | 2026-10-15 |

### 제품별 기존 통합·실사용 수용 권위 (16)

| 이슈 | 제목 | 최종 갱신 (UTC) |
|---|---|---|
| [#4649](https://github.com/skerishKang/ai-revenue-lab/issues/4649) | [B62/B54/B66][VOICE][TTS][P1] 연속 음성 대화 출력 — 브라우저 무료 TTS 기본 + 선택형 외부 TTS API | 2026-10-15 |
| [#4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643) | [B62/B54][VOICE] Global Classroom STT 재사용 — Chat·Claw 공통 마이크 입력 | 2026-10-15 |
| [#4489](https://github.com/skerishKang/ai-revenue-lab/issues/4489) | [B62][LIBRARY][P1] '라이브러리' 비활성·잘못된 프로젝트 연결 해결 — 실제 파일/이미지 탐색 화면 | 2026-10-15 |
| [#4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488) | [B62/B54][UX][OPEN] Chat·Claw 동일 화면 구조 및 자동화 공통 디자인 | 2026-10-15 |
| [#4483](https://github.com/skerishKang/ai-revenue-lab/issues/4483) | [CENTRAL MODEL S3] Cross-product exact-model runtime enforcement and staged rollout | 2026-10-14 |
| [#4469](https://github.com/skerishKang/ai-revenue-lab/issues/4469) | [PADIEM][CORE WEB SEARCH][통합연결] Chat·Claw·B66 공통 검색 실행·근거 표시·운영 검증 | 2026-10-15 |
| [#4453](https://github.com/skerishKang/ai-revenue-lab/issues/4453) | [CENTRAL MODEL S1][CENTRAL CTO][#4428] 공통 제품·등급별 모델 정책 저장·감사·적용 게이트 | 2026-10-14 |
| [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) | [PADIEM][통합구현] PADIEM 브랜드 고객 홈·중앙 관리자 — 공통 계정·제품별 권한 격리 | 2026-10-14 |
| [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318) | [AI-PLATFORM][ENGINE/P01/B14/CP][통합검증] 공통 런타임 운영·승인·장시간 작업·모델 E2E | 2026-10-14 |
| [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317) | [B62][CHAT][통합검증] 파디엠 챗 운영 로그인·모델·대화·프로젝트·파일 E2E | 2026-10-15 |
| [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316) | [B66][통합 검증][운영 E2E] 구현 완료 기능의 검증 항목 단일 누적 관리 | 2026-10-14 |
| [#4139](https://github.com/skerishKang/ai-revenue-lab/issues/4139) | [PADIEM Connector][통합구현] 공통 계정·Broker·Windows Connector·Claw 첫 파일 실행 | 2026-10-15 |
| [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) | [B54][CLAW][통합검증] 실사용 대화·실행기록·P01 승인·Hark XLSX/PDF E2E | 2026-10-14 |
| [#3933](https://github.com/skerishKang/ai-revenue-lab/issues/3933) | [B54][CLAW][WEB-FIRST][통합구현] Hark형 대화·P01 실행·XLSX/PDF·후속 업무 연결 | 2026-10-15 |
| [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) | [B54][CLAW][통합검증][DESKTOP-ALPHA] Windows·실페어링·서명 설치·실행·회복 E2E | 2026-10-14 |
| [#2010](https://github.com/skerishKang/ai-revenue-lab/issues/2010) | [부분 운영 중][IP-ENGINE][E10] 공유 커넥터 READ — Drive/Gmail/Telegram 운영 · Slack/Calendar 활성화 대기 | 2026-10-11 |

### 상위/지속 운영·포트폴리오 (10)

| 이슈 | 제목 | 최종 갱신 (UTC) |
|---|---|---|
| [#3989](https://github.com/skerishKang/ai-revenue-lab/issues/3989) | [CI][P1] Reduce PR workflow fanout and eliminate indefinite Pending checks | 2026-10-14 |
| [#2996](https://github.com/skerishKang/ai-revenue-lab/issues/2996) | [OPEN-LONG-TERM][P1][TECH-ADOPTION] Technology inventory + OSS/commercial replacement radar | 2026-10-14 |
| [#2505](https://github.com/skerishKang/ai-revenue-lab/issues/2505) | [OPEN-STANDING][PRODUCT-AUTHORITY][B62] Padiem Chat current product authority — general AI front door + workspace shell | 2026-10-11 |
| [#1911](https://github.com/skerishKang/ai-revenue-lab/issues/1911) | [OPEN-STANDING][CONSTITUTION/GOVERNANCE][OPS] External-model session adoption rule — contract, clean tree, PR, exact-head evidence required | 2026-09-26 |
| [#1753](https://github.com/skerishKang/ai-revenue-lab/issues/1753) | [HOLD][LONG-TERM][IP-ENGINE][E9] Capability-by-capability Engine activation and product migration | 2026-10-14 |
| [#1743](https://github.com/skerishKang/ai-revenue-lab/issues/1743) | [OPEN-LONG-TERM][PLATFORM-PROGRAM][IP-ENGINE] Complete cross-product Core capability projection for all Padiem AI products | 2026-10-14 |
| [#1631](https://github.com/skerishKang/ai-revenue-lab/issues/1631) | [OPEN-LONG-TERM][ROADMAP][B54][Connectivity] Padiem Claw execution & connector expansion — Local Agent, cloud, storage, messaging, mail, SaaS | 2026-10-14 |
| [#1224](https://github.com/skerishKang/ai-revenue-lab/issues/1224) | [OPEN-STANDING][CONSTITUTION/GOVERNANCE][B62] Padiem Chat product boundary guard — UI/product only, no Core/Engine/B14 ownership drift | 2026-10-01 |
| [#366](https://github.com/skerishKang/ai-revenue-lab/issues/366) | [포트폴리오 감사] Portfolio Product Quality Audit: reclassify and upgrade all Businesses | 2026-10-14 |
| [#154](https://github.com/skerishKang/ai-revenue-lab/issues/154) | [영구상위이슈] Portfolio Product Evidence Queue: demo → MVP → pilot → commercialization | 2026-10-14 |

### 장기·미래·보류·승인 의존 (34)

| 이슈 | 제목 | 최종 갱신 (UTC) |
|---|---|---|
| [#4727](https://github.com/skerishKang/ai-revenue-lab/issues/4727) | [DEFERRED][B14/ENGINE][C안] AI 모델 네이티브 Tool Calling — A안 자동 웹검색 완료 후 확장 | 2026-10-14 |
| [#4654](https://github.com/skerishKang/ai-revenue-lab/issues/4654) | [PADIEM][CORE/P01][FUTURE][DESIGN-HOLD] 전 제품 공통 AI 성격·사용자 동의 기반 공유 기억 설계 | 2026-10-13 |
| [#4651](https://github.com/skerishKang/ai-revenue-lab/issues/4651) | [FUTURE][IDEA][B62/B54/B66] Chat↔Claw 작업 위임·대화/툴유즈 분류 + 선택형 Jev 검토 | 2026-10-13 |
| [#4647](https://github.com/skerishKang/ai-revenue-lab/issues/4647) | [B54][CLAW][IDEA][FUTURE] 통화·회의 파일 전사 원문/요약 보기 → 약속·할 일 후보를 캘린더로 연결 | 2026-10-13 |
| [#4633](https://github.com/skerishKang/ai-revenue-lab/issues/4633) | [BACKLOG][PADIEM Connector][MCP] ChatGPT·KILO용 Windows PC 도구 Gateway (기존 Identity/Broker 재사용) | 2026-10-14 |
| [#3367](https://github.com/skerishKang/ai-revenue-lab/issues/3367) | [B69][MASTER][HOLD] Padiem Company OS — 단일 장기 백로그 (추후 개발 시 이슈 분할) | 2026-10-11 |
| [#3342](https://github.com/skerishKang/ai-revenue-lab/issues/3342) | [B68][VISION][MARKET] Saudi-first AI Color Lens Discovery + Virtual Try-On platform | 2026-10-01 |
| [#3235](https://github.com/skerishKang/ai-revenue-lab/issues/3235) | [HOLD][CLAW][WEB-P0][SKILLS] Project registered Skill catalogue into Web Claw | 2026-09-29 |
| [#3063](https://github.com/skerishKang/ai-revenue-lab/issues/3063) | [DEFERRED][HOLD] AI Tryout Points — future product decision; no active work | 2026-09-25 |
| [#2833](https://github.com/skerishKang/ai-revenue-lab/issues/2833) | [HOLD][PROD-GATE][B54][AUTOMATION] Durable Claw cron/scheduler — source complete; live activation deferred | 2026-10-11 |
| [#2826](https://github.com/skerishKang/ai-revenue-lab/issues/2826) | [HOLD][BACKLOG][B54][HWP] Legacy HWP ingestion/conversion — deferred behind Web/Desktop P0 | 2026-10-14 |
| [#2504](https://github.com/skerishKang/ai-revenue-lab/issues/2504) | [HOLD][FUTURE-BUSINESS] Padiem Code — standalone Korean AI coding agent; implementation not authorized | 2026-10-01 |
| [#2409](https://github.com/skerishKang/ai-revenue-lab/issues/2409) | [HOLD][ARCH][POST-P0] Promote B62-shared runtime responsibilities into Padiem AI Platform boundaries | 2026-10-01 |
| [#2394](https://github.com/skerishKang/ai-revenue-lab/issues/2394) | [DEFERRED][B62][P1 Security/Ops] Split R2 metadata read credential from local-ops write credential | 2026-10-01 |
| [#2223](https://github.com/skerishKang/ai-revenue-lab/issues/2223) | [B03][MASTER] Living Fiction — Modal·Neon 운영 수용 대기 / Cloudflare 이전 HOLD | 2026-10-11 |
| [#2208](https://github.com/skerishKang/ai-revenue-lab/issues/2208) | [DEFERRED_HOLD][B53][Packaging] Private browser package + deterministic bundle skeleton | 2026-09-25 |
| [#2204](https://github.com/skerishKang/ai-revenue-lab/issues/2204) | [DEFERRED_HOLD][B53][SIDECAR] Server-mediated EnginePort adapter source slice | 2026-10-11 |
| [#2107](https://github.com/skerishKang/ai-revenue-lab/issues/2107) | [B14][MASTER][HOLD] 모델·공급업체 관리자 센터 + BYOK·Auto Router·Max 장기 백로그 | 2026-10-13 |
| [#2092](https://github.com/skerishKang/ai-revenue-lab/issues/2092) | [OWNER-DECISION-GATE][HOLD][B61][Ops] StoryMemory canonical Production URL and Cloudflare Pages target cleanup v1 | 2026-10-11 |
| [#2002](https://github.com/skerishKang/ai-revenue-lab/issues/2002) | [오너 결정 대기][IP-ENGINE][A4] Memory/RAG 저장소 방식 선택 여부 — 프로비저닝 미승인 (#1967) | 2026-10-08 |
| [#1971](https://github.com/skerishKang/ai-revenue-lab/issues/1971) | [Production 검증 대기][IP-ENGINE][A6] 이미지 실행·스트리밍 — 바인딩·실사용 검증 후 활성화 | 2026-10-11 |
| [#1967](https://github.com/skerishKang/ai-revenue-lab/issues/1967) | [결정 대기][IP-ENGINE][A4] Memory/RAG 활성화 — 저장소 방식 결정 후 재검토 (#2002) | 2026-10-08 |
| [#1878](https://github.com/skerishKang/ai-revenue-lab/issues/1878) | [HOLD][B54][Commercial] Padiem Claw pricing, deployment package, Engine usage and first-customer offer design | 2026-10-01 |
| [#1821](https://github.com/skerishKang/ai-revenue-lab/issues/1821) | [B61][MASTER][HOLD] StoryMemory — 제품 개발·UI·UX 단일 백로그 (#2092 운영 게이트 별도) | 2026-10-11 |
| [#1741](https://github.com/skerishKang/ai-revenue-lab/issues/1741) | [OPEN-FUTURE-GATE][Padiem Control Plane][Auth] Real contact-verification delivery adapter — Kakao/SMS | 2026-10-01 |
| [#1405](https://github.com/skerishKang/ai-revenue-lab/issues/1405) | [HOLD][P1][B54][Cloud Sandbox] Managed/BYOC sandbox provider selection — optional after Web/Desktop MVP | 2026-10-01 |
| [#1355](https://github.com/skerishKang/ai-revenue-lab/issues/1355) | [OPEN-LONG-TERM][RESEARCH/STRATEGY][Core/B62] Search provider portfolio + multi-provider routing strategy | 2026-10-07 |
| [#987](https://github.com/skerishKang/ai-revenue-lab/issues/987) | [B64][통합][HOLD] AI Reward Router — 제품·ayeT/Adscend 광고·Tremendous 지급 실증 | 2026-10-11 |
| [#772](https://github.com/skerishKang/ai-revenue-lab/issues/772) | [BIO][MASTER][HOLD] 바이오·헬스케어 연구·사업 후보 단일 백로그 (BIO-003/016/022) | 2026-10-11 |
| [#735](https://github.com/skerishKang/ai-revenue-lab/issues/735) | [B63][추후작업] Customer discovery gate — hospitals / HIS vendors | 2026-10-01 |
| [#731](https://github.com/skerishKang/ai-revenue-lab/issues/731) | [HOLD][B63 Proposal] Korean Clinical AI Egress Control Plane — validation master | 2026-10-01 |
| [#637](https://github.com/skerishKang/ai-revenue-lab/issues/637) | [HOLD][B01][V7][통합] 핵심 화면 교정 → 전체 화면 확장·오너 리뷰 | 2026-10-11 |
| [#389](https://github.com/skerishKang/ai-revenue-lab/issues/389) | [B59][MASTER][HOLD] Living Archive / 나의 기록서재 — 제품·확장 런타임 단일 백로그 | 2026-10-11 |
| [#348](https://github.com/skerishKang/ai-revenue-lab/issues/348) | [B29][통합 로드맵][추후] 우리단지 운영 원장 — 유료 파일럿·Phase 3 백엔드 | 2026-10-11 |

### 그 밖의 현재 OPEN — 범위 유지 및 개별 증거 확인 (24)

| 이슈 | 제목 | 최종 갱신 (UTC) |
|---|---|---|
| [#4745](https://github.com/skerishKang/ai-revenue-lab/issues/4745) | [B54/B62][PADIEM CALENDAR][NEXT] Chat·Claw AI 자연어 일정 등록·조회 공통 도구 | 2026-10-14 |
| [#4724](https://github.com/skerishKang/ai-revenue-lab/issues/4724) | [B66][PDF][LICENSE] Verify public GitHub AGPL compliance first; replacement conditional | 2026-10-14 |
| [#4721](https://github.com/skerishKang/ai-revenue-lab/issues/4721) | [B66][SOL61][TEST-ONLY][SECURITY] Update pypdf 6.18.0 test pin without renderer or runtime changes | 2026-10-14 |
| [#4702](https://github.com/skerishKang/ai-revenue-lab/issues/4702) | [Phone][INTEGRATION] Authenticated Claw tool and outbound SIP/voice E2E | 2026-10-14 |
| [#4549](https://github.com/skerishKang/ai-revenue-lab/issues/4549) | [INCIDENT][B62][P01][P1] 040 스키마 선행 누락 배포 가능 장애 창·사용자 영향·게이트 재발방지 감사 | 2026-10-13 |
| [#4434](https://github.com/skerishKang/ai-revenue-lab/issues/4434) | [PADIEM Connector][#4139][구현] 웹 XLSX → PC 자동 Pull·로컬 처리 → 웹 결과 E2E | 2026-10-12 |
| [#4389](https://github.com/skerishKang/ai-revenue-lab/issues/4389) | [B66][OPS] Connect existing Oracle Hermes Telegram, Discord and email alerts | 2026-10-11 |
| [#4089](https://github.com/skerishKang/ai-revenue-lab/issues/4089) | [P1][B66][GOOGLE DRIVE] B66 로그인과 별도 Google 저장 계정 · 재로그인 후 연결 유지 | 2026-10-11 |
| [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782) | [P1][CLAW][BROWSER][#3775][다음 개발] Broker 작업별 P01 승인·액션 전달 → Desktop 실행 | 2026-10-12 |
| [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595) | [P0][B66][REPRODUCTION-CERTIFICATION] Canonical Template -> reference-equivalent PDF gate before execution | 2026-10-11 |
| [#3580](https://github.com/skerishKang/ai-revenue-lab/issues/3580) | [CLAW][FILES][MULTICHANNEL][남은 구현] Drive WRITE·Telegram SEND·선택형 Desktop 파일 전달 | 2026-10-14 |
| [#3404](https://github.com/skerishKang/ai-revenue-lab/issues/3404) | [P1][B66][VOICE] Dual-mode voice input — review-to-send + live turns with isolated STT lane | 2026-10-13 |
| [#3330](https://github.com/skerishKang/ai-revenue-lab/issues/3330) | [ARCH][P0][FILES+EXECUTION] Drive-authoritative workspace + ephemeral Execution Broker | 2026-10-14 |
| [#3298](https://github.com/skerishKang/ai-revenue-lab/issues/3298) | [IP-ENGINE][E9][A7][ACTIVATION-PREFLIGHT] Prove E7 Control Plane admission composition and Production readiness | 2026-10-14 |
| [#3186](https://github.com/skerishKang/ai-revenue-lab/issues/3186) | [P1][B66][NEW QUOTE SKILL] 견적서 관리 -> 새 견적서 만들기 (자동 / 직접 / 맡기기) | 2026-10-11 |
| [#3180](https://github.com/skerishKang/ai-revenue-lab/issues/3180) | [B66][Epic] Learn an existing business quotation into a reusable Saved Quote Skill | 2026-10-11 |
| [#3100](https://github.com/skerishKang/ai-revenue-lab/issues/3100) | [CLAW][BETA-GATE] Closed beta readiness — useful SME workflows, reliability and operations | 2026-10-11 |
| [#2952](https://github.com/skerishKang/ai-revenue-lab/issues/2952) | [BLOCKED][OWNER+PROD-GATE][E10][Calendar][PROD-READ] Google Calendar READ activation and one-shot live acceptance | 2026-10-09 |
| [#2951](https://github.com/skerishKang/ai-revenue-lab/issues/2951) | [BLOCKED][PROD-GATE][E10][Slack][PROD-READ] Shared Slack READ activation preflight and bounded live acceptance | 2026-10-01 |
| [#2824](https://github.com/skerishKang/ai-revenue-lab/issues/2824) | [P0][FILES][SECURITY] Generic file intake safety gate — browser-first + zero-cost fallbacks | 2026-10-01 |
| [#1966](https://github.com/skerishKang/ai-revenue-lab/issues/1966) | [활성화 검증 대기][IP-ENGINE][APPROVAL] 승인 후 실행 재개 — Production 실증 및 매니페스트 확인 | 2026-10-11 |
| [#1722](https://github.com/skerishKang/ai-revenue-lab/issues/1722) | [B53] Padiem Sidecar — embedded AI workspace product consolidation and commercialization | 2026-10-11 |
| [#616](https://github.com/skerishKang/ai-revenue-lab/issues/616) | World Feed — Phase 2 concierge MVP validation: Finite Cultural Discovery → Local Action | 2026-10-01 |
| [#369](https://github.com/skerishKang/ai-revenue-lab/issues/369) | Business 35 Product Upgrade v3: interactive AI media transformation studio | 2026-10-01 |

## 5. 전체 OPEN PR 스냅샷 (59)

| PR | 상태 | 제목 | 마지막 변경 |
|---|---|---|---|
| [#4751](https://github.com/skerishKang/ai-revenue-lab/pull/4751) | OPEN | feat(claw): dedicated PC connection page in site card language (#4139) | 2026-10-14 |
| [#4750](https://github.com/skerishKang/ai-revenue-lab/pull/4750) | DRAFT | [DRAFT][#4139][LOCAL1] Actual TXT approval-material supply path for admitted reads | 2026-10-15 |
| [#4715](https://github.com/skerishKang/ai-revenue-lab/pull/4715) | DRAFT | feat(voice): browser TTS output primitive (no product auto-play wiring) | 2026-10-14 |
| [#4714](https://github.com/skerishKang/ai-revenue-lab/pull/4714) | DRAFT | feat(voice): isolated Mode2 turn coordinator (default manual, no runtime wiring) | 2026-10-14 |
| [#4712](https://github.com/skerishKang/ai-revenue-lab/pull/4712) | DRAFT | [DRAFT][CORE][#2996] Lock pypdf on the 6.19.x line that patches CVE-2026-102998/102999/103000 | 2026-10-14 |
| [#4705](https://github.com/skerishKang/ai-revenue-lab/pull/4705) | DRAFT | [DRAFT][#4139] Broker verified TXT result producer (LOCAL1 → CENTRAL) | 2026-10-14 |
| [#4704](https://github.com/skerishKang/ai-revenue-lab/pull/4704) | DRAFT | [DRAFT][#4139][LOCAL1] Broker verified Windows TXT result + production Request Port factory | 2026-10-14 |
| [#4698](https://github.com/skerishKang/ai-revenue-lab/pull/4698) | DRAFT | feat(voice): live wiring for shared Chat/Claw microphone (default-off) (#4643) | 2026-10-14 |
| [#4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572) | DRAFT | [DRAFT][#4139][CENTRAL] Broker recovery + Windows S2 integration and guarded autostart | 2026-10-14 |
| [#4490](https://github.com/skerishKang/ai-revenue-lab/pull/4490) | DRAFT | [DRAFT][#4139][LOCAL2] Windows Connector integration — enrollment HTTP transport + protected install gate | 2026-10-14 |
| [#4477](https://github.com/skerishKang/ai-revenue-lab/pull/4477) | DRAFT | docs(core): common AI pre-instruction dispatch contract — source census & trust gates (#4465) | 2026-10-12 |
| [#4476](https://github.com/skerishKang/ai-revenue-lab/pull/4476) | DRAFT | [DRAFT][#4139][CENTRAL] Connector enrollment server S1 composition and guarded HTTP handlers | 2026-10-13 |
| [#4470](https://github.com/skerishKang/ai-revenue-lab/pull/4470) | DRAFT | docs(b66): AI natural conversation, quote intent, KST context and Core web search plan (HOLD) | 2026-10-12 |
| [#4463](https://github.com/skerishKang/ai-revenue-lab/pull/4463) | DRAFT | [DRAFT][#4139][LOCAL2] PADIEM Connector S2 — reviewed login, canonical device enrollment, real Resident (on PR #4420 base) | 2026-10-13 |
| [#4438](https://github.com/skerishKang/ai-revenue-lab/pull/4438) | DRAFT | feat(control-plane): enroll a PADIEM Connector PC from the canonical account session (#4139) | 2026-10-13 |
| [#4361](https://github.com/skerishKang/ai-revenue-lab/pull/4361) | DRAFT | fix(b14): retire TokenHarbor Haiku; keep DeepSeek as sole candidate | 2026-10-11 |
| [#4022](https://github.com/skerishKang/ai-revenue-lab/pull/4022) | OPEN | fix(web): localize Hangul TinyFish Search and safely diagnose zero evidence (#3523) | 2026-10-09 |
| [#3863](https://github.com/skerishKang/ai-revenue-lab/pull/3863) | DRAFT | docs(ops): 요청 범위에 집중하는 보고 규칙 정비 | 2026-10-09 |
| [#3855](https://github.com/skerishKang/ai-revenue-lab/pull/3855) | DRAFT | [DRAFT][B66 #3839] Deterministic multi-A4 page planning (source-only gate) | 2026-10-09 |
| [#3835](https://github.com/skerishKang/ai-revenue-lab/pull/3835) | DRAFT | [DRAFT][B14] StepFun Step 5 등록 및 견적서 10건 검증 — 무료 경로 429 보류 | 2026-10-12 |
| [#3830](https://github.com/skerishKang/ai-revenue-lab/pull/3830) | DRAFT | [DRAFT][B14] StepFun Step 5 평가 1순위 및 예비 성능 검증 기록 | 2026-10-12 |
| [#3783](https://github.com/skerishKang/ai-revenue-lab/pull/3783) | DRAFT | [P1][CLAW][#3782] Validate broker/P01 browser-control work ticket correlation (source-only) | 2026-10-09 |
| [#3763](https://github.com/skerishKang/ai-revenue-lab/pull/3763) | OPEN | [P1][B66][VOICE] Add dual-mode Gemini voice input to the quote composer (#3404) | 2026-10-13 |
| [#3715](https://github.com/skerishKang/ai-revenue-lab/pull/3715) | OPEN | test(b66): capture customer handoff screenshots | 2026-10-07 |
| [#3597](https://github.com/skerishKang/ai-revenue-lab/pull/3597) | DRAFT | fix(b14): per-model max_tokens budget, exlab→GLM route, truthful kilo has_key | 2026-10-09 |
| [#3549](https://github.com/skerishKang/ai-revenue-lab/pull/3549) | DRAFT | [P0][B66][#3391] Reserve output budget for quote extraction | 2026-10-05 |
| [#3544](https://github.com/skerishKang/ai-revenue-lab/pull/3544) | DRAFT | [B66][#3542][DOCS] Make source analysis the gate before Skill/Template compilation | 2026-10-05 |
| [#3522](https://github.com/skerishKang/ai-revenue-lab/pull/3522) | DRAFT | [P0][B66] Fix CGI partial quote interpretation boundary and pin guided finalize acceptance | 2026-10-05 |
| [#3469](https://github.com/skerishKang/ai-revenue-lab/pull/3469) | DRAFT | [P0][CLAW][#3436] Add read-only result artifact presentation to the run surface | 2026-10-05 |
| [#3455](https://github.com/skerishKang/ai-revenue-lab/pull/3455) | DRAFT | docs: test execution economy policy (§11A) + formatting cleanup | 2026-10-04 |
| [#3386](https://github.com/skerishKang/ai-revenue-lab/pull/3386) | DRAFT | feat(core): add TinyFish Search/Fetch web provider (#3385) | 2026-10-09 |
| [#3343](https://github.com/skerishKang/ai-revenue-lab/pull/3343) | OPEN | docs(B68): establish Saudi-first AI color lens business track | 2026-10-01 |
| [#3290](https://github.com/skerishKang/ai-revenue-lab/pull/3290) | DRAFT | [B54][#3283] Add owner-gated Vercel parser runtime probe executor | 2026-10-01 |
| [#3066](https://github.com/skerishKang/ai-revenue-lab/pull/3066) | DRAFT | [HOLD][DEFERRED] AI Tryout Points foundation — preserve only, no active work | 2026-10-09 |
| [#2122](https://github.com/skerishKang/ai-revenue-lab/pull/2122) | DRAFT | feat(core): shared credential binding-name grammar contract (#2103 ACT-1) | 2026-10-09 |
| [#988](https://github.com/skerishKang/ai-revenue-lab/pull/988) | DRAFT | chore: reconcile AI Reward Router as B64 | 2026-10-09 |
| [#986](https://github.com/skerishKang/ai-revenue-lab/pull/986) | DRAFT | feat(padiem-lab): publish B42 public card | 2026-10-09 |
| [#792](https://github.com/skerishKang/ai-revenue-lab/pull/792) | DRAFT | [BIO-022] Add synthetic health-model egress privacy benchmark | 2026-10-09 |
| [#783](https://github.com/skerishKang/ai-revenue-lab/pull/783) | DRAFT | [BIO-016] Add synthetic medical-AI change revalidation benchmark | 2026-10-09 |
| [#774](https://github.com/skerishKang/ai-revenue-lab/pull/774) | DRAFT | [BIO-003] Add synthetic My Health Story validation pack | 2026-10-09 |
| [#767](https://github.com/skerishKang/ai-revenue-lab/pull/767) | DRAFT | [Portfolio] Preserve idea ledger and Bio/Healthcare candidate queue | 2026-10-09 |
| [#635](https://github.com/skerishKang/ai-revenue-lab/pull/635) | DRAFT | design(B01): prove V7 Library Write Read archetype system | 2026-10-09 |
| [#431](https://github.com/skerishKang/ai-revenue-lab/pull/431) | DRAFT | feat(personal-writing-voice): add voice-profile review UX | 2026-10-09 |
| [#430](https://github.com/skerishKang/ai-revenue-lab/pull/430) | DRAFT | feat(classic-literature-translation): add fidelity-review UX | 2026-10-09 |
| [#429](https://github.com/skerishKang/ai-revenue-lab/pull/429) | DRAFT | feat(local-ai-fleet): add governed fleet-operations UX | 2026-10-09 |
| [#428](https://github.com/skerishKang/ai-revenue-lab/pull/428) | DRAFT | feat(embedded-ai-sdk): add integration-spec UX | 2026-10-09 |
| [#427](https://github.com/skerishKang/ai-revenue-lab/pull/427) | DRAFT | feat(scheduled-agent-operations): add human-governed run UX | 2026-10-09 |
| [#426](https://github.com/skerishKang/ai-revenue-lab/pull/426) | DRAFT | feat(ai-workflow-marketplace): add install-review UX | 2026-10-09 |
| [#425](https://github.com/skerishKang/ai-revenue-lab/pull/425) | DRAFT | feat(public-data-connector-hub): add mapping-validation UX | 2026-10-09 |
| [#424](https://github.com/skerishKang/ai-revenue-lab/pull/424) | DRAFT | feat(ai-verification-engine): add evidence-verification UX | 2026-10-09 |
| [#423](https://github.com/skerishKang/ai-revenue-lab/pull/423) | DRAFT | feat(real-time-feedback-engine): add inspect-and-apply UX | 2026-10-09 |
| [#422](https://github.com/skerishKang/ai-revenue-lab/pull/422) | DRAFT | feat(ai-personalization-engine): add explainable-personalization UX | 2026-10-09 |
| [#421](https://github.com/skerishKang/ai-revenue-lab/pull/421) | DRAFT | feat(ai-content-engine): add source-to-review UX | 2026-10-09 |
| [#420](https://github.com/skerishKang/ai-revenue-lab/pull/420) | DRAFT | feat(ai-software-factory): add request-to-review UX | 2026-10-09 |
| [#419](https://github.com/skerishKang/ai-revenue-lab/pull/419) | DRAFT | feat(ai-development-control-tower): add evidence-review UX | 2026-10-09 |
| [#418](https://github.com/skerishKang/ai-revenue-lab/pull/418) | DRAFT | feat(foreign-emergency-assistant): add confirmed-handoff UX | 2026-10-09 |
| [#417](https://github.com/skerishKang/ai-revenue-lab/pull/417) | DRAFT | feat(emergency-urgency-ai): add human-triage UX | 2026-10-09 |
| [#415](https://github.com/skerishKang/ai-revenue-lab/pull/415) | DRAFT | feat(ai-exercise-coach): add adaptive-session UX | 2026-10-09 |
| [#412](https://github.com/skerishKang/ai-revenue-lab/pull/412) | DRAFT | feat(ai-dubbing-studio): add rights-first dubbing UX | 2026-10-09 |

**정리 규칙:** OPEN PR은 병합됐다고 볼 수 없고 Draft는 특히 검토 중인 소스입니다. 서로 다른 PR이 동일 기능을 설명하면 head SHA·파일 diff·base와 이미 main에 들어간 변경을 비교한 뒤 supersede 처리합니다. 이 장부 생성만으로 자동 merge/close하지 않습니다.

## 6. 다음 관리 주기

1. GitHub 최신 OPEN Issue/PR를 다시 조회하고 **신규/변경된 항목만** 이 인덱스와 비교합니다.
2. 기능별 상위 이슈/실제 재현된 하위 개발이슈만 OPEN 유지; 완료된 하위 이슈는 해결 PR/배포/기기 수용 경계를 명시하고 CLOSE하거나 기존 상위로 수용 이관합니다.
3. CI fail 수는 **어느 SHA/어느 Run**인지 같이 기록합니다. 모델·권한/보안 정책을 오래된 테스트 기대값 때문에 회귀시키지 않습니다.
4. 운영 문서와 이슈는 **링크 기준 단일 원본 + 이력 보존** 방식으로 정리합니다. 전체 문서의 물리적 일괄 병합이나 삭제는 하지 않습니다.
