# AI 개발 운영정책 v2.0

## 역할 분리형 개발·검증 체계

상태: Canonical  
적용 범위: `ai-revenue-lab` 저장소 전체  
관련 Issue: #148

## 1. 목적

이 정책은 AI를 이용한 저장소 개발에서 제품 결정, 설계·검토, 구현, 실제 환경 검증, 최종 승인 책임을 분리하여 개발 속도와 검증 신뢰성을 동시에 확보하는 것을 목적으로 한다.

본 정책은 신규 기능, 수정, 리팩터링, 배포, 문서화, 기존 Pull Request 보완 작업에 공통 적용한다.

## 2. 기본 원칙

### 2.1 역할 분리

다음 역할을 원칙적으로 서로 다른 대화 또는 실행 환경으로 분리한다.

1. User / Product Owner
2. Web CTO
3. Web Developer
4. Local Validator

동일한 AI 또는 사람이 둘 이상의 역할을 수행하더라도 각 단계의 책임, 입력, 출력, 판정을 분리해 기록해야 한다.

### 2.2 증거 우선

작업자의 완료 선언, 요약, 자신감 표현, 자체 평가는 검증 증거를 대체하지 않는다.

우선하는 원본 증거는 다음과 같다.

- commit SHA
- branch와 base 관계
- 실제 diff와 changed-file 목록
- GitHub CI 상태와 로그
- 로컬에서 실행한 명령과 원문 결과
- 브라우저 화면, console, page error, network 기록
- 실제 배포 응답과 배포 revision

### 2.3 정확한 revision 고정

모든 구현 작업은 시작 전에 다음을 고정한다.

- Repository
- Default branch
- Exact base SHA
- Target branch
- Allowed paths
- Forbidden paths

`최신 main`, `현재 코드`, `방금 버전` 같은 상대적 표현만으로 구현 또는 검증을 시작해서는 안 된다.

### 2.4 `main` 직접 수정 금지

일반 개발 작업은 반드시 별도 branch와 Pull Request를 거친다.

명시적인 사용자 승인 없이 `main`에 파일을 직접 생성·수정·삭제하거나 force push해서는 안 된다.

### 2.5 CI는 필요조건이지 충분조건이 아니다

CI 통과만으로 작업을 완료 또는 `READY`로 판정하지 않는다.

실제 실행 환경, 브라우저 동작, 외부 연동, 인증, 데이터베이스, 운영 배포 검증이 필요한 작업은 별도의 Local Validation을 거쳐야 한다.

## 3. 역할과 책임

### 3.1 User / Product Owner

사용자는 다음을 결정한다.

- 제품 목표와 우선순위
- 허용 가능한 범위와 위험
- 주요 UX·비즈니스 판단
- scope 확대 또는 축소 승인
- 최종 병합·배포 승인

구현 세부사항은 위임할 수 있지만 제품 의미를 바꾸는 결정은 사용자 승인 없이 확정하지 않는다.

### 3.2 Web CTO

Web CTO는 설계 책임자이자 독립 최종 리뷰어다.

책임:

- 최신 GitHub 원격 상태 재검증
- 요구사항, non-goals, acceptance criteria 정의
- exact base SHA와 변경 범위 고정
- 필수 테스트와 증거 정의
- 보안·개인정보·아키텍처 경계 정의
- 구현 diff와 CI 검토
- Local Validation 증거 검토
- 회귀 위험과 제한사항 판단
- 최종 상태 부여

Web CTO는 원칙적으로 구현 코드를 직접 작성하거나 수정하지 않는다.

구현이 필요하면 `templates/CTO_WORK_ORDER.md`를 기준으로 별도의 Web Developer가 실행할 작업계약을 작성한다.

### 3.3 Web Developer

Web Developer는 CTO 작업계약에 따라 코드를 구현한다.

책임:

- 작업 시작 시 원격 상태와 base SHA 재확인
- 지정 branch와 허용 범위 준수
- 코드·테스트·문서 작성
- 자체 정적·단위·통합 테스트
- commit과 Draft PR 생성
- GitHub CI 확인과 실패 수정
- 정확한 구현 증거와 제한사항 보고

Web Developer는 다음을 해서는 안 된다.

- CTO가 확정하지 않은 제품 범위 임의 확대
- 실패한 구현에 맞춘 acceptance criteria 완화
- unrelated files 포함
- 실패 테스트 삭제 또는 skip 전환으로 통과 처리
- 완료되지 않은 기능을 완료로 표현

### 3.4 Local Validator

Local Validator는 실제 실행 환경의 독립 테스터다.

책임:

- 정확한 원격 branch checkout
- tested HEAD SHA 일치 확인
- clean worktree 또는 기존 dirty 상태 기록
- 의존성 설치, build, 실행
- 테스트 명령과 원문 결과 기록
- 브라우저·UI·반응형·외부 연동 검증
- console, page error, failed request 수집
- 재현 가능한 실패 보고

Local Validator는 원칙적으로 제품 소스코드를 수정하지 않는다.

허용되는 로컬 조정:

- 비밀정보를 commit하지 않는 환경변수 설정
- 로컬 포트 선택
- 운영체제별 실행 명령 선택
- 로컬 경로 설정
- 비영구적 테스트 환경 준비

소스 수정이 필요하면 실패 증거를 Web Developer에게 반환한다. 별도 승인 없이 수정한 결과는 독립 검증 증거로 인정하지 않는다.

## 4. 표준 작업 흐름

```text
User request
→ Web CTO work contract
→ Web Developer implementation
→ GitHub CI
→ Local validation
→ Web CTO final review
→ User approval
→ Merge
→ Production verification
```

### Gate 0 — Intake

사용자 요구를 제품 목표와 기술 작업으로 분리한다.

구현 가능한 수준으로 목표와 범위가 정리되지 않았으면 `PLANNING` 상태를 유지한다.

### Gate 1 — CTO Work Contract

최소 항목:

- Repository
- Issue
- Exact base SHA
- Target branch
- Objective
- Non-goals
- Allowed paths
- Forbidden paths
- Required implementation
- Required tests
- Required evidence
- Acceptance criteria
- Completion definition

계약이 확정되지 않은 상태에서 구현을 시작하지 않는다.

### Gate 2 — Web Development and CI

Web Developer는 작업계약에 따라 구현하고 Draft PR을 생성한다.

CI가 존재하면 반드시 실행한다. CI가 없거나 범위가 불충분하면 그 사실을 명시하고 재현 가능한 대체 검증을 제공한다.

CI 실패 상태에서 완료를 선언하지 않는다.

### Gate 3 — Local Environment Validation

다음 작업은 원칙적으로 Local Validation이 필요하다.

- UI·UX 변경
- 브라우저 상호작용과 반응형 화면
- 외부 API
- 로컬 AI 모델, GPU, OS 종속 기능
- 인증, 세션, 권한
- 데이터베이스
- 환경변수 또는 secret binding
- 파일·장치·네트워크 접근
- 실제 배포 환경

검증자는 exact tested HEAD SHA를 기록해야 한다.

### Gate 4 — CTO Final Review

Web CTO는 다음을 독립적으로 재검토한다.

- 요구사항 충족
- non-goals 침범 여부
- allowed/forbidden path 준수
- 실제 diff와 보고의 일치
- 테스트 적절성
- 실패·경계 조건
- 보안·개인정보
- 회귀 위험
- Local Validation revision 일치
- 제한사항의 정직한 기록

최종 판정은 `WORKFLOW_STATUS_MODEL.md`에 따라 `READY`, `CONDITIONALLY_READY`, `NOT_READY` 중 하나로 부여한다.

### Gate 5 — User Approval and Merge

`READY`는 자동 병합 명령이 아니다.

사용자가 최종 제품 판단을 승인한 뒤에만 병합 또는 배포한다.

Production 환경이 있으면 merge SHA 또는 승인된 release SHA 기반으로 다시 검증한다.

## 5. 구현 전달 방식

### Mode A — GitHub Direct Implementation

기본 방식이다.

Web Developer가 GitHub 작업 branch에서 파일을 직접 생성·수정·삭제하고 Draft PR을 만든다.

적합한 작업:

- 일반 웹 애플리케이션
- Python, JavaScript, TypeScript 코드
- 테스트와 GitHub Actions
- 정적 자산
- 문서
- 제한된 범위의 리팩터링

### Mode B — Patch Package

GitHub 직접 구현이 어렵거나 로컬 저장소 전체가 필요한 경우 사용한다.

패키지 최소 구성:

- 저장소 상대경로가 보존된 변경 파일
- unified diff
- base SHA
- file hash manifest
- 적용 절차
- 테스트 절차
- 알려진 제한

Local Validator는 패치를 임의로 재설계하지 않고 적용·실행 결과를 반환한다.

### Mode C — Local Environment Validation

Windows, WSL, GPU, 로컬 모델, 장치, 비공개 데이터베이스처럼 로컬 환경이 필요한 경우 사용한다.

Web Developer가 코드를 작성하고 Local Validator는 실행과 증거 수집을 담당한다.

## 6. 필수 보고 형식

- CTO 작업계약: `templates/CTO_WORK_ORDER.md`
- Web Developer 보고: `templates/WEB_DEVELOPER_REPORT.md`
- Local Validation 보고: `templates/LOCAL_VALIDATION_REPORT.md`
- CTO 최종 리뷰: `templates/CTO_FINAL_REVIEW.md`

## 7. 금지사항

다음 행위를 금지한다.

- 명시적 승인 없는 `main` 직접 수정
- 검증하지 않은 과거 보고의 사실화
- exact SHA 없는 테스트 결과를 현재 코드 증거로 사용
- CI 통과만으로 `READY` 선언
- Local Validator의 숨겨진 제품 소스 수정
- allowed paths 밖 파일 변경
- unrelated dirty file의 commit 포함
- secret, API key, credential, personal data 노출
- 실패 테스트 삭제·완화·skip으로 통과 처리
- acceptance criteria를 구현 결과에 맞춰 사후 변경
- 배포 URL과 revision 관계를 확인하지 않은 production 완료 선언
- 작업자의 완료 서술을 원본 증거보다 우선하는 행위

## 8. 긴급 예외

긴급 장애 대응에서도 가능한 한 branch와 PR을 사용한다.

표준 절차를 생략해야 하면 다음을 기록한다.

- 생략한 단계
- 생략 사유
- 승인자
- 적용 commit
- 사후 검증 계획
- rollback 방법

예외는 이후 작업의 일반 관행으로 자동 승계되지 않는다.

## 9. 적용

본 정책은 Issue #148 승인 이후 시작되는 신규 작업에 적용한다.

기존 Draft PR은 다음 수정 또는 재검증 시 이 정책의 revision identity, evidence, Local Validation, CTO final review 규칙을 적용한다.

이미 병합된 과거 작업은 일괄 재작성하지 않지만, 후속 판단에 사용할 때 최신 원격 상태를 다시 검증한다.
