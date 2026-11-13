## 왜

11-03 컴2 재배포 1차 `--apply`가 실패했다. `deploy_from_main.sh`는 대기 중인 Chat 마이그레이션을
`PADIEM_COM2_CHAT_DB_USER`(기본 `padiem-chat`)로 적용하는데, 그 python 안에서
`git -C <운영 체크아웃> show <sha>:apps/padiem-chat/migrations/<name>`을 **같은 서비스 사용자로**
실행한다. 체크아웃은 root 소유이고 그 계정의 git 설정에는 `safe.directory`가 없어서 git이
`dubious ownership`으로 거부했고, 마이그레이션 파일을 하나도 읽지 못했다. 그 실행만
`PADIEM_COM2_CHAT_DB_USER=root`로 다시 돌려 통과했고, 호스트 설정은 바뀌지 않았다.

## 어떻게

호스트 전역(`git config --global --add safe.directory`)을 바꾸지 않고, 서비스 사용자 대신
체크아웃을 읽는 **그 한 명령에만** `-c safe.directory=<운영 체크아웃>`을 붙인다.

```python
[git, "-c", "safe.directory=%s" % checkout,
 "-C", checkout, "show", "%s:apps/padiem-chat/migrations/%s" % (sha, name)]
```

`pending_migrations()`는 root로 실행되므로 손대지 않았다. `deploy/host-com2/chat/install.sh`에는
git 실행 지점이 없다(`runuser`는 venv python 호출에만 쓰인다) — 확인 결과 변경 없음.

## 시험

`deploy/host-com2/tests/test_deploy_from_main.py`의 `MigrationServiceUserGitTest`:
argv를 기록하는 `git` 래퍼를 PATH 앞에 두고 마이그레이션 시나리오를 실제로 돌린 뒤,

- `show` 호출에 `-c safe.directory=<체크아웃>`이 붙어 있고 `-c`가 `-C`·`show`보다 앞에 있으며,
- 스크립트 어디에도 `config --global`이 없다

는 것을 확인한다. 같은 파일 전체 39개 시험이 통과했다.

## 운영 반영

다음 배포 때 반영된다. 이번에 운영 배포는 하지 않는다.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
https://claude.ai/code/session_01FCsUSWdwU9cz9NcGvU93dd
