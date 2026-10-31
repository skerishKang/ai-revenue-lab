# COM2 전환 후 관측 리포트 (읽기 전용)

2026-10-31 21:07 KST에 `chat.padiem.net` 운영이 COM2(8798 Chat, 8811 P01,
8789 B14)로 넘어갔다. 이 스크립트는 **전환 뒤 24시간 동안 #5479(Python Worker
NoGilError)와 #6127(`/api/auth/status`·`/api/projects` 간헐 500)이 다시
나타났는지** journald만 읽어서 센다.

- 서비스를 시작·중지·재시작·enable·reload하지 않는다.
- 로그 설정(unit, drop-in, logrotate, uvicorn 옵션)을 바꾸지 않는다.
- 원본 로그 줄, 요청 본문, 쿼리 문자열, 헤더, 쿠키, 클라이언트 주소, 사용자·
  대화 식별자, request id, 비밀 값을 출력하지 않는다.
- health 응답 본문은 최대 64 KiB만 읽어 `status=ok` 확인에만 쓰고 출력하지
  않는다. 상태 코드와 판정만 남는다.

## 실행

COM2 호스트에서 실행한다(journald와 systemd가 있는 곳).

```bash
# 기본: 지금부터 최근 24시간
python3 deploy/host-com2/observe/post_cutover_report.py

# 종결 판단용: 전환 시각부터 정확히 24시간
python3 deploy/host-com2/observe/post_cutover_report.py \
  --since 2026-10-31T21:07:00+09:00 \
  --until 2026-11-01T21:07:00+09:00 \
  --json-out /tmp/post-cutover-20261101.json
```

출력은 사람용 요약 표 다음에 JSON 한 줄이 이어진다. `--json-out`은 같은 JSON을
파일로도 저장한다.

| 옵션 | 뜻 |
| --- | --- |
| `--since`, `--until` | ISO-8601 시각. 기본 `until=now`, `since=until-24h` |
| `--cutover` | 종결 판단 기준 전환 시각. 기본 `2026-10-31T21:07:00+09:00` |
| `--json-out` | JSON 리포트 파일 경로 |
| `--health-url UNIT=URL` | loopback health URL 재정의(반복 가능) |
| `--no-health` | health 확인 생략 |
| `--health-timeout` | health 요청 타임아웃(초), 기본 5 |
| `--journalctl`, `--systemctl` | 실행 파일 경로 재정의(시험·이식용) |

종료 코드는 리포트 생성 시 `0`, 인자 오류·JSON 파일 쓰기 실패 시 `2`다.
리포트의 판정 결과 자체는 종료 코드에 영향을 주지 않는다.

## 읽는 것

| 항목 | 출처 |
| --- | --- |
| Traceback 수 | `journalctl -u padiem-chat-com2`, `padiem-p01`, `padiem-b14` |
| `ERROR` 줄 수 | 같은 journald 창 |
| `NoGilError`·`PyProxy` 문자열 수 | 같은 journald 창(발생 횟수) |
| HTTP 5xx(경로별) | Chat 앱의 `http_request` 이벤트 우선, 없으면 uvicorn 접근 로그 |
| 재시작 횟수 | `systemctl show -p NRestarts` |
| 유닛 상태 | `systemctl show -p ActiveState,ExecMainStatus` |
| health | `127.0.0.1`의 Chat `/health`, P01 `/internal/v1/health`, B14 `/health` |

`5xx`는 다음 순서로 한 소스만 쓴다. 두 소스를 동시에 더하면 같은 요청을 두 번
세게 되기 때문이다.

1. Chat 앱의 구조화 요청 이벤트(`"event":"http_request"`, `status`, `route`)
2. uvicorn/gunicorn 형식 접근 로그(`"GET /path HTTP/1.1" 500 ...`)
3. 둘 다 없으면 **`5xx 집계 불가`**(`available=false`, `reason=no_request_records`)

경로는 집계용으로만 정규화한다. 쿼리·프래그먼트를 제거하고, `/api/projects/...`
같은 동적 구간은 `/api/projects/*`로 접는다. 리포트에 원래 경로가 나가지 않는다.

## 접근 로그가 꺼져 있을 때 (제안만, 이 스크립트는 바꾸지 않음)

현재 단위 파일 기준:

- **Chat**: `padiem-chat-com2.service`는 `--no-access-log`를 넘기지 않는다.
  uvicorn 기본값으로 접근 로그가 켜져 있고, 앱의 `http_request` 이벤트도 있다.
  따라서 5xx 집계에 별도 변경이 필요 없다.
- **P01**: `padiem-p01.service`의 `ExecStart`에 `--no-access-log`가 있다.
- **B14**: `apps/korean-ai-platform/asgi.py`가 `access_log=False`로 uvicorn을
  실행한다.

P01/B14에서 5xx를 세려면 운영자가 별도로 결정해야 한다. 아래는 **제안**이며
로그 설정을 이 저장소나 이 스크립트가 적용하지 않는다.

1. P01: unit의 `--no-access-log`를 제거하거나 `--access-log`로 바꾼다.
2. B14: `asgi.py`의 `access_log=False`를 `True`로 바꾸거나, uvicorn을 CLI로
   띄우는 경우 `--access-log`를 준다.
3. 두 경우 모두 접근 로그에 클라이언트 주소와 요청 대상이 남는다. journald
   보존 기간, 접근 권한, 개인정보 처리 방침을 먼저 확인한다. 요청 본문·쿼리·
   쿠키는 로그에 남기지 않는 현재 앱 동작을 유지한다.

앱이 자체 요청 이벤트를 남기게 하는 편이 접근 로그보다 노출이 적다. 이때도
경로 템플릿, 상태 코드, 소요 시간만 남기고 요청 내용은 남기지 않는다.

## #5479·#6127 종결 판단 기준 (전환 뒤 24시간 0건)

리포트의 `closure`가 판정한다. **아래 세 조건이 모두 참일 때만 닫는다.**

1. `window_covers_full_24h=true`
   - 창이 `2026-10-31T21:07:00+09:00`(전환)부터 그 24시간 뒤까지를 모두 덮어야 한다.
   - 기본 최근 24시간 실행은 전환 직후에는 이 조건을 만족하지 않는다. 위의
     `--since`/`--until` 예시처럼 전환 시각을 명시한다.
2. `#5479.pass=true`
   - `padiem-chat-com2` journald 창에서 `NoGilError` 발생 횟수가 0.
   - `PyProxy`는 별도로 표시한다. 종결 조건은 `NoGilError` 0건이다.
3. `#6127.pass=true`
   - Chat의 5xx 집계가 **가능**하고(`http_5xx_available=true`),
   - `/api/auth/status` 5xx가 0,
   - `/api/projects` 및 그 하위 경로 5xx가 0.

`closeable=true`는 위 조건이 모두 참이라는 뜻이다.

- `#6127=UNKNOWN` 또는 `5xx 집계 불가`는 "0건"이 아니다. **닫지 않는다.**
  P01/B14의 `5xx 집계 불가`는 Chat의 #6127 판정을 막지 않는다.
- `counts=null`, `n/a`는 journald를 읽지 못했다는 뜻이다. 0으로 해석하지 않는다.
- `Traceback`·`ERROR` 수, 재시작 횟수, health는 판정 근거를 설명하는 참고값이다.
  #5479/#6127의 종결 조건 자체는 위 3개다.
- `NRestarts`는 systemd의 현재 누적 카운터다. `daemon-reload` 등으로 초기화될 수
  있어 창 전체의 재시작 횟수와 정확히 같지 않다.
- health는 실행 시점의 한 번의 확인이다. 창 전체의 가용성을 대신하지 않는다.

예시:

```text
closure: #5479=PASS #6127=PASS full_24h=YES closeable=YES
```

## 시험

가짜 journal 문자열로 집계·비밀 비노출·판정을 확인한다. 실제 COM2에 접속하지
않고 Windows/Linux 어디서나 돈다.

```bash
python -m unittest discover -s deploy/host-com2/observe/tests -v
```

검사 항목:

- 앱 요청 이벤트와 접근 로그의 5xx/경로 집계, 우선순위
- Traceback·ERROR·NoGilError·PyProxy 집계
- 요청 기록이 없을 때 `5xx 집계 불가`
- journald 읽기 실패 시 `0`이 아닌 `null`
- 24시간 창·재발·5xx 불가에 따른 종결 판정
- 쿼리·이메일·토큰·쿠키·요청 본문·request id가 요약/JSON에 없는지
- health 200/비200, loopback 외 URL 거부, 응답 본문 비노출
- 명령이 `journalctl` 읽기와 `systemctl show`만 쓰는지