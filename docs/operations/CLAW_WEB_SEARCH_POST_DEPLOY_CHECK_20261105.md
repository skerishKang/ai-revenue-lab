# Claw 공개 웹 검색 — 배포 후 확인 점검표 (#6915)

대상: 컴2 Chat (`/opt/padiem/chat-com2`, unit `padiem-chat-com2.service`, loopback `127.0.0.1:8798`)
근거: #6915 (main `26f1b29`) — 호스트 `app/local_cpython.py:596-620`에서 스위치가 `true`일 때만
`build_local_p01_lanes` → `trusted_claw_search_activation` 조립.

이 문서는 **읽기 전용 점검**만 다룬다. 스위치를 켜는 결정·실행은 대표 확인 후 배포 레인이 한다.
요청 본문·세션 쿠키·모델 이름·키는 티켓에 옮기지 않는다.

## 0. 사전 조건과 기준선

- [ ] 배포된 main이 `26f1b29` 이상이다: `git -C /opt/padiem/chat-com2 rev-parse HEAD`
- [ ] 서비스가 healthy다:
      `/opt/padiem/chat-com2/venv/bin/python /opt/padiem/chat-com2/health.py --url http://127.0.0.1:8798/health`
      → `CHAT_COM2_HEALTH=PASS STATUS=200`
- [ ] `.env`에 아래가 있다(값은 화면에 출력하지 않고 존재만 확인):
      `PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED=true`,
      `PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN`, `PADIEM_CHAT_LOCAL_P01_CALLER_ID`,
      `PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL`, `PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN`,
      `PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET`, `PADIEM_CHAT_QUOTA_SALT`
      확인: `grep -c '^PADIEM_' /opt/padiem/chat-com2/.env` (개수만 기록)
- [ ] 켜기 **전** 기준선을 기록한다(4번 명령으로 503 건수).

## 1. 로그인 사용자 일반 질문 → 200

가장 안전한 방법은 브라우저다. 로그인 세션을 복사하지 않아도 된다.

- [ ] Claw 화면에서 최신성이 필요 없는 질문 1건: 예) `파이썬이 뭐야?`
- [ ] DevTools → Network → `general` 요청 확인:
      status **200**, `content-type: text/event-stream`, 마지막 frame에 `"done":true`
- [ ] `error.code=engine_not_configured`가 **없다**
- [ ] 같은 요청을 CLI로 재현하려면 Network 탭의 **Copy as cURL**을 그대로 쓴다
      (세션 쿠키가 포함된다. 쿠키 값을 따로 읽거나 출력하지 않는다).

판정: 200 + `done` frame = PASS. 401이면 세션 미첨부, 402/429면 quota, 503이면 3번(스위치) 확인.

## 2. 최신 정보 질문 → 판정·근거·출처

- [ ] 최신성이 필요한 질문 2~3건. 예) `이번 주 기준금리 결정 알려줘`
- [ ] 응답 `done` frame의 `sources` 확인:
      `[{"url":"https://…","title":"…","retrieved_at":"…"}]` 최대 5건, **모두 https**
      (`app/claw_general_routes.py:682-704`가 https·title·retrieved_at만 투영한다)
- [ ] 화면에 출처 목록이 보인다

판정:
- sources 1건 이상 + 인용된 답변 = PASS (검색 경로가 provider까지 갔다)
- sources 0건 = 검색이 안 돈 것. 단, "모델이 검색 불필요 판정"과 "호출 실패"를
  저널로 구분할 수 없다(4번 한계). 2~3건 중 전부 0건이면 실패로 본다.

## 3. 되돌리기 — 스위치 off → 503 복귀

- [ ] `/opt/padiem/chat-com2/.env`에서 `PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED`를 `false`로
      바꾸거나 줄을 지운다(값 백업은 배포 레인 절차를 따른다).
- [ ] 서비스 재시작(배포 레인 창구에서, 무중단 아님).
- [ ] 1번과 같은 요청 → **503** JSON `{"error":{"code":"engine_not_configured",…}}`
- [ ] 다시 `true`로 복구 → 재시작 → 1번이 **200**으로 돌아온다.

의도된 동작: off면 호스트는 P01 레인을 조립하지 않으므로 Claw 일반 레인 전체가 503이다.
이는 #6915 이전 컴2의 상태와 같다(#6915 본문 "남는 사실" 참조).

## 4. 저널 집계 — 요청 이벤트와 검색 단계 이벤트

두 종류의 한 줄 JSON이 남는다: HTTP 요청 이벤트(`"event":"http_request"`,
`app/request_telemetry.py:58` — 경로 템플릿·상태·`duration_ms`·`error_code`, 본문 없음)와
웹 검색 단계 이벤트(`"event":"claw_web_search"`, (d)).

### (a) Claw 요청 상태 집계

```sh
journalctl -u padiem-chat-com2.service --since '1 hour ago' -o cat \
  | grep '"event":"http_request"' \
  | grep '"route":"/api/claw/general"' \
  | /opt/padiem/chat-com2/venv/bin/python -c '
import sys, json, collections
counts = collections.Counter()
for line in sys.stdin:
    try:
        event = json.loads(line)
    except Exception:
        continue
    if event.get("route") == "/api/claw/general":
        counts[(event.get("status"), event.get("error_code") or "-")] += 1
for key, count in sorted(counts.items(), key=lambda item: str(item[0])):
    print("status=%s code=%s count=%d" % (key[0], key[1], count))
'
```

기대: 켠 뒤 `status=200 code=- count=N`. `status=503 code=engine_not_configured`는 0으로 수렴.

### (b) 503만 따로 세기 (켜기 전/후 비교)

```sh
journalctl -u padiem-chat-com2.service --since today -o cat \
  | grep '"route":"/api/claw/general"' | grep -c '"status":503' || true
```

### (c) 요청 지연

```sh
journalctl -u padiem-chat-com2.service --since '1 hour ago' -o cat \
  | grep '"route":"/api/claw/general"' \
  | /opt/padiem/chat-com2/venv/bin/python -c '
import sys, json
values = []
for line in sys.stdin:
    try:
        event = json.loads(line)
    except Exception:
        continue
    if isinstance(event.get("duration_ms"), (int, float)):
        values.append(event["duration_ms"])
values.sort()
if values:
    index = max(0, int(len(values) * 0.95) - 1)
    print("n=%d p95=%.0fms max=%.0fms" % (len(values), values[index], values[-1]))
'
```

### (d) 웹 검색 단계 집계 — `claw_web_search`

판정(decide)·근거(ground) 단계가 끝날 때 한 줄 JSON이 남는다(#4469 텔레메트리):

```json
{"event":"claw_web_search","stage":"decide|ground","outcome":"ok|skipped|error","sources":0,"duration_ms":12.3}
```

- `stage=decide`: 모델 판정 호출. `ok`=판정 도착, `skipped`=판정 자체를 못 함(클라이언트·digest·model id 없음), `error`=호출 예외.
- `stage=ground`: 근거 조회. `ok`=출처 확보, `skipped`=모델이 "검색 불필요" 판정, `error`=조회 예외 또는 증거 형태 거부(`error="invalid_evidence"`).
- `error` 필드는 예외 클래스 이름 또는 `invalid_evidence`만. query·대화·증거 본문·URL은 남지 않는다.
- 스위치가 꺼진 턴은 이 줄을 남기지 않는다(오늘과 동일한 무로그).

```sh
journalctl -u padiem-chat-com2.service --since '1 hour ago' -o cat \
  | grep '"event":"claw_web_search"' \
  | /opt/padiem/chat-com2/venv/bin/python -c '
import sys, json, collections
counts = collections.Counter()
sources = 0
for line in sys.stdin:
    try:
        event = json.loads(line)
    except Exception:
        continue
    if event.get("event") != "claw_web_search":
        continue
    counts[(event.get("stage"), event.get("outcome"), event.get("error") or "-")] += 1
    sources += int(event.get("sources") or 0)
for key, count in sorted(counts.items()):
    print("stage=%s outcome=%s error=%s count=%d" % (key[0], key[1], key[2], count))
print("sources_total=%d" % sources)
'
```

실패만 세기:

```sh
journalctl -u padiem-chat-com2.service --since today -o cat \
  | grep '"event":"claw_web_search"' | grep -c '"outcome":"error"' || true
```

판정 대비 검색 비율: `decide ok` 대비 `ground ok` 비율로 본다(둘 다 위 집계에 나온다).
`ground error`가 연속되면 Engine 판정/근거 경로를 확인한다 — 이제 저널만으로 원인이 보인다.

## 5. 기록 양식

| 시각(UTC) | 요청 수 | 200 | 503 | sources 합계 | 특이사항 |
|---|---|---|---|---|---|
| | | | | | |

## 6. 켠 뒤 24시간 관찰

- [ ] `/api/claw/general` 503 비율 0에 가까움 (a)
- [ ] 5xx 없음: `grep -c '"status":5'`
- [ ] p95 `duration_ms`가 켜기 전과 크게 다르지 않음 (c)
- [ ] `claw_web_search` 집계에서 `ground ok` / `ground error` 비율 기록 ((d) 명령)
- [ ] 최신성 질문 5건 중 sources가 붙은 비율도 함께 기록 (응답 쪽 대조)
