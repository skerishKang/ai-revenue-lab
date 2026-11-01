# COM2 전환 후 24시간 관찰 — #5479·#6127 종결 판단 근거 (2026-11-01)

```text
DOC_ROLE=POST_CUTOVER_24H
STATUS=관측 도구 준비·자가검증 완료 / 24h 집계 데이터 미수집(COM2 도달 불가) — 종결 창은 닫지 않음
RELATED=deploy/host-com2/observe/, PR #6455, PR #6444, issues #5479·#6127,
        docs/operations/CHAT_COM2_RUNBOOK.md §8, docs/operations/CHAT_COM2_RUNBOOK.md §8-2
작성: 아스트라3(COM1) / 2026-11-01 21:46 KST
```

## 0. 한 줄 판정

- **#5479(Python Worker 동시성 503·NoGilError): 판정 보류(UNKNOWN).** 관측 창
  (10-31 21:07 ~ 11-01 21:07 KST)의 journald 집계를 이 세션에서 수집하지 못했다.
  관측 스크립트의 규칙대로 "집계 불가는 0건이 아니며", 이 문서는 창을 닫지 않는다.
- **#6127(`/api/auth/status`·`/api/projects` 간헐 500): 판정 보류(UNKNOWN).** 동일 사유.
- 보고 시점(11-01 21:46 KST) 운영 확인: `https://chat.padiem.net/health` →
  **HTTP 200** `{"status":"ok", "runtime":"b14", "b14_configured":true}` —
  관측 창 종료 뒤에도 COM2 서빙이 살아 있다는 현재값 1건(창 전체를 대신하지 않는다).

## 1. 관측 도구 (확정)

| 항목 | 내용 |
| --- | --- |
| 스크립트 | `deploy/host-com2/observe/post_cutover_report.py` — **COM2 호스트에서 실행**(journald·systemctl만 사용) |
| 출처 | PR #6455(feat(com2): post-cutover observation report + 24h close gate) |
| 자가검증 | `python -m unittest discover -s deploy/host-com2/observe/tests` → **15 tests OK**(11-01, COM1에서 실행 — 실제 COM2 접속 없음, Windows/Linux 어디서나 돈다) |
| 보조 | `.github/scripts/chat_post_cutover_smoke.py`(PR #6444) — health·게스트 페이지·asset·auth status 실측 |
| 비밀·개인정보 | 원본 로그 줄·본문·쿼리·헤더·쿠키·클라이언트 주소·식별자·request id·비밀 값을 출력하지 않는다(스크립트 계약) |

### 실행 (COM2에서, 종결 판단용 정확한 창)

```bash
python3 deploy/host-com2/observe/post_cutover_report.py \
  --since 2026-10-31T21:07:00+09:00 \
  --until 2026-11-01T21:07:00+09:00 \
  --json-out /tmp/post-cutover-20261101.json
```

### 종결 3조건 (스크립트 README 인용 — 세 조건이 모두 참일 때만 닫는다)

1. `window_covers_full_24h=true` — 창이 전환 시각부터 24시간 뒤까지를 모두 덮는다.
2. `#5479.pass=true` — `padiem-chat-com2` journald 창에서 `NoGilError` 0건
   (`PyProxy`는 별도 표시, 종결 조건은 NoGilError 0).
3. `#6127.pass=true` — Chat 5xx 집계가 **가능**하고, `/api/auth/status` 5xx 0,
   `/api/projects`와 그 하위 5xx 0.

`#6127=UNKNOWN`·`5xx 집계 불가`는 "0건"이 아니다 — **닫지 않는다**. `counts=null`은
journald를 읽지 못했다는 뜻이며 0으로 해석하지 않는다.

## 2. 관측 창과 배포·재시작 시각

| 시각 (KST) | 사건 | 집계 표기 |
| --- | --- | --- |
| 10-31 21:07 | 컷오버(운영 → COM2 8798) | 창 시작 |
| 11-01 17:25 | 재배포 | 배포 중 |
| 11-01 17:55 | 배포·재시작 | 배포 중 |
| 11-01 18:31 | 배포·재시작 | 배포 중 |
| 11-01 19:27 | 배포·재시작 | 배포 중 |
| 11-01 19:41 | 배포·재시작 | 배포 중 |
| 11-01 20:04 | 배포·재시작 | 배포 중 |
| 11-01 21:07 | 관측 창 종료 | 창 끝 |

- 배포 6건의 시각은 CTO 제공(11-01 지시)이다. COM2 journald의 유닛 시작 기록으로
  실측 대조하는 것을 권한다(`journalctl -u padiem-chat-com2 --since … | grep Started`).
- 집계 규칙: 각 배포 시각 ±10분 구간의 오류는 **"배포 중"**으로 분리해 판정에서 제외한다.

## 3. 집계 방법 (창: 10-31 21:07 ~ 11-01 21:07 KST)

| 항목 | 방법 |
| --- | --- |
| 요청 수·5xx 수·비율 | Chat은 앱의 `http_request` 이벤트(`status`·`route`) 우선, 없으면 uvicorn 접근 로그, 둘 다 없으면 `5xx 집계 불가`(`available=false`) |
| 503·500 라우트별 상위 | 경로 정규화(쿼리 제거, `/api/projects/*` 접기) 후 건수 순 표 — 원래 경로는 문서에 남기지 않는다 |
| 403 | 11-01 #6559 배포 뒤 생긴 403은 **원인이 별도 확정**(앞단 검증 replay DB를 `/mnt/d`(9p)에 두면 잠금 경쟁으로 정상 서명 요청도 403 — RUNBOOK §8-2, 11-01부터 검증 직렬화). 따라서 403은 일반 5xx·인증 실패와 **별도 행**으로 분리해 표기하고 #6127 판정에 넣지 않는다 |
| 재시작·크래시 루프 | `systemctl show -p NRestarts`(누적 카운터, 창 합계와 다를 수 있음) + 창 내 장애 구간(예: §8-1 — `ReadWritePaths` 밖 쓰기 → readonly database 크래시 루프) |
| Traceback·ERROR·NoGil·PyProxy | 3개 유닛(`padiem-chat-com2`, `padiem-p01`, `padiem-b14`) journald 건수 |
| health | 실행 시점 1회(창 전체 가용성 아님) |

P01·B14는 접근 로그가 꺼져 있어(unit `--no-access-log`, `access_log=False`) 5xx
집계가 불가하다 — 이는 Chat의 #6127 판정을 막지 않는다(README 규칙).

## 4. 집계 표 (미완 — COM2 레인 실행 결과로 채운다)

```text
| 유닛              | 요청 수 | 5xx(수/비율) | 500 상위 경로 | 503 상위 경로 | 403(#6559 이후, 별도) | 배포 중 5xx |
| padiem-chat-com2  |         |              |               |               |                       |             |
| padiem-p01        |  n/a(접근로그 꺼짐)      | —             | —             |                       |             |
| padiem-b14        |  n/a(접근로그 꺼짐)      | —             | —             |                       |             |
| 메시 큐(8797)      |         |              |               |               |                       |             |
Traceback 수 / ERROR 줄 수 / NoGilError / PyProxy: (JSON 값)
재시작: NRestarts (창 내 구간: )
```

판정(배포 구간 제외 기준): `#5479 재발 = (JSON)` · `#6127 재발 = (JSON)` ·
`closeable = (JSON)` — 값이 채워지기 전까지 이 문서는 창을 닫지 않는다.

## 5. 데이터 수집 상태 (이 세션의 사실)

- COM1(192.168.0.159)에서 COM2(K_lipvoice, 문서 기준 192.168.0.101)로 도달 불가:
  ping 100% 손실, `ssh -o BatchMode=yes` 포트 22 타임아웃(키·사용자 4종 시도,
  11-01 21:38~21:44 KST), 호스트명 미해석(NetBIOS·mDNS 모두).
- COM1에는 COM2용 SSH 키·설정이 없다(`~/.ssh`에 cgi_handoff 키뿐, known_hosts에
  192.168.0.101 없음, ssh-agent 미구동). 구버전 `scripts/ops/com2_remote_diagnose.py`
  의 설정 파일(`%USERPROFILE%\Padiem\com2-mesh-config.json`)도 COM1에 없다.
- GitHub에도 리포트가 없다: PR #6455 댓글 없음, 11-01 이슈 코멘트는 Pages 배포 봇뿐.
- 결론: 이 문서는 24h 집계를 **수행하지 않았다**. 판정은 §0대로 보류이며, 값이 없는
  채로 "0건"이라 쓰지 않는다(스크립트 규칙).

## 6. 종결 완료 절차 (COM2 운영 레인)

1. §1의 명령 1줄을 COM2에서 실행한다(창은 이미 고정: 10-31 21:07 ~ 11-01 21:07 KST).
2. 출력 JSON의 `closure`를 §4 표에 채운다. `--cutover` 기본값이 전환 시각이라 별도 인자 불필요.
3. **배포 구간(§2, ±10분)의 오류는 판정에서 제외**하고, 비배포 구간에서
   NoGilError·`/api/auth/status`·`/api/projects` 5xx 재발 여부로 #5479·#6127을 판정한다.
4. 판정 줄(`closure: #5479=… #6127=… full_24h=YES closeable=…`)과 §4 표를 이 문서에
   남기고 #5479·#6127에 보고한다. `5xx 집계 불가`면 닫지 않는다.
