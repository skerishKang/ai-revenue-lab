# 컴2 만료 삭제 타이머 + 배포 git 권한 (261103)

- 12:2x 시작: 운영 설치본 e1dbeb8에서 expired_purge.py 확인(app 심볼릭 링크 경유 존재), 유닛 4개는 11:42에 이미 렌더됨(disabled)
- A1: 운영 설치본 e1dbeb8(/opt/padiem/chat-com2/app 심볼릭 링크)에 expired_purge.py 존재 확인
- A2: install-cron.sh --profile production --schedule "*-*-* 18:00:00" --apply 로 서비스·타이머 렌더(11:42 최초, 12:2x 재렌더). 타이머는 아직 꺼 둠
- A2-보정: 설치된 타이머가 @UNIT_NAME@(자동화 틱)을 가리키는 템플릿 결함 발견 → PR #6739로 수정 후 재렌더
- A3: VACUUM INTO 백업 /opt/padiem/com2-deploy/backup-20261103-purge/chat-before-purge-20261103T032252Z.sqlite3 (integrity ok, 97 tables)
- A4: dry-run 1회 — 테이블별 행 수만: p01_requests 12, quote_write_pauses 6, selections 13, android_auth_handoffs 18, password_reset_tokens 10 (합 59), 나머지 0
- A5: 실제 1회 — CHAT_EXPIRED_PURGE=ERROR reason=purge_failed. 원인은 NO ACTION 외래 키(영수증) → 0행. ExitMainStatus=0으로 실패가 성공처럼 보임
- A5-원인수정: 영수증이 인용한 행은 남기는 가드 + 실패 시 비0 종료 → PR #6740 (운영은 다음 배포 때)
- A6: systemctl enable --now padiem-chat-expired-purge-com2.timer — next 2026-11-03 18:00 KST
- A7: Chat /health 200, NRestarts 0 → 0, MainPID 변화 없음
- B1: 원인 위치 deploy/host-com2/deploy_from_main.sh:759 apply_pending_chat_migrations — runuser -u <db user> python 안의 git show
- B2: 그 한 명령에만 git -c safe.directory=<체크아웃> 추가(전역 설정 불변). chat/install.sh에는 git 실행 지점 없음
- B3: deploy/host-com2/tests/test_deploy_from_main.py MigrationServiceUserGitTest 추가(전체 39개 통과)
- B4: PR #6738 → CI 녹색 → automerge MERGED (SHA는 아래 보고)
- B5: 운영 배포는 하지 않음
- B4 확정: PR #6738 MERGED 0e67fdffc61f57c917b3cd50e6c5940fc8816ec7
- A2 확정: PR #6739 MERGED f31471869636bea23d45b58e65954263b0ccf381
- A5 확정: PR #6740 MERGED ad069bdf9ad4ddb144c907c7f9b2f78b59583a75
