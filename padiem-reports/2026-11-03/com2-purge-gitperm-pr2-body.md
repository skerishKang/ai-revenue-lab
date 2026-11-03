## 왜

11-03 컴2에 만료 정리 타이머를 설치했는데, `padiem-chat-expired-purge.timer.template`이
`Requires=`·`Unit=`에 `@UNIT_NAME@`을 썼다. 설치 스크립트는 `@UNIT_NAME@`을 프로필의
`UNIT_NAME`(자동화 틱)으로 치환하므로 렌더된 만료 정리 타이머는
`Unit=padiem-chat-cron-com2.service`가 됐다. 그대로 켜면 매일 `app.local_cron`만 돌고
만료 행은 한 줄도 지우지 않는다.

## 어떻게

- 타이머 템플릿의 `Requires=`·`Unit=`을 `@PURGE_UNIT_NAME@`으로 바꾼다
  (프로필의 `PURGE_UNIT_NAME` = `padiem-chat-expired-purge-com2`).
- `install-cron.sh`의 `render()`가 `@PURGE_UNIT_NAME@`을 치환하도록 한 줄 추가.
  `@UNIT_NAME@` 치환보다 먼저 둔다(패턴이 겹치지 않지만 순서를 명시해 둔다).
- 자동화 틱 타이머는 그대로 `@UNIT_NAME@`을 쓴다. 두 방향이 서로를 끌어오지 않는지 시험한다.

설치 결과는 바뀌지 않는다. 이 PR은 템플릿과 설치 스크립트만 고치고, 유닛 설치·시작·활성화는
하지 않는다(설치 스크립트는 여전히 시작·활성화를 하지 않는다).

## 시험

`deploy/host-com2/cron/tests/test_cron_package.py`:

- `render_units()` — 렌더 결과를 유닛 파일 이름별로 나눠 돌려주는 도우미.
- `test_the_purge_timer_triggers_the_purge_oneshot` — 만료 정리 타이머의 `Requires=`·`Unit=`
  이 `padiem-chat-expired-purge-com2.service`이고, 디렉티브 어디에도 자동화 틱 유닛이 없다.
  반대 방향(틱 타이머)도 확인한다.
- `test_the_purge_units_follow_their_own_profile` — staging 렌더가 staging 정리 유닛을 가리킨다.

`ShellPackaging` 8개 시험이 통과했다. 같은 파일의 `TickRunner` 3개는 이 호스트의 기준선에서도
같은 이유로 실패한다(이 PR과 무관, 손대지 않음).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
https://claude.ai/code/session_01FCsUSWdwU9cz9NcGvU93dd
