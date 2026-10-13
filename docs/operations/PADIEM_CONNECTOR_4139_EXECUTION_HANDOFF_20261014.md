# PADIEM Connector #4139 — CENTRAL·LOCAL6 현황 원장 및 실행 인수인계

> **기준:** 2026-10-14 KST. 이 파일은 GitHub에 공개 가능한 기술·증거 정리다. 비공개 사업 운영 결정의 권위는 [루트 AGENTS.md](../../AGENTS.md)의 로컬 Governance 문서에 있으며, 이 문서는 공개 운영 승인·보안 예외·실제 기기 등록 성공 선언이 아니다.
>
> **단일 이슈:** [#4139 기술 구현](https://github.com/skerishKang/ai-revenue-lab/issues/4139), [#3099 Windows/Alpha 실기기 검증](https://github.com/skerishKang/ai-revenue-lab/issues/3099). [#3936 Claw Web/P01 SSE](https://github.com/skerishKang/ai-revenue-lab/issues/3936)는 다른 모델 작업이므로 침범하지 않는다.

## 1. 확인된 실제 진행 상태

| 대상 | 실측 또는 구현 상태 | 남은 검증 |
| --- | --- | --- |
| Windows Connector CLI / WSS / 보호된 자격증명 | 소스 구현. 전체 Windows 격리 테스트 447 PASS, 4 SKIP; 연결 컴퓨터에서 DPAPI 합성 저장·조회·삭제 별도 PASS | 사용자 실제 PC 등록, 클라우드 인증·DPAPI ACK·동기화 E2E 미검증 |
| 운영 PADIEM Chat Worker | Wrangler OAuth 읽기 성공; Identity 서비스 바인딩은 보였으나 Broker 서비스 바인딩 및 Connector 게이트 플래그는 배포본에 없음 | 운영 Connector OFF 유지. 제품/운영 권한 활성화 아님 |
| 기존 운영 Identity / Broker | 배포되어 있음. 조회 당시 Identity 2026-10-05 배포, Broker 2026-09-06 배포 | Broker 옛 운영 버전에 신규 등록 RPC가 들어갔는지 미확인 |
| Connector 전용 Cloudflare D1 | **생성 완료**: padiem-connector-acceptance-4139 | 운영 padiem-chat-db 및 다른 팀 QA DB 재사용 금지 |
| 전용 D1 마이그레이션 | Cloudflare 원격 마이그레이션 성공. SQL 읽기 결과 users, password_credentials, conversations 테이블 존재 | 실제 owner 계정·로그인 E2E 미증명 |
| 격리 Identity | **별도 비공개 Worker 배포 완료**: padiem-control-plane-identity-acceptance-4139 | 실제 private RPC/DO/secret binding readback 상세 미완료 |
| 격리 Broker | **별도 비공개 Worker 배포 완료**: padiem-local-agent-broker-state-acceptance-4139 | 신규 등록의 단회 소진·연결 상태 실증 미완료 |
| 격리 PADIEM Chat | **별도 비공개 Worker 배포 완료**: padiem-chat-connector-acceptance-4139 | Owner UI 실사용 E2E 미완료 |
| 시험용 비밀키 | Identity lookup/ticket, Broker pepper, Chat session 등 **시험용 독립 난수만 각 시험 Worker에 별도 등록** | 운영 비밀키 복사·조회·회전 없음. 값과 UUID를 Git/로그에 쓰지 않음 |
| 시험 URL | https://connector-acceptance.padiem.net **예정 주소 문자열만 소스의 고정 핀으로 구현** | DNS, Cloudflare Access, HTTPS route 미개설. 지금 브라우저 접속 가능이라고 주장 금지 |
| 브라우저 로그인→동의→등록코드→WSS→Windows DPAPI ACK | **미완료·미검증** | 진짜 사용자 인증/동의, TLS·브로커 검증, 1회 challenge, 저장 ACK, ONLINE/철회 확인 필요 |

세 격리 Worker에 대해 실제 Cloudflare 배포 버전 조회는 성공했다. 이것은 **리소스가 배포됐다는 증거**이지 소유자 권한이 부여됐거나 Windows PC가 CONNECTED라는 증거가 아니다. 운영 Worker/운영 D1은 해당 시험 배치에서 변경하지 않았다.

## 2. Cloudflare 계정·설정 상태

- Windows 환경변수 Process/User에 CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID는 등록되어 있었지만 기존 Bearer API token은 검증 HTTP 401 및 Worker API 403으로 인증 사용이 불가했다.
- 기존 Wrangler OAuth 로그인은 유효하다. 그때 실행하는 **자식 프로세스의 API token 환경변수만 제외**하면 실제 Worker 배포 목록/버전 조회, 전용 D1 생성, 비공개 Worker 배포에 성공했다. 따라서 현재 상황을 'Cloudflare API 키 미보유'라고 기록하지 않는다.
- 비밀번호, 인증 토큰, 계정 ID 원문, D1 UUID, 유저 개인정보를 Issue/PR/문서에 게시하지 않는다.
- 설정 파일 apps/padiem-chat/wrangler.connector-acceptance-4139.local.toml 은 per-PC Git 무시 오버레이이다. 새 D1에만 연결되며 password auth + mock runtime + 두 비공개 시험 Service Binding 선언을 담는다. 저장소 템플릿 wrangler.connector-acceptance-4139.toml 은 여전히 공개 route 없음, 기본 로그인 OFF.
- 스크립트 apps/padiem-chat/scripts/prepare_connector_acceptance.py 는 기존 Wrangler OAuth로 D1 목록을 **읽기만** 하고 해당 이름의 전용 D1만 허용한다. --render도 로컬 파일 작성만 하며 D1 생성·마이그레이션·Worker 배포·라우트 공개는 하지 않는다. 연관 테스트 test_4139_prepare_acceptance_d1.py, 정확한 .gitignore가 PR에 커밋되어 있다.

## 2A. CENTRAL 비공개 Cloudflare 서버 실배포 바인딩 정밀 감사 — 2026-10-14 KST

**검증 방법:** 유효한 Windows Wrangler OAuth 인증을 사용하되 오래된 환경의 Cloudflare Bearer 토큰은 각 읽기 전용 명령 자식 프로세스에서만 제외. `wrangler deployments list --json` → **100% 활성** 최신 배포 버전 → `wrangler versions view --json`의 배포 리소스(바인딩의 종류·이름·서버 대상/문자열만 비교). **운영 Worker 배포, D1 SQL 쓰기, secrets 조회, DNS, 공개 URL, 계정/PC 등록 변경 없음.**

**19개 조건 모두 TRUE 확인:**
- Chat의 `IDENTITY_AUTHORITY_SERVICE`, `LOCAL_AGENT_BROKER_AUTHORITY_SERVICE`: **두 바인딩이 service 타입이며 각각 정확히 격리된 acceptance Identity·Broker Worker를 가리킴**.
- Chat `PADIEM_CHAT_DB`: 실제 배포본 D1 ID가 gitignored 로컬 staging manifest의 전용 D1 UUID와 **정확히 일치**, DB 이름은 `padiem-connector-acceptance-4139`.
- Chat Auth/WSS/안전 설정 8개: `PADIEM_CHAT_AUTH_MODE=password`, `PADIEM_CHAT_RUNTIME_MODE=mock`, `PADIEM_CHAT_LIVE_ENABLED=false`, stage base URL/origin exact fixed pin, owner enrollment and WSS feature flags `enabled`, release scope isolated acceptance. 검증은 **일치 여부만 출력**, 실값 로그·비밀키 원문 노출 없음.
- Chat session secret은 `secret_text` 타입으로 배포됨.
- Identity와 Broker는 각각 필요한 **durable_object_namespace 타입**과 필수 secrets(`secret_text`)가 배포본에 존재.
- **Identity DO 및 Broker DO의 실제 namespace ID가 각각 운영의 대응 DO namespace와 서로 다름**. namespace ID 자체는 출력/문서 저장 안 함.

**증명 범위:** 이것은 `CLOUDFLARE_PRIVATE_BINDING_METADATA=PASS`다. **RPC를 실제로 호출·인가/거부·1회 challenge 소비한 증거는 아님**. 또한 `connector-acceptance.padiem.net`의 DNS, HTTPS, Cloudflare Access 설정이나 owner 브라우저 로그인·실기기 PC 등록 성공을 의미하지 않는다.

## 3. GitHub 구현 및 근거

- 현재 CENTRAL 통합 작업은 [Draft PR #4572](https://github.com/skerishKang/ai-revenue-lab/pull/4572)이며 이 문서 직전 최신 GitHub HEAD는 **ebdfe2ddaf6549b6356a61196838f0a340cc1267**. 이 문서 커밋 이후에는 PR HEAD를 다시 조회한다.
- 이전 소스 HEAD 6ccfb26d0a31be98482c616366321716c9bc92a9 는 GitHub CI 21/21 성공으로 확인했다. 최신 HEAD도 CI 종료 후 정확한 SHA 기준으로 판정하며 지난 HEAD의 GREEN을 현재 HEAD에 전용하지 않는다.
- 별도 운영 Worker, 다른 모델의 P01 SSE, B66 고객의 로그인/기기/작업 권한을 이 Connector 시험 환경과 공유하지 않는다.
- 구 상태 원장: [2026-10-13 기술 현황 문서 (main)](https://github.com/skerishKang/ai-revenue-lab/blob/main/docs/operations/PADIEM_CONNECTOR_4139_CENTRAL_STATUS_20261013.md). 현재 배포 실측에 관한 결론은 이 2026-10-14 파일을 우선한다.
- 직접 확인된 Cloudflare 배포/D1 작업은 [PR #4572의 실배포 보고](https://github.com/skerishKang/ai-revenue-lab/pull/4572#issuecomment-6156763348)에, 이번 GitHub 코드 정리는 [복구 보고](https://github.com/skerishKang/ai-revenue-lab/pull/4572#issuecomment-6156892991)에 기록되어 있다.

## 4. Desktop Commander Remote 장애 및 읽기 전용 복구 확인 (Connector 제품 장애와 별개)

사용자 PC의 실행 로그는 **Local Desktop Commander MCP 접속 성공 → Remote MCP 서버 접속 성공 → 기존 장치 세션 복구 성공 → 실시간 채널 연결 실패** 순서였다.

- 대표 오류: channel error: transport failure / socket=connecting, 반복되는 Channel closed/Recreating channel. 'Channel subscribed'가 나오기 전에는 원격 명령이 PC에 전달되지 않는다고 보았다.
- 등록된 Padiem-Command-Center 장치는 관찰 시점에 Online/Offline이 번갈아 표시됐다. **2026-10-14 KST 재확인 시 실제 Remote ping/pong과 PowerShell READ-ONLY 명령 수신·출력까지 성공했다.** 원격 명령 왕복은 회복된 것으로 확인했으나 채널 장시간 안정성·LOCAL6의 워크트리 정합은 아직 검증 중이다. 이는 제품 Connector의 사용자 PC 등록 성공과는 별개다.
- 기존 CENTRAL Windows 격리 워크트리: E:\central-4139-runtime-261014. 원격 장애 당시 이 폴더에 미커밋 파일, 시험 helper/test, Python .venv-connector 및 gitignored staging TOML이 있었다.
- 장애 중 CENTRAL은 GitHub Contents API로 동일 기능의 prepare_connector_acceptance.py / 관련 테스트 / .gitignore 를 별도 커밋해 PR #4572에 반영했다. **LOCAL6은 로컬에 남은 동일 파일을 중복 git add/push 하거나 중앙 워크트리를 reset/clean 하지 않는다.**

**실제 Windows read-only 명령 확인:** 복구 직후 원격 PowerShell이 REMOTE_READ_ONLY_COMMAND=RECEIVED 를 출력했고, CENTRAL 워크트리는 Git HEAD ebdfe2ddaf6549b6356a61196838f0a340cc1267 (최신 GitHub 문서 커밋 이전)인 것을 확인했다. git status: 수정 apps/padiem-chat/scripts/connector_cloudflare_runtime_readiness.py 1개, 미추적 .check-4139-private-chat.py / .provision-4139-stage-secrets.py / .venv-connector/ / apps/padiem-chat/python_modules/. **실제 PC 파일을 읽기만 했으며 삭제·커밋·리셋하지 않았다.** 최신 GitHub HEAD와 충돌 정합 없이 이 로컬 파일들을 자동으로 push하면 안 된다.

## 5. LOCAL6 현장 작업 인계 — 실행 순서

LOCAL6은 Windows 로컬 현장 담당, CENTRAL은 PR/CI·Cloudflare 상태·범위 조율 담당이다. 독립 리뷰어를 새로 만들지 않는다.

1. **장치 연결 회복:** Remote 프로세스의 중복 여부, WebSocket channel·네트워크·프록시·방화벽을 확인한다. 다른 모델의 Node 프로세스·브라우저를 종료하지 않는다. Channel subscribed 로그뿐 아니라 실제 READ-ONLY 왕복 한 건으로 복구를 확인한다.
2. **파일·버전 정합:** 중앙 워크트리 E:\central-4139-runtime-261014 를 먼저 READ-ONLY 검사한다. git status --short, git rev-parse HEAD, 실제 #4572 head_sha 를 대조한다. LOCAL6은 별도 새 worktree를 우선 사용한다. 기존 .venv-connector, 비공개 staging TOML, 미커밋 파일은 지우거나 덮지 않는다. 강제 reset/clean/rebase 금지.
3. **로컬 코드 정리:** 원격 최신 prepare_connector_acceptance.py, 테스트, .gitignore 와 중앙 워크트리의 과거 미커밋 동등 파일을 비교한다. 이미 원격 반영된 변경을 재커밋하지 않는다.
4. **실사용 사전 조회:** CENTRAL은 Wrangler OAuth로 이미 배포본의 D1 UUID·Identity/Broker 서비스 대상·secrets 종류·암호 모드 및 Durable Object의 운영/시험 분리까지 실제 읽기 전용으로 확인했다(19/19 PASS). LOCAL6은 이 검증을 무의미하게 재작업하지 말고 실제 사용자 동의·Windows WSS/DPAPI 경로에서 미증명 부분만 담당한다. 운영 계정/DB/Worker를 배포하거나 고치지 않는다.
5. **접속 허가와 인증:** 시험용 공개 HTTPS 주소는 현재 미개설이다. 대상 사용자/접근 통제·공개 여부에 대한 적법한 소유자 판단 없이는 DNS/route/Access를 열지 않는다. 실제 owner 로그인과 명시적 동의가 가능한 경로가 준비되면 그 세션으로 등록 테스트한다.
6. **실제 E2E:** 사용자 로그인 → B54 owner-bound challenge → PC pairing code 단회 검증 → pinned WSS / TLS → Windows DPAPI 저장·readback 및 ACK → 서버 연결 상태 확인. 시간 초과·거부·철회·재연결을 #3099에서 검증한다. 테스트 PASS만으로 PC 등록 성공을 선언하지 않는다.

**범위 제한:** 운영 Worker·D1·secret 무단 수정 금지, 임의 공개 HTTPS 활성화 금지, 타팀 P01 SSE(#3936)와 B66 고객 레인 침범 금지, 독립 리뷰어 추가 금지, PR Ready/merge 금지.

## 6. 단일 후속 체크리스트

- [x] 전용 시험 D1 신규 생성·원격 스키마 적용·핵심 테이블 읽기 확인
- [x] 전용 비밀키 등록·비공개 시험 Identity/Broker/Chat 3개 Worker 배포
- [x] 승인된 시험 도메인 문자열과 운영 주소를 구별하는 WSS 코드 가드 작성
- [x] GitHub PR #4572에 전용 DB guard 스크립트·테스트·gitignore 커밋
- [x] Desktop Commander 실제 READ-ONLY 원격 명령 왕복 성공. LOCAL6 워크트리 정합·채널 재연결 안정성은 별도 미완료
- [x] CENTRAL이 시험용 3 Worker의 **실제 Cloudflare 배포버전**에서 Service Binding 대상명, 전용 D1 실제 ID, owner 인증·게이트 설정값, secrets 바인딩 유형, Identity/Broker의 Durable Object 분리 ID를 **비밀값 출력 없이 19개 조건으로 직접 검증 PASS**
- [ ] 실제 owner 인증을 거치는 **private RPC 발급·소진 성공** 증명 및 접근 범위 검증 (위 메타데이터 검증과 구별)
- [ ] 허용된 사용자만 접근 가능한 시험 HTTPS route 및 실제 브라우저 로그인
- [ ] 진짜 사용자 동의→challenge→Windows PC WSS/DPAPI ACK와 서버 상태 확인
- [ ] #3099에 실기기 Alpha 수용 근거 기록; 운영 배포/출시는 별도 소유자 결정

**상태:** STAGE_D1_CREATED=YES; STAGE_3_WORKERS_DEPLOYED=YES; PRODUCTION_CONNECTOR_ON=NO; STAGE_PUBLIC_HTTPS=NO; AUTHENTICATED_OWNER_PC_PAIRING=NOT_PROVEN; PR_4572=DRAFT.
