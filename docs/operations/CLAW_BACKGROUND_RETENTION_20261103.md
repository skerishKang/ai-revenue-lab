# Claw 작업 영수증 보존 및 계정 탈퇴 정리

## 보존 기간

`RemoteBackgroundJobs` 영수증과 로그는 작업 완료 시각부터 7일이 지나면 제거한다. 경계 시각(`finished_at <= now - retention_seconds`)을 포함한다. 실행 중 기록은 만료 정리에서 제외한다. 기간은 `PADIEM_OUTPUT_STORE_RETENTION_SECONDS` 설정을 출력 저장소와 함께 읽으며, 기본값은 604800초(7일)다. 법률 보관 초안의 90일은 본문 없는 PC 작업 집계와 화면 캡처용이고 실제 작업 출력에는 적용하지 않는다.

실행기는 `pending_results()` 호출 중 최대 60초 간격으로 정리한다. 실패는 호출부까지 전파되어 실행기를 성공 상태로 남기지 않는다. 수동 정리 CLI는 다음과 같이 실행하며, 성공 시 제거 파일 수 한 줄만 출력하고 실패 시 0이 아닌 코드를 반환한다.

```sh
PYTHONPATH=/opt/padiem/mesh-queue python -m padiem_ai_core.pc_background --directory "$ORACLE_MESH_WORK_DIR/background-jobs"
```

## 계정 탈퇴

Chat의 `account_deletion.py`는 세션 폐기 뒤 queue RPC `delete_account_pc_data`를 Chat DB 삭제보다 먼저 호출한다. Queue는 공유 작업 폴더에서 사용자 소유 영수증·로그를 잠금 아래 지우고, `pc-outputs` 저장소의 사용자 해시 인덱스를 따라 업로드·출력 파일을 지운 다음 기존 PC 계정별 SQL 정리를 실행한다. 영수증·출력 저장소에는 전역 파일 잠금과 계정별 잠금을 사용한다. 사용자 식별자는 해시 파일 이름에만 쓰며 명령·출력 본문을 DB에 저장하지 않는다. 삭제 후 해시 tombstone이 늦은 업로드나 새 작업의 파일 재생성을 막는다.

Queue와 executor 서비스의 `ORACLE_MESH_WORK_DIR`는 반드시 같은 로컬 경로여야 한다. Queue 설치 스크립트는 기존 `queue.env` 값을 보존하고, 재설치 시 `ORACLE_MESH_WORK_DIR` 환경변수로 새 경로를 전달할 수도 있다. 값이 없으면 탈퇴 정리를 성공으로 가장하지 않고 queue RPC를 실패시킨다. Chat은 해당 실패에서 Chat DB를 지우지 않고 503을 반환하므로 같은 경로를 두 서비스에 설정한 뒤 재시도해야 한다.

## 기존 파일 한계

이 변경 전의 `pc-outputs` 파일은 경로에 복합 소유자 해시만 있고 계정 인덱스가 없다. 그 해시를 되돌려 사용자 파일만 식별할 수 없으므로 탈퇴 요청에서 다른 계정 파일을 건드리지 않는다. 기존 인덱스 없는 파일은 기존 7일 만료 정리로 수명을 제한한다. 새 업로드는 계정별 해시 인덱스를 함께 기록하므로 이후 탈퇴에서 즉시 제거된다.

DB 스키마 변경은 없다. 097번 마이그레이션은 추가하지 않았다.
