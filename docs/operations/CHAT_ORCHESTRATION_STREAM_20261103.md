# 러브트리 Chat 일반 답변 스트리밍 — 서버·앞단 (2026-11-03, 2단계)

1단계(`perf/chat-latency-step1-261103`)는 구간 시간·상태 확인 캐시·앞단 기본값만 다뤘다.
이 단계는 일반 답변을 **엔진 토큰이 오는 대로** 흘려보내는 서버·앞단 경로를 추가한다.
브라우저 전환은 다음 단계다(`static/app.js`는 이번에 건드리지 않았다).

## 1. 켜는 방법
- 서버 스위치: `PADIEM_CHAT_ORCHESTRATION_STREAM` (기본 **off**). Worker 바인딩과 local host 환경변수를
  같은 `binding_value`로 읽는다. `1`·`true`·`on`만 켜짐으로 본다.
- 요청 조건: 본문 `{"stream": 1}` 또는 헤더 `Accept: application/x-ndjson`.
- 꺼져 있거나 요청에 스트림 표시가 없으면 기존 JSON 응답을 **바이트 단위로 그대로** 만든다.
  (`/api/orchestration`의 라우트·게이트·정책 코드는 동일하고, 응답 생성만 분기한다.)

## 2. 줄 형식 (한 줄에 JSON 하나, UTF-8, `application/x-ndjson`)
```
{"type":"meta","stream":true}
{"type":"delta","text":"…"}          ← 1개 이상
{"type":"done","done":true,"conversation_id":"…","message_id":"…","usage":null,"notice":"…","evidence":[…],"tool":{…}}
{"type":"error","code":"…"}          ← 실패 시 1개
```
- `done`은 정확히 1회. `usage`는 지금 Engine 공개 투영이 토큰 사용량을 넘기지 않아 `null`이다.
- `error` 코드는 닫힌 어휘(`invalid_engine_stream`, `engine_execution_failed`)만 나간다.
  엔진 본문·제공자 메시지·사용자 식별자는 줄에 넣지 않는다.
- 헤더: `Cache-Control: no-store`, `X-Accel-Buffering: no`.

## 3. 엔진 스트림과 대체 동작
- 일반 답변도 `B62EngineOrchestrationBridge.start_stream`(NDJSON)을 쓴다. 지금까지는 PC 레인만 썼다.
- 첫 delta **전에** 스트림을 받지 못하면(엔진 미지원·계약 위반) 같은 요청을 완성 응답(`bridge.start`)으로
  한 번 더 보내 한 덩어리 delta로 대체한다. 중복 답변을 만들지 않는다.
- 첫 delta **후** 실패하면 다시 보내지 않고 `{"type":"error","code":"invalid_engine_stream"}`로 끝낸다.

## 4. 저장 정책
- 검증된 완료 결과에서만, `done` 직전에 한 번 저장한다(`_save_terminal_history`).
- 스트림이 중간에 끊기면(브라우저 절단·엔진 중단) **저장하지 않는다.** 부분 저장도 하지 않는다.
  지금 JSON 경로가 실패하면 저장하지 않는 것과 같은 정책이다.

## 5. 시간 기록
`orchestration_timing_com2` 한 줄에 1단계 8개 구간에 `first_token_ms`가 추가된다.
첫 delta까지의 시간이며, 스트림이 없으면 `-1`이다. 로그에는 단계 이름과 ms만 남는다.

## 6. 앞단(worker.mjs)
- 오케스트레이션 응답이 `application/x-ndjson`이면 본문을 읽지 않고 그대로 흘린다.
  `content-type` 유지, `cache-control: no-store`로 덮어쓴다.
- 60초 마감은 **첫 바이트까지**다. 헤더가 오면 타이머를 지우므로 스트림은 마감 없이 흐른다.
- JSON 응답 경로는 1단계와 동일하다.

## 7. 브라우저
`static/chat-transport.js`에 `requestOrchestrationStream`·`readOrchestrationNdjson`만 추가했다.
`static/app.js`는 호출하지 않으므로 지금 화면 동작은 바뀌지 않는다.

## 8. 다음 단계(브라우저 전환·플래그 켜기)에 필요한 것
1. `app.js`의 `requestStreamingAnswer`에서 `requestOrchestrationStream`을 먼저 시도하고 `null`이면 기존 경로로
   폴백한다. delta를 문단에 이어 쓰고 `done`에서 `applyStreamDone`과 같은 커밋을 수행한다.
2. PC 레인(`/api/orchestration` SSE)과 일반 NDJSON이 같은 함수에 섞이지 않도록 응답 타입으로 분기한다.
3. 진행 표시를 "준비 중"에서 첫 delta 시점에 "생성 중"으로 바꾼다(1단계의 경과 시계 유지).
4. 플래그를 켜기 전에 `/api/orchestration`의 NDJSON 경로에 대한 운영 관측(첫 토큰 시간·끊김 비율)을
   1주일 모은다. 끊김 시 저장 정책이 지금과 같으므로 재시도 UI는 기존 것을 그대로 쓴다.
5. 앞단 캐시: NDJSON 응답은 `no-store`이므로 CDN 캐시 규칙 변경이 필요 없다.
