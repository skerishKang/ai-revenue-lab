# Korean AI Platform (Business 14)

Status: **Interactive frontend MVP (demo)**

여러 AI 모델과 코딩 에이전트를 연결하고 작업·검증·비용·보안·승인 과정을 관리하는
한국형 AI 실행 플랫폼의 사용 흐름을 체험할 수 있는 프런트엔드 중심 MVP입니다.

> AI가 코드를 만드는 데서 끝나지 않도록, 작업·검증·승인까지 관리합니다.

이 버전은 **결정론적 목업**입니다. 실제 AI 제공자, GitHub API, 컨테이너 실행기,
실제 push는 연결되지 않았고 모든 데이터와 모델은 가짜(Demo)입니다.

## 핵심 사용 흐름

1. 프로젝트/저장소를 선택한다.
2. 자연어로 개발 작업을 입력한다.
3. 작업 모델과 검증 모델을 선택한다.
4. 수정 허용 경로와 금지 경로를 지정한다.
5. 작업 AI가 계획과 구현 결과를 만든다.
6. 검증 AI가 변경 파일, diff, 테스트 결과를 검토한다.
7. 사용자가 승인하거나 재작업을 요청한다.
8. **승인된 경우에만** 데모 브랜치·커밋 반영 단계로 이동한다.

## 제품 차별점 (UI에 반영)

- 작업자 AI와 검증자 AI 분리
- AI 완료 보고를 그대로 신뢰하지 않고 실제 diff·테스트 증거와 대조
- 허용/금지 경로 강제 및 위반 경고
- 사람 승인 전 반영 차단
- 비용·토큰·데이터 처리 위치 공개
- 외부 고급 모델과 국내·자체 호스팅 모델을 함께 선택 가능

## 상태 전이

```text
ready → running → awaiting_approval → completed   (승인)
                                    → rework → running …  (재작업)
                                    → rejected           (거절)
```

승인 전에는 `commit_sha`/`branch_name`이 생성되지 않습니다.

### 승인 결과 (브랜치 모드)

- **AUTO**: 승인 시 데모 `branch_name`과 `commit_sha`가 생성됩니다.
- **MANUAL**: 승인 상태·승인자·완료 시각은 기록하지만 `branch_name`/`commit_sha`는
  `None`으로 유지됩니다. 완료 화면에는 "승인 완료 · 수동 반영 대기"가 표시되고
  존재하지 않는 SHA/branch의 복사 버튼은 렌더링되지 않습니다.

### 승인 차단 (거버넌스)

- 검증자 판단이 **REJECT**(수정 금지 경로 위반 시 부여)이면 승인할 수 없습니다.
  승인 시도 시 오류 메시지와 함께 상태·승인자·완료 시각·branch·commit이 변경되지 않으며,
  재작업 또는 거절만 선택할 수 있습니다. REJECT 화면에는 승인 버튼이 표시되지 않습니다.
- **CAUTION**(허용 외 경로, 비용 초과, 외부 처리 경고)은 사람이 증거를 확인하고 승인할 수
  있으며, 관련 경고는 승인 화면에 계속 표시됩니다.

## 로컬 실행

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
python -m pip install -e '.[dev]'
uvicorn app.main:app --host 127.0.0.1 --port 8014
```

브라우저에서 `http://127.0.0.1:8014` 접속.

## 테스트

```bash
python -m pytest -q
```

## 보안·데이터 처리

### 실제로 집행되는 정책

- **승인 없는 push 차단(필수, 읽기 전용)**: 사람 승인 전 브랜치·커밋 생성 차단은 항상
  적용되며 설정으로 해제할 수 없습니다. POST로 false를 보내도 승인 게이트는 약화되지 않습니다.
- **외부 모델 전송 허용**: 끄면 해외 처리 모델(자체 호스팅/국내 아님)로 작업 생성이 차단됩니다.
- **프로젝트 기본 비용 한도**: 작업 생성 시 비용 한도를 비워두면 이 전역 기본값이 적용됩니다
  (명시적 `0`은 제한 없음). 설정 값이 음수·NaN·Infinity·비숫자이면 저장 전체가 거부됩니다(원자적).
- **REJECT/금지 경로 위반 승인 차단**, **조작된 enum 입력 거부**(500 없이 폼 오류).

### Demo 표시 전용 (실제 통제 아님)

- **민감정보 발견 시 차단**: 실제 secret scanner가 연결되지 않은 정책 미리보기입니다.
  실제 차단 기능이 아니며 외부 서비스도 추가하지 않았습니다.

### BYOK API 키 처리

- 입력한 API 키는 **외부 AI provider로 전송하지 않고**, 서버의 DB·파일·환경변수·로그에
  **영속 저장하지 않습니다**. 현재 요청에서 입력 존재 여부만 확인한 뒤 원문 값은 즉시
  폐기하며, 화면과 응답에 raw key를 다시 출력하지 않습니다.
- 브라우저에서 앱 서버로는 폼 전송되므로, 실제 운영에서는 HTTPS·비밀 저장소 연동이 필요합니다.
- 키 입력을 비워 둔 채 저장하면 기존 등록 상태가 유지되며, 등록 해제는 명시적 체크박스로만 수행됩니다.
- 비밀 값은 코드·픽스처·로그에 포함되지 않습니다.

## 영속 저장 (Persistence)

- Business 14는 자체 **product-local SQLite DB**를 소유합니다. 다른 Business 또는
  portal DB와 분리되며, 다른 Business DB를 직접 조회하지 않습니다.
- 기본 backend·경로: `KAP_DB_BACKEND=sqlite`, `KAP_DATABASE_PATH=var/korean-ai-platform.db`
  (Business 14 workspace 기준 상대 경로).
- migration은 앱 startup(lifespan)에 deterministic·forward-only로 실행됩니다.
  자세한 계약은 `docs/PERSISTENCE_CONTRACT.md` 참조.
- 서버를 재시작해도 작업·실행 evidence·승인/거절/재작업·설정·BYOK 등록 상태가 복구됩니다.
- 테스트에서는 `create_app(store=...)`로 인메모리 Store를 주입하거나,
  `create_app(db_path=...)`로 임시 SQLite를 주입할 수 있습니다.
- raw BYOK key는 저장하지 않습니다(등록 여부 boolean만 저장).
- **단일 프로세스 제한**: SQLite 단일 파일·단일 프로세스 전제입니다. 멀티프로세스
  워커, 백업·복원·암호화, production migration 실행은 미구현입니다.
- **PostgreSQL 미구현**: `KAP_DB_BACKEND=postgresql`은 SQLite로 fallback하지 않고
  고정된 설정 오류로 실패합니다(fail closed).
- DB 파일을 삭제하면 로컬 상태가 초기화됩니다.

## 기술 스택

저장소 관례를 그대로 따릅니다: FastAPI + Jinja2 + vanilla JS/CSS, pytest + httpx.
신규 프레임워크나 대규모 의존성을 추가하지 않았습니다.

## 현재 한계

의도적으로 미구현된 항목과 그 위험 범위입니다. 1차 단일 사용자 데모 범위이며,
실제 배포 전에는 아래 항목을 반드시 보완해야 합니다.

- 실제 모델·Git·실행기·GitHub 미연결 (의도된 데모 범위). 모든 모델·commit·branch는 Demo 값입니다.
- **CSRF 방어 미구현**: 상태 변경 POST(생성·실행·승인·재작업·거절·설정)에 CSRF 토큰이 없습니다.
  단일 사용자 로컬 데모 전제이며, 실제 배포 시 필수 보완이 필요합니다.
- **인증·사용자 분리 미구현**: 누구나 모든 작업과 설정에 접근할 수 있습니다.
- **단일 프로세스 SQLite**: product-local SQLite 단일 파일·단일 프로세스 전제입니다.
  멀티프로세스 워커를 늘리면 상태가 일치하지 않습니다. 백업·복원·암호화 미구현.
- **PostgreSQL runtime 미구현**: 선택 시 fail closed. production 배포·마이그레이션 미구현.
- 모바일에서는 상태 확인 중심으로 동작합니다.

## 입력 검증 notes

- 허용/금지 경로는 정규화(역슬래시·`../`·중복 슬래시·`./`·드라이브 문자·후행 와일드카드 처리) 후
  세그먼트 경계로 비교합니다. `apps/example`은 `apps/example-evil`과 일치하지 않습니다.
- 비용 한도는 0 이상의 유한한 숫자만 허용하며, 음수·NaN·Infinity·비숫자는 거부됩니다.
- 모든 사용자 입력(작업 지시, 재작업 사유 등)은 Jinja2 autoescape로 이스케이프됩니다.
