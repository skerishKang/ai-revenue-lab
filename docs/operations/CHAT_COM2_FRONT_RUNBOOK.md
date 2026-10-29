# chat.padiem.net 앞단 프록시 전환·원복 런북 (4단계)

```text
DOC_ROLE=CHAT_FRONT_CUTOVER_RUNBOOK
STATUS=코드·테스트·설정 준비 완료 / 배포·전환 없음 (CTO 창 승인 후 Qoder 실행)
RELATED=apps/padiem-chat-front/, docs/architecture/COM2_CHAT_CPYTHON_STAGE2_20261029.md §9
경계: chat.padiem.net Custom Domain은 전환 전까지 padiem-chat(Python Worker)에 그대로 있다.
```

## 0. 앞단이 하는 일 / 하지 않는 일

- 한다: 모든 경로를 `FRONT_ORIGIN`(chat-com2 Tunnel)으로 그대로 전달. 본문·상태코드·헤더(다중 Set-Cookie 포함)·SSE 스트림·WebSocket 업그레이드를 **같은 응답 객체로** 통과. `302`(Google OAuth)도 그대로 브라우저로.
- 하지 않는다: 본문 파싱·JSON/HTML 변환, `response.text()/json()`, 암호화, 자산 캐시. 10ms CPU 예산은 URL/헤더 조립과 fetch 1회에만 쓴다(테스트가 소스 형태까지 고정).
- **정적 자산 캐시: 하지 않는다(권장·기본).** 배포 직후 JS/HTML이 앞단에 남아 컴2와 갈라지는 사고를 막는다. 필요하면 `/static/`만 짧은 TTL로 별도 결정 — 캐시 키·무효화 절차가 먼저 있어야 한다.

## 1. 폴백 규칙 (테스트로 고정됨)

| 상황 | 읽기(GET/HEAD/OPTIONS) | 쓰기(POST/PUT/PATCH/DELETE) |
|---|---|---|
| com2 정상 | com2 응답 그대로 | com2 응답 그대로 |
| com2 무응답/타임아웃/5xx, `COM2_CANONICAL=off` | `FALLBACK_MODE`: `service`→Python Worker / `static`→503 안내 | 데이터 정본이 아직 Python이므로 같은 폴백 허용 |
| 〃, `COM2_CANONICAL=writes` | 같은 읽기 폴백 | **503 `잠시 점검 중` — Python Worker로 절대 폴백 금지(데이터 갈림 방지)** |

- 폴백 판단은 요청 단위. 실패 직후 `HEALTH_TTL_MS`(기본 10초) 동안만 읽기가 com2를 건너뛰고 폴백으로 간다(짧은 헬스 캐시). 창이 지나면 다시 com2를 시도한다.
- 타임아웃은 **헤더 수신까지**에만 적용(기본 8초). 헤더가 온 뒤 스트림은 끊지 않는다(SSE/긴 응답 보호).

## 2. 전환 순서 (CTO 창 승인 후, Qoder)

1. **데이터**: Chat 쓰기 중지(유지보수 센티널) → D1 export → `tools/chat_d1_migration.py plan/load/verify` PASS → 쓰기 재개는 아직 하지 않는다.
2. **컴2 확인**: `chat-com2.padiem.net` 공개 health·로그인·목록·mock 채팅 1회(읽기·쓰기 스모크). 이 시점까지 `chat.padiem.net`은 Python Worker 그대로.
3. **앞단 배포**: `wrangler deploy`(apps/padiem-chat-front) — 아직 Custom Domain 없음(코드·바인딩만 올라감).
4. **전환(1회)**: `chat.padiem.net` Custom Domain을 `padiem-chat`에서 `padiem-chat-front`로 이동. 동시에 앞단 env `COM2_CANONICAL=writes` 반영(전환과 같은 배포에서). 정본은 이 순간 컴2가 된다.
5. **스모크**: `https://chat.padiem.net/health` → 컴2 응답, 로그인(302 왕복)·대화 목록·일반 채팅 1회·PC 목록. Cloudflare 로그에서 앞단이 응답을 대신 만들지 않았는지(`x-padiem-front` 없음) 확인.
6. **쓰기 재개**(센티널 제거)는 컴2 정본 전환이 확인된 뒤에만. 순서를 뒤집지 않는다.

## 3. 원복 (1회)

1. 앞단 env `COM2_CANONICAL=off`로 되돌릴 필요 없이, **Custom Domain을 `padiem-chat`으로 재이동**(1회)하면 트래픽은 Python Worker로 돌아간다.
2. 컴2에만 쓰인 데이터가 있으면 `tools/chat_d1_migration.py export --live`로 핸드백 → Qoder의 D1 재적재 → 장부 대조.
3. 재개 전 대표 시나리오 스모크. 원복도 같은 스모크 목록을 통과해야 완료로 본다.

## 4. 장애 판단 체크리스트

- 읽기만 503이고 쓰기도 503 → com2 다운 + static 모드(정상 폴백 동작).
- 쓰기만 503(`x-padiem-front=write_com2_canonical_refused`) → com2 다운, 정본 보호 규칙이 작동.
- 컴2는 정상인데 앞단 5xx → 터널/바인딩 문제. 앞단 로그와 터널 상태를 먼저 본다.
- 응답이 Python Worker에서 오는지 의심되면 `x-padiem-front` 헤더와 응답의 `server`/`cf-ray`를 대조한다.

## 5. 배포하지 않는 것

이 런북의 어떤 단계도 이 저장소 PR로 자동 실행되지 않는다. `wrangler.toml`의 `routes`는 주석 상태이며, Custom Domain 이동은 승인된 창에서만 한다.
