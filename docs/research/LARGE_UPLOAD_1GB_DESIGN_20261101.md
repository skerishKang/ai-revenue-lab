# 1GB 파일 업로드 구조 설계 조사 (2026-11-01)

- 발단: 대표 결정 — **파일 업로드 상한 1GB 통일**. 코드는 건드리지 않는 조사 문서다.
- 한 줄 추천: **A안(조각 업로드, tus 프로토콜 계열, 앞단 그대로 통과)** — 새 인프라 없이 무료 플랜 100MB 한도 안에서 1GB를 내는 길. B안은 같은 존·같은 플랜이라 한도를 못 피해 기각, C안(R2 직접 업로드)은 무료 저장 10GB월이라 보조 수단.
- 기준 커밋: main `a4ef4aad`(2026-11-01). 근거는 아래 링크·코드 위치로 직접 확인한 것만 넣었다.

## 1. 배경과 제약

- 경로: `chat.padiem.net` → Cloudflare(무료 플랜) 앞단 `padiem-chat-front` → 터널 → 컴2 Chat.
- 앞단 워커는 **순수 프록시**다. 본문을 읽지 않고 그대로 통과한다(`apps/padiem-chat-front/worker.mjs:4` — "Pure proxy: the request body … pass through untouched. No body reads").
- 1GB를 막는 것은 워커가 아니라 **Cloudflare 엣지의 요청 본문 한도**다.
  - 공식: "request body size limits **depend on the domain's Cloudflare plan** … Requests exceeding these limits return a `413 Request entity too large`" — [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).
  - 공식 표: 최대 업로드 **Free·Pro 100MB**, Business 200MB, Enterprise 최대 5GB(존 Network 페이지에서 상향) — [Default Cache Behavior](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/), [Error 413](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/).
- 컴2 본체는 큰 본문을 받을 수 있다. 프로젝트 파일·웹 XLSX의 앱 상한이 이미 1GiB이고(§2), 파일 레인은 1MiB 청크로 100MiB 넘는 PDF를 파싱한다는 증명도 있다(`apps/padiem-file-lane/README.md:162`).

## 2. 현재 업로드 경로·상한 (코드 기준)

| 경로 | 브라우저→컴2 방식 | 앱 상한(값·위치) | 실효 한도 |
|---|---|---|---|
| Chat 첨부(사진·문서) | 채팅 전송 JSON 본문에 base64 1개 | 앱 상한 없음 — 첨부 상한 심볼은 #4379부터 미강제(`attachments.py:14-18`, 1GiB), 채팅 본문 한도 `MAX_BROWSER_BODY_BYTES=None`(`request_contract.py:27`, `chat_routes.py:352-359`) | Cloudflare 100MB. base64가 33% 부풀어 파일은 약 75MB까지 |
| 프로젝트 파일 | 바이너리 스풀 업로드(임시 파일로 스트리밍, `project_file_routes.py:218`) | 1GiB — `MAX_BINARY_DOCUMENT_BYTES`(`padiem-ai-core/document_normalization.py:41`). JSON 본문은 2.25MiB(`project_file_routes.py:55`) | Cloudflare 100MB |
| 웹 XLSX | 인라인 10MB 이하는 본문 직접, 그 위는 파일 레인 티켓 스트리밍 | 1GiB — `MAX_WEB_XLSX_BYTES`(`workspace_storage.py:18`), 인라인 10MB(`:22`), 편집기 원본 1GiB(`claw_web_xlsx_quote_editor.py:24`) | Cloudflare 100MB |
| PC 가져오기 | 컴2가 PC 커넥터에 **1MB 청크 범위 읽기** 요청(#6541 큰 파일 나눠 읽기) | 청크 1MB(`claw_pc_read_command.py:26`), 오피스 접두 읽기 16MiB(`:35`) | 브라우저·엣지를 거치지 않아 100MB 한도와 무관 |
| (참고) 파일 레인(파서) | 티켓 발급 후 예산제 스트리밍 | 티켓 `max_bytes` 예산(`file_lane.py:74,133`), 10MB 자동 기준(`:263`) | 컴2 내부는 100MiB 초과도 처리 증명(README:162) |

정리: **앱 상한은 이미 1GiB이거나 없다. 실제 병목은 Cloudflare 무료 플랜 100MB 하나다.**

## 3. 방식 비교

### A. 조각 업로드 — 앞단을 그대로 통과 (추천)

- 원리: 브라우저가 파일을 **90MB 이하 조각**으로 나눠 기존 앞단 경로로 여러 요청을 보내고, 컴2가 순서대로 받아 합친다.
- 왜 90MB: 엣지 100MB 한도 위에 헤더·중간 처리 여유를 남긴다.
- 장점: 새 주소·새 인프라가 필요 없다. 기존 로그인·엣지 HMAC 증명 경로를 그대로 쓴다. 조각 하나가 실패하면 그 조각만 다시 보내면 된다(이어올리기). 무료 플랜에서 그대로 동작한다.
- 단점·새로 할 일: 수신 엔드포인트·합치기·재개 상태 관리가 새로 필요하다. 합치기 전 중간 파일이 컴2 디스크에 생긴다 — **11-01 운영 교훈 8-1**대로 systemd 쓰기 가능 경로(`/opt/padiem/chat-com2/data` 또는 `/mnt/d/padiem/...`) 안에 둬야 한다.
- 변경 위치: ① 브라우저 업로드 클라이언트 ② 컴2 Chat 수신·합치기 ③ 저장(기존 객체 저장 재사용) ④ 상한·안내 상수 정리. 앞단 워커는 그대로.
- 보안: 기존 세션 인증 + 엣지 HMAC을 조각마다 통과. 합치기 완료 전에는 완성 파일이 생기지 않는다.
- 이어올리기: 가능. 조각 단위 재시도 기본이고, tus 프로토콜을 쓰면 offset 재개가 표준으로 내장된다.
- 오픈소스 후보(라이선스는 GitHub API로 확인 — 전부 **MIT**):

| 후보 | 역할 | 라이선스 | 확인 |
|---|---|---|---|
| [tus 프로토콜 v1.0.0](https://tus.io/) | 재개 업로드 표준(CREATE → PATCH offset) | 프로토콜(사양 공개) | [tus.io](https://tus.io/) |
| [tus-js-client](https://github.com/tus/tus-js-client) | 브라우저 조각·재개 전송 | MIT | [GitHub API](https://api.github.com/repos/tus/tus-js-client) |
| [tusd](https://github.com/tus/tusd) | 컴2 수신 서버(Go). 디스크·GCS·AWS S3(또는 S3 호환) 저장 지원 | MIT | [README](https://github.com/tus/tusd/blob/master/README.md) |
| [Uppy](https://github.com/transloadit/uppy) | 브라우저 업로드 UI(진행률·재개, tus 플러그인) | MIT | [GitHub API](https://api.github.com/repos/transloadit/uppy) |

### B. 큰 파일만 앞단 우회 — upload.padiem.net → 터널

- 원리: 업로드 전용 호스트명을 만들어 터널로 컴2에 직접 붙이고, 서명 URL로 권한을 확인한다.
- **판정: 같은 존(padiem.net)의 무료 플랜이면 새 호스트명·터널로도 한도가 그대로다.**
  - 공식: 본문 한도는 "domain's Cloudflare plan"을 따르고, 상향은 Enterprise만 존 Network 페이지에서 가능 — [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).
  - 커뮤니티 확인(보조 근거): 터널 공개 호스트명은 DNS-only를 쓸 수 없어 100MB 한도가 적용된다 — [100mb tunnel limit(Community, 2026-03)](https://community.cloudflare.com/t/100mb-tunnel-limit/901339).
- 진짜 우회는 프록시를 끄고 집 회선을 직접 노출하는 것뿐인데, IP 노출·TLS·가용성 문제로 권장하지 않는다.
- 장단점: 설정이 적지만 한도를 못 피한다. 서명 URL은 짧은 만료가 필요하다.
- 결론: **기각** — 1GB 목적에 효과가 없다.

### C. 저장소(R2) 직접 업로드 — 서명 URL

- 원리: 컴2가 프리사인 URL을 발급 → 브라우저가 R2 S3 엔드포인트로 직접 업로드 → 컴2가 나중에 가져간다(다운로드 이그레스 무료).
- Cloudflare 엣지 100MB를 피한다. R2는 단일 PUT 최대 **5GiB**, 멀티파트로 최대 4.995TiB(파트 최대 10,000개) — [R2 limits](https://developers.cloudflare.com/r2/platform/limits/).
- 장점: 컴2 부하·디스크 부담이 줄고, 멀티파트로 이어올리기가 가능하다.
- 단점: 무료 저장 **10GB월**(1GB 파일 몇 개면 초과 — 초과분 $0.015/GB월), Class A 100만·Class B 1,000만 건/월 무료 — [R2 pricing](https://developers.cloudflare.com/r2/pricing/). 버킷 CORS 설정·프리사인 단기 만료·키 관리, 업로드 완료 후 컴2가 회수·정리하는 절차가 추가된다. 워커 프록시와 다른 경로라 인증을 컴2가 따로 검증해야 한다.
- 변경 위치: ① 컴2 프리사인 발급 엔드포인트(신규) ② R2 버킷·CORS ③ 브라우저 클라이언트 ④ 회수·정리 작업.
- 보안: 프리사인 URL은 단기 만료 + 업로드 완료 후 컴2 검증. 키는 레인 규칙대로 출력·argv 금지, 파일→파일만.
- 결론: **보조 수단**. 컴2 디스크 부담이 커지거나 저장 비용을 감수할 때 A안 다음 단계로 유효.

## 4. 추천안

**A안(tus 계열 조각 업로드, 앞단 그대로)로 시작한다.** 이유: 무료 플랜 한도 안에서 해결되고, 기존 로그인·엣지 HMAC·앞단 워커를 그대로 쓰며, 이어올리기가 표준으로 제공되고, 후보 OSS가 전부 MIT라 가져다 쓸 수 있다(레인 규칙: MIT·Apache·BSD는 가져온다).

- tusd를 컴2에 두면 저장을 디스크로 시작했다가 나중에 S3 호환(R2) 백엔드로 바꿀 수 있어, C안으로 넘어갈 길이 남는다.
- 1GB 확인 방법: 조각 수(예: 90MB×12≈1.08GB) + 합치기 후 총 크기·SHA256 대조.

## 5. 단계별 작업 목록 (레인 배분)

| 순서 | 작업 | 레인 |
|---|---|---|
| 1 | 규격 확정: 엔드포인트·조각 크기(≤90MB)·재개 계약·합치기 검증(SHA256)·상한 1GB·실패 문구 | CTO. 브라우저→수신→합치기→저장 **3곳 이상을 잇는 일**이므로 레인 규칙 §2대로 최고 모델에 규격째 주거나, CTO가 규격을 이슈에 올린 뒤 조각 단위로 나눈다 |
| 2 | 수신 서비스 준비: tusd(또는 Chat 내 수신) 설치·systemd 유닛·logrotate, 쓰기 경로를 11-01 교훈 8-1 안으로 | 컴2 운영 레인(qwen). 유닛·설치 스크립트 작성은 컴1 |
| 3 | 브라우저 클라이언트: tus-js-client(Uppy) 연결, 진행률·재개 | 컴1(딥시크). 화면 마무리·한국어 문구는 아스트라(6.1 테라) |
| 4 | Chat·저장 연결: 업로드 완료 → 기존 객체 저장·파일 레인 파싱로 이어 주기 | 컴1/최고 모델 |
| 5 | 기존 경로 정리: 첨부·프로젝트·XLSX 안내 문구를 1GB로 통일, 413(너무 큰 파일) 오류 화면 안내 | 아스트라 |
| 6 | 실전 시험: 1GB 파일 업로드, 중간에 끊고 재개, 로그인 상태로 처음부터 끝까지 1건 성공 | 컴1 준비 + 대표 확인 |

## 6. 근거 링크

**저장소 코드(main `a4ef4aad`)**
- 앞단 순수 프록시: `apps/padiem-chat-front/worker.mjs:4`
- 채팅 본문 한도 없음: `apps/padiem-chat/app/request_contract.py:27`, `chat_routes.py:352-359`
- 첨부 상한 미강제(#4379): `apps/padiem-chat/app/attachments.py:14-18`
- 프로젝트 파일 1GiB 스풀·2.25MiB: `apps/padiem-chat/app/project_file_routes.py:55,218`, `packages/padiem-ai-core/padiem_ai_core/document_normalization.py:41`
- 웹 XLSX 1GiB·인라인 10MB: `apps/padiem-chat/app/workspace_storage.py:18,22`, `claw_web_xlsx_quote_editor.py:24`
- PC 1MB 청크: `apps/padiem-chat/app/claw_pc_read_command.py:26,35`
- 파일 레인 예산·청크 증명: `apps/padiem-chat/app/file_lane.py:74,133,263`, `apps/padiem-file-lane/README.md:162`
- 11-01 운영 교훈(쓰기 경로·100MB): `docs/operations/CHAT_COM2_RUNBOOK.md` §8

**공식 문서**
- Cloudflare Workers limits(본문 한도는 플랜 따름, 413): https://developers.cloudflare.com/workers/platform/limits/
- 최대 업로드 표(Free 100MB): https://developers.cloudflare.com/cache/concepts/default-cache-behavior/ , https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/
- R2 limits(단일 PUT 5GiB·멀티파트 10,000파트): https://developers.cloudflare.com/r2/platform/limits/
- R2 pricing(무료 10GB월·이그레스 무료): https://developers.cloudflare.com/r2/pricing/
- tus 프로토콜: https://tus.io/ · tusd README(디스크·S3 호환 저장): https://github.com/tus/tusd/blob/master/README.md

**라이선스 확인(GitHub API, 2026-11-01)**: `repos/tus/tusd` · `repos/tus/tus-js-client` · `repos/transloadit/uppy` — 모두 MIT

**보조(커뮤니티)**: 터널 100MB 적용 확인 — https://community.cloudflare.com/t/100mb-tunnel-limit/901339
