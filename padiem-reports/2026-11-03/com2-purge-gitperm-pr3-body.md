## 왜

11-03 컴2 운영에서 만료 정리 첫 실제 실행이 `CHAT_EXPIRED_PURGE=ERROR reason=purge_failed`로 끝났고,
`ExecMainStatus=0`이라 systemd에는 성공으로 보였다. 원인은 두 가지다.

1. `claw_web_xlsx_p01_requests`와 `claw_web_xlsx_selections`는 각각
   `claw_web_xlsx_p01_decision_receipts`·`claw_web_xlsx_quote_edit_receipts`가 `NO ACTION` 외래 키로
   참조한다. 만료된 부모 행을 지우려 하면 `sqlite3.IntegrityError: FOREIGN KEY constraint failed`가
   나고, 그 예외가 회차 전체를 멈춰 **그 뒤 8개 테이블은 아예 처리되지 않았다.**
2. `main()`이 항상 0을 반환해서 실패한 회차도 타이머 입장에서는 성공이었다.

## 어떻게

- `PurgeTarget`에 `key_column`·`referenced_by`를 더하고, 영수증이 아직 인용하는 부모 행은
  `NOT EXISTS` 가드로 남긴다. 가드는 dry-run 카운트에도 같이 들어가므로 미리 세는 수와 실제로
  지우는 수가 어긋나지 않는다. 외래 키를 끄지 않는다 — 무결성 검사는 켜 둔 채로 지울 수 있는
  행만 지운다. 인용된 쌍은 영수증 보관 기간이 정해질 때 함께 다룬다(문서에 근거 기록).
- `main()`이 상태 줄에 맞는 종료 코드를 낸다: `ok`·`dry_run` → 0, `ERROR`·`STORAGE_ERROR` → 1,
  나머지 거부 → 2. 실패한 회차가 성공으로 보고되지 않는다.

## 확인

- 백업본 사본에 고친 모듈을 실행: `CHAT_EXPIRED_PURGE=ok`, `PRAGMA foreign_key_check` 빈 결과.
- `apps/padiem-chat/tests/test_expired_purge.py`: 영수증이 인용한 행은 남고 인용되지 않은 만료 행만
  지워지는 시험, dry-run 카운트가 같은 가드를 쓰는 시험, 실패·성공 회차의 종료 코드 시험을 추가.

## 운영

이 PR은 다음 배포 때 운영에 반영된다. 타이머·유닛은 바뀌지 않는다(이미 설치·활성화됨).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
https://claude.ai/code/session_01FCsUSWdwU9cz9NcGvU93dd
