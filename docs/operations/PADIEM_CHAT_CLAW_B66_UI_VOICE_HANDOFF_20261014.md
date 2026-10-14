<!-- CENTRAL_UI_VOICE_LIVE_STATUS_20261014_START -->
## 현재 진행 상태 및 소유권 갱신 — 2026-10-14 KST

> 아래 'Phase A를 아직 구현하지 않음/LOCAL2가 우선 UI를 편집 중'이라는 문구는 **그 당시의 이력**이다. 더 이상 병합된 UI 전체를 재구현하거나 다른 팀의 UI 작업을 막는 현재 지시가 아니다.

- **Claw UI 구조:** [#4650](https://github.com/skerishKang/ai-revenue-lab/pull/4650)과 [#4653](https://github.com/skerishKang/ai-revenue-lab/pull/4653) **병합 완료**. [#4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488)에서 production Worker/정적 제공 검증 기록됨. 기존 구조 UI 소유권 해제 → 별도 팀은 **최신 main**에서 UI 수정 가능. 남은 것은 승인 대기·승인된 메모리·재로그인 등 **실제 데이터가 필요한 운영 수용 검증**이다.
- **음성:** 공통 STT 서버 소스 [#4663](https://github.com/skerishKang/ai-revenue-lab/pull/4663) **병합**, 하지만 STT 기능 기본 OFF·CP voice 권한 발급/실제 binding/제품 마이크 실사용 **미완료**. [#4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643)이 유일한 Chat·Claw STT 추적 이슈; B66 [#3404](https://github.com/skerishKang/ai-revenue-lab/issues/3404)는 별도 입력 UI 소관.
- **B66:** [#4661](https://github.com/skerishKang/ai-revenue-lab/pull/4661)은 제품 구분 저장+안전 Markdown **병합**; [#4672](https://github.com/skerishKang/ai-revenue-lab/pull/4672)는 고객 화면 실제 연결 및 재시도 **Draft**. LOCAL2가 유일한 `easy-mode.js`/B66 고객 화면 소유자이므로 다른 로컬은 같은 파일을 동시 수정하지 않는다. 새 HEAD `b7b80b43`에 보완 소스와 신규 동시성 테스트가 반영됐으나 CI/교차 isolate 비용 보호는 별도 판정. 고객 운영 출시 수락은 [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316).
- **병렬 지침:** CLAW2는 Claw UI 데이터 상태/키보드 테스트(별도 테스트 파일), LOCAL3는 CP STT 권한 계약(제품 `app.js` 불변), LOCAL1은 Claw SSE 오프라인 하네스(실 모델 POST 금지), LOCAL4는 B66 QuoteCore/SQLite 소스 검증(`easy-mode.js` 불변), LOCAL5는 B14 모델 정책 최종 호출 경로 분석. LOCAL6의 Windows Connector 브랜치 [#4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572)와 파일 영역 충돌 금지.
- **정확한 기술 상태**는 [개발 스냅샷 상단의 최신 정정](PADIEM_CENTRAL_CTO_DEVELOPMENT_SNAPSHOT_20261014.md) 및 각 이슈를 우선한다. 이 문서의 과거 옵션 A/A/A 및 'LOCAL2 먼저'는 당시 수행 순서 기록이다.

<!-- CENTRAL_UI_VOICE_LIVE_STATUS_20261014_END -->

# PADIEM Chat·Claw·B66 — UI 통일 및 음성 인식 개발 인수인계 (2026-10-14 KST)

> **성격:** 공개 가능한 기술 작업 조율 문서. 새로운 사업방침·모델 승인·운영 배포 허가가 아니다.
> **기준:** 대표의 2026-10-14 대화상 지시와 GitHub 현재 소스/이슈. LOCAL2의 Windows 화면 계측은 **LOCAL2 보고**로 표기하며 CENTRAL 독립 실측으로 간주하지 않는다.
> **최신 진행·소유권:** [UI #4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488) · [Chat/Claw Voice #4643](https://github.com/skerishKang/ai-revenue-lab/issues/4643) · [B66 Voice #3404](https://github.com/skerishKang/ai-revenue-lab/issues/3404). 상태가 바뀌면 이슈/PR의 현재 증거를 우선한다.

## 1. 확정된 대표 요구

1. **Claw는 Chat과 동일한 기본 대화 UI**로 만든다. 색상·Glass 효과만 비슷하게 하는 것으로 완료 처리하지 않는다. Chat/Claw는 제품 표시는 구별하되 공통 사이드바·상단바·본문·메시지·입력창·반응형 계약을 재사용한다.
2. Chat/Claw/B66 모두 **마이크를 눌러 말하고, 확인 가능한 전사를 기존 제품 입력 경로에 전달**할 수 있어야 한다. 우선 실사용 가능한 음성 입력부터 완성하고, 연속 핸즈프리 발화 자동 전송은 별도 기능 단계로 검증한다.
3. `skerishKang/global-classroom`의 STT 발화/전사 경계를 재사용하고 **기존 Gemini·Groq 공급자 설정/폴백 역할**을 존중한다. 기존 Cloudflare Secrets Store에 키가 있다는 사실은 **대표 확인사항**이며, 특정 Worker/Pages에 키 바인딩과 호출권한이 있는지는 별도 운영 사실로 검증해야 한다.
4. 제품의 **기존 모델 선택·B14 라우팅·P01 실행 승인·QuoteCore 계산·계정 권한·B66 인증 PDF**를 음성/UI 작업을 이유로 변경하지 않는다. Secret 값을 열람/출력/복사하거나 클라이언트에 전달하지 않는다.

## 2. Claw UI — 이슈 #4488

### 구현된 범위와 미완료 구분

- **코드 병합 확인:** #4520 Claw Glass/에이전트 배지, #4533 자동화 Glass, #4551 터치 영역 개선. 기존 구현을 재개발하지 않는다.
- **LOCAL2 읽기 전용 조사:** main `12276cea`, 별도 `wt-4488` / `local2/4488-chat-shell-parity-261014`; 소스·화면 진단 보고서 `scratch-4488/LOCAL2_4488_PHASE_A_RECON_REPORT.md` (LOCAL2 작업공간의 로컬 경로이며 GitHub 문서 존재를 뜻하지 않음). 이 조사 단계에서는 코드 수정/PR/배포 0건이라고 보고됨.
- **LOCAL2 보고의 원인:** 사이드바/상단바는 Chat과 이미 공유하지만 `claw-focus-layout.css`의 Claw 전용 `1000px` 중앙 본문/ `920px` 컴포저 제약이 Chat의 폭 계산을 덮는다. Claw 시작화면 task hub·승인 메모리·최근 실행 이력이 세로로 쌓여 대화보다 먼저 보인다(LOCAL2 보고: 실행 이력 약 1615px).
- **별도 상태:** Phase A의 구조 수정·수정 전후 스크린샷·최신 main 대응 Draft PR·실제 운영 수용은 **아직 이 문서에서 완료로 증명되지 않음**. 로컬 보고서의 계측치를 Production 진실로 확대하지 않는다.

### CTO가 확정한 옵션 (A/A/A)

- **Q1=A:** Chat의 실제 반응형 본문/입력창 폭·여백을 재사용하되 **Claw는 중앙 정렬**. Chat 초상화용 좌측 정렬/우측 빈자리까지 복제하지 않는다. 임의의 `1200px` 고정 폭이 유일한 규칙이 되어서는 안 된다.
- **Q2=A:** HTML/JS/CSS의 **점진적 노출**로 초기 대화 입력·실제 답변을 우선한다. 업무 예시는 보조로, 승인 메모리/실행 이력은 접근 가능하고 펼칠 수 있는 보조 영역으로 이동한다. **진행 중인 실행/승인 대기/오류/결과는 관련 맥락에서 명확하게 표시**하며 은폐하지 않는다. 데이터 삭제 금지.
- **Q3=A:** LOCAL2가 **실제 구현 → 1440/1920/820/390px 브라우저 검증(확대율 100%) → 집중 테스트 → Draft PR**까지 진행한다. LOCAL 자체 병합/운영 배포 없음. CENTRAL이 최신 PR head 및 필수 CI·권한/기능 보존을 검토하고 병합/배포 판단한다.
- **Phase B:** 자동화·캘린더·라이브러리·Connectors는 Chat 공통 시각 계약만 따르고 각 화면의 기능 의미를 유지한다. 자동화에 가짜 Chat 입력창을 추가하지 않는다. 이미 완료된 국소 수정/이슈를 중복 생성하지 않는다. 라이브러리 저장 기능은 별도 [#4489](https://github.com/skerishKang/ai-revenue-lab/issues/4489).

## 3. 공통 STT — Chat/Claw #4643 · B66 #3404

### 재사용 원본

- [Global Classroom 저장소](https://github.com/skerishKang/global-classroom) — `hooks/useInterviewLive.ts`, `utils/liveTranscriptTurn.ts`, `netlify/functions/transcribe.mts`, `tests/e2e/interview.spec.ts`.
- 기존 구현 구조: **Gemini Live 전사 → 지원 브라우저 SpeechRecognition → 서버측 Groq Whisper** 대체. `utterance_id`, interim/final 분리, 마이크 에코 억제·잡음 억제, 발화별 독립 컨텍스트, 중복 확정 방지가 핵심.
- [원본의 미완료 장문 STT #87](https://github.com/skerishKang/global-classroom/issues/87): 20–40초 발화·평범한 중간 휴지·브라우저/Whisper 대체 시 문장 잘림 위험. 이 결함과 특정 모델의 실제 가용성을 확인하지 않고 단순 복사해 완료 처리하지 않는다.
- 글로벌클래스룸은 React/Netlify, 목표 제품은 브라우저 JS/Cloudflare Worker·Pages. **소스 계약을 이식**하되 글로벌클래스룸의 Netlify 함수/React 훅에 런타임 의존하지 않는다.

### 제품별 사용자 경로

| 제품 | 현재 소스 확인(2026-10-14) | 1차 개발 목표 | 후속 단계 |
| --- | --- | --- | --- |
| Chat (B62) | 공통 `#composerForm/#messageInput`에 마이크 입력 연결 없음 | 아이콘 → 음성 임시/확정 전사 → 수정 가능한 기존 입력창 → 사용자가 전송 | 명시적 연속 음성 대화 |
| Claw (B54) | Chat과 공통 컴포저 사용. Phase A UI 개편 진행 중 | 동일 마이크 UX, 기존 Claw 메시지/실행·P01 승인 경로 보존 | 명시적 연속 음성 대화 |
| B66 견적 | `reference/business-66-padiem-quote-v1/index.html`에 `#easyVoiceMic` 존재하나 `disabled` | **'한번에 말하기' 안에서만** 음성 전사 → `#easyComposer` → 수량/단가/거래처 확인·수정 후 기존 Send | 확정 발화만 1회 자동 전송, 후속질문 응답 |

B66의 음성은 **세 번째 홈 카드가 아니다**. STT는 견적을 계산하거나 회사/금액을 추측하는 모델이 아니며, **최종 금액은 QuoteCore만** 산출한다. 각 제품의 AI 답변 모델·모델 권한·폴백은 기존 설정 그대로 두고, STT 모델과 답변 모델을 혼동하지 않는다.

### 전사/서버/보안 계약

- 권한 없는 마이크는 활성화되지 않고, 브라우저 미지원/거절/연결오류 시 **텍스트 입력이 정상 작동**해야 한다. 마이크 녹음 중 상태 및 종료를 사용자에게 명시한다.
- `interim`은 화면 표시만, **`final`만 사용자 입력 후보**. 발화 ID별 최대 1회 제출. 폴백·재연결·응답 대기 중 발화 혼입/중복 자동 제출 0건. 음성 출력(TTS)이나 AI 답변이 마이크에 되돌아가 사용자 입력으로 처리되는 루프 금지.
- Cloudflare의 **해당 실행 환경**에서 인증된 STT 요청·바인딩·허용된 호출 예산·청크/음성 크기·타임아웃·Origin/속도 제한을 확인한다. 브라우저에는 공급자 장기 API 키를 노출하지 않는다. 공개 익명 사용자가 무제한 유료 호출을 유도하는 경로를 만들지 않는다.
- 기존 Secrets Store 항목은 재사용한다. **존재 주장 ≠ B62 Worker 또는 B66 Pages binding 확인 ≠ 실시간 모델 요청 성공**. 누락 시 안전하게 차단하고 **키 이름/권한 및 에러 유형만** 보고한다.
- Review-to-send(사용자 검토 후 전송)를 먼저 완료한다. 자동 전송/핸즈프리, TTS 출력 및 운영 활성화는 테스트 결과가 있을 때만 별도 상태로 취급한다.

## 4. 충돌 방지와 실행 순서

1. **LOCAL2 / #4488 Phase A 먼저:** `apps/padiem-chat/static/index.html`, `app.js`, `claw-focus-layout.css` 등의 UI 공통 파일은 현재 작업자 범위다. 별도 음성 작업자가 이 파일을 동시에 편집하거나 오래된 파일 전체를 덮어쓰지 않는다.
2. **병렬 가능한 음성 기반:** 별도 로컬 작업자는 충돌 없는 STT 계약/Cloudflare 서버 경계/독립 테스트부터 구현하고 **Draft PR** 제출. 기존 Worker/Pages 바인딩·권한은 읽기 전용 확인이 선행된다.
3. **#4488 구조 PR 반영 뒤 Chat/Claw 음성 UI 연결:** 새 기준 Chat/Claw 컴포저에 공통 마이크를 추가하고 기능/보안 회귀 테스트.
4. **B66 독립 연결:** #3404 담당 파일에서 이미 있는 `#easyVoiceMic` 활성화 및 Freeform/Saved Quote Skill/QuoteCore 경로 검증. B66의 Pages 브리지는 Chat Worker의 Secret 접근권을 자동 승계하지 않는다.
5. **검증과 출고 구분:** 각 PR의 exact-head CI/보안, 화면/음성 기능 검증, 실제 Production served-version 및 로그인 사용자 확인은 **서로 다른 증거**다. LOCAL은 Draft까지만, CENTRAL은 기존 보호 절차에 따라 검토·병합·안전한 배포 여부를 결정한다. 불필요한 독립 검토자/새 공통 플랫폼/새 API 키/중복 이슈는 만들지 않는다.

## 5. 보고 시 필수 상태값

- `UI_PHASE_A_SOURCE`: NOT_VERIFIED / IN_PROGRESS / DRAFT_PR / MERGED
- `CHAT_CLAW_MIC`, `B66_MIC`: NOT_IMPLEMENTED / SOURCE_READY / LIVE_VERIFIED
- `VOICE_DEFAULT_FALLBACK`: SOURCE_POLICY / BINDING_VERIFIED / PROVIDER_E2E_VERIFIED
- `CLOUDFLARE_SECRETS`: OWNER_REPORTED / RUNTIME_BINDING_VERIFIED (키 값 기재 금지)
- `LONG_UTTERANCE_QA`, `DUPLICATE_FINAL`, `MOBILE_QA`, `EXACT_HEAD_CI`, `PRODUCTION_DEPLOYED`, `OWNER_VISUAL_ACCEPTED`

**2026-10-14 작성 시점:** #4488은 LOCAL2의 읽기 전용 결과와 CTO A/A/A 구현 승인까지만 근거 있음. #4643/#3404는 기술 범위 확정·참조 구현 확인 단계이며 새 음성 코드·운영 음성 기능 완료 증거는 없음. 운영 Secret 바인딩/마이크 E2E도 검증 완료라고 기록하지 않는다.
