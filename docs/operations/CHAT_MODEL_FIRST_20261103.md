# Chat model-first 답변 경로 (#4651, 2026-11-03)

대표 결정: 별도 분류 호출 없이, 답하는 모델에게 질문과 서버가 구성한 도구 목록을
한 번에 준다. 도구 호출이 없으면 그 답을 바로 쓰고, 도구 호출이 있을 때만 기존
P01 PC 실행 경로로 넘긴다.

## 1. 스위치

- 이름: `PADIEM_CHAT_MODEL_FIRST`
- 기본: **off** (`1`, `true`, `on`만 켜짐)
- Worker 바인딩과 CPython host 환경변수를 같은 `binding_value`로 읽는다.
- 꺼져 있으면 `/api/orchestration`은 지금과 같은 엔진 경로를 바이트 단위로 그대로 쓴다.
- host 예시: `deploy/host-com2/chat/.env.example`

## 2. 켜졌을 때의 흐름

1. 기존 `/api/orchestration` 검증·등급·usage gate·conversation·PC 문맥·grounding을
   **먼저 그대로** 통과한다.
2. 서버가 `pc_context["pc_tools"]["allowed_scopes"]`에서 모델에 보일 도구를 고른다.
   쓰기 도구는 이번 발화가 변경을 요청했을 때만 추가한다.
3. 같은 B14 답변 모델에 질문 + 도구 목록을 한 번에 보낸다. 별도 분류 호출은 없다.
4. `tool_call`이 없으면 그 답을 `answer`로 쓰고, 기존 `_save_terminal_history`로
   대화를 저장한다. 엔진 P01은 호출하지 않는다.
5. `tool_call`이 있으면 **서버가 실제로 제안한 도구 이름만** 받아들인다. 그 이름을
   기존 `execute_chat_pc_drive_lane`(P01 PC 실행 경로)에 넘긴다. 소유자·Mesh grant·
   PC target·scope는 그 경로가 다시 확인한다.
6. 모델이 도구를 지원하지 않는 route(예: `google/gemma-` 폴백)이고 PC 도구가 필요한
   turn이면 model-first를 건너뛰고 지금의 엔진 경로로 보낸다.
7. 선택한 PC가 꺼져 있으면 도구는 비우고, `pc_work_context`의 서버 문맥(꺼짐 안내)을
   모델에 함께 준다. "접근 권한이 없다"로 오해하지 않게 하는 문구다.

## 3. 모델 선택 자리

이 경로는 라우트가 이미 해석한 `policy`(등급별 B14 route)를 그대로 쓴다. 새 모델·공급자
선택을 여기서 만들지 않는다. 나중에 별도 "고르는 모델"을 앞에 두려면
`_answer_model_first` 호출 전의 `policy` 지점 하나만 바꾸면 되고, 그 판단을 위한
분류 호출은 이 PR에 없다.

## 4. 바뀌지 않는 것

- 모델·공급자·등급 route: 바꾸지 않는다.
- usage gate: 기존 `UsageGate.authorize`를 먼저 호출한다. 직행 답변도 같은 gate를 쓴다.
- B14 원장/최종 dispatch guard: `/api/chat/stream`과 같은
  `create_guard_from_request`/`apply_guard_to_client`를 통과한다.
- 권한 교집합: 도구 목록은 서버 `pc_context` scope에서만 만들고, 모델이 제안하지 않은
  도구 호출은 403 `model_first_tool_not_allowed`로 거부한다.
- P01 실행 경로: 도구 호출은 기존 Chat PC lane을 그대로 재사용한다. 새 executor나
  target store를 만들지 않는다.
- 스트리밍: 도구 호출 없는 답변은 기존 NDJSON 경로(`PADIEM_CHAT_ORCHESTRATION_STREAM`)로
  `meta`/`delta`/`done`을 흘린다. 화면 전환은 별도 작업이다.

## 5. 시간 기록

`orchestration_timing_com2` 한 줄의 끝에 `path=`가 추가된다.

```text
... total_ms=… path=engine|model_first_direct|model_first_tool retried=unknown
```

- `engine`: 지금의 엔진 경로
- `model_first_direct`: 모델이 바로 답한 경로(엔진 0회)
- `model_first_tool`: 모델이 도구를 골라 P01 경로로 간 경우

본문·질문·답변·subject·쿠키는 넣지 않는다.

## 6. 켜는 순서 (다음 컴2 배포 뒤)

1. 코드가 들어간 Chat/P01을 기존 절차로 배포한다. 이때 스위치는 **비어 있는 상태(off)**.
2. 일반 질문 1회와 PC 질문 1회로 기존 동작과 `path=engine`을 확인한다.
3. Chat host env에 `PADIEM_CHAT_MODEL_FIRST=1`을 넣고 Chat만 재기동한다. P01은
   재기동하지 않아도 된다.
4. 검증:
   - "안녕": `path=model_first_direct`, P01 로그에 새 `engine_timing`이 없어야 한다.
   - PC 파일 요청: `path=model_first_tool`, P01 `engine_timing`/PC lane이 그대로 남는다.
   - 무료 한도 소진: `usage_denied`가 B14/P01 전에 나온다.
   - Gemma 폴백 PC 질문: `path=engine`으로 P01이 실행된다.
   - 선택한 PC 꺼짐: 도구 없이 "꺼져 있음" 안내가 답에 반영된다.
5. 문제 시 env를 비우거나 `0`으로 두고 Chat만 재기동한다. 데이터·스키마·P01 설정
   변경은 없다.

## 7. 시험

- `apps/padiem-chat/tests/test_model_first_4651.py`: off 동일 동작, "안녕" 직행(엔진 0),
  PC tool → 기존 lane, 웹 grounding evidence, usage 거부, 꺼진 PC, Gemma 폴백,
  scope 교집합, 미제안 tool 거부, 쓰기 도구 규칙, guard 재사용, NDJSON.
- 기존 orchestration timing/stream/PC/bridge/tier/identity 시험 전부 통과.
