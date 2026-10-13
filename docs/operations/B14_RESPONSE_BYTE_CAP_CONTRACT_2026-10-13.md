# B14 응답 바이트 캡 계약 (2026-10-13, #4552 / #4379)

```text
DOC_SCOPE = B14 gateway response byte limits only
DEFAULT_1MIB_CHANGED = NO
PRODUCTION_CHANGED = NO
LIVE_PROVIDER_CALLS = 0
STATUS = SOURCE_MEASURED / NOT_DEPLOYED
```

기본값 1MiB는 그대로 유지한다. 이 노트의 목적은 "설정값과 실제 제한이 다르다"는 것을
코드의 실효 경로로 특정하고, 제한을 실제로 올리려면 무엇이 필요한지 승인 대기 상태로
남기는 것이다.

## 1. 실효 응답 제한 (main `dc8f8ee` 기준, 소스 측정)

| 경로 | 소스 위치 | 실효 제한 | 초과 시 |
|---|---|---|---|
| 일반 completed JSON | `platform.py:418` → `_read_bounded_body` (`:289`) | `platform.MAX_RESPONSE_BYTES` = 1,048,576 B | `upstream_response_too_large` |
| 일반 completed 상위 오류 본문 | `platform.py:401` (같은 헬퍼) | 1,048,576 B | `upstream_response_too_large` (상태 매핑보다 먼저) |
| OpenCode Go completed | `opencode_go_wire.py:222` (같은 헬퍼) | 1,048,576 B | `upstream_response_too_large` |
| Go completed 오류 본문 | `opencode_go_wire.py:220` — 본문 읽지 않고 상태 코드만 매핑 | 0 B (벤더 본문 미수집) | 상태 코드 매핑 오류 |
| legacy BYOK completed | `provider.py:192` (같은 헬퍼) | 1,048,576 B | `upstream_response_too_large` |
| BYOK completed 오류 본문 | `provider.py:181-189` — 상태 코드만 | 0 B | 상태 코드 매핑 오류 |
| 일반 SSE 미완성 tail | `platform.py:605` | 1,048,576 B | `upstream_response_too_large` |
| 일반 SSE 완성 frame 1개 | `platform.py:608` | 1,048,576 B | `upstream_response_too_large` |
| 일반 SSE 생성 총량 | 없음 (설계상) | 제한 없음 | — |
| 일반 SSE 상위 오류 본문 | `platform.py:582` `await response.aread()` | **바이트 캡 없음** | 상태 코드 매핑 오류 (F-2) |
| Go SSE 읽기 블록 + tail | `opencode_go_wire.py:337` | 1,048,576 B | `upstream_response_too_large` (F-3) |
| Go SSE 생성 총량 | 없음 (설계상) | 제한 없음 | — |

세 개의 실효 축(generic completed / generic SSE / Go SSE)은 모두 같은 정수
`platform.MAX_RESPONSE_BYTES`를 읽는다. 실효 제한의 단일 출처는 `b14_runtime_config`가
아니라 `platform` 모듈 상수다.

## 2. `b14_runtime_config.max_response_bytes` 계약

- 생산자: `app/pilot/b14_runtime_config.py:23` 하드 리터럴. 이 파일이 읽는 환경 변수는
  `B14_PROVIDER_MODE` 하나뿐이다. secret·env·중앙 관리자·운영자 입력 중 이 필드에
  연결된 것은 측정 결과 없음.
- 소비자: 앱 소스 내 없음. 실제 소비되는 것은 `provider_mode` / `is_live` / `is_mock` /
  `build_http_timeout()` 뿐이고, 이 필드는 `redacted_summary()` 표시와 테스트 4곳의
  save/restore에서만 읽힌다.
- 결론: `CONFIG_FIELD_EFFECTIVE = NO`. 필드를 64MiB로 바꿔도 completed와 SSE 어느 축의
  제한도 움직이지 않는다.
- 따라서 이 필드는 "모델 응답 용량 설정"이 아니다. 표시 문자열에
  `max_response_bytes_effect=no` 토큰을 붙여 로그를 읽는 운영자가 오해하지 않게 했다.
- 죽은 제한 상수도 함께 기록한다. `platform.MAX_ERROR_BODY_CHARS = 500` (`platform.py:62`)
  는 소비자가 없고, `UpstreamResponseTooLarge`의 기본값 1MiB (`errors.py:177`) 는 모든
  raise 지점에서 명시 인자를 넘기기 때문에 실제로 쓰이지 않는다.

## 3. 오류 코드 동작

- `UpstreamResponseTooLarge` → `code=upstream_response_too_large`, HTTP 502, 메시지에
  바이트 수 표기 (`errors.py:174-183`).
- 재시도·폴백 없음. 어댑터는 정확히 1회 POST (`transport.calls == 1` 핀), gateway는 이
  코드를 폴백 불가로 분류한다 (`test_alpha1.py`의
  `is_error_fallback_allowed("upstream_response_too_large") is False`).
- 잘림 없음. 캡과 똑같은 크기의 본문은 통째로 반환된다
  (`test_helper_exact_cap_boundary_returned_verbatim`), 캡+1은 명시 오류.

## 4. 이번 감사에서 측정된 결함 3건 (모두 미수정, 승인 대기)

**F-1 — completed 응답 메타데이터가 스트리밍 본문에서 예외.**
`platform.py:472`의 `len(response.content)`은 #4547이 `client.post`(자동 read)를
`client.stream` + 수동 수집기로 바꾸기 전에는 유효했다. httpx는 `aread()`를 호출한
응답에만 `.content`를 채우고 `aiter_bytes()`는 채우지 않는다. 그래서 본문 수집이 성공한
뒤에도 이 줄이 `httpx.ResponseNotRead`을 낸다. 기존 fixture가 `content=`로 완성 바이트를
httpx에 넘겨 `_content`가 이미 있던 탓에 CI에서 숨었다. Go는 `len(raw)`
(`opencode_go_wire.py:233`)를 쓰므로 안전하고, BYOK는 `.content`를 읽지 않는다. 한 단어
수정(`len(body_bytes)`)은 live completed 응답을 바꾸므로 이 PR에서는 테스트로만 고정했다.

**F-2 — 일반 SSE의 상위 오류 본문에는 바이트 캡이 없다.**
`platform.py:582`의 `await response.aread()`에는 인자도 대조도 없다. 측정: 500 +
3,145,730B 본문이 전부 소비되고 `UpstreamServerError`가 났다. 같은 본문은 completed 경로에서
`upstream_response_too_large`로 먼저 잡힌다. 여기를 맞추면 메모리 보호는 강해지지만 어떤
오류가 나는지가 바뀌므로 별도 승인 사항이다. 이 관측은 Worker 총 메모리 상한을 증명하지
않는다.

**F-3 — Go SSE와 일반 SSE가 같은 스트림에서 다른 판정을 낸다.**
Go는 frame을 분리하기 전 버퍼를 검사하고 (`opencode_go_wire.py:337`), 일반은 분리한 뒤
남은 tail과 frame 하나를 검사한다 (`platform.py:605`, `:608`). 측정: 개별 967B 정상 frame
1,087개를 한 읽기 블록 1,051,143B로 전달하면 Go는 `upstream_response_too_large(1048576)`,
일반은 1,088 이벤트가 그대로 스트림된다. 같은 스트림인데 판정이 반대다. 실제 네트워크에서
한 읽기에 1MiB 이상이 묶여 도착할 수 있으므로 합성 상태가 아니다. Go를 일반 순서로 맞추면
#4539/#4416으로 병합된 보호가 완화되는 것이므로 승인 필요하다.

## 5. 바이트 가드와 모델 토큰 한도는 다른 축이다

- `MAX_RESPONSE_BYTES`는 수집 바이트 수를 막는 자원 가드다. 모델·토큰 한도가 아니고
  벤더 용량에 대한 주장도 아니다.
- 요청측: gateway는 `max_tokens`를 양의 정수 또는 null로 받고 자체 상수를 만들지 않는다
  (`gateway.py:246-253`). `registry_v2.max_output_tokens` (`registry_v2.py:169`)는 선언
  메타데이터이며 응답 경로에서 강제되지 않는다.
- 결과: 1MiB 바이트를 넘는 정상 응답은 프로바이더가 충분히 생성 가능해도 거부될 수 있다.
  이는 정책이지 모델 사실이 아니다.

## 6. 단계적 바운드 캡 제안 (승인 전 미적용)

1. **S0 (이 PR)** — 제한 변경 없음. 실효 출처·표시 계약·회귀 핀만 정합화.
2. **S1** — F-1 메타데이터 수정을 승인한다. 이후 필드를 실제 노브로 만들려면 기본 인자가
   아니라 호출 시점에 값을 전달해야 한다. 측정: `cap` 기본 인자를
   `runtime_config.max_response_bytes`로 바꾸면 import 시점에 1MiB가 고정되어 런타임
   변경이 반영되지 않는 가짜 노브가 되고, 현재 테스트는 그 배선을 잡지 못한다. 호출 시점
   배선에만 새 테스트가 반응한다.
3. **S2** — 제품/경로 allowlist + 상한. 허용된 product ID만 1MiB 초과를 요청하게 하고,
   상한은 실제로 측정된 Worker 메모리 예산에서 유도한다(추정 8MiB 불가). per-product
   override, toggle default-off, 단계별 rollout.
4. **S3** — SSE 축 정합화. completed / SSE / error-body의 캡 지점을 한 계약으로 모으고
   F-2·F-3을 같은 규칙으로 정리한다. 각 단계는 별도 자원 증거와 승인을 요구한다.
- 압축·디코딩 위험: 캡은 헬퍼가 수집하는 디코딩 바이트를 세고, HTTP 클라이언트는 청크를
  헬퍼에 넘기기 전에 디코딩할 수 있다. 따라서 캡은 누적량을 제한하지 클라이언트 내부
  peak를 증명하지는 않는다. 상한을 올리려면 실제 content-encoding 환경 측정이 먼저다.
- 이 제안에는 무제한 할당, 가드 제거, 벤더 marketed 토큰수를 근거로 한 상한이 없다.

## 7. 재현

```text
python -m venv <venv>            # repo 밖 권장
pip install -e apps/korean-ai-platform pytest pytest-asyncio
cd apps/korean-ai-platform
python -m pytest -q tests/test_b14_completed_response_bounds.py
```

프로바이더 호출 없음. 모든 outbound은 합성 transport이고, Go 모델 OFF·ZansLab 미접촉·
운영 배포 없음은 기존 핀과 동일하게 유지된다.
