# Chat D1 변경분 handback 게이트 계약 — 초안

STATUS=NOT_READY. 현재 #6200은 로컬 SQLite 전용이다. 원격 D1 적재 코드·게이트 dispatch·파일 이동은 구현하거나 실행하지 않았다.

## 모드

기존 b62-d1-migrate-gate의 보호된 production 환경과 exact-main SHA 재확인·실행 이력·명시적 확인 문구 방식을 따른 별도 handback 모드를 설계한다. 기존 마이그레이션 apply를 데이터 복원으로 속여 사용하지 않는다.

1. **readonly-plan**: 입력은 전환 기준 스냅숏, 동결한 COM2 현재 스냅숏과 D1 현재 읽기 스냅숏 및 객체 매니페스트. 스키마·정본·기본키를 검증하고 D1이 전환 기준과 다른 경우 쓰기 0으로 거부한다. 표별 INSERT/UPDATE/DELETE 건수, 기준/목표 해시, 제외 소유 표, 파일 추가/변경/삭제 건수와 크기·해시, 검사 SHA와 계획 식별자를 출력한다. 행·파일 내용·개인 식별자·비밀은 로그/PR에 넣지 않는다.
2. **apply**: 보호된 환경의 승인된 확인 문구와 exact main SHA, 동일 계획 식별자, 동결 상태 및 현재 D1/COM2·객체 해시를 다시 확인한다. 하나라도 다르면 0 쓰기. 실제 D1에 변경을 묶어 적용하는 경로의 원자성이 증명되지 않으면 적용을 제공하지 않는다. D1과 객체 저장소는 공동 트랜잭션이 아니므로 사전 staging과 재시작 가능한 복구 순서가 필요하며, 실패 시 쓰기를 동결한 채 복구한다.
3. **verify**: 모든 비제외 표의 행 수·기본키 기준 해시, 추가/변경/삭제, 트리거 및 참조 객체의 크기·SHA-256을 현재 COM2와 대조한다. 검증 실패/누락/호출 불명 상태는 FAIL 또는 UNKNOWN이며 쓰기 재개 금지.

## 원격 원자성과 제약

Cloudflare D1 공식 문서는 각 batch 내부 개별 SQL 제한과 전체 batch의 30초 API 실행 제약을 명시한다. SQL 문장 100,000바이트, statement당 바인드 100개 등은 플랫폼 제약이며 데이터 크기에 따른 실패가 가능하다. 출처: https://developers.cloudflare.com/d1/platform/limits/

공식 문서는 import 중 D1 접근이 막힌다고 설명하나 그 자체가 이 프로젝트의 충돌 감지·전체 롤백 증거는 아니다: https://developers.cloudflare.com/api/resources/d1/subresources/database/methods/import/

**실측: UNKNOWN.** 이 회차는 D1 gate 실행이 금지되어 있으며 로컬 SQLite 트랜잭션 테스트는 원격 D1의 batch 원자성이나 크기 한계 실측이 아니다. 테스트 전 해당 특성을 PASS로 표시하거나 큰 변경을 여러 batch로 쪼갠 뒤 전부 원자적이라고 주장하지 않는다. 예상 크기에서 한 트랜잭션에 들어가지 않는다면 전환/원복 설계가 필요하다.

## 객체·project_files

CPython은 LocalDiskR2 아래 objects에 객체를 기록하며 project_files의 원본 객체 경로는 서버 생성 키로 연계된다. 표 행만 복원하면 파일이 빠질 수 있다. 기준/현재의 참조·객체 manifest를 동일 동결점에서 수집하고 추가·변경·삭제 및 hash·size를 계획한다. 타 사용자 격리와 삭제 대상·스냅숏을 검사하고 staging한 다음, D1과 객체가 같은 세대를 가리키는 상태를 확인한다. 객체 전송·삭제가 일부 실패하면 전체 복구 전 동결을 해제하지 않는다. 이 교차 저장소 복구는 구현 및 리허설 전이다.

## 추가 확인 사항

- 현재 오프라인 방식은 유효한 UNIQUE 값 교환도 순차 갱신 제약에 걸려 전체 롤백할 수 있다.
- 큐/broker 정본, identity 세션, LoveTree handoff, 비HTTP 쓰기·예약 작업 및 in-flight를 별도 확인한다.
- D1 대상 schema와 trigger의 일치 및 삭제·상호 참조를 검증한다. 익명화된 테스트와 별도 D1 환경에서 정상·충돌·중단·오류·재개를 검증하기 전 운영에 쓰지 않는다.
