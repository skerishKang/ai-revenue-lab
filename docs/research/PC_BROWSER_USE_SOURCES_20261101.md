# 연결 PC 브라우저·컴퓨터 사용 — 자료 조사와 추천 조합 (#3782, 2026-11-01)

```text
SCOPE=PC_BROWSER_USE_LANE_ONLY
TARGET=WEB_MODEL -> CONNECTED_PC_KAGENT -> DEDICATED_WORK_PROFILE
DESKTOP_EMBEDDED_BROWSER=OUT_OF_SCOPE_THIS_DOC  (#3829/#3843 decision retained)
SOURCE_CHANGE_THIS_STEP=DOC_ONLY
```

## 1. 읽은 자료

| 자료 | 확인한 내용 |
|---|---|
| #4935 X 링크 모음 | 브라우저·PC 조작 후보 5건(Browser Use, Drex Browser Harness, Kimi Work, Grok Bot/Paseo, Agent-Reach) |
| #4956 YouTube 모음 | n8n 자동화 등 사용자 자동화 사례. 브라우저 조작 구현체는 없음 |
| #2996 기술레이더 | 74개 저장소 1차 조사. 브라우저/컴퓨터 사용 후보 표와 LOCAL1 source-pinned 감사(댓글) 포함 |
| #6537 / #6545 | #6460 연결 재사용 후보 Top 10과 2차 조사(라이선스 74건 실제 조회) |
| `docs/research/REUSE_CANDIDATES_20261101.md` | 위 이슈들의 표·한계 정리본 |
| `docs/architecture/PADIEM_BROWSER_EXECUTION_ADAPTER_DECISION_3782.md` | 2026-10-09 이미 확정된 브라우저 실행 결정(Desktop Electron/CDP 유지, Playwright MCP는 옵션 파일럿 후보) |
| #2996 댓글 LOCAL1 감사 | 후보별 정확한 태그·SHA·egress·라이선스 실측(2026-10-09) |

## 2. 브라우저·컴퓨터 사용 후보 (원문 확인분)

라이선스는 2026-11-01 GitHub LICENSE API로 다시 조회했다. "방식"은 코드를 가져오지 않고 설계만 참고한다는 뜻이다.

| 이름 | 무엇을 하는지 | 라이선스 | 우리 구조 적합성 | 가져올 부분 |
|---|---|---|---|---|
| **Playwright MCP** (`microsoft/playwright-mcp`) | MCP 서버로 브라우저를 조작. navigate/snapshot/click/type/screenshot 도구 제공 | Apache-2.0 | **높음**. AI 계층·모델 라우터가 없고 호스트가 도구를 고른다. 이 저장소에서 Windows 3/3 PASS(중앙값 2,610ms), `@playwright/mcp@0.0.83` 고정 기록 존재 | 코드 의존성(MCP stdio 클라이언트로 호출) + 도구 4개만 사설 매핑 |
| **Playwright** (`microsoft/playwright`) | 브라우저 자동화 프레임워크 본체 | Apache-2.0 | 높음(Python/Node SDK). 다만 브라우저 바이너리·의존성 부담 | 직접 사용은 MCP 경유로 대체 |
| **Browser Use** (`browser-use/browser-use`) | 자체 에이전트 루프를 가진 Python 브라우저 에이전트 | MIT | **낮음**. 기본값이 벤더 호스팅 모델(`ChatBrowserUse`)로 떨어져 B14 단일 모델 라우터 권한과 충돌. 텔레메트리 기본 ON(`config.py:59`, `:63`, `:201`) | 에이전트 루프·행동 어휘·관찰 축약 **방식만** |
| **Stagehand v4** (`browserbase/stagehand`) | act/observe/extract AI 브라우저 SDK | MIT | 낮음. AI 계획 계층이 하나 더 생김. Node 요구 `>=22.18.0` | locator 결정성 패턴만 참고 |
| **Drex Browser Harness** (`nace-ai/drex-browser-harness-pub`) | 소규모 CDP/MCP 하네스 | MIT | 중간. 규모가 작아 참고용 | CDP 연결·수명 관리 방식 |
| **Browser Use Web UI** (`browser-use/web-ui`) | 브라우저 에이전트 웹 UI | MIT | 낮음(우리 UI는 Claw가 소유) | 진행 표시 UI 참고 |
| **amontlabs/lcu** | Codex computer use를 앱에서 분리한 하네스 | MIT | 중간. Windows 11 x64 후보 단계, 실측 없음 | OS 수준 컴퓨터 사용 방식(이번 범위 밖) |
| **Agent-Reach** (`Panniantong/Agent-Reach`) | CLI로 X/Reddit/YouTube/GitHub 등 읽기·검색, API 키 불필요 | MIT | 중간. 읽기 전용 수집에는 유용, 조작은 없음 | 사이트별 읽기 어댑터 방식 |
| **wigolo** (`KnockOutEZ/wigolo`) | 로컬 검색·fetch·crawl MCP | NOASSERTION(라이선스 파일 판독 불가) | 낮음 | **방식만** (라이선스 불명) |
| **Lightpanda** (`lightpanda-io/browser`) | AI용 headless 브라우저 엔진 | AGPL-3.0 | 낮음 | **방식만**. 코드·바이너리 반입 금지 |
| **Paseo** (`getpaseo/paseo`) | 데스크톱/모바일에서 코딩 에이전트 오케스트레이션, 로컬 브라우저 브리지 언급 | NOASSERTION | 낮음 | **방식만** |
| **tarsier** (`reworkd/tarsier`) | 스크린샷에 요소 라벨을 그려 모델이 읽게 하는 비전 유틸 | MIT | 높음(작음) | 캡처→라벨 좌표 방식 |
| **Steel Browser** (`steel-dev/steel-browser`) | 브라우저 샌드박스 API 서버 | Apache-2.0 | 낮음. 별도 서버 운영 부담 | 세션 격리 방식만 |
| **Qwen Code Browser Use** | Chrome 확장 아키텍처 | 문서 | 낮음. 공식 지원 macOS/Linux | 방식만 |

기존 저장소 결정과 중복되지 않게 정리하면 다음과 같다.

```text
DESKTOP_EMBEDDED_BROWSER=RETAIN_ELECTRON_CDP        (#3843 유지, 이 문서가 바꾸지 않음)
PC_LANE_EXECUTION_BACKEND=PLAYWRIGHT_MCP_0_0_83
PC_LANE_AI_AGENT_LOOP=BUILD_NONE                    (B14만 모델 선택)
BROWSER_USE=REFERENCE_ONLY
LIGHTPANDA_AGPL=REFERENCE_ONLY
WIGOLO_PASEO_NOASSERTION=REFERENCE_ONLY
```

## 3. 라이선스 처리

MIT·Apache-2.0·BSD·ISC는 고지 후 코드 의존성으로 사용한다. MPL은 파일 단위, GPL·AGPL·SSPL·BSL·무라이선스(NOASSERTION)는 방식만 참고하고 코드·바이너리를 반입하지 않는다.

이번 조합에서 코드로 들어오는 것은 **Playwright MCP(Apache-2.0)** 하나다. 고지는 `apps/padiem-chat/static/third-party-licenses.html`과 `apps/korean-ai-code-agent/THIRD_PARTY_NOTICES.md`에 추가한다.

## 4. 추천 조합 (1개)

```text
BACKEND=@playwright/mcp@0.0.83 (Apache-2.0) — kagent가 stdio 자식 프로세스로만 기동
MODEL_LAYER=NONE — B14가 유일한 모델 라우터, 브라우저 쪽에 별도 LLM 없음
TOOLS=claw.pc.browser_open / browser_read / browser_screenshot / browser_act
PROFILE=전용 작업 프로필(--user-data-dir), 대표 Chrome 프로필 미사용
OUTPUT=본문·링크는 8KB까지만 인라인, 초과분은 handle로 보관 후 구간 읽기
CONFIRM=로그인·결제·게시·발송·제출은 실행하지 않고 확인 질문 반환
FORBIDDEN=cookie/password/localStorage 반환, javascript_evaluate, 일반 MCP 카탈로그 노출
```

선정 이유:

- 이미 이 저장소에서 Windows 실측(3/3 PASS)과 버전 고정 근거가 있는 유일한 후보입니다.
- AI 계층이 없어 B14 단일 모델 라우터 원칙을 깨지 않습니다.
- kagent의 Python 의존성 0개 프로필을 유지합니다(Node는 실행 전제조건이며, 없으면 명확히 실패).
- Browser Use는 기본 텔레메트리와 벤더 모델 폴백 때문에 코드 반입 시 권한 경계가 흐려집니다.

## 5. 확인된 제약

```text
VERIFIED_NOW=LICENSE_API / 저장소 설명 / #3843 기존 Windows 실측 인용
NOT_VERIFIED=@playwright/mcp 0.0.83의 Windows 재실측, 전이 의존성 전체 라이선스, 실제 공개 사이트 장기 안정성
UNSUPPORTED_IN_SLICE=CSS 선택자 직접 지정(스냅샷 텍스트/역할 기반 해석으로 대체), 다중 탭, 파일 업로드·다운로드
```

## 6. 다음 단계

1단계에서 위 도구 4개를 kagent에 구현하고, Engine 공통 단계(`ActionGuardedPCQueryStepDriver`)·MCP 게이트웨이·`pc_work_metrics`에 등록한다. 로그인·결제·게시·발송 확인 질문과 큰 페이지 보관 핸들을 시험으로 고정한다.