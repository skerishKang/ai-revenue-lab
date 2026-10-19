# PADIEM 개발·운영 이슈 정합화 — 2026-10-19

> **현재 판단 기준:** 최신 대표 지시 → 현재 GitHub 이슈/병합 PR → 실제 배포·운영 E2E. 이 문서는 공개 가능한 기술 상태만 기록한다. 비공개 Governance 원문·고객 계정·credential은 포함하지 않는다. 과거 날짜의 문서는 역사적 스냅샷이며, 이 표도 이후 상태 변경 시 현재 이슈를 우선한다.

## 1. 구현 / 검증 분리

**원칙:** 기능별 구현 이슈에는 코드·집중 테스트·PR 및 병합 결과를, 통합 검증 이슈에는 실제 운영 served-version·사용자/계정·권한·결과 E2E를 기록한다. 이미 증빙된 결과는 재사용하며 검증 부족을 근거로 같은 구현을 재개발하지 않는다.

| 운영 검증 원장 | 범위 | 상태 |
| --- | --- | --- |
| [#4317](https://github.com/skerishKang/ai-revenue-lab/issues/4317) | B62 Chat 인증·대화·모델·프로젝트·라이브러리 | OPEN |
| [#3936](https://github.com/skerishKang/ai-revenue-lab/issues/3936) | B54 Claw/P01 승인·실행·XLSX/PDF·원대화 반환 | OPEN |
| [#4316](https://github.com/skerishKang/ai-revenue-lab/issues/4316) | B66 견적·업무·PDF·사용자 권한 | OPEN |
| [#4318](https://github.com/skerishKang/ai-revenue-lab/issues/4318) | Engine/P01/B14/Control Plane 공통 런타임 | OPEN |
| [#3099](https://github.com/skerishKang/ai-revenue-lab/issues/3099) | Windows Connector 설치·재연결·실PC 실행 | OPEN |
| [#4089](https://github.com/skerishKang/ai-revenue-lab/issues/4089) | **별도 교차제품 커넥터 검증 원장:** Chat/Claw/B66 Drive/GitHub/Gmail 등 연결·재로그인 지속·READ/WRITE·결과 | OPEN |

공통 커넥터 #4089는 위 5개 제품/엔진/Windows 검증 원장과 **기능 경계가 다른 추가 통합 수용 원장**이다. 제품별 고객업무 검증과 원시 커넥터 권한·기능 검증을 중복 실행하지 않는다.

## 2. 현재 공통 구현 소유권

| 구현 이슈 | 공통 코드·기능 범위 | 검증 원장 |
| --- | --- | --- |
| [#3580](https://github.com/skerishKang/ai-revenue-lab/issues/3580) | Chat·Claw·B66 공통 Drive WRITE·외부 SEND·PC 파일/산출물 전달 | #4089 및 제품별 |
| [#5015](https://github.com/skerishKang/ai-revenue-lab/issues/5015) | Chat·Claw·B66 PC/Drive 연결 인식과 P01 tool capability | #4089 및 제품별 |
| [#4434](https://github.com/skerishKang/ai-revenue-lab/issues/4434) | 공통 웹 XLSX→PC 로컬 처리→웹 업무 결과 반환 | #3099·#4089 및 제품별 |
| [#4976](https://github.com/skerishKang/ai-revenue-lab/issues/4976) | 공통 PC 지정 폴더 검색·읽기·색인 | #3099·#4089 |
| [#4871](https://github.com/skerishKang/ai-revenue-lab/issues/4871) | 커넥터 OAuth/권한 및 provider action 구현 | #4089 |
| [#5034](https://github.com/skerishKang/ai-revenue-lab/issues/5034) | Chat·Claw·B66 공통 알림함·Web Push | 제품별 |
| [#5108](https://github.com/skerishKang/ai-revenue-lab/issues/5108) | 총관리자 허브·기존 제품 관리자 연결·B14 모델 변경 반영 | #4317·#3936·#4316·#4318 |

공통 기능은 하나의 인증·실행·결과 원천을 재사용한다. Chat·Claw·B66은 제품별 UI, entitlement, workspace/tenant, 견적 계산 등 고유 권한을 유지한다. **공통 코드 등록은 제품별 권한 자동 허용을 뜻하지 않는다.**

## 3. 개별 구현·개발 대기

- [#3186](https://github.com/skerishKang/ai-revenue-lab/issues/3186): B66 새 견적서 자동·직접·맡기기. 구현이 남은 부분과 운영 E2E(#4316)를 구분.
- [#3595](https://github.com/skerishKang/ai-revenue-lab/issues/3595): B66 다른 양식의 범용 템플릿·PDF 재현.
- [#3782](https://github.com/skerishKang/ai-revenue-lab/issues/3782): Claw 브라우저 액션·Desktop 실행 접합.
- [#4702](https://github.com/skerishKang/ai-revenue-lab/issues/4702): 전화 업무의 실제 SIP/음성 공급자 및 인증 실행 연결.
- [#5080](https://github.com/skerishKang/ai-revenue-lab/issues/5080): Android 기기 Connector 후속 개발.
- [#5035](https://github.com/skerishKang/ai-revenue-lab/issues/5035): 이카운트 ERP API 연동(고객 업무 범위 결정 후).
- [#5093](https://github.com/skerishKang/ai-revenue-lab/issues/5093): COM2 Cloudflare/R2 백업·복구 구현(기존 COM2 A 담당).
- [#3404](https://github.com/skerishKang/ai-revenue-lab/issues/3404): B66 STT — UI PR #5105 병합·배포 보고, 실마이크 STT E2E 미완. 대표의 **작업 중단** 지시 유지.
- [#5002](https://github.com/skerishKang/ai-revenue-lab/issues/5002): 모델/auto 테스트 정합화는 **다른 팀 담당**.
- [#5094](https://github.com/skerishKang/ai-revenue-lab/issues/5094): 기존 B66 후속 이슈 **CLOSED**, 진행 중인 개발로 중복 배정 금지.

## 4. 최근 종결/완료 범위

| 이슈 | 현재 추적 판정 |
| --- | --- |
| [#4428](https://github.com/skerishKang/ai-revenue-lab/issues/4428) | CLOSED: 중앙 관리자 signing key 복구·routes_write_enabled true·preview/apply/rollback 운영 E2E 완료 보고 |
| [#4453](https://github.com/skerishKang/ai-revenue-lab/issues/4453) | CLOSED: 중앙 모델 S1 중복 추적 종료. 관리자 UX 후속은 #5108 |
| [#4483](https://github.com/skerishKang/ai-revenue-lab/issues/4483) | CLOSED: S3 중복 추적 종료. 개별 실제 디스패치 장애는 해당 제품/플랫폼 운영 이슈 |
| [#4488](https://github.com/skerishKang/ai-revenue-lab/issues/4488) | CLOSED: 공통 composer/scroll 운영 로드·패리티 및 배포 가드 #5089 병합 |
| [#1971](https://github.com/skerishKang/ai-revenue-lab/issues/1971) | CLOSED/duplicate: 이미지 Production 활성화 검증은 #4318에 이관, 실제 활성화 완료 주장 아님 |
| [#1966](https://github.com/skerishKang/ai-revenue-lab/issues/1966) | CLOSED/duplicate: 승인 후 resume Production 검증은 #4318에 이관, 실제 활성화 완료 주장 아님 |

## 5. 모델·배포 정확성

- 2026-10-18 [B14 모델 운영 기록](B14_FREE_ROLLOUT_REPO_WIDE_STATUS_2026-10-18.md)의 Beam Free/LongCat Free 및 Free/Plus/Pro/Max 지정 모델 표가 2026-10-16 Cat-Jam 기반 문서보다 후속 기술 스냅샷이다.
- 공급자 모델의 등급별 실제 유효성은 현재 배포·운영 원장, 중앙 모델 관리자 정책 snapshot, B14 현재 카탈로그에서 읽는다. 10월 18일 정적 표 자체를 미래의 영구 사업 규칙으로 승격하지 않는다.
- `b14/auto`는 현재 실추론 중단 지시가 있으며, 장기 관리자/자동 라우터 백로그 [#2107](https://github.com/skerishKang/ai-revenue-lab/issues/2107)이 이를 자동 활성화하지 않는다.
- 제품 모델 정책 선택은 관리자 후속 [#5108](https://github.com/skerishKang/ai-revenue-lab/issues/5108)에서 기존 `/admin-models`·D1/CAS/감사 계약을 재사용한다.
- 코드 MERGED, 배포 DEPLOYED, 실제 사용자 LIVE_VERIFIED는 별도 판정한다. 날짜가 지난 서빙 SHA를 최신 운영 SHA라고 쓰지 않는다.

## 6. 후속 문서 운영

1. 이 인덱스는 **이슈/문서 연결과 작업 범위**만 소유한다. Secret 이름/값·내부 사업방침 원문·사적 계정 정보는 공개 문서에 복제하지 않는다.
2. 기존 `PADIEM_PORTFOLIO_ISSUE_DOC_RECONCILIATION_20261013.md` 및 제품별 장문 기술 상태 기록은 날짜가 고정된 **이력**으로 보존한다. 신규 에이전트는 이 문서와 실제 최신 이슈를 먼저 읽는다.
3. 구현 이슈를 닫을 때 미완료 운영 검증 항목을 소유 통합검증 이슈로 링크한다. 검증 담당 이슈를 새로 계속 만들지 않는다.
