# chat.padiem.net 배포 절차 — release_chat.ps1

`release_chat.ps1` 은 chat.padiem.net 을 한 번에 끝내는 유일한 배포 명령이다.
정적(화면) 변경은 **이 스크립트로만** 나간다. 컴2의 `deploy_from_main.sh` 는
화면 자산을 배송하지 않는다(위상 문서:
`docs/operations/CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md`).

## 배포 6단계(스크립트가 하는 일)

1. `git fetch origin` 후 배포할 SHA 를 고정하고(`-Sha`, 없으면 main), 컴2의
   origin/main 과 같은지 검증한다.
2. 컴2(OPS 체크아웃)에서 `deploy_from_main.sh <sha> --apply` 를 격리 유닛으로
   실행하고 `chat:PASS` 또는 `chat:SKIP` 을 요구한다.
3. 화면 Worker(`padiem-chat-front`): node --test → 직전 Version ID 기록
   (롤백 지점) → `wrangler deploy --keep-vars`.
4. pages 거울(`padiem-chat.pages.dev`): build + `wrangler pages deploy`.
5. 검증: `/health`·`/privacy` 200, 정적 자산 sha256 대조, 도메인 연결 확인.
6. 화면 배포 뒤 실패는 기록된 Version 으로 자동 롤백하고 요약을 남긴다.

첫 실행은 `-DryRun` 이다(배포 없이 계획만 출력). 감사 로그는
`release_<n>.log` 로 남고, 10분 이내 실제 재실행은 `-Force` 가 필요하다.

## 배포마다 새 소식 쓰기 규칙 (#7847 4번, 운영 기준 6-4)

배포가 **성공으로 끝나면** 그 배포에 들어간 변화를 새 소식으로 올린다. 순서:

1. **범위 고르기.** 이전 배포 SHA .. 이번 배포 SHA 사이의 머지 중에서
   사용자가 느낄 변화만 고른다. 아직 운영에 안 나간 변화(다음 배포분)는
   넣지 않는다.
2. **쉬운 말 초안.** 항목 1~5줄, 종류는 `improved`(더 나아진 것)·`fixed`(고친 것).
   기술 용어, 페르소나 이름, 모델·공급자 이름, 내부 이슈 번호는 쓰지 않는다.
3. **출처는 셋 중 하나.** `ai_tester`(AI 테스터가 찾아 준 것) / `user`(사용자
   의견으로 고친 것) / `none`(없음). 사용자 의견으로 고친 항목은 의견 행을
   연결한다(`--feedback fb_...`).
4. **CTO 확인.** 초안과 출처 구분을 CTO 가 먼저 본다.
5. **dry-run → 올리기.** `apps/padiem-chat/tools/chat_news_publish.py` 로
   먼저 dry-run(기본 동작, `--apply` 없음)을 출력해 실제 문구·길이 검사를
   확인한 뒤, `--apply` 로 올린다.

```bash
# dry-run (운영, 배포 트리 기준 — 아무것도 쓰지 않는다)
sudo -u root /opt/padiem/chat-com2/venv/bin/python \
  /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/chat_news_publish.py \
  --version 2026.11.18 --kind improved --source ai_tester \
  --title "..." --detail "..."

# 확인 후 올리기 (--apply 를 붙일 때만 쓴다; 의견 연결은 --feedback)
... chat_news_publish.py --version 2026.11.18 --kind fixed --source user \
  --title "..." --detail "..." --feedback fb_<32hex> --apply
```

성공한 실제 배포는 마지막에 "새 소식 쓸 차례" 안내 한 줄을 출력한다
(`-DryRun` 과 검증 실패 시에는 출력하지 않는다).
