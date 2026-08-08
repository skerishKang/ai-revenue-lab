# 외부 개발 프로젝트 운영 정책

## 목적

AI Revenue Lab 내부 저장소와 외부 개발 저장소의 경계를 명확히 하여, AI 모델이나 작업자가 외부 프로젝트를 내부 `apps/` 또는 `reference/`에 다시 만들거나 중복 구현하는 일을 방지한다.

이 문서는 외부 개발 프로젝트를 **목록과 연결 정보로만 관리**하기 위한 운영 기준이다.

## 핵심 규칙

### 1. 번호가 없는 프로젝트는 외부 개발 프로젝트로 취급한다

Business 번호가 부여되지 않은 프로젝트는 기본적으로 **외부 개발 프로젝트**다.

AI Revenue Lab 저장소에서는 해당 프로젝트를 위해 다음을 만들지 않는다.

- `apps/<project>/`
- `reference/business-*/`
- 빈 scaffold 폴더
- UI/UX placeholder 폴더
- backend/API/Auth/DB placeholder
- 배포 설정이나 CI 설정

내부 저장소에는 프로젝트 이름, 외부 저장소, 현재 상태, 필요한 경우 관련 메모만 목록으로 남긴다.

번호가 없다는 사실만으로 새 Business 번호를 임의 부여해서도 안 된다.

### 2. 외부에서 개발 중인 기존 프로젝트는 내부에 복제하지 않는다

외부 저장소가 실제 구현 원본인 프로젝트는 AI Revenue Lab 안에 같은 이름의 구현 폴더나 관리용 anchor 폴더를 만들지 않는다.

내부에 빈 폴더나 README만 존재해도 다음 모델이 그것을 미완성 내부 Business로 오해하고 UI, UX, backend를 새로 구현할 수 있으므로 금지한다.

외부 프로젝트 작업이 필요하면 해당 외부 저장소로 이동하여 그 저장소의 운영문서와 source of truth를 먼저 읽고 작업한다.

### 3. 포트폴리오 번호가 표시되어도 `existing-project` 외부 원본은 외부에 둘 수 있다

Portfolio Console에 관리 목적의 번호가 표시되어 있더라도, `numberAuthority = existing-project`이고 실제 구현 원본이 별도 저장소라면 **번호만으로 내부 `apps/` workspace를 만들지 않는다.**

명시적인 source migration 승인 전까지 manifest의 workspace/source 표시는 외부 구현 저장소를 가리키는 것이 맞다.

현재 이 규칙이 적용되는 외부 구현 프로젝트:

| Portfolio 표시 | 프로젝트 | 외부 구현 저장소 | AI Revenue Lab 내부 구현 폴더 |
|---|---|---|---|
| B23 | LoveBud / 러브버드 | `skerishKang/LoveBud` | 만들지 않음 |
| B24 | LoveTree 3.0 / 러브트리 3.0 | `skerishKang/lovetree3.0` | 만들지 않음 |
| B25 | Love Matchmaking / 공명·서사 매칭 | `skerishKang/401-love-match-making` | 만들지 않음 |

위 프로젝트는 목록과 외부 연결만 유지한다. 실제 UI/UX 또는 제품 구현은 각 외부 저장소에서 수행한다.

## 외부 개발 프로젝트 목록 운영

번호 없는 외부 프로젝트는 이 문서 또는 후속 전용 registry 문서의 표에 **행만 추가**한다.

권장 필드:

| 프로젝트명 | 외부 저장소 | 번호 | 상태 | 비고 |
|---|---|---|---|---|
| 예시 | `owner/repository` | 없음 | external-development | 내부 폴더 생성 금지 |

목록 등록은 구현 권한 부여가 아니다.

## AI 작업자 실행 규칙

AI 모델이나 작업자는 외부 개발 프로젝트를 발견했을 때 다음 순서를 따른다.

1. AI Revenue Lab 내부에 동일 프로젝트 폴더가 없다고 해서 새 폴더를 만들지 않는다.
2. 번호가 없으면 `external-development`로 간주하고 외부 저장소 연결 여부를 확인한다.
3. 외부 저장소가 있으면 그 저장소를 source of truth로 사용한다.
4. UI/UX 개선 요청도 실제 외부 저장소에서 수행한다.
5. AI Revenue Lab에는 상태 또는 링크만 기록한다.
6. 사용자의 명시적 "내부로 이전" 결정 없이는 코드, UI, 문서 anchor, backend scaffold를 복제하지 않는다.

## 내부 이전이 허용되는 유일한 경우

외부 프로젝트를 AI Revenue Lab 내부 구현으로 옮기는 것은 사용자가 명시적으로 source migration을 승인한 경우에만 가능하다.

이때는 별도 Issue/PR에서 다음을 먼저 확정한다.

- 이전 대상 프로젝트와 정확한 외부 source revision
- 새 내부 Business 번호 또는 기존 번호의 권한 변경 여부
- 구현 원본의 최종 위치
- 기존 외부 저장소의 read-only/archived/continued 역할
- 배포·CI·Auth·DB·비밀값 경계
- 중복 개발 금지 시점

승인 전에는 이동하지 않는다.

## 금지되는 해석

다음 해석은 금지한다.

- "Portfolio Console에 번호가 있으니 `apps/` 폴더가 필요하다."
- "외부 저장소 링크만 있으면 미구현이므로 내부 UI를 새로 만들어야 한다."
- "README anchor만 만들어 두면 안전하다."
- "번호가 없으니 적당한 빈 번호를 부여해서 구현하면 된다."

외부 개발 프로젝트는 **외부에서 개발하고, AI Revenue Lab에서는 목록과 연결만 관리**한다.

## 현재 결정

2026-08-09 사용자 결정:

```text
EXTERNAL_PROJECTS_LIST_ONLY
NO_INTERNAL_PLACEHOLDER_FOLDER
NO_INTERNAL_DUPLICATE_IMPLEMENTATION
UNNUMBERED_PROJECT_DEFAULT=EXTERNAL_DEVELOPMENT
EXISTING_EXTERNAL_SOURCE_REMAINS_EXTERNAL_UNTIL_EXPLICIT_MIGRATION
```
