# Windows 레인 시험 실행 (2026-11-03)

1. Windows에서 `apps/padiem-chat`·`apps/padiem-mesh-queue`의 `python -m pytest`는 기본 임시 루트 `%SystemDrive%\pt\c<사용자 키><PID>`·`%SystemDrive%\pt\q<사용자 키><PID>`를 쓴다(최대 19자, 실측 15자); Linux는 pytest 기본값을 유지한다.
2. 임시 루트 부모는 `PADIEM_PYTEST_TEMP_ROOT`로 덮어쓸 수 있고, 명시한 `--basetemp`가 우선한다.
3. 기준 `e6fc92a` 이후 남은 기준 실패는 Chat 37건(로케일/UI·Windows worker·SQLite 계약 검사)과 Queue 1건 `tests/test_queue_watchdog.py::test_deploy_scripts_parse_as_bash_and_are_lf_only`다; 4485 브라우저 2건은 임의 포트 1723 오류로 각 트리 재실행에서 2/2 통과했다.
