# Claw 작업 영수증 보존 및 계정 탈퇴 정리

## 작업 정보
- 작업 트리: `D:\PADIEM\claw-jobs-retention-261103`
- 브랜치: `feat/claw-jobs-retention-261103`
- 최신 재기반 기준: `origin/main` 165269e70c2fb4ed4f8b3276cb22bf82f35d7afc
- 작업 시작 때 동일 목적 원격 브랜치는 없었다. main #6763의 B14 만료·캡처 코드와 Claw 코드 경로는 다르다. 최신 #6767은 탈퇴 경로와 `test_queue_internal_store_rpc.py`를 수정해 같은 테스트 파일에서 두 변경을 함께 보존하고 재검증했다.

## 기존 MCP 설계와 통합 기준 비교
| 항목 | MCP 3단계(096, CGI-1 브랜치) | main의 Claw 공통 경로 |
|---|---|---|
| 저장소 | DB에 소유·상태 메타데이터, PC `%LOCALAPPDATA%\padiem-mcp-jobs`에 작업 파일 | executor `pending_dir/background-jobs`의 JSON 영수증·로그, Queue `pc-outputs` OutputStore |
| 소유 확인 | DB 행이 user/token/PC를 묶고 read/stop 접근을 확인 | 영수증의 account/node/run, 출력의 계정 해시 인덱스·Queue RPC |
| PC 출력 | 본문은 DB에 저장하지 않고 PC 파일에 저장 | 대용량 출력은 공통 PC OutputStore 파일 |
| 취소 | `pc_shell_stop`이 프로세스 트리를 멈추고 대기 디스패치를 취소 | 공통 영수증/status/output 경로에는 MCP 전용 stop 도구 없음 |
| 보존·감사 | PC 파일 30일, DB에는 명령 digest와 상태만 | OutputStore 기존 7일 TTL을 공유하고 영수증/출력 본문은 파일, 로그는 정리 건수만 |

통합 기준은 main Claw 경로다. 이미 executor와 Mesh OutputStore가 쓰는 경로이며, 별도 job 저장소와 추가 migration을 만들지 않는다. MCP 레인은 start/read/stop을 공통 영수증·출력 저장소에 연결하고, DB 소유 확인과 명령 digest 감사는 유지하며, 출력 본문을 DB에 넣지 않고 7일 TTL 및 계정 삭제 Queue RPC에 맞추면 된다.

## 보존 기간과 탈퇴
- Claw 영수증·로그와 PC 출력은 기존 OutputStore 기본값 604800초(7일) 및 `PADIEM_OUTPUT_STORE_RETENTION_SECONDS`를 공유한다. 승인 보존 초안의 90일은 본문 없는 B14 집계/캡처에만 적용된다.
- 만료 경계는 `finished_at <= now - retention`; 실행 중 작업은 보존한다. 파일만 정리하고 정리 건수만 기록한다. 실패는 0이 아닌 종료 코드다. migration 097은 추가하지 않았다.
- Chat `account_deletion.py`는 세션 폐기 후 Queue `delete_account_pc_data` RPC를 호출하고 성공한 뒤 Chat DB를 정리한다. Queue 오류 시 503으로 멈춰 Chat 기록은 보존된다.
- Queue RPC는 계정의 Claw 영수증·로그와 색인된 pc-outputs 파일을 지운 뒤 tombstone으로 재쓰기를 막고 기존 PC SQL 정리를 수행한다. Queue와 executor는 같은 `ORACLE_MESH_WORK_DIR`이 필요하며 미설정이면 RPC는 fail-closed다. 설치 스크립트는 기존 설정을 보존하거나 설치 환경에서 받는다.
- 기존 계정 인덱스 없는 pc-outputs 파일은 계정 소유를 안전하게 판별할 수 없어 탈퇴 때 계정별 제거를 하지 않는다. 다른 계정 파일은 보존하고 기존 7일 만료 정리를 따른다.

## Astra3 겹침 확인
- `feat/retention-enforce-261103` 및 `expired-purge-261103` 작업 트리를 읽기 전용으로 살폈다. 대상은 B14 집계·캡처와 `expired_purge`; 이 변경은 Claw 영수증·Queue pc-outputs다. 파일 충돌이 없으며 Astra3 작업 트리를 수정하지 않았다. main #6763 및 탈퇴 경로 #6767의 변경을 재기반으로 포함했다.

## 검증
- Queue/Claw/OutputStore 표적 시험: 55 passed.
- Claw executor 전달·출력 통합: 21 passed.
- 최신 main 재기반 후 Queue/Claw/OutputStore, executor, Chat 계정 탈퇴 회귀: 845 passed, 3 skipped, 1 failed. 유일한 실패는 로컬 `websockets` 17.4와 기존 시험의 고정 요구값 17.2 차이다. 시험과 의존성 조건은 바꾸지 않았다.
- 7일 전후 경계, 실행 중 보존, 사용자 격리, 정리 오류 종료 코드 및 Queue RPC 탈퇴 연결을 시험했다.

## Push 확인
- 최신 `origin/main` 165269e70c2fb4ed4f8b3276cb22bf82f35d7afc 위로 재기반했고, 원격 브랜치가 이전에 본 작업에서 push한 SHA 그대로인지 lease로 확인해 갱신했다.
- 구현 커밋 81133954d0463809415f780e8d08e1781ec8fe2b의 `git ls-remote` 결과가 로컬 SHA와 일치했다. PR·merge·배포는 하지 않았다.
