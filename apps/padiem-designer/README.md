# PADIEM Designer — 인터랙티브 UI 미리보기

```text
DOC_STATUS = IMPLEMENTATION_README
SCOPE = apps/padiem-designer/
ISSUE = #5513
UPSTREAM = CopilotKit/OpenIntelligentUI @ 8391a94c1c3939c679e40ddd7bfc08a9ef690e70 (MIT)
AI_PROVIDER_CALLS_IN_THIS_APP = 1 (the configured model route)
CUSTOMER_API_KEY_SCREEN = NONE
INDEPENDENT_LOGIN_AUTHORITY = NONE
PRODUCTION_DEPLOYED = NO
```

사용자 요청을 받아 **실제로 동작하는 인터랙티브 UI**를 만들고, 그 UI를 사용자가
조작한 뒤 **그 조작 결과가 다음 AI 턴에 전달되는 것**까지 보는 앱이다.
CopilotKit/OpenIntelligentUI 의 제너레이티브 UI 계약을 재사용하되, 렌더러를
새로 만들지 않았다.

## 1. 실제로 동작하는 것

```text
자연어 요청
  → 모델이 generateSandboxedUi 도구를 호출
  → 생성된 html / css / jsFunctions / jsExpressions
  → 샌드박스 프레임에서 실제 렌더링
  → 사용자가 입력·클릭
  → 생성된 JS가 값을 계산해 화면에 반영
  → 프레임이 현재 컨트롤 값을 앱에 보고
  → 다음 AI 턴이 그 값을 받아 UI를 수정
```

## 2. 재사용한 것 (upstream 고정 커밋)

| upstream 요소 | 이 앱에서의 재사용 |
|---|---|
| `generateSandboxedUi` 도구 이름 | 그대로 사용 (`app/model_route.py`) |
| 파라미터 순서 `initialHeight`→`placeholderMessages`→`css`→`html`→`jsFunctions`→`jsExpressions` | 그대로 사용 |
| 활동 콘텐츠 채널 이름 | 그대로 사용 (`app/contracts.py`) |
| `assembleStandaloneHtmlFromActivity` 조립 규칙 (css 별도 style 블록, jsFunctions 최상위 classic script, jsExpressions async IIFE, 닫는 태그 가드) | 같은 규칙으로 재구현 (`app/sandbox.py`) |
| 샌드박스 규칙·상호작용 품질 규칙 | 같은 규칙 (`app/designer_prompt.py`) |
| `Websandbox.connection.remote.sendPrompt` 브리지 | 같은 이름으로 두고 이 앱으로 전달 (`app/sandbox.py`) |

자세한 대조표와 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 3. 파일과 실제 책임

| 파일 | 실제 구현 책임 |
|---|---|
| `app/contracts.py` | 생성 UI·턴·상호작용 상태 계약. upstream 채널 이름 |
| `app/config.py` | 환경설정. **키 화면·키 저장소 없음** |
| `app/identity.py` | B62 `padiem_session` 쿠키 재사용, 테넌트 분리, 인증 모드 정직 보고 |
| `app/model_route.py` | 모델 경로 인터페이스 + OpenAI 호환 경로 + B14 경로(툴채널 미구현을 정직하게 보고) |
| `app/designer_prompt.py` | 시스템 프롬프트 (upstream 규약 + PADIEM 추가 규칙) |
| `app/sandbox.py` | 샌드박스 문서 조립 + PADIEM 상호작용 브리지 |
| `app/app_factory.py` | HTTP 표면 (`/`, `/api/designer/{health,turn,sandbox}`) |
| `app/cli.py` | 실행 진입점 |
| `static/` | 미리보기 페이지와 클라이언트 |
| `tests/` | 계약·샌드박스·모델경로·앱·세션 테스트 + 실제 모델/브라우저 E2E |

## 4. 실행

```powershell
$env:PYTHONPATH = "$PWD\packages\padiem-ai-core;$PWD\apps\padiem-designer"
$env:DESIGNER_MODEL_BASE_URL = "<OpenAI 호환 chat-completions origin>"
$env:DESIGNER_MODEL_API_KEY  = "<그 origin의 자격증명>"
$env:DESIGNER_MODEL_ID       = "<모델 id>"
python -m app.cli --host 127.0.0.1 --port 8788
```

`python -m app.cli --print-status` 로 현재 실제로 설정된 값을 확인할 수 있다.
키를 입력하는 화면은 없다. 자격증명은 실행하는 사람이 환경변수로 준다.

## 5. 인증과 테넌트

- 세션 쿠키는 B62 제품이 소유하는 `padiem_session` 그대로 쓰고, **검증도 B62의
  권위 모듈에 위임**한다. 이 앱은 쿠키 형식을 다시 구현하지 않는다.
- 세션 쿠키는 *누구인지*만 증명한다. **테넌트는 서버 설정**(`DESIGNER_TENANT_ID`)
  이다. 세션 쿠키에 테넌트 클레임이 없기 때문이다.
- 세션 시크릿이 설정되어 있으면 세션 쿠키가 없거나 잘못되면 **거부**한다
  (401). 시크릿이 없으면 `dev_configured` 모드로 동작하고 그 사실을
  `/api/designer/health` 가 밝힌다.
- 신규 API 키 화면도, 독립 로그인 권위도 만들지 않았다.

## 6. B14 모델 경로 — 현재 상태

**확인된 사실:** B14 execution contract는 `agent + messages → answer` 구조이고
**툴콜 채널이 없다.** 그래서 `generateSandboxedUi` 계약은 현재 B14로 표현할 수
없다.

이 앱은 그걸 우회하지 않는다.

- `B14Route` 는 B14 실행 계약과 바인딩 프로토콜을 그대로 갖되, 툴채널이 없으면
  `b14_tool_channel_unavailable` 로 **정직하게 보고**한다.
- 로컬 E2E 는 **개발용 모델 경로**(OpenAI 호환)로 돈다. 이 경로와 운영 B14 경로는
  코드에서 분리되어 있고, 어느 경로가 쓰였는지는 매 턴 응답의 `routeKind` 와
  `/api/designer/health` 에 나타난다.
- 운영 B14 툴콜 채널 연동은 별도 후속 이슈다.

## 7. 검증

```bash
python -m pytest apps/padiem-designer/tests -q
```

| 테스트 | 내용 |
|---|---|
| `test_contracts.py` | 요청·결과 계약, upstream 채널 이름과 순서 |
| `test_sandbox.py` | upstream 조립 규칙, 닫는 태그 가드, 브리지, 테마 변수 |
| `test_model_route.py` | 도구 스키마, 생성 UI 변환, html 계약 위반 거부, 라우트 오류, B14 공백 보고 |
| `test_app.py` | HTTP 표면, 상호작용 상태 전달, 툴채널 없는 경로 거부, 인증 거부 |
| `test_identity.py` | B62 세션 권위 재사용, 유효·무효 세션, 개발 모드 |
| `test_designer_e2e.py` | **실제 모델 + 실제 Chromium**. 모델이 UI를 만들고, 사용자가 조작하고, 조작 결과가 다음 턴에 전달되는지 확인 |

`test_designer_e2e.py` 는 모델 경로가 설정되어 있지 않으면 건너뛴다. 그래서
CI 는 결정론적 테스트만 돌리고, 실제 모델·브라우저 증명은 별도 실행에서 나온다.

## 8. 아직 하지 않은 것

- 운영 B14 툴콜 채널 (별도 후속 이슈)
- Production 배포와 정식 URL·메뉴 위치 (대표이 나중에 결정)
- 채팅·Claw·B66 화면과의 통합
- 멀티테넌트 세션 바인딩 (테넌트는 지금 서버 설정)
